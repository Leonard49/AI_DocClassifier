#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Classify leftover docs under TARGET/Others* into theme subfolders.

Theme folders are created ONLY under the primary Others folder (usually
"Others"). Documents from Others (2)+ are moved into those themes so the
secondary Others folders become empty (or nearly empty).

Usage:
  python -m tools.others_theme_classify_move --dry-run
  python -m tools.others_theme_classify_move
  python -m tools.others_theme_classify_move --no-llm --max-documents 50
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from classify.llm_rate_limit import LLM_CONCURRENCY, LLM_RATE_LIMITER
from classify.others_theme import (
    DEFAULT_THEME,
    OTHERS_THEMES,
    classify_theme_by_rules,
    parse_theme_response,
    theme_prompt,
)
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.read_doc import FeishuDocumentReader
from feishu.title_check import FolderNameChecker
from feishu.token_manager import TokenManager
from feishu.wiki_move import FeishuWikiMover
from feishu.wiki_scanner import SimpleWikiScanner
from state.folder_rollover import FolderRolloverManager
from state.shared_folder_rollover import SharedFolderRolloverStore, default_rollover_db_path
from state.shared_state import default_worker_id
from state.tag_folder_path import ensure_child_folder
from tools.reclassify_others_move import discover_others_folders, move_with_rollover

from openai import OpenAI


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="将 Others* 文档按主题归入主 Others 下的主题子文件夹，并尽量清空 Others2"
    )
    p.add_argument("--dry-run", action="store_true", help="只分类打印计划，不建夹/不移动")
    p.add_argument(
        "--others-token",
        action="append",
        default=None,
        help="Others 文件夹 token（可多次）；默认自动发现",
    )
    p.add_argument(
        "--primary-token",
        default=None,
        help="挂载主题子文件夹的主 Others token；默认取发现列表中的第一个（Others）",
    )
    p.add_argument("--max-documents", type=int, default=0, help="最多处理 N 篇（0=不限制）")
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="仅用规则分类；未命中的一律进「杂项」",
    )
    p.add_argument(
        "--skip-read",
        action="store_true",
        help="不读正文，仅用标题规则/LLM（更快）",
    )
    return p.parse_args()


def _pick_primary(
    others_folders: List[Tuple[str, str]],
    primary_token: Optional[str],
) -> Tuple[str, str, List[Tuple[str, str]]]:
    if not others_folders:
        raise ValueError("no Others folders")
    if primary_token:
        for title, token in others_folders:
            if token == primary_token:
                secondary = [(t, tok) for t, tok in others_folders if tok != primary_token]
                return title, token, secondary
        # Explicit primary not in discovered list — still use it
        return f"token:{primary_token}", primary_token, others_folders
    title, token = others_folders[0]
    return title, token, others_folders[1:]


def collect_docs(
    scanner: SimpleWikiScanner,
    space_id: str,
    others_folders: List[Tuple[str, str]],
    max_documents: int,
) -> List[Dict]:
    all_docs: List[Dict] = []
    for title, token in others_folders:
        print(f"\n📂 扫描: {title} ({token})")
        docs = scanner.scan_space(space_id=space_id, root_token=token, use_cache=False)
        for d in docs:
            d = dict(d)
            d["others_folder_title"] = title
            d["others_folder_token"] = token
            all_docs.append(d)
        print(f"   叶子文档: {len(docs)}")
    if max_documents > 0:
        all_docs = all_docs[:max_documents]
        print(f"⚠️ 限制处理前 {max_documents} 篇")
    return all_docs


def ensure_theme_folders(
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    space_id: str,
    primary_token: str,
    dry_run: bool,
) -> Dict[str, str]:
    """Create theme children under primary Others. Returns {theme_name: node_token}."""
    mapping: Dict[str, str] = {}
    for name in OTHERS_THEMES:
        if dry_run:
            # Resolve existing if any, else placeholder
            dup = name_checker.check_duplicate(space_id, name, primary_token)
            if dup.get("is_duplicate") and dup.get("node_token"):
                mapping[name] = dup["node_token"]
                print(f"[dry-run] 已有主题夹: {name}")
            else:
                mapping[name] = f"dry-run:{name}"
                print(f"[dry-run] 将创建主题夹: {name}")
            continue
        token = ensure_child_folder(
            creator, name_checker, space_id, primary_token, name
        )
        if not token:
            raise RuntimeError(f"无法创建/找到主题文件夹: {name}")
        mapping[name] = token
    return mapping


class ThemeLLM:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
            max_retries=0,
        )
        self.model = config.LLM_MODEL
        self.max_retries = config.LLM_MAX_RETRIES

    def classify(self, title: str, content: str) -> str:
        import random
        import time

        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )

        messages = [
            {"role": "system", "content": "只输出一个主题文件夹名称。"},
            {"role": "user", "content": theme_prompt(title, content)},
        ]
        last_error: Optional[BaseException] = None
        with LLM_CONCURRENCY:
            for attempt in range(self.max_retries):
                LLM_RATE_LIMITER.wait()
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.1,
                        max_tokens=64,
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    return parse_theme_response(raw)
                except Exception as e:
                    last_error = e
                    retryable = isinstance(
                        e,
                        (
                            APIConnectionError,
                            APITimeoutError,
                            InternalServerError,
                            RateLimitError,
                        ),
                    ) or (
                        isinstance(e, APIStatusError)
                        and e.status_code in {408, 429, 500, 502, 503, 504}
                    )
                    if not retryable or attempt >= self.max_retries - 1:
                        print(f"⚠️ 主题 LLM 失败 ({title}): {e} → {DEFAULT_THEME}")
                        return DEFAULT_THEME
                    wait = min(2**attempt + random.uniform(0.2, 1.0), 45.0)
                    time.sleep(wait)
        return DEFAULT_THEME


def classify_one(
    title: str,
    content: str,
    *,
    use_llm: bool,
    llm: Optional[ThemeLLM],
) -> Tuple[str, str]:
    """Return (theme, method)."""
    ruled = classify_theme_by_rules(title, content)
    if ruled:
        return ruled, "rules"
    if use_llm and llm is not None:
        return llm.classify(title, content), "llm"
    return DEFAULT_THEME, "default"


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    args = _parse_args()
    config.validate()

    space_id = config.SPACE_ID
    target_parent = config.TARGET_PARENT_TOKEN
    if not target_parent:
        print("❌ 需要配置 TARGET_PARENT_TOKEN")
        return 1

    worker_id = config.WORKER_ID or default_worker_id()
    print("=" * 60)
    print("Others 主题归类 → 主 Others 子文件夹（并清空 Others2）")
    print(f"dry_run={args.dry_run} | no_llm={args.no_llm} | worker={worker_id}")
    print("=" * 60)

    tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    scanner = SimpleWikiScanner(tm, enable_db_cache=False)
    reader = FeishuDocumentReader(tm)
    name_checker = FolderNameChecker(tm)
    creator = FeishuNodeCreator(tm, space_id)
    mover = FeishuWikiMover(tm, space_id)

    shared_store = None
    rollover = None
    if config.ENABLE_FOLDER_ROLLOVER:
        db_path = config.FOLDER_ROLLOVER_DB or default_rollover_db_path(
            config.SHARED_STATE_DB
        )
        shared_store = SharedFolderRolloverStore(db_path=db_path, worker_id=worker_id)
        rollover = FolderRolloverManager(
            lambda parent, name: ensure_child_folder(
                creator, name_checker, space_id, parent, name
            ),
            shared_store=shared_store,
        )

    if args.others_token:
        others_folders = [(f"token:{t}", t) for t in args.others_token]
        # Prefer naming from discovery when possible
        discovered = discover_others_folders(name_checker, space_id, target_parent)
        token_to_title = {t: title for title, t in discovered}
        others_folders = [
            (token_to_title.get(t, f"token:{t}"), t) for _, t in others_folders
        ]
        # Keep Others / Others (N) order
        def sort_key(item: Tuple[str, str]):
            title = item[0]
            m = re.search(r"\((\d+)\)$", title)
            return (0 if title == "Others" else 1, int(m.group(1)) if m else 0, title)

        others_folders.sort(key=sort_key)
    else:
        others_folders = discover_others_folders(name_checker, space_id, target_parent)
        if not others_folders:
            print("❌ 未发现 Others / Others (N)")
            return 1

    primary_title, primary_token, secondary = _pick_primary(
        others_folders, args.primary_token
    )
    print(f"\n📌 主 Others（挂主题夹）: {primary_title} ({primary_token})")
    if secondary:
        print("🧹 待清空的次级 Others:")
        for t, tok in secondary:
            print(f"  - {t}: {tok}")
    else:
        print("ℹ️ 仅一个 Others 文件夹")

    print("\n📁 确保主题子文件夹…")
    theme_tokens = ensure_theme_folders(
        creator, name_checker, space_id, primary_token, args.dry_run
    )

    docs = collect_docs(
        scanner, space_id, others_folders, args.max_documents or 0
    )
    if not docs:
        print("✅ 无待处理文档")
        return 0

    by_obj: Dict[str, Dict] = {}
    for d in docs:
        obj = d.get("obj_token") or d["node_token"]
        by_obj.setdefault(obj, d)
    unique_docs = list(by_obj.values())
    print(f"\n待处理唯一文档: {len(unique_docs)}")

    # Skip docs that are theme-folder nodes themselves (shouldn't appear as leaf docx)
    theme_token_set = {t for t in theme_tokens.values() if not str(t).startswith("dry-run:")}

    read_map: Dict[str, Tuple[str, str]] = {}
    if args.skip_read:
        for d in unique_docs:
            obj = d.get("obj_token") or d["node_token"]
            read_map[obj] = (d.get("title") or "", "")
    else:
        print("\n📖 读取正文…")

        def _read(doc: Dict):
            title = doc.get("title") or ""
            obj = doc.get("obj_token") or doc["node_token"]
            node = doc["node_token"]
            try:
                content = reader.get_raw_content(obj, wiki_node_token=node) or ""
            except Exception as exc:
                print(f"⚠️ 读取失败 {title}: {exc}")
                content = ""
            return obj, title, content

        with ThreadPoolExecutor(max_workers=max(1, config.READ_WORKERS)) as pool:
            futs = [pool.submit(_read, d) for d in unique_docs]
            for fut in as_completed(futs):
                obj, title, content = fut.result()
                read_map[obj] = (title, content)

    use_llm = not args.no_llm
    llm = ThemeLLM() if use_llm else None
    print("\n🏷️ 主题分类…")

    theme_by_obj: Dict[str, Tuple[str, str]] = {}

    def _cls(doc: Dict):
        obj = doc.get("obj_token") or doc["node_token"]
        title, content = read_map.get(obj, (doc.get("title") or "", ""))
        theme, method = classify_one(title, content, use_llm=use_llm, llm=llm)
        return obj, theme, method

    with ThreadPoolExecutor(max_workers=max(1, config.CLASSIFY_WORKERS)) as pool:
        futs = [pool.submit(_cls, d) for d in unique_docs]
        for fut in as_completed(futs):
            obj, theme, method = fut.result()
            theme_by_obj[obj] = (theme, method)

    from collections import Counter

    dist = Counter(t for t, _ in theme_by_obj.values())
    print("\n📊 主题分布:")
    for name in OTHERS_THEMES:
        print(f"  {name}: {dist.get(name, 0)}")

    report = {
        "run_at": datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "no_llm": args.no_llm,
        "primary": {"title": primary_title, "token": primary_token},
        "secondary": [{"title": t, "token": tok} for t, tok in secondary],
        "theme_tokens": theme_tokens,
        "stats": {
            "total": len(unique_docs),
            "moved": 0,
            "already_there": 0,
            "move_failed": 0,
            "from_secondary_moved": 0,
            "theme_dist": dict(dist),
        },
        "documents": [],
    }

    moved = already = failed = from_sec = 0
    secondary_tokens = {tok for _, tok in secondary}

    for doc in unique_docs:
        obj = doc.get("obj_token") or doc["node_token"]
        node_token = doc["node_token"]
        title = doc.get("title") or ""
        theme, method = theme_by_obj.get(obj, (DEFAULT_THEME, "default"))
        dest = theme_tokens[theme]
        parent = doc.get("parent_node_token")
        src_folder = doc.get("others_folder_token")
        entry = {
            "title": title,
            "node_token": node_token,
            "obj_token": obj,
            "from_folder": doc.get("others_folder_title"),
            "theme": theme,
            "method": method,
            "action": None,
            "error": None,
        }

        if parent == dest or (
            not str(dest).startswith("dry-run:") and parent in theme_token_set and parent == dest
        ):
            already += 1
            entry["action"] = "already_there"
            report["documents"].append(entry)
            continue

        if args.dry_run:
            entry["action"] = "dry_run_move"
            entry["target_theme"] = theme
            report["documents"].append(entry)
            print(
                f"[dry-run] {title}\n"
                f"         {doc.get('others_folder_title')} → Others/{theme} ({method})"
            )
            continue

        try:
            ok = move_with_rollover(
                mover,
                node_token,
                leaf_token=dest,
                leaf_parent=primary_token,
                leaf_base=theme,
                rollover=rollover,
            )
            if ok:
                moved += 1
                if src_folder in secondary_tokens:
                    from_sec += 1
                entry["action"] = "moved"
                entry["target_theme"] = theme
                print(f"✅ {title} → {theme}")
            else:
                failed += 1
                entry["action"] = "move_failed"
        except Exception as exc:
            failed += 1
            entry["action"] = "move_failed"
            entry["error"] = str(exc)
            print(f"❌ 移动失败 {title}: {exc}")

        report["documents"].append(entry)

    report["stats"]["moved"] = moved
    report["stats"]["already_there"] = already
    report["stats"]["move_failed"] = failed
    report["stats"]["from_secondary_moved"] = from_sec

    os.makedirs(config.LOG_DIR, exist_ok=True)
    out_path = os.path.join(config.LOG_DIR, "others_theme_classify_move.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(
        f"完成 | moved={moved} | already={already} | failed={failed} | "
        f"from_secondary={from_sec} | dry_run={args.dry_run}"
    )
    print(f"📄 报告: {out_path}")
    print("=" * 60)
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

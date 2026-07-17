#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reclassify documents currently under TARGET/Others* and MOVE them
to the correct classification folders (does not copy).

Usage:
  python reclassify_others_move.py --dry-run
  python reclassify_others_move.py
  python reclassify_others_move.py --others-token <token> --max-documents 50
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

import config
from classify.classify_cache import ClassifyCache
from feishu.copy_doc import FeishuCopyError
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.title_check import FolderNameChecker
from state.folder_rollover import FolderRolloverManager, is_node_limit_error
from classify.llm_tree_classifier import (
    LLMTreeClassifier,
    is_excluded_report_tag,
)
from feishu.read_doc import FeishuDocumentReader
from state.shared_folder_rollover import SharedFolderRolloverStore, default_rollover_db_path
from state.shared_state import default_worker_id
from state.tag_folder_path import ensure_child_folder, resolve_tag_leaf_folder
from feishu.token_manager import TokenManager
from feishu.wiki_move import FeishuWikiMover
from feishu.wiki_scanner import SimpleWikiScanner

OTHERS_NAME_RE = re.compile(r"^Others(?:\s+\(\d+\))?$", re.IGNORECASE)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="对 TARGET 下 Others* 中的文档重分类并移动（非复制）"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只分类并打印计划，不执行 move",
    )
    p.add_argument(
        "--others-token",
        action="append",
        default=None,
        help="Others 文件夹 node_token（可多次）；默认自动发现 TARGET 下 Others*",
    )
    p.add_argument(
        "--max-documents",
        type=int,
        default=0,
        help="最多处理 N 篇（0=不限制）",
    )
    p.add_argument(
        "--skip-others-ratio-check",
        action="store_true",
        help="跳过本次 Others 占比门禁（存量纠偏时常用）",
    )
    return p.parse_args()


def discover_others_folders(
    name_checker: FolderNameChecker,
    space_id: str,
    target_parent: str,
) -> List[Tuple[str, str]]:
    """Return [(title, node_token), ...] for Others / Others (N) under target."""
    children = name_checker.list_children(space_id, target_parent)
    found = []
    for title, token in children.items():
        if OTHERS_NAME_RE.match(title.strip()):
            found.append((title, token))
    # Sort: Others, Others (2), ...
    def sort_key(item: Tuple[str, str]):
        title = item[0]
        m = re.search(r"\((\d+)\)$", title)
        return (0 if title == "Others" else 1, int(m.group(1)) if m else 0, title)

    found.sort(key=sort_key)
    return found


def collect_docs(
    scanner: SimpleWikiScanner,
    space_id: str,
    others_folders: List[Tuple[str, str]],
    max_documents: int,
) -> List[Dict]:
    all_docs: List[Dict] = []
    for title, token in others_folders:
        print(f"\n📂 扫描 Others 文件夹: {title} ({token})")
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


def batch_read(
    docs: List[Dict],
    reader: FeishuDocumentReader,
    workers: int,
) -> Dict[str, Tuple[str, Optional[str], str]]:
    results: Dict[str, Tuple[str, Optional[str], str]] = {}

    def _one(doc: Dict):
        title = doc.get("title") or ""
        obj = doc.get("obj_token") or doc["node_token"]
        node = doc["node_token"]
        path = doc.get("source_path") or ""
        try:
            content = reader.get_raw_content(obj, wiki_node_token=node)
        except Exception as exc:
            print(f"⚠️ 读取失败 {title}: {exc}")
            content = None
        return obj, (title, content, path)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(_one, d) for d in docs]
        for fut in as_completed(futs):
            obj, payload = fut.result()
            results[obj] = payload
    return results


def batch_classify(
    read_map: Dict[str, Tuple[str, Optional[str], str]],
    classifier: LLMTreeClassifier,
    workers: int,
) -> Dict[str, Optional[Dict]]:
    out: Dict[str, Optional[Dict]] = {}

    def _one(item):
        obj, (title, content, path) = item
        if not (content or "").strip():
            return obj, None
        try:
            tag = classifier.classify(
                content or "",
                obj_token=obj,
                title=title,
                source_path=path,
            )
        except Exception as exc:
            print(f"⚠️ 分类失败 {title}: {exc}")
            tag = None
        return obj, tag

    items = list(read_map.items())
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(_one, it) for it in items]
        for fut in as_completed(futs):
            obj, tag = fut.result()
            out[obj] = tag
    return out


def move_with_rollover(
    mover: FeishuWikiMover,
    node_token: str,
    *,
    leaf_token: str,
    leaf_parent: Optional[str],
    leaf_base: str,
    rollover: Optional[FolderRolloverManager],
    max_rollovers: int = 3,
) -> bool:
    folder = leaf_token
    for attempt in range(max_rollovers + 1):
        try:
            mover.move_node(node_token, folder)
            return True
        except FeishuCopyError as exc:
            if (
                rollover is not None
                and is_node_limit_error(exc)
                and attempt < max_rollovers
            ):
                print("⚠️ 目标文件夹超限，切换分卷后重试 move…")
                rolled = rollover.rollover(leaf_parent, leaf_base)
                if not rolled:
                    raise
                folder = rolled[0]
                continue
            raise
    return False


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
    print("Others 重分类 → 移动")
    print(f"dry_run={args.dry_run} | worker={worker_id}")
    print("=" * 60)

    tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    scanner = SimpleWikiScanner(tm, enable_db_cache=False)
    reader = FeishuDocumentReader(tm)
    name_checker = FolderNameChecker(tm)
    creator = FeishuNodeCreator(tm, space_id)
    mover = FeishuWikiMover(tm, space_id)

    cache = ClassifyCache() if config.USE_CLASSIFY_CACHE else None
    classifier = LLMTreeClassifier(
        api_key=config.LLM_API_KEY,
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        max_content_chars=config.CLASSIFY_MAX_CHARS,
        verbose=config.CLASSIFY_VERBOSE,
        cache=cache,
        max_retries=config.LLM_MAX_RETRIES,
        request_timeout=config.LLM_REQUEST_TIMEOUT,
    )

    shared_store = None
    if config.ENABLE_FOLDER_ROLLOVER:
        db_path = config.FOLDER_ROLLOVER_DB or default_rollover_db_path(
            config.SHARED_STATE_DB
        )
        shared_store = SharedFolderRolloverStore(db_path=db_path, worker_id=worker_id)
        print(f"📂 分卷共享库: {db_path}")

    rollover = None
    if config.ENABLE_FOLDER_ROLLOVER:
        rollover = FolderRolloverManager(
            lambda parent, name: ensure_child_folder(
                creator, name_checker, space_id, parent, name
            ),
            shared_store=shared_store,
        )

    if args.others_token:
        others_folders = [(f"token:{t}", t) for t in args.others_token]
    else:
        others_folders = discover_others_folders(name_checker, space_id, target_parent)
        if not others_folders:
            print("❌ 未在 TARGET 下发现名为 Others / Others (N) 的文件夹")
            print("   可用 --others-token 手动指定")
            return 1

    print("\n将处理以下 Others 文件夹:")
    for title, token in others_folders:
        print(f"  - {title}: {token}")

    docs = collect_docs(
        scanner, space_id, others_folders, args.max_documents or 0
    )
    if not docs:
        print("✅ 无待处理文档")
        return 0

    # Dedup by obj_token
    by_obj: Dict[str, Dict] = {}
    for d in docs:
        obj = d.get("obj_token") or d["node_token"]
        by_obj.setdefault(obj, d)
    unique_docs = list(by_obj.values())
    print(f"\n待处理唯一文档: {len(unique_docs)}")

    print("\n📖 读取正文…")
    read_map = batch_read(unique_docs, reader, config.READ_WORKERS)
    print("\n🤖 重新分类…")
    classify_map = batch_classify(read_map, classifier, config.CLASSIFY_WORKERS)

    classified = 0
    still_others = 0
    excluded = 0
    empty = 0
    failed_cls = 0
    for obj, tag in classify_map.items():
        title, content, _ = read_map.get(obj, ("", None, ""))
        if not (content or "").strip():
            empty += 1
            continue
        if tag is None:
            failed_cls += 1
            continue
        if is_excluded_report_tag(tag):
            excluded += 1
            continue
        classified += 1
        if tag.get("tag1") == ["Others"]:
            still_others += 1

    ratio = (still_others / classified) if classified else 0.0
    threshold = config.OTHERS_RATIO_FAIL_THRESHOLD
    print(
        f"\n📊 重分类结果: 有效 {classified} | 仍为 Others {still_others} "
        f"({ratio:.1%}) | 排除 {excluded} | 空正文 {empty} | 失败 {failed_cls}"
    )
    if (
        not args.skip_others_ratio_check
        and threshold > 0
        and classified > 0
        and ratio > threshold
    ):
        print(
            f"❌ Others 占比 {ratio:.1%} 超过阈值 {threshold:.0%}，"
            "中止移动。可用 --skip-others-ratio-check 强制执行。"
        )
        return 2

    report = {
        "run_at": datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "worker_id": worker_id,
        "stats": {
            "total": len(unique_docs),
            "classified": classified,
            "still_others": still_others,
            "excluded": excluded,
            "empty": empty,
            "failed_classify": failed_cls,
            "moved": 0,
            "move_failed": 0,
            "skipped_still_others": 0,
        },
        "documents": [],
    }

    moved = 0
    move_failed = 0
    skipped_others = 0

    for doc in unique_docs:
        obj = doc.get("obj_token") or doc["node_token"]
        node_token = doc["node_token"]
        title = doc.get("title") or ""
        tag = classify_map.get(obj)
        entry = {
            "title": title,
            "node_token": node_token,
            "obj_token": obj,
            "from_folder": doc.get("others_folder_title"),
            "tag": tag,
            "action": None,
            "error": None,
        }

        if not tag or is_excluded_report_tag(tag):
            entry["action"] = "skip_excluded_or_failed"
            report["documents"].append(entry)
            continue

        if tag.get("tag1") == ["Others"]:
            skipped_others += 1
            entry["action"] = "skip_still_others"
            report["documents"].append(entry)
            print(f"⏭️ 仍为 Others，保留原位: {title}")
            continue

        resolved = resolve_tag_leaf_folder(
            tag,
            creator=creator,
            name_checker=name_checker,
            space_id=space_id,
            target_root_token=target_parent,
            rollover=rollover,
        )
        if not resolved:
            move_failed += 1
            entry["action"] = "resolve_folder_failed"
            entry["error"] = "无法解析目标文件夹"
            report["documents"].append(entry)
            print(f"❌ 无法解析目标路径: {title} -> {tag}")
            continue

        leaf_token, leaf_parent, leaf_base, active_title = resolved
        entry["target_folder"] = active_title
        entry["target_folder_token"] = leaf_token

        # Already under correct leaf?
        if doc.get("others_folder_token") == leaf_token:
            entry["action"] = "already_there"
            report["documents"].append(entry)
            continue

        if args.dry_run:
            entry["action"] = "dry_run_move"
            report["documents"].append(entry)
            print(
                f"[dry-run] 将移动: {title}\n"
                f"         {doc.get('others_folder_title')} → {active_title} | {tag}"
            )
            continue

        try:
            ok = move_with_rollover(
                mover,
                node_token,
                leaf_token=leaf_token,
                leaf_parent=leaf_parent,
                leaf_base=leaf_base,
                rollover=rollover,
            )
            if ok:
                moved += 1
                entry["action"] = "moved"
                print(f"✅ 已移动: {title} → {active_title}")
            else:
                move_failed += 1
                entry["action"] = "move_failed"
        except Exception as exc:
            move_failed += 1
            entry["action"] = "move_failed"
            entry["error"] = str(exc)
            print(f"❌ 移动失败: {title}: {exc}")

        report["documents"].append(entry)

    report["stats"]["moved"] = moved
    report["stats"]["move_failed"] = move_failed
    report["stats"]["skipped_still_others"] = skipped_others

    os.makedirs(config.LOG_DIR, exist_ok=True)
    out_path = os.path.join(config.LOG_DIR, "others_reclassify_move.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(
        f"完成 | moved={moved} | failed={move_failed} | "
        f"still_others={skipped_others} | dry_run={args.dry_run}"
    )
    print(f"📄 报告: {out_path}")
    print("=" * 60)
    return 0 if move_failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

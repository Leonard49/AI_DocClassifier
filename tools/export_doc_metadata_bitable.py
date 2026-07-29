#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone tool: export wiki document metadata into Feishu bitable(s).

Independent of main.py classify/copy. Only needs Feishu + (optional) LLM config.

Write modes:
  aggregated  — one bitable under parent (default title: 文档元数据汇总)
  per-token   — one bitable per scan folder / token
  both        — write aggregated and per-token tables (default)

Usage:
  python -m tools.export_doc_metadata_bitable --list-folders
  python -m tools.export_doc_metadata_bitable --dry-run --max-documents 20
  python -m tools.export_doc_metadata_bitable --all-enabled --mode both
  python -m tools.export_doc_metadata_bitable --folder 29-GNSS-FAE --mode per-token
  python -m tools.export_doc_metadata_bitable --scan-token <wiki_token> --scan-name MyFolder
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from classify.doc_metadata import (
    DEFAULT_DOC_TYPE,
    DocMetadata,
    classify_doc_type_by_rules,
    doc_type_prompt,
    extract_doc_metadata,
    parse_doc_type_response,
)
from classify.llm_rate_limit import LLM_CONCURRENCY, LLM_RATE_LIMITER
from feishu.bitable import FeishuBitableClient
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.read_doc import FeishuDocumentReader
from feishu.title_check import FolderNameChecker
from feishu.token_manager import TokenManager
from feishu.wiki_meta import WikiMetaClient
from feishu.wiki_scanner import SimpleWikiScanner
from state.metadata_bitable import (
    MetadataBitableRef,
    MetadataRecordIndex,
    ensure_metadata_bitable,
    upsert_metadata_record,
)
from state.scan_folders import (
    ScanFolder,
    default_scan_folders_path,
    filter_folders,
    format_folder_table,
    load_scan_folders,
)
from state.shared_state import default_worker_id

from openai import OpenAI

_VALID_MODES = ("aggregated", "per-token", "both")
_VALID_PER_PARENT = ("target", "source")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="独立工具：导出文档元数据到飞书多维表格（汇总表 / 按 token 分表）"
    )
    p.add_argument("--dry-run", action="store_true", help="只提取打印，不创建/写入多维表格")
    p.add_argument("--list-folders", action="store_true", help="列出清单后退出")

    src = p.add_argument_group("扫描范围（任选其一）")
    src.add_argument("--folder", action="append", default=None, metavar="ID", help="清单 id")
    src.add_argument("--all-assigned", action="store_true", help="assignee==WORKER_ID")
    src.add_argument("--all-enabled", action="store_true", help="清单内全部 enabled")
    src.add_argument("--folders-file", default=None, help="覆盖 SCAN_FOLDERS_FILE")
    src.add_argument(
        "--scan-token",
        default=None,
        metavar="TOKEN",
        help="直接指定 wiki node token（不依赖清单）",
    )
    src.add_argument(
        "--scan-name",
        default=None,
        help="配合 --scan-token 的显示名（默认用 token 前缀）",
    )

    out = p.add_argument_group("写入目标")
    out.add_argument(
        "--mode",
        choices=_VALID_MODES,
        default=None,
        help="aggregated | per-token | both（默认读 METADATA_BITABLE_MODE，缺省 both）",
    )
    out.add_argument(
        "--parent-token",
        default=None,
        help="汇总表 / per-token(挂 target) 的父节点；默认 TARGET_PARENT_TOKEN",
    )
    out.add_argument(
        "--aggregated-title",
        default=None,
        help="汇总多维表格标题（默认 METADATA_BITABLE_TITLE）",
    )
    out.add_argument(
        "--per-token-title-tmpl",
        default=None,
        help="分表标题模板，可用 {id}/{name}/{token}（默认 文档元数据-{id}）",
    )
    out.add_argument(
        "--per-token-parent",
        choices=_VALID_PER_PARENT,
        default=None,
        help="分表挂载：target=与汇总同级父节点；source=各扫描根目录下",
    )

    p.add_argument("--max-documents", type=int, default=0, help="最多处理 N 篇（0=不限制）")
    p.add_argument("--no-llm", action="store_true", help="文档类型仅用规则，不用 LLM")
    p.add_argument("--skip-read", action="store_true", help="不读正文（仅标题规则）")
    p.add_argument("--skip-author", action="store_true", help="不解析作者（更快）")
    return p.parse_args()


def _resolve_mode(args: argparse.Namespace) -> str:
    mode = (args.mode or getattr(config, "METADATA_BITABLE_MODE", None) or "both").strip().lower()
    if mode not in _VALID_MODES:
        raise SystemExit(f"❌ 无效 mode={mode!r}，应为 {_VALID_MODES}")
    return mode


def _resolve_per_token_parent(args: argparse.Namespace) -> str:
    v = (
        args.per_token_parent
        or getattr(config, "METADATA_BITABLE_PER_TOKEN_PARENT", None)
        or "target"
    ).strip().lower()
    if v not in _VALID_PER_PARENT:
        raise SystemExit(f"❌ 无效 per-token-parent={v!r}，应为 {_VALID_PER_PARENT}")
    return v


def _per_token_title(tmpl: str, folder: ScanFolder) -> str:
    token_short = (folder.token or "")[:12]
    try:
        return tmpl.format(id=folder.id, name=folder.name, token=token_short)
    except KeyError as exc:
        raise SystemExit(f"❌ 分表标题模板无效: {tmpl!r} ({exc})") from exc


def _resolve_folders(args: argparse.Namespace) -> List[ScanFolder]:
    if args.scan_token:
        name = (args.scan_name or "").strip() or f"scan-{(args.scan_token or '')[:8]}"
        return [
            ScanFolder(
                id="cli-scan-token",
                name=name,
                token=args.scan_token.strip(),
                assignee="",
                enabled=True,
                priority=1,
            )
        ]

    path = args.folders_file or config.SCAN_FOLDERS_FILE or default_scan_folders_path()
    worker = config.WORKER_ID or default_worker_id()
    registry = load_scan_folders(path)

    if args.list_folders:
        print(f"📄 清单: {path}")
        print(f"👷 WORKER_ID: {worker}")
        print(format_folder_table(registry, worker_id=worker))
        raise SystemExit(0)

    if args.folder:
        return filter_folders(registry, ids=args.folder, enabled_only=False)
    if args.all_enabled:
        return filter_folders(registry, enabled_only=True)
    if args.all_assigned:
        assigned = filter_folders(
            registry, worker_id=worker, assigned_only=True, enabled_only=True
        )
        if not assigned:
            raise SystemExit(
                f"❌ 没有分配给 WORKER_ID={worker} 的文件夹；可用 --all-enabled / --folder / --scan-token"
            )
        return assigned

    # Convenience default: assigned → SCAN_ROOT_TOKEN → error (explicit flags preferred)
    assigned = filter_folders(
        registry, worker_id=worker, assigned_only=True, enabled_only=True
    )
    if assigned:
        return assigned
    if config.SCAN_ROOT_TOKEN:
        return [
            ScanFolder(
                id="env-scan-root",
                name="SCAN_ROOT_TOKEN",
                token=config.SCAN_ROOT_TOKEN,
                assignee=worker or "",
                enabled=True,
                priority=1,
            )
        ]
    if not registry:
        raise SystemExit(f"❌ 找不到清单: {path}")
    raise SystemExit(
        "❌ 请指定扫描范围: --folder / --all-assigned / --all-enabled / --scan-token"
    )


class DocTypeLLM:
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
            {"role": "system", "content": "只输出一个文档类型名称。"},
            {"role": "user", "content": doc_type_prompt(title, content)},
        ]
        with LLM_CONCURRENCY:
            for attempt in range(self.max_retries):
                LLM_RATE_LIMITER.wait()
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.1,
                        max_tokens=32,
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    return parse_doc_type_response(raw)
                except Exception as e:
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
                        print(f"⚠️ 文档类型 LLM 失败 ({title}): {e} → {DEFAULT_DOC_TYPE}")
                        return DEFAULT_DOC_TYPE
                    time.sleep(min(2**attempt + random.uniform(0.2, 1.0), 30.0))
        return DEFAULT_DOC_TYPE


def _write_rows(
    *,
    bitable: FeishuBitableClient,
    ref: MetadataBitableRef,
    index: MetadataRecordIndex,
    rows: List[DocMetadata],
    label: str,
) -> Dict[str, int]:
    created = updated = failed = 0
    print(f"\n✍️ 写入 [{label}] {ref.title} …", flush=True)
    for i, meta in enumerate(rows, 1):
        try:
            action, _rid = upsert_metadata_record(bitable, ref, index, meta)
            if action == "created":
                created += 1
            else:
                updated += 1
            if i % 20 == 0 or i == len(rows):
                print(
                    f"   [{label}] {i}/{len(rows)} | created={created} updated={updated}",
                    flush=True,
                )
        except Exception as exc:
            failed += 1
            print(f"❌ [{label}] 写入失败 {meta.title}: {exc}")
    return {"created": created, "updated": updated, "failed": failed, "total": len(rows)}


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    args = _parse_args()
    mode = _resolve_mode(args)
    per_parent = _resolve_per_token_parent(args)
    use_llm = (not args.no_llm) and getattr(config, "METADATA_USE_LLM_DOC_TYPE", True)

    parent_token = (args.parent_token or config.TARGET_PARENT_TOKEN or "").strip()
    need_target_parent = (not args.dry_run) and (
        mode in ("aggregated", "both") or per_parent == "target"
    )
    try:
        config.validate(
            require_scan_source=False,
            require_llm=use_llm,
            require_target=False,
        )
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    if need_target_parent and not parent_token:
        print("❌ 需要 --parent-token 或 TARGET_PARENT_TOKEN（汇总表 / target 分表挂载）")
        return 1

    folders = _resolve_folders(args)
    print("=" * 60)
    print("文档元数据 → 飞书多维表格（独立工具）")
    print(f"dry_run={args.dry_run} | mode={mode} | per_token_parent={per_parent}")
    print(f"folders={len(folders)} | use_llm={use_llm}")
    if parent_token:
        print(f"parent_token={parent_token}")
    print("=" * 60)
    for f in folders:
        print(f"  - {f.id}: {f.name} ({f.token})")

    tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    scanner = SimpleWikiScanner(tm, enable_db_cache=False)
    reader = FeishuDocumentReader(tm)
    name_checker = FolderNameChecker(tm)
    creator = FeishuNodeCreator(tm, config.SPACE_ID)
    bitable = FeishuBitableClient(tm)
    wiki_meta = WikiMetaClient(tm)

    # Collect docs per folder (preserve folder for per-token write)
    docs_by_folder: Dict[str, List[Dict]] = defaultdict(list)
    all_docs: List[Dict] = []
    for folder in folders:
        if args.max_documents > 0 and len(all_docs) >= args.max_documents:
            break
        remaining = (
            args.max_documents - len(all_docs) if args.max_documents > 0 else 0
        )
        print(f"\n📂 扫描: {folder.name} ({folder.token})", flush=True)
        docs = scanner.scan_space(
            space_id=config.SPACE_ID,
            root_token=folder.token,
            use_cache=False,
            max_documents=remaining if remaining > 0 else 0,
        )
        for d in docs:
            d = dict(d)
            d["source_folder_id"] = folder.id
            d["source_folder_name"] = folder.name
            d["source_folder_token"] = folder.token
            docs_by_folder[folder.id].append(d)
            all_docs.append(d)
            if args.max_documents > 0 and len(all_docs) >= args.max_documents:
                break
        print(
            f"   叶子文档(本夹扫描): {len(docs)} | 累计选取: {len(all_docs)}",
            flush=True,
        )

    if args.max_documents > 0 and len(all_docs) > args.max_documents:
        all_docs = all_docs[: args.max_documents]
        # Rebuild per-folder slice consistently
        docs_by_folder = defaultdict(list)
        for d in all_docs:
            docs_by_folder[d["source_folder_id"]].append(d)
    if args.max_documents > 0:
        print(f"⚠️ 限制处理 {len(all_docs)} 篇", flush=True)

    by_obj: Dict[str, Dict] = {}
    for d in all_docs:
        obj = d.get("obj_token") or d["node_token"]
        by_obj.setdefault(obj, d)
    unique_docs = list(by_obj.values())
    print(f"\n待处理唯一文档: {len(unique_docs)}")
    if not unique_docs:
        print("✅ 无文档")
        return 0

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

    llm = DocTypeLLM() if use_llm else None

    print("\n🏷️ 提取元数据…")
    meta_by_obj: Dict[str, DocMetadata] = {}
    for doc in unique_docs:
        obj = doc.get("obj_token") or doc["node_token"]
        node = doc["node_token"]
        title, content = read_map.get(obj, (doc.get("title") or "", ""))
        dtype = classify_doc_type_by_rules(title, content)
        if dtype is None and llm is not None:
            dtype = llm.classify(title, content)
        if dtype is None:
            dtype = DEFAULT_DOC_TYPE

        author = ""
        if not args.skip_author:
            try:
                author = wiki_meta.get_author_display_name(node)
            except Exception as exc:
                print(f"⚠️ 作者解析失败 {title}: {exc}")

        meta_by_obj[obj] = extract_doc_metadata(
            title=title,
            content=content,
            obj_token=obj,
            node_token=node,
            source_folder=doc.get("source_folder_name") or doc.get("source_folder_id") or "",
            source_path=doc.get("source_path") or "",
            author=author,
            doc_type=dtype,
        )

    rows_all = list(meta_by_obj.values())
    print("\n📊 产品线:", dict(Counter(r.product_line for r in rows_all)))
    print("📊 文档类型:", dict(Counter(r.doc_type for r in rows_all)))

    report: Dict = {
        "run_at": datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "mode": mode,
        "per_token_parent": per_parent,
        "stats": {"total": len(rows_all), "targets": []},
        "bitables": [],
        "documents": [r.to_dict() for r in rows_all],
    }

    if args.dry_run:
        print("\n[dry-run] 示例（前 10 条）:")
        for r in rows_all[:10]:
            print(
                f"  · {r.title[:50]} | {r.product_line} | {r.doc_type} | "
                f"mods={r.modules[:40]} | author={r.author}"
            )
        print(
            f"\n[dry-run] 将写入 mode={mode}"
            + (f" | aggregated under {parent_token}" if mode in ("aggregated", "both") else "")
            + (
                f" | per-token parent={per_parent}"
                if mode in ("per-token", "both")
                else ""
            )
        )
        os.makedirs(config.LOG_DIR, exist_ok=True)
        out_path = os.path.join(config.LOG_DIR, "doc_metadata_bitable.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"📄 报告: {out_path}")
        return 0

    index_db = (
        getattr(config, "METADATA_BITABLE_INDEX_DB", None) or "metadata_bitable_index.db"
    )
    index = MetadataRecordIndex(index_db)
    total_failed = 0

    try:
        if mode in ("aggregated", "both"):
            agg_title = (
                args.aggregated_title
                or getattr(config, "METADATA_BITABLE_TITLE", None)
                or "文档元数据汇总"
            )
            print(f"\n📁 确保汇总多维表格: {agg_title}")
            ref = ensure_metadata_bitable(
                space_id=config.SPACE_ID,
                target_parent_token=parent_token,
                title=agg_title,
                creator=creator,
                name_checker=name_checker,
                bitable=bitable,
                wiki_meta=wiki_meta,
                app_token_override=getattr(config, "METADATA_BITABLE_APP_TOKEN", None),
            )
            print(f"✅ aggregated app_token={ref.app_token} table_id={ref.table_id}")
            stats = _write_rows(
                bitable=bitable,
                ref=ref,
                index=index,
                rows=rows_all,
                label="aggregated",
            )
            total_failed += stats["failed"]
            report["bitables"].append(
                {
                    "scope": "aggregated",
                    "title": ref.title,
                    "node_token": ref.node_token,
                    "app_token": ref.app_token,
                    "table_id": ref.table_id,
                    "stats": stats,
                }
            )
            report["stats"]["targets"].append({"scope": "aggregated", **stats})

        if mode in ("per-token", "both"):
            tmpl = (
                args.per_token_title_tmpl
                or getattr(config, "METADATA_BITABLE_PER_TOKEN_TITLE_TMPL", None)
                or "文档元数据-{id}"
            )
            folder_by_id = {f.id: f for f in folders}
            for folder_id, folder_docs in docs_by_folder.items():
                folder = folder_by_id.get(folder_id)
                if not folder:
                    continue
                # Dedupe within folder
                seen: Dict[str, Dict] = {}
                for d in folder_docs:
                    obj = d.get("obj_token") or d["node_token"]
                    seen.setdefault(obj, d)
                folder_rows = [
                    meta_by_obj[obj]
                    for obj in seen
                    if obj in meta_by_obj
                ]
                if not folder_rows:
                    continue

                title = _per_token_title(tmpl, folder)
                hang_under = (
                    folder.token if per_parent == "source" else parent_token
                )
                print(
                    f"\n📁 确保分表 [{folder.id}]: {title} (parent={hang_under[:16]}…)"
                )
                ref = ensure_metadata_bitable(
                    space_id=config.SPACE_ID,
                    target_parent_token=hang_under,
                    title=title,
                    creator=creator,
                    name_checker=name_checker,
                    bitable=bitable,
                    wiki_meta=wiki_meta,
                    app_token_override=None,
                )
                print(
                    f"✅ per-token[{folder.id}] app_token={ref.app_token} "
                    f"table_id={ref.table_id}"
                )
                stats = _write_rows(
                    bitable=bitable,
                    ref=ref,
                    index=index,
                    rows=folder_rows,
                    label=f"per-token:{folder.id}",
                )
                total_failed += stats["failed"]
                report["bitables"].append(
                    {
                        "scope": "per-token",
                        "folder_id": folder.id,
                        "folder_token": folder.token,
                        "title": ref.title,
                        "node_token": ref.node_token,
                        "app_token": ref.app_token,
                        "table_id": ref.table_id,
                        "parent_token": hang_under,
                        "stats": stats,
                    }
                )
                report["stats"]["targets"].append(
                    {"scope": "per-token", "folder_id": folder.id, **stats}
                )
    finally:
        index.close()

    os.makedirs(config.LOG_DIR, exist_ok=True)
    out_path = os.path.join(config.LOG_DIR, "doc_metadata_bitable.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"完成 | docs={len(rows_all)} | bitables={len(report['bitables'])} | failed={total_failed}")
    for b in report["bitables"]:
        st = b.get("stats") or {}
        print(
            f"  · {b.get('scope')} {b.get('folder_id', '')} {b.get('title')}: "
            f"created={st.get('created')} updated={st.get('updated')} failed={st.get('failed')}"
        )
    print(f"📄 报告: {out_path}")
    print("=" * 60)
    return 0 if total_failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

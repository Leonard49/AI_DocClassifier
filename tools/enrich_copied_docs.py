# -*- coding: utf-8 -*-
"""
Backfill document enrichment on already-copied wiki nodes.

Reads `shared_copy_state` copy_registry and runs the same enrichment pipeline
used after classify/copy (metadata table + attachment separator, extensible).

Usage:
  python -m tools.enrich_copied_docs --dry-run --limit 20
  python -m tools.enrich_copied_docs
  python -m tools.enrich_copied_docs --steps metadata_table
  python -m tools.enrich_copied_docs --steps attachment_separator --limit 50
  python -m tools.enrich_copied_docs --scan-root <token>
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Set

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from enrichment.base import EnrichmentContext, EnrichmentPipeline, StepResult
from enrichment.hooks import format_results
from enrichment.steps import AttachmentSeparatorStep, MetadataTableStep
from feishu.read_doc import FeishuDocumentReader
from feishu.token_manager import TokenManager
from feishu.wiki_meta import WikiMetaClient
from state.shared_state import SharedCopyState, default_worker_id


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="对已复制文档回填 enrichment（元数据表 / 附件分隔符等）"
    )
    p.add_argument("--dry-run", action="store_true", help="只列出待处理，不写入")
    p.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
    p.add_argument(
        "--scan-root",
        default="",
        help="仅处理 copy_registry.scan_root 等于该 token 的记录",
    )
    p.add_argument(
        "--steps",
        default="",
        help="逗号分隔 step id，默认按配置：metadata_table,attachment_separator",
    )
    p.add_argument(
        "--db",
        default="",
        help="共享去重库路径（默认 SHARED_STATE_DB）",
    )
    p.add_argument(
        "--skip-read-content",
        action="store_true",
        help="不读取正文（元数据产品线/类型可能较粗）",
    )
    p.add_argument(
        "--no-author",
        action="store_true",
        help="不解析作者",
    )
    return p.parse_args()


def _selected_steps(raw: str) -> Optional[Set[str]]:
    text = (raw or "").strip()
    if not text:
        return None
    return {s.strip() for s in text.split(",") if s.strip()}


def _build_pipeline(
    tm: TokenManager,
    *,
    selected: Optional[Set[str]],
) -> EnrichmentPipeline:
    enable_meta = config.ENABLE_METADATA_TABLE
    enable_sep = config.ENABLE_ATTACHMENT_SEPARATOR
    if selected is not None:
        enable_meta = "metadata_table" in selected
        enable_sep = "attachment_separator" in selected
    steps = []
    if enable_meta:
        steps.append(MetadataTableStep(tm, enabled=True))
    if enable_sep:
        steps.append(AttachmentSeparatorStep(tm, enabled=True))
    if not steps:
        raise SystemExit("没有启用的 enrichment step（检查 --steps / .env）")
    return EnrichmentPipeline(steps)


def main() -> int:
    args = _parse_args()
    config.validate()

    db_path = args.db or config.SHARED_STATE_DB
    shared = SharedCopyState(
        db_path=db_path,
        worker_id=default_worker_id(),
    )
    limit = args.limit if args.limit and args.limit > 0 else None
    rows = shared.list_copied(
        scan_root=args.scan_root or None,
        require_copied_node=True,
        limit=limit,
    )
    print(f"📦 共享库: {db_path}")
    print(f"📋 待处理副本: {len(rows)} 篇")
    if not rows:
        print("✅ 无已复制记录（或缺少 copied_node_token）")
        return 0

    if args.dry_run:
        for i, row in enumerate(rows[:50], 1):
            print(
                f"  {i}. {row.get('title') or '(无标题)'} "
                f"| copy={row.get('copied_node_token')} "
                f"| src={row.get('source_node_token')}"
            )
        if len(rows) > 50:
            print(f"  … 另有 {len(rows) - 50} 篇")
        print("\n(dry-run，未写入)")
        return 0

    tm = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    pipeline = _build_pipeline(tm, selected=_selected_steps(args.steps))
    reader = FeishuDocumentReader(tm)
    wiki_meta = None
    if not args.no_author and config.METADATA_TABLE_FETCH_AUTHOR:
        wiki_meta = WikiMetaClient(tm)

    counts: Dict[str, int] = {"applied": 0, "skipped": 0, "failed": 0}
    t0 = datetime.now()

    for i, row in enumerate(rows, 1):
        title = row.get("title") or ""
        copied = row.get("copied_node_token") or ""
        source = row.get("source_node_token") or ""
        obj_token = row.get("obj_token") or ""
        print(f"\n[{i}/{len(rows)}] {title or copied}")

        content = ""
        if not args.skip_read_content and obj_token:
            try:
                content = (
                    reader.get_raw_content(
                        obj_token, wiki_node_token=source or None
                    )
                    or ""
                )
            except Exception as exc:
                print(f"  ⚠️ 读取正文失败: {exc}")

        author = ""
        if wiki_meta and source:
            try:
                author = wiki_meta.get_author_display_name(source) or ""
            except Exception as exc:
                print(f"  ⚠️ 作者解析失败: {exc}")

        ctx = EnrichmentContext(
            target_node_token=copied,
            title=title,
            obj_token=obj_token,
            source_node_token=source,
            source_path="",
            content=content,
            tag=None,
            author=author,
        )
        results: List[StepResult] = pipeline.run(ctx)
        print(f"  → {format_results(results)}")
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1

    elapsed = (datetime.now() - t0).total_seconds()
    print(
        f"\n✅ 回填完成: applied={counts.get('applied', 0)} "
        f"skipped={counts.get('skipped', 0)} "
        f"failed={counts.get('failed', 0)} "
        f"| 耗时 {elapsed:.1f}s"
    )
    return 1 if counts.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

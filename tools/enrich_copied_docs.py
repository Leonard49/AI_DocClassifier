# -*- coding: utf-8 -*-
"""
Backfill enrichment on TARGET leaf docs (classified copies only).

Default document universe: TARGET_PARENT_TOKEN (not SCAN source).
Skip-existing is per-op via tool_ops.db OperationLedger.

Usage:
  python -m tools.enrich_copied_docs --dry-run --limit 20
  python -m tools.enrich_copied_docs --skip-existing
  python -m tools.enrich_copied_docs --steps metadata_table
  python -m tools.enrich_copied_docs --scope scan --all-assigned   # legacy
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
from state.operation_ledger import (
    OP_ATTACHMENT_SEPARATOR,
    OP_METADATA_TABLE,
    OperationLedger,
)
from tools.runner import ToolJob, add_scope_args, ensure_utf8_stdio


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="对 TARGET（已分类复制）文档回填 enrichment；默认不扫源目录"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
    p.add_argument("--steps", default="", help="metadata_table,attachment_separator")
    p.add_argument("--skip-read-content", action="store_true")
    p.add_argument("--no-author", action="store_true")
    add_scope_args(p)
    return p.parse_args()


def _selected_steps(raw: str) -> Optional[Set[str]]:
    text = (raw or "").strip()
    if not text:
        return None
    return {s.strip() for s in text.split(",") if s.strip()}


def _planned_ops(selected: Optional[Set[str]]) -> List[str]:
    if selected is not None:
        return [s for s in (OP_METADATA_TABLE, OP_ATTACHMENT_SEPARATOR) if s in selected]
    ops = []
    if config.ENABLE_METADATA_TABLE:
        ops.append(OP_METADATA_TABLE)
    if config.ENABLE_ATTACHMENT_SEPARATOR:
        ops.append(OP_ATTACHMENT_SEPARATOR)
    return ops


def _build_pipeline(
    tm: TokenManager,
    *,
    selected: Optional[Set[str]],
    ledger: OperationLedger,
    skip_existing: bool,
) -> EnrichmentPipeline:
    enable_meta = config.ENABLE_METADATA_TABLE
    enable_sep = config.ENABLE_ATTACHMENT_SEPARATOR
    if selected is not None:
        enable_meta = OP_METADATA_TABLE in selected
        enable_sep = OP_ATTACHMENT_SEPARATOR in selected

    class _LedgerStep:
        def __init__(self, inner, op: str):
            self.inner = inner
            self.id = inner.id
            self.title = inner.title
            self.op = op

        def apply(self, ctx: EnrichmentContext) -> StepResult:
            entity = ctx.obj_token or ctx.target_node_token
            node = ctx.target_node_token
            if skip_existing and ledger.is_done(entity, self.op, node_token=node):
                return StepResult(self.id, "skipped", "ledger done")
            result = self.inner.apply(ctx)
            if result.status in ("applied", "skipped") and result.message != "disabled":
                ledger.mark(
                    entity,
                    self.op,
                    node_token=node,
                    status="done" if result.status == "applied" else "skipped",
                    detail=result.message or "",
                )
            elif result.status == "failed":
                ledger.mark(
                    entity,
                    self.op,
                    node_token=node,
                    status="failed",
                    detail=result.message or "",
                )
            return result

    steps = []
    if enable_meta:
        steps.append(
            _LedgerStep(MetadataTableStep(tm, enabled=True), OP_METADATA_TABLE)
        )
    if enable_sep:
        steps.append(
            _LedgerStep(
                AttachmentSeparatorStep(tm, enabled=True), OP_ATTACHMENT_SEPARATOR
            )
        )
    if not steps:
        raise SystemExit("没有启用的 enrichment step")
    return EnrichmentPipeline(steps)


def main() -> int:
    ensure_utf8_stdio()
    args = _parse_args()
    selected = _selected_steps(args.steps)
    planned = _planned_ops(selected)

    job = ToolJob(
        title="文档增强回填（默认仅 TARGET）",
        ops=planned,
        skip_config_key="ENRICHMENT_SKIP_EXISTING",
        require_llm=False,
        require_target=True,
        require_scan_source=False,
        max_documents_attr="limit",
    )
    try:
        ctx = job.open(args, banner_extra=f"ops={planned}")
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except SystemExit:
        raise

    try:
        docs = ctx.docs
        if not docs:
            print("✅ 无需处理")
            return 0

        if args.dry_run:
            for i, d in enumerate(docs[:50], 1):
                print(
                    f"  {i}. {d.get('title') or ''} | "
                    f"node={d.get('node_token')} | "
                    f"path={d.get('target_path') or d.get('source_path') or ''}"
                )
            if len(docs) > 50:
                print(f"  … 另有 {len(docs) - 50} 篇")
            print("\n(dry-run，未写入)")
            return 0

        pipeline = _build_pipeline(
            ctx.tm,
            selected=selected,
            ledger=ctx.ledger,
            skip_existing=ctx.skip_existing,
        )
        reader = FeishuDocumentReader(ctx.tm)
        wiki_meta = None
        if not args.no_author and config.METADATA_TABLE_FETCH_AUTHOR:
            wiki_meta = WikiMetaClient(ctx.tm)

        counts: Dict[str, int] = {"applied": 0, "skipped": 0, "failed": 0}
        t0 = datetime.now()
        for i, doc in enumerate(docs, 1):
            title = doc.get("title") or ""
            node = doc.get("node_token") or ""
            obj = doc.get("obj_token") or node
            print(f"\n[{i}/{len(docs)}] {title or node}")

            content = ""
            if not args.skip_read_content and obj:
                try:
                    content = (
                        reader.get_raw_content(obj, wiki_node_token=node) or ""
                    )
                except Exception as exc:
                    print(f"  ⚠️ 读取正文失败: {exc}")

            author = ""
            if wiki_meta and node:
                try:
                    author = wiki_meta.get_author_display_name(node) or ""
                except Exception as exc:
                    print(f"  ⚠️ 作者解析失败: {exc}")

            enrich_ctx = EnrichmentContext(
                target_node_token=node,
                title=title,
                obj_token=obj,
                source_node_token="",
                source_path=doc.get("target_path") or doc.get("source_path") or "",
                content=content,
                tag=None,
                author=author,
            )
            results: List[StepResult] = pipeline.run(enrich_ctx)
            print(f"  → {format_results(results)}")
            for r in results:
                counts[r.status] = counts.get(r.status, 0) + 1

        elapsed = (datetime.now() - t0).total_seconds()
        print(
            f"\n✅ 回填完成: applied={counts.get('applied', 0)} "
            f"skipped={counts.get('skipped', 0)} "
            f"failed={counts.get('failed', 0)} | {elapsed:.1f}s"
        )
        job.finish_report(
            ctx,
            "enrich_copied_docs.json",
            {
                "dry_run": False,
                "ops": planned,
                "docs_total": len(docs) + ctx.ledger_skipped,
                "docs_processed": len(docs),
                "counts": counts,
                "elapsed_seconds": round(elapsed, 2),
            },
        )
        return 1 if counts.get("failed", 0) else 0
    finally:
        ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())

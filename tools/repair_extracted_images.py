# -*- coding: utf-8 -*-
"""
Rebind or re-extract images that were pasted by attachment extract.

Default document universe: TARGET copies. Wiki copy often leaves extracted
images bound to the SCAN source (or uploaded without extra.drive_route_token),
so they appear broken in the hub.

Usage:
  python -m tools.repair_extracted_images --dry-run --limit 20
  python -m tools.repair_extracted_images
  python -m tools.repair_extracted_images --reextract   # delete 附件： section and extract again
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from attachment.extractor import AttachmentExtractor
from state.operation_ledger import OP_REPAIR_EXTRACTED_IMAGES
from state.shared_state import SharedCopyState, default_worker_id
from tools.runner import ToolJob, add_scope_args, ensure_utf8_stdio
from util.progress import print_progress


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="修复附件提取写入的图片（默认仅 TARGET 副本）"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="最多处理条数（0=不限）")
    p.add_argument(
        "--reextract",
        action="store_true",
        help="删除「附件：」提取区后从附件重新提取（空图块/格式损坏时用）",
    )
    add_scope_args(p)
    return p.parse_args()


def _open_shared_state() -> Optional[SharedCopyState]:
    db = (getattr(config, "SHARED_STATE_DB", None) or "").strip()
    if not db:
        return None
    try:
        return SharedCopyState(
            db_path=db,
            worker_id=config.WORKER_ID or default_worker_id(),
        )
    except Exception as exc:
        print(f"⚠️ 无法打开 SHARED_STATE_DB: {exc}")
        return None


def main() -> int:
    ensure_utf8_stdio()
    args = _parse_args()
    job = ToolJob(
        title="修复附件提取图片（默认仅 TARGET）",
        ops=[OP_REPAIR_EXTRACTED_IMAGES],
        skip_config_key="REPAIR_EXTRACTED_IMAGES_SKIP_EXISTING",
        require_llm=False,
        require_target=True,
        require_scan_source=False,
        max_documents_attr="limit",
    )
    try:
        ctx = job.open(
            args,
            banner_extra=f"reextract={bool(args.reextract)}",
        )
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    try:
        docs = ctx.docs
        if not docs:
            print("✅ 无需处理")
            return 0

        shared = _open_shared_state()
        registry_by_copy: Dict[str, Dict] = {}
        if shared:
            registry_by_copy = shared.index_by_copied_node()
            print(f"🔗 共享去重库映射: {len(registry_by_copy)} 条 copied→source")

        extractor = AttachmentExtractor(ctx.tm)
        t0 = datetime.now()
        totals = {
            "docs": 0,
            "with_images": 0,
            "rebound": 0,
            "empty": 0,
            "failed": 0,
            "reextracted": 0,
        }

        if args.dry_run:
            preview = docs[:50]
            for i, doc in enumerate(preview, 1):
                node = doc.get("node_token") or ""
                src = (registry_by_copy.get(node) or {}).get("source_node_token") or ""
                print(
                    f"  {i}. {doc.get('title') or node} | target={node} | src={src or '-'}"
                )
            if len(docs) > 50:
                print(f"  … 另有 {len(docs) - 50} 篇")
            print(
                "\n(dry-run，未上传/未重提。正式跑会跳过没有「附件：」图片区的文档。)"
            )
            return 0

        for i, doc in enumerate(docs, 1):
            title = doc.get("title") or ""
            node = doc.get("node_token") or ""
            src = (registry_by_copy.get(node) or {}).get("source_node_token") or ""
            totals["docs"] += 1
            print(f"\n[{i}/{len(docs)}] {title or node}", flush=True)
            if src:
                print(f"  源节点={src}", flush=True)

            try:
                if args.reextract:
                    result = extractor.reextract_attachments(
                        node, title=title, source_path=""
                    )
                    totals["reextracted"] += 1 if result.status == "extracted" else 0
                    if result.status in ("failed", "partial"):
                        totals["failed"] += 1
                        print(f"  ❌ 重提 {result.status}: {result.error or ''}")
                    else:
                        print(f"  → 重提 {result.status}")
                    ctx.ledger.mark(
                        doc.get("obj_token") or node,
                        OP_REPAIR_EXTRACTED_IMAGES,
                        node_token=node,
                        status="done" if result.status != "failed" else "failed",
                        detail=result.status,
                    )
                else:
                    stats = extractor.repair_images(node, source_node_token=src)
                    n_img = int(stats.get("images") or 0)
                    if n_img:
                        totals["with_images"] += 1
                    totals["rebound"] += int(stats.get("rebound") or 0)
                    totals["empty"] += int(stats.get("empty") or 0)
                    totals["failed"] += int(stats.get("failed") or 0)
                    print(
                        f"  → images={n_img} rebound={stats.get('rebound')} "
                        f"empty={stats.get('empty')} failed={stats.get('failed')}",
                        flush=True,
                    )
                    if n_img == 0:
                        ctx.ledger.mark(
                            doc.get("obj_token") or node,
                            OP_REPAIR_EXTRACTED_IMAGES,
                            node_token=node,
                            status="skipped",
                            detail="no extracted images",
                        )
                    else:
                        ctx.ledger.mark(
                            doc.get("obj_token") or node,
                            OP_REPAIR_EXTRACTED_IMAGES,
                            node_token=node,
                            status="failed" if stats.get("failed") and not stats.get("rebound") else "done",
                            detail=(
                                f"rebound={stats.get('rebound')} "
                                f"empty={stats.get('empty')} failed={stats.get('failed')}"
                            ),
                        )
            except Exception as exc:
                totals["failed"] += 1
                print(f"  ❌ {exc}", flush=True)
                ctx.ledger.mark(
                    doc.get("obj_token") or node,
                    OP_REPAIR_EXTRACTED_IMAGES,
                    node_token=node,
                    status="failed",
                    detail=str(exc),
                )

            if i == 1 or i == len(docs) or i % max(1, int(config.PROGRESS_INTERVAL or 5)) == 0:
                print_progress(
                    "修复提取图片",
                    i,
                    len(docs),
                    start=t0,
                    extra=(
                        f"有图 {totals['with_images']} | "
                        f"重绑 {totals['rebound']} | 空块 {totals['empty']} | "
                        f"失败 {totals['failed']}"
                    ),
                )

        elapsed = (datetime.now() - t0).total_seconds()
        print(
            f"\n✅ 修复完成: docs={totals['docs']} with_images={totals['with_images']} "
            f"rebound={totals['rebound']} empty={totals['empty']} "
            f"failed={totals['failed']} reextracted={totals['reextracted']} | "
            f"{elapsed / 60:.1f} 分钟"
        )
        if totals["empty"] and not args.reextract:
            print(
                "提示: 有空图块（上传从未成功）。对这些文档再跑 "
                "`python -m tools.repair_extracted_images --reextract`"
            )
        job.finish_report(
            ctx,
            "repair_extracted_images.json",
            {
                "dry_run": False,
                "reextract": bool(args.reextract),
                "docs_total": len(docs) + ctx.ledger_skipped,
                "docs_processed": len(docs),
                "totals": totals,
                "elapsed_seconds": round(elapsed, 2),
            },
        )
        return 1 if totals["failed"] else 0
    finally:
        ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Retry failed attachment extractions from a previous run report."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from attachment.extractor import (
    AttachmentExtractor,
    load_failed_docs_from_report,
    print_attachment_summary,
    save_attachment_report,
)
from feishu.token_manager import TokenManager


def main() -> int:
    parser = argparse.ArgumentParser(description="重试失败的附件提取")
    parser.add_argument(
        "--report",
        default="logs/attachment_extract.json",
        help="上次运行的 attachment_extract.json 路径",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计待处理文档，不清理标题、不重新提取",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="跳过清理空标题（需已手动删除）",
    )
    args = parser.parse_args()

    try:
        failed_docs = load_failed_docs_from_report(args.report)
    except OSError as exc:
        print(f"❌ 无法读取报告: {args.report} — {exc}")
        return 1

    if not failed_docs:
        print("✅ 报告中没有失败的附件记录")
        return 0

    file_count = sum(len(doc["failed_files"]) for doc in failed_docs)
    print(f"📋 待重试: {len(failed_docs)} 篇文档，{file_count} 个失败附件")
    for doc in failed_docs:
        names = ", ".join(dict.fromkeys(doc["failed_files"]))
        print(f"   - {doc['title']}")
        print(f"     失败附件: {names}")

    if args.dry_run:
        print("\n(dry-run 模式，未执行清理或提取)")
        return 0

    config.validate()
    token_manager = TokenManager(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    extractor = AttachmentExtractor(token_manager)

    if not args.skip_cleanup:
        print("\n🧹 清理失败附件留下的空标题块...")
        removed_total = 0
        for doc in failed_docs:
            doc_token = extractor._get_doc_token(doc["node_token"])
            if not doc_token:
                print(f"  ⚠️ 跳过（无法解析 doc_token）: {doc['title']}")
                continue
            unique_names = list(dict.fromkeys(doc["failed_files"]))
            removed = extractor.clear_orphan_attachment_headings(
                doc_token, unique_names
            )
            removed_total += removed
            if removed:
                print(f"  ✓ {doc['title']}: 删除 {removed} 个空标题")
        print(f"共删除 {removed_total} 个空标题块")

    print("\n📎 重新提取附件...")
    docs_to_process = [
        {
            "node_token": doc["node_token"],
            "title": doc["title"],
            "source_path": doc["source_path"],
        }
        for doc in failed_docs
    ]
    start = datetime.now()
    stats, results = extractor.process_documents(docs_to_process, progress_interval=1)
    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n✅ 重试完成，耗时 {elapsed / 60:.1f} 分钟")
    print_attachment_summary(results, stats)
    report_path = save_attachment_report(results, stats, config.LOG_DIR)
    if report_path:
        print(f"📄 报告已保存: {report_path}")

    return 0 if stats.files_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

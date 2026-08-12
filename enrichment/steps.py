# -*- coding: utf-8 -*-
"""Built-in enrichment steps (idempotent)."""

from __future__ import annotations

from typing import Optional

from classify.doc_metadata import classify_doc_type_by_rules, extract_doc_metadata, format_classify_path
from enrichment.base import EnrichmentContext, StepResult
from enrichment.detect import (
    batch_delete_root_children,
    first_attachment_heading_index,
    has_attachment_section,
    has_metadata_table,
    insert_children_at,
    list_all_blocks,
    list_root_children,
    metadata_root_span,
    resolve_docx_id,
)
from enrichment.markers import attachment_section_blocks
from feishu.metadata_table import MetadataTableInserter
from feishu.token_manager import TokenManager


class MetadataTableStep:
    """Insert `文档元数据` table at document start if missing."""

    id = "metadata_table"
    title = "文档元数据表"

    def __init__(self, tm: TokenManager, *, enabled: bool = True):
        self.tm = tm
        self.enabled = enabled
        self._inserter = MetadataTableInserter(tm)

    def apply(self, ctx: EnrichmentContext) -> StepResult:
        if not self.enabled:
            return StepResult(self.id, "skipped", "disabled")
        if not ctx.target_node_token:
            return StepResult(self.id, "skipped", "no target_node_token")

        doc_id = resolve_docx_id(self.tm, ctx.target_node_token)
        if not doc_id:
            return StepResult(self.id, "skipped", "not a docx / resolve failed")

        blocks = list_all_blocks(self.tm, doc_id)
        force = bool((ctx.extras or {}).get("force_metadata"))
        if has_metadata_table(blocks):
            if not force:
                return StepResult(self.id, "skipped", "already present")
            root = list_root_children(self.tm, doc_id)
            span = metadata_root_span(root)
            if not span:
                return StepResult(self.id, "failed", "force: metadata span not found")
            ok_del, msg = batch_delete_root_children(
                self.tm, doc_id, start_index=span[0], end_index=span[1]
            )
            if not ok_del:
                return StepResult(self.id, "failed", f"force delete failed: {msg}")

        tag = ctx.tag
        source_path = ctx.source_path or ""
        source_folder = ""
        if source_path:
            source_folder = source_path.split(" / ")[0].strip()
        # Prefer LLM tag path; backfill has no tag → use TARGET folder breadcrumb
        classify_path = format_classify_path(tag) or (ctx.target_path or "").strip()
        meta = extract_doc_metadata(
            title=ctx.title or "",
            content=ctx.content or "",
            obj_token=ctx.obj_token or "",
            node_token=ctx.source_node_token or ctx.target_node_token,
            source_folder=source_folder,
            source_path=source_path,
            author=ctx.author or "",
            doc_type=classify_doc_type_by_rules(ctx.title or "", ctx.content or ""),
            tag=tag,
            classify_path=classify_path,
        )
        ok = self._inserter.insert_from_metadata(
            meta, wiki_node_token=ctx.target_node_token
        )
        if ok:
            return StepResult(
                self.id,
                "applied",
                f"{meta.product_line} / {meta.doc_type}",
            )
        return StepResult(self.id, "failed", "MetadataTableInserter failed")


class AttachmentSeparatorStep:
    """Insert attachment extract banner before first `附件：` heading if missing."""

    id = "attachment_separator"
    title = "附件提取分隔符"

    def __init__(self, tm: TokenManager, *, enabled: bool = True):
        self.tm = tm
        self.enabled = enabled

    def apply(self, ctx: EnrichmentContext) -> StepResult:
        if not self.enabled:
            return StepResult(self.id, "skipped", "disabled")
        if not ctx.target_node_token:
            return StepResult(self.id, "skipped", "no target_node_token")

        doc_id = resolve_docx_id(self.tm, ctx.target_node_token)
        if not doc_id:
            return StepResult(self.id, "skipped", "not a docx / resolve failed")

        all_blocks = list_all_blocks(self.tm, doc_id)
        if has_attachment_section(all_blocks):
            return StepResult(self.id, "skipped", "already present")

        root = list_root_children(self.tm, doc_id)
        idx = first_attachment_heading_index(root)
        if idx is None:
            return StepResult(self.id, "skipped", "no attachment heading")

        ok, msg = insert_children_at(
            self.tm,
            doc_id,
            attachment_section_blocks(),
            index=idx,
        )
        if ok:
            return StepResult(
                self.id, "applied", f"separator inserted at index={idx}"
            )
        return StepResult(self.id, "failed", msg)


def default_steps(
    tm: TokenManager,
    *,
    enable_metadata_table: bool = True,
    enable_attachment_separator: bool = True,
) -> list:
    return [
        MetadataTableStep(tm, enabled=enable_metadata_table),
        AttachmentSeparatorStep(tm, enabled=enable_attachment_separator),
    ]

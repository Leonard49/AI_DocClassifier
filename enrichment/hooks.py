# -*- coding: utf-8 -*-
"""Hook helpers for main.py and backfill tools."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from enrichment.base import EnrichmentContext, EnrichmentPipeline, StepResult
from enrichment.steps import default_steps
from feishu.token_manager import TokenManager


def build_default_pipeline(
    tm: TokenManager,
    *,
    enable_metadata_table: bool = True,
    enable_attachment_separator: bool = True,
) -> EnrichmentPipeline:
    return EnrichmentPipeline(
        default_steps(
            tm,
            enable_metadata_table=enable_metadata_table,
            enable_attachment_separator=enable_attachment_separator,
        )
    )


def enrich_after_copy(
    tm: TokenManager,
    *,
    target_node_token: str,
    title: str = "",
    obj_token: str = "",
    source_node_token: str = "",
    source_path: str = "",
    content: str = "",
    tag: Optional[Dict[str, Any]] = None,
    author: str = "",
    enable_metadata_table: bool = True,
    enable_attachment_separator: bool = True,
) -> List[StepResult]:
    """Run all enabled enrichment steps on a freshly copied document."""
    pipeline = build_default_pipeline(
        tm,
        enable_metadata_table=enable_metadata_table,
        enable_attachment_separator=enable_attachment_separator,
    )
    ctx = EnrichmentContext(
        target_node_token=target_node_token,
        title=title,
        obj_token=obj_token,
        source_node_token=source_node_token,
        source_path=source_path,
        content=content,
        tag=tag,
        author=author,
    )
    return pipeline.run(ctx)


def format_results(results: List[StepResult]) -> str:
    parts = [f"{r.step_id}={r.status}" + (f"({r.message})" if r.message else "") for r in results]
    return "; ".join(parts)

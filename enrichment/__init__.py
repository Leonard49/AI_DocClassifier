# -*- coding: utf-8 -*-
"""Document enrichment package (post-copy + backfill plugins)."""

from enrichment.base import EnrichmentContext, EnrichmentPipeline, StepResult
from enrichment.hooks import build_default_pipeline, enrich_after_copy, format_results

__all__ = [
    "EnrichmentContext",
    "EnrichmentPipeline",
    "StepResult",
    "build_default_pipeline",
    "enrich_after_copy",
    "format_results",
]

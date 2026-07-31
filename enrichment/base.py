# -*- coding: utf-8 -*-
"""Document enrichment pipeline: pluggable post-copy / backfill steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence


@dataclass
class EnrichmentContext:
    """Target document to enrich (usually the classified *copy*)."""

    target_node_token: str
    title: str = ""
    obj_token: str = ""  # source or copy obj_token when known
    source_node_token: str = ""
    source_path: str = ""
    content: str = ""
    tag: Optional[Dict[str, Any]] = None
    author: str = ""
    # Optional pre-built helpers injected by runner
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    step_id: str
    status: str  # applied | skipped | failed
    message: str = ""


class EnrichmentStep(Protocol):
    id: str
    title: str

    def apply(self, ctx: EnrichmentContext) -> StepResult:
        ...


class EnrichmentPipeline:
    def __init__(self, steps: Sequence[EnrichmentStep]):
        self.steps = list(steps)

    def run(self, ctx: EnrichmentContext) -> List[StepResult]:
        results: List[StepResult] = []
        for step in self.steps:
            try:
                results.append(step.apply(ctx))
            except Exception as exc:
                results.append(
                    StepResult(
                        step_id=getattr(step, "id", "unknown"),
                        status="failed",
                        message=str(exc),
                    )
                )
        return results

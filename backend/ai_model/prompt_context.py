"""DataSourceContext — one bag of state for the batch-analysis prompt (Q2.1).

Before this module existed, ``get_batch_analysis_prompt_parts`` took 13
optional kwargs. Every call site had to build them individually and
every new data source (traces, capabilities, cluster context, memory)
meant editing 3-5 call sites plus the signature. That kind of
positional-then-keyword fan-out is exactly how signatures drift out of
sync (missing kwarg on one call site → silent capability regression).

The context is a **dumb data holder**. It carries the same fields the
old kwargs did, with the same defaults. No behaviour, no derived state,
no serialisation — the prompt builder is still the single place that
knows how to render each section.

Design decisions:

* **Dataclass, not TypedDict.** We want typo safety at construction
  time (``ctx.logs = ...`` fails loudly) and a discoverable field
  list for future readers. TypedDict is for JSON shapes we serialise.
* **All fields default to None / empty.** Callers that don't have a
  data source leave the field unset — the prompt builder treats
  None/empty identically. This matches the pre-refactor kwarg default.
* **No validation.** The prompt builder is fail-open on garbage; if
  we start validating here we'd have to duplicate the "skip section
  when the shape is wrong" logic that already lives in prompts.py.
* **No factory helpers for now.** Building a context is 1-2 lines at
  each call site. When 3+ call sites need the same construction
  logic (e.g. "from AIAnalyzedBatch"), extract a classmethod then.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class DataSourceContext:
    """Everything the RCA prompt builder needs to render one batch.

    Only ``batch_data`` is required — every other field maps to an
    optional data source. Fields that are None or empty produce no
    section in the rendered prompt (with the exception of
    ``enabled_capabilities`` — see below).
    """

    # ----- required -----
    batch_data: dict[str, Any]

    # ----- optional signal payloads -----
    logs: list[str] | None = None
    system_metrics: dict[str, Any] | None = None
    metrics_summary: dict[str, Any] | None = None
    code_changes: list[dict[str, Any]] | None = None
    ci_cd_outputs: list[str] | None = None
    correlations: dict[str, Any] | None = None
    traces_summary: dict[str, Any] | None = None
    cicd_summary: dict[str, Any] | None = None

    # ----- optional narrative context -----
    project_context: dict[str, Any] | None = None
    sentinel_context: dict[str, Any] | None = None
    past_memories: str | None = None
    # What the engineer who requested an investigation reported seeing.
    operator_context: str | None = None

    # ----- capability gating (#29) -----
    # None = legacy/all-on behaviour; empty list = no data sources
    # configured (prompt emits a "none configured" hint). See
    # prompts._build_user_content for the interaction with the other
    # fields — omitted capabilities wipe their sections entirely.
    enabled_capabilities: Iterable[str] | None = None

"""Calibrated confidence model for the correlation engine (Q1.6).

Before this module existed, every correlation function in
``correlation_engine.py`` invented its own thresholds and its own
numeric scores. The same ``'MEDIUM'`` label attached to scores of
0.55, 0.60, and 0.70 across different correlation types; two
correlations emitted no score at all and relied on a downstream
fallback for ranking; the exact 1-hour / 2-hour / 4-hour cutoffs
had no documented rationale. The launch plan flagged this as Q1.6:
"HIGH/MEDIUM/LOW labels + numeric scores are magic numbers picked
by feel. AI trusts these labels — needs grounding."

**What this module does**

One place to look for every threshold and every score. The
correlation engine imports named constants and helpers from here
so a threshold review is one file, not seven.

**The label taxonomy**

- ``HIGH``:   Multiple independent signals point at the same cause,
              OR a single very-tight match (exact message overlap,
              deploy window inside the typical resource-manifestation
              band). Enough for the AI to reference in the root_cause
              statement without hedging.
- ``MEDIUM``: One strong signal, or several weaker ones that
              corroborate. Worth mentioning; not worth asserting
              causality on.
- ``LOW``:    Plausible temporal proximity but the window is stale
              or the join key is loose. Include for completeness;
              downstream should not treat as evidence.

**The numeric-score scale**

Scores are for **ordinal ranking** (``primary_correlation`` picks
the top-scored correlation across all types). They are NOT
probabilities — do not divide, average, or threshold-compare them
against external calibrations. The scale is:

- ``SCORE_HIGH   = 0.85`` — top of the confident band.
- ``SCORE_MEDIUM = 0.60`` — middle band. The 0.6 value was
                            chosen so ``MEDIUM`` always outranks a
                            missing-score fallback of 0.5 (see
                            ``correlation_engine.build_comprehensive_correlations``).
- ``SCORE_LOW    = 0.40`` — below every unlabelled fallback.

Same label = same score everywhere. If a caller wants to break
ties inside a band (e.g. exact-hit vs. near-hit within HIGH),
add a per-caller adjustment rather than a new magic number here.

**The time-proximity thresholds**

Two families of thresholds exist because two families of physics
apply:

*Commit → error / build failure (used in ``file_to_error`` and
``cicd_failure_to_commit``)*: A regression introduced by a commit
tends to fire as soon as the code path is exercised. Real-world
distribution from public post-mortems and our own dogfooding runs
is heavily front-loaded — the vast majority of commit-caused
errors surface inside the first hour. After 4 hours the signal
is dominated by unrelated events. Boundaries: **1h HIGH · 2h
MEDIUM · 4h LOW**.

*Deploy → resource anomaly (used in ``deployment_to_metric_spike``)*:
Memory leaks, warm-up GC pressure, and cache-priming spikes
typically manifest 15-60 minutes after a deploy, not immediately
(JIT warm-up, first-request cost). Spikes < 15 min after deploy
usually reflect a pre-existing issue plus a coincidental
deploy — noise. Spikes > 2 h are almost never causally linked.
Boundaries: **15-60 min HIGH · 60-120 min MEDIUM · drop
outside**.

Both are conservative — a MEDIUM label here is what other tools
call "possibly related". If you tighten the thresholds, expect
the AI to lean harder on individual correlations; if you loosen
them, expect more spurious HIGH labels in the RCA text.

**Testing contract**

Every threshold has a boundary test in
``Data/tests/test_correlation_confidence.py``. Do not change a
constant here without moving the corresponding boundary test.
"""

from __future__ import annotations

from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Label taxonomy
# ---------------------------------------------------------------------------

HIGH: str = 'HIGH'
MEDIUM: str = 'MEDIUM'
LOW: str = 'LOW'

VALID_LABELS = frozenset({HIGH, MEDIUM, LOW})


# ---------------------------------------------------------------------------
# Score scale (ordinal, not probabilistic)
# ---------------------------------------------------------------------------

SCORE_HIGH: float = 0.85
SCORE_MEDIUM: float = 0.60
SCORE_LOW: float = 0.40

# Fallback used by ``build_comprehensive_correlations`` when a
# correlation entry has no explicit ``score`` (legacy shape). Sits
# strictly BELOW ``SCORE_MEDIUM`` so a scored MEDIUM always
# outranks a fallbacked one.
SCORE_MISSING_FALLBACK_MEDIUM: float = 0.50
SCORE_MISSING_FALLBACK_OTHER: float = 0.30


def score_for(label: str) -> float:
    """Return the canonical numeric score for a label."""
    if label == HIGH:
        return SCORE_HIGH
    if label == MEDIUM:
        return SCORE_MEDIUM
    if label == LOW:
        return SCORE_LOW
    return SCORE_MISSING_FALLBACK_OTHER


# ---------------------------------------------------------------------------
# Time proximity — commit → error / build failure
# ---------------------------------------------------------------------------

# One-hour boundary. Below this a commit-triggered error is the
# dominant explanation; above it, the causal signal weakens.
TIME_PROXIMITY_HIGH_SECONDS: int = 3600
TIME_PROXIMITY_MEDIUM_SECONDS: int = 7200
TIME_PROXIMITY_LOW_SECONDS: int = 14400


def confidence_from_time_proximity(
    seconds_since_commit: float,
) -> Optional[Tuple[str, float]]:
    """Map "how long after the commit did the error/failure fire" to
    a (label, score) pair.

    Returns ``None`` when the gap is either negative (event before
    commit — not causal) or beyond ``TIME_PROXIMITY_LOW_SECONDS``
    (too stale to include). Callers should drop the correlation on
    ``None``.

    Boundary semantics: ``seconds_since_commit == 3600`` is exactly
    on the HIGH/MEDIUM edge and rounds to MEDIUM. That's the
    conservative choice — the strict inequality ``< HIGH`` gives us
    HIGH, everything else falls into the next band down. The same
    boundary logic applies at 7200 and 14400.
    """
    if seconds_since_commit <= 0:
        return None
    if seconds_since_commit < TIME_PROXIMITY_HIGH_SECONDS:
        return (HIGH, SCORE_HIGH)
    if seconds_since_commit < TIME_PROXIMITY_MEDIUM_SECONDS:
        return (MEDIUM, SCORE_MEDIUM)
    if seconds_since_commit < TIME_PROXIMITY_LOW_SECONDS:
        return (LOW, SCORE_LOW)
    return None


# ---------------------------------------------------------------------------
# Time proximity — deploy → resource anomaly
# ---------------------------------------------------------------------------

DEPLOY_METRIC_LOWER_BOUND_MINUTES: float = 15.0
DEPLOY_METRIC_HIGH_UPPER_MINUTES: float = 60.0
DEPLOY_METRIC_MEDIUM_UPPER_MINUTES: float = 120.0


def confidence_from_deploy_metric_lag(
    minutes_since_deploy: float,
) -> Optional[Tuple[str, float]]:
    """Map "how long after the deploy did the resource anomaly fire"
    to a (label, score) pair.

    Returns ``None`` when the lag is outside the plausible
    manifestation window (``< 15 min`` or ``> 120 min``). Callers
    should drop the correlation on ``None``.
    """
    if minutes_since_deploy < DEPLOY_METRIC_LOWER_BOUND_MINUTES:
        return None
    if minutes_since_deploy < DEPLOY_METRIC_HIGH_UPPER_MINUTES:
        return (HIGH, SCORE_HIGH)
    if minutes_since_deploy <= DEPLOY_METRIC_MEDIUM_UPPER_MINUTES:
        return (MEDIUM, SCORE_MEDIUM)
    return None

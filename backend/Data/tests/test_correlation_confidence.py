"""Boundary tests for the calibrated confidence model (Q1.6).

The correlation engine consumes ``confidence_from_time_proximity`` and
``confidence_from_deploy_metric_lag`` in a handful of places. If a
threshold shifts silently, the AI's HIGH/MEDIUM/LOW labels drift and
we discover it via analyst complaints, not tests. These tests pin
every documented boundary — a threshold change without a matching
test update is caught here first.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from Data.correlation_confidence import (
    DEPLOY_METRIC_HIGH_UPPER_MINUTES,
    DEPLOY_METRIC_LOWER_BOUND_MINUTES,
    DEPLOY_METRIC_MEDIUM_UPPER_MINUTES,
    HIGH,
    LOW,
    MEDIUM,
    SCORE_HIGH,
    SCORE_LOW,
    SCORE_MEDIUM,
    SCORE_MISSING_FALLBACK_MEDIUM,
    SCORE_MISSING_FALLBACK_OTHER,
    TIME_PROXIMITY_HIGH_SECONDS,
    TIME_PROXIMITY_LOW_SECONDS,
    TIME_PROXIMITY_MEDIUM_SECONDS,
    VALID_LABELS,
    confidence_from_deploy_metric_lag,
    confidence_from_time_proximity,
    score_for,
)


class LabelTaxonomyTest(SimpleTestCase):

    def test_valid_labels_is_the_three_documented_labels(self):
        self.assertEqual(VALID_LABELS, frozenset({'HIGH', 'MEDIUM', 'LOW'}))

    def test_score_ordering_high_medium_low(self):
        self.assertGreater(SCORE_HIGH, SCORE_MEDIUM)
        self.assertGreater(SCORE_MEDIUM, SCORE_LOW)

    def test_scored_medium_outranks_unscored_medium_fallback(self):
        """The whole point of the two fallback constants is that a
        scored MEDIUM always wins the ranking against a legacy entry
        with no score — otherwise ``primary_correlation`` picks the
        wrong root cause."""
        self.assertGreater(SCORE_MEDIUM, SCORE_MISSING_FALLBACK_MEDIUM)
        self.assertGreater(
            SCORE_MISSING_FALLBACK_MEDIUM, SCORE_MISSING_FALLBACK_OTHER,
        )

    def test_score_for_maps_labels(self):
        self.assertEqual(score_for(HIGH), SCORE_HIGH)
        self.assertEqual(score_for(MEDIUM), SCORE_MEDIUM)
        self.assertEqual(score_for(LOW), SCORE_LOW)

    def test_score_for_unknown_label_returns_other_fallback(self):
        self.assertEqual(score_for('BOGUS'), SCORE_MISSING_FALLBACK_OTHER)


class TimeProximityBoundaryTest(SimpleTestCase):
    """Every threshold boundary is pinned so a stealth cutoff change
    surfaces here instead of in downstream RCA text."""

    def test_zero_or_negative_lag_returns_none(self):
        # A log written before the commit isn't causally correlated.
        self.assertIsNone(confidence_from_time_proximity(0))
        self.assertIsNone(confidence_from_time_proximity(-1))

    def test_just_inside_high_boundary_is_high(self):
        # 3599 seconds — one second under the 1h boundary.
        outcome = confidence_from_time_proximity(TIME_PROXIMITY_HIGH_SECONDS - 1)
        self.assertEqual(outcome, (HIGH, SCORE_HIGH))

    def test_exact_high_boundary_falls_to_medium(self):
        # By design: strict inequality on the upper band. Exactly on
        # the HIGH/MEDIUM edge → MEDIUM. That's the conservative
        # choice documented in the module.
        outcome = confidence_from_time_proximity(TIME_PROXIMITY_HIGH_SECONDS)
        self.assertEqual(outcome, (MEDIUM, SCORE_MEDIUM))

    def test_just_inside_medium_boundary_is_medium(self):
        outcome = confidence_from_time_proximity(TIME_PROXIMITY_MEDIUM_SECONDS - 1)
        self.assertEqual(outcome, (MEDIUM, SCORE_MEDIUM))

    def test_exact_medium_boundary_falls_to_low(self):
        outcome = confidence_from_time_proximity(TIME_PROXIMITY_MEDIUM_SECONDS)
        self.assertEqual(outcome, (LOW, SCORE_LOW))

    def test_just_inside_low_boundary_is_low(self):
        outcome = confidence_from_time_proximity(TIME_PROXIMITY_LOW_SECONDS - 1)
        self.assertEqual(outcome, (LOW, SCORE_LOW))

    def test_exact_low_boundary_drops(self):
        # A commit whose error surfaces exactly 4h later is dropped —
        # we don't emit an even-lower band; there's no evidence for a
        # causal link past this window.
        self.assertIsNone(
            confidence_from_time_proximity(TIME_PROXIMITY_LOW_SECONDS),
        )

    def test_very_stale_lag_drops(self):
        self.assertIsNone(confidence_from_time_proximity(60 * 60 * 24))

    def test_sub_second_lag_is_high(self):
        outcome = confidence_from_time_proximity(1)
        self.assertEqual(outcome, (HIGH, SCORE_HIGH))


class DeployMetricBoundaryTest(SimpleTestCase):

    def test_just_below_lower_bound_drops(self):
        # < 15 min — likely a pre-existing issue plus a coincidental
        # deploy. Drop, don't downgrade.
        self.assertIsNone(
            confidence_from_deploy_metric_lag(
                DEPLOY_METRIC_LOWER_BOUND_MINUTES - 0.01,
            ),
        )

    def test_exact_lower_bound_is_high(self):
        outcome = confidence_from_deploy_metric_lag(DEPLOY_METRIC_LOWER_BOUND_MINUTES)
        self.assertEqual(outcome, (HIGH, SCORE_HIGH))

    def test_just_inside_high_band_is_high(self):
        outcome = confidence_from_deploy_metric_lag(
            DEPLOY_METRIC_HIGH_UPPER_MINUTES - 0.01,
        )
        self.assertEqual(outcome, (HIGH, SCORE_HIGH))

    def test_exact_high_upper_boundary_falls_to_medium(self):
        outcome = confidence_from_deploy_metric_lag(DEPLOY_METRIC_HIGH_UPPER_MINUTES)
        self.assertEqual(outcome, (MEDIUM, SCORE_MEDIUM))

    def test_just_inside_medium_upper_boundary_is_medium(self):
        outcome = confidence_from_deploy_metric_lag(
            DEPLOY_METRIC_MEDIUM_UPPER_MINUTES - 0.01,
        )
        self.assertEqual(outcome, (MEDIUM, SCORE_MEDIUM))

    def test_exact_medium_upper_boundary_is_still_medium(self):
        # The <= at the upper deploy-metric boundary is intentional —
        # 120 min lag is the last minute of the plausible-attribution
        # window (see confidence_from_deploy_metric_lag docstring).
        outcome = confidence_from_deploy_metric_lag(DEPLOY_METRIC_MEDIUM_UPPER_MINUTES)
        self.assertEqual(outcome, (MEDIUM, SCORE_MEDIUM))

    def test_beyond_medium_upper_drops(self):
        # Stale enough to be noise.
        self.assertIsNone(
            confidence_from_deploy_metric_lag(
                DEPLOY_METRIC_MEDIUM_UPPER_MINUTES + 0.01,
            ),
        )
        self.assertIsNone(confidence_from_deploy_metric_lag(600.0))


class RationaleDocumentedTest(SimpleTestCase):
    """Meta-test: the module docstring is the source of truth for
    every constant. Assertions here catch drift between the numbers
    the engine actually uses and the numbers the docstring claims.
    """

    def test_time_proximity_thresholds_match_documented_rationale(self):
        # Documented as "1h HIGH · 2h MEDIUM · 4h LOW".
        self.assertEqual(TIME_PROXIMITY_HIGH_SECONDS, 60 * 60)
        self.assertEqual(TIME_PROXIMITY_MEDIUM_SECONDS, 2 * 60 * 60)
        self.assertEqual(TIME_PROXIMITY_LOW_SECONDS, 4 * 60 * 60)

    def test_deploy_metric_thresholds_match_documented_rationale(self):
        # Documented as "15-60 min HIGH · 60-120 min MEDIUM".
        self.assertEqual(DEPLOY_METRIC_LOWER_BOUND_MINUTES, 15.0)
        self.assertEqual(DEPLOY_METRIC_HIGH_UPPER_MINUTES, 60.0)
        self.assertEqual(DEPLOY_METRIC_MEDIUM_UPPER_MINUTES, 120.0)

    def test_score_scale_matches_documented_values(self):
        # Documented as 0.85 / 0.60 / 0.40. If we ever tune these,
        # move the docstring in correlation_confidence.py first.
        self.assertEqual(SCORE_HIGH, 0.85)
        self.assertEqual(SCORE_MEDIUM, 0.60)
        self.assertEqual(SCORE_LOW, 0.40)

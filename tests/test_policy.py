import pytest

from slam_regression.config import MetricThreshold
from slam_regression.errors import MetricsError
from slam_regression.policy import compare_metric, evaluate


def rel(p):
    return MetricThreshold(max_relative_regression_percent=p)


def rel_abs(p, a):
    return MetricThreshold(max_relative_regression_percent=p, max_absolute_regression=a)


def ceiling(v):
    return MetricThreshold(max_value=v)


class TestRelativeRule:
    def test_pass_when_change_below_threshold(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.105, threshold=rel(10.0))
        assert result.passed is True
        assert result.change_percent == pytest.approx(5.0)

    def test_boundary_change_equals_threshold_passes(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.11, threshold=rel(10.0))
        assert result.passed is True
        assert result.change_percent == pytest.approx(10.0)

    def test_fail_when_change_exceeds_threshold(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.111, threshold=rel(10.0))
        assert result.passed is False

    def test_improvement_always_passes(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.05, threshold=rel(0.0))
        assert result.passed is True
        assert result.change_percent == pytest.approx(-50.0)

    def test_zero_threshold_rejects_any_increase(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.1001, threshold=rel(0.0))
        assert result.passed is False

    def test_zero_baseline_and_zero_candidate_passes(self):
        result = compare_metric("ate_rmse", baseline=0.0, candidate=0.0, threshold=rel(10.0))
        assert result.passed is True
        assert result.change_percent == 0.0

    def test_zero_baseline_with_positive_candidate_fails_with_note(self):
        result = compare_metric("ate_rmse", baseline=0.0, candidate=0.02, threshold=rel(10.0))
        assert result.passed is False
        assert result.change_percent is None
        assert "relative change is undefined" in result.note

    def test_no_threshold_reports_without_gating(self):
        result = compare_metric("ate_rmse", baseline=0.1, candidate=100.0, threshold=MetricThreshold())
        assert result.passed is True
        assert "no threshold" in result.note

    def test_negative_values_rejected(self):
        with pytest.raises(MetricsError, match="non-negative"):
            compare_metric("ate_rmse", baseline=-1.0, candidate=0.0, threshold=rel(10.0))


class TestAbsoluteRule:
    def test_small_baseline_passes_within_absolute_budget(self):
        # 1 mm increase is +100% relative; with only an absolute budget
        # configured (3 cm), it passes. Configure only the rules you want.
        threshold = MetricThreshold(max_absolute_regression=0.03)
        result = compare_metric("ate_rmse", baseline=0.001, candidate=0.002, threshold=threshold)
        assert result.passed is True
        assert result.absolute_excess == pytest.approx(0.001)

    def test_absolute_budget_fails_despite_passing_relative(self):
        # 9% of a 10 m baseline is 0.9 m — inside 10% relative, over 0.1 m budget.
        result = compare_metric("ate_rmse", baseline=10.0, candidate=10.9, threshold=rel_abs(10.0, 0.1))
        assert result.passed is False
        assert "exceeds budget" in result.note

    def test_absolute_budget_alone_gates(self):
        threshold = MetricThreshold(max_absolute_regression=0.02)
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.15, threshold=threshold)
        assert result.passed is False

    def test_absolute_budget_improvement_passes(self):
        threshold = MetricThreshold(max_absolute_regression=0.0)
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.05, threshold=threshold)
        assert result.passed is True


class TestCeilingRule:
    def test_ceiling_fail(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.30, threshold=ceiling(0.25))
        assert result.passed is False
        assert "ceiling" in result.note

    def test_ceiling_pass(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.12, threshold=ceiling(0.25))
        assert result.passed is True

    def test_ceiling_is_absolute_not_relative(self):
        # Ceiling applies to the candidate value itself, even on improvement.
        result = compare_metric("ate_rmse", baseline=0.50, candidate=0.30, threshold=ceiling(0.25))
        assert result.passed is False


class TestCombinedRules:
    def test_any_rule_failure_fails(self):
        # Relative passes (5% of 10 = 0.1%... within 10%), ceiling fails.
        threshold = MetricThreshold(
            max_relative_regression_percent=10.0, max_absolute_regression=0.5, max_value=0.05
        )
        result = compare_metric("ate_rmse", baseline=10.0, candidate=10.5, threshold=threshold)
        assert result.passed is False
        assert "ceiling" in result.note

    def test_all_rules_pass(self):
        threshold = MetricThreshold(
            max_relative_regression_percent=10.0, max_absolute_regression=0.5, max_value=0.25
        )
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.105, threshold=threshold)
        assert result.passed is True

    def test_to_dict_contains_all_rule_fields(self):
        payload = compare_metric(
            "ate_rmse", 0.1, 0.12, rel_abs(10.0, 0.05)
        ).to_dict()
        for key in ("absolute_budget", "absolute_excess", "max_value", "threshold_percent"):
            assert key in payload


class TestEvaluate:
    def test_all_metrics_combined_verdict(self):
        thresholds = {
            "ate_rmse": rel(10.0),
            "rpe_translation_rmse": rel(10.0),
        }
        baseline = {"ate_rmse": 0.10, "rpe_translation_rmse": 0.01}
        passing = {"ate_rmse": 0.10, "rpe_translation_rmse": 0.0105}
        failing = {"ate_rmse": 0.10, "rpe_translation_rmse": 0.02}
        assert evaluate(baseline, passing, list(thresholds), thresholds).passed is True
        assert evaluate(baseline, failing, list(thresholds), thresholds).passed is False

    def test_missing_baseline_metric_is_reported(self):
        with pytest.raises(MetricsError, match="missing metric"):
            evaluate({}, {"ate_rmse": 0.1}, ["ate_rmse"], {"ate_rmse": rel(10.0)})

    def test_missing_candidate_metric_is_reported(self):
        with pytest.raises(MetricsError, match="missing metric"):
            evaluate({"ate_rmse": 0.1}, {}, ["ate_rmse"], {"ate_rmse": rel(10.0)})

    def test_coverage_none_by_default_and_serialized_when_present(self):
        result = evaluate({"ate_rmse": 0.1}, {"ate_rmse": 0.1}, ["ate_rmse"], {"ate_rmse": rel(10.0)})
        assert result.coverage is None
        result.coverage = {"matched_pose_count": 5, "passed": True}
        assert result.to_dict()["coverage"]["matched_pose_count"] == 5

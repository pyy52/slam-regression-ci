import pytest

from slam_regression.errors import MetricsError
from slam_regression.policy import compare_metric, evaluate


class TestCompareMetric:
    def test_pass_when_change_below_threshold(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.105, threshold_percent=10.0)
        assert result.passed is True
        assert result.change_percent == pytest.approx(5.0)

    def test_boundary_change_equals_threshold_passes(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.11, threshold_percent=10.0)
        assert result.passed is True
        assert result.change_percent == pytest.approx(10.0)

    def test_fail_when_change_exceeds_threshold(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.111, threshold_percent=10.0)
        assert result.passed is False

    def test_improvement_always_passes(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.05, threshold_percent=0.0)
        assert result.passed is True
        assert result.change_percent == pytest.approx(-50.0)

    def test_zero_threshold_rejects_any_increase(self):
        result = compare_metric("ate_rmse", baseline=0.10, candidate=0.1001, threshold_percent=0.0)
        assert result.passed is False

    def test_zero_baseline_and_zero_candidate_passes(self):
        result = compare_metric("ate_rmse", baseline=0.0, candidate=0.0, threshold_percent=10.0)
        assert result.passed is True
        assert result.change_percent == 0.0

    def test_zero_baseline_with_positive_candidate_fails_with_note(self):
        result = compare_metric("ate_rmse", baseline=0.0, candidate=0.02, threshold_percent=10.0)
        assert result.passed is False
        assert result.change_percent is None
        assert "relative change is undefined" in result.note

    def test_no_threshold_reports_without_gating(self):
        result = compare_metric("ate_rmse", baseline=0.1, candidate=100.0, threshold_percent=None)
        assert result.passed is True
        assert "no threshold" in result.note

    def test_negative_values_rejected(self):
        with pytest.raises(MetricsError, match="non-negative"):
            compare_metric("ate_rmse", baseline=-1.0, candidate=0.0, threshold_percent=10.0)


class TestEvaluate:
    def test_all_metrics_combined_verdict(self):
        thresholds = {"ate_rmse": 10.0, "rpe_translation_rmse": 10.0}
        baseline = {"ate_rmse": 0.10, "rpe_translation_rmse": 0.01}
        passing = {"ate_rmse": 0.10, "rpe_translation_rmse": 0.0105}
        failing = {"ate_rmse": 0.10, "rpe_translation_rmse": 0.02}
        assert evaluate(baseline, passing, list(thresholds), thresholds).passed is True
        assert evaluate(baseline, failing, list(thresholds), thresholds).passed is False

    def test_missing_baseline_metric_is_reported(self):
        with pytest.raises(MetricsError, match="missing metric"):
            evaluate({}, {"ate_rmse": 0.1}, ["ate_rmse"], {"ate_rmse": 10.0})

    def test_missing_candidate_metric_is_reported(self):
        with pytest.raises(MetricsError, match="missing metric"):
            evaluate({"ate_rmse": 0.1}, {}, ["ate_rmse"], {"ate_rmse": 10.0})

    def test_to_dict_is_stable(self):
        result = evaluate(
            {"ate_rmse": 0.1}, {"ate_rmse": 0.1}, ["ate_rmse"], {"ate_rmse": 10.0}
        )
        payload = result.to_dict()
        assert payload["passed"] is True
        assert payload["comparisons"][0]["metric"] == "ate_rmse"
        assert "warnings" in payload

import json

import pytest

from slam_regression.config import MetricThreshold
from slam_regression.errors import MetricsError
from slam_regression.policy import compare_metric, compare_metric_distribution
from test_cli import fixed_noise, line_positions, run_compare, run_record, write_tum


@pytest.fixture
def multi_env(tmp_path):
    """Ground truth plus three same-quality baseline runs and a degraded run."""
    n = 30
    reference = write_tum(tmp_path / "reference.tum", line_positions(n, 0.1))
    runs = [
        write_tum(tmp_path / f"run{i}.tum", line_positions(n, 0.1, fixed_noise(n, 0.02, seed=seed)))
        for i, seed in enumerate([7, 9, 11], start=1)
    ]
    degraded = write_tum(
        tmp_path / "degraded.tum", line_positions(n, 0.1, fixed_noise(n, 0.06, seed=13))
    )
    return {"reference": reference, "runs": runs, "degraded": degraded, "tmp": tmp_path}


class TestMultiRunRecord:
    def test_three_runs_produce_v2_baseline_with_stats(self, multi_env):
        out = str(multi_env["tmp"] / "baseline.json")
        code = run_record(multi_env["reference"], multi_env["runs"], out)
        assert code == 0
        payload = json.load(open(out))
        assert payload["schema"] == "slam-regression-baseline/v2"
        runs = payload["runs"]["ate_rmse"]
        assert len(runs) == 3
        stats = payload["metrics"]["ate_rmse"]
        assert stats["n"] == 3
        assert stats["median"] == pytest.approx(sorted(runs)[1])
        assert stats["mad"] == pytest.approx(
            sorted(abs(v - stats["median"]) for v in runs)[1]
        )
        assert stats["min"] == pytest.approx(min(runs))
        assert stats["max"] == pytest.approx(max(runs))
        assert len(payload["input_hashes"]["estimates"]) == 3
        assert payload["inputs"]["estimates"] == ["run1.tum", "run2.tum", "run3.tum"]

    def test_single_run_stays_v1(self, multi_env):
        out = str(multi_env["tmp"] / "baseline.json")
        assert run_record(multi_env["reference"], multi_env["runs"][:1], out) == 0
        payload = json.load(open(out))
        assert payload["schema"] == "slam-regression-baseline/v1"
        assert isinstance(payload["metrics"]["ate_rmse"], float)


class TestMultiRunCompare:
    def test_median_of_candidate_runs_gates_against_v2(self, multi_env, capsys):
        baseline_json = str(multi_env["tmp"] / "baseline.json")
        assert run_record(multi_env["reference"], multi_env["runs"], baseline_json) == 0

        # Two good candidate runs: median of medians ~ same quality -> PASS.
        candidate_runs = multi_env["runs"][:2]
        code = run_compare(baseline_json, multi_env["reference"], candidate_runs)
        out = capsys.readouterr().out
        assert code == 0
        assert "STATUS: PASS" in out

    def test_degraded_candidate_fails_v2_gate(self, multi_env, capsys):
        baseline_json = str(multi_env["tmp"] / "baseline.json")
        assert run_record(multi_env["reference"], multi_env["runs"], baseline_json) == 0
        code = run_compare(baseline_json, multi_env["reference"], [multi_env["degraded"]])
        out = capsys.readouterr().out
        assert code == 1
        assert "STATUS: FAIL" in out

    def test_report_shows_run_counts(self, multi_env, tmp_path):
        baseline_json = str(multi_env["tmp"] / "baseline.json")
        assert run_record(multi_env["reference"], multi_env["runs"], baseline_json) == 0
        report_md = str(multi_env["tmp"] / "report.md")
        code = run_compare(
            baseline_json,
            multi_env["reference"],
            multi_env["runs"][:2],
            extra=["--report", report_md],
        )
        assert code == 0
        text = open(report_md).read()
        assert "- baseline runs: 3 (baseline column is the median)" in text
        assert "- candidate runs: 2 (candidate column is the median)" in text

    def test_json_report_carries_candidate_run_stats(self, multi_env, tmp_path):
        baseline_json = str(multi_env["tmp"] / "baseline.json")
        assert run_record(multi_env["reference"], multi_env["runs"], baseline_json) == 0
        report_json = str(multi_env["tmp"] / "report.json")
        run_compare(
            baseline_json,
            multi_env["reference"],
            multi_env["runs"][:2],
            extra=["--json", report_json],
        )
        payload = json.load(open(report_json))
        assert payload["candidate"]["count"] == 2
        assert payload["candidate"]["runs"]["ate_rmse"]["n"] == 2


class TestMadRule:
    """Robust max_mad_multiples gate (unit level via compare_metric_distribution)."""

    def _stats(self, values):
        ordered = sorted(values)
        n = len(ordered)
        median = ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
        devs = sorted(abs(v - median) for v in values)
        mad = devs[n // 2] if n % 2 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])
        return {"n": n, "median": median, "mad": mad}

    def test_within_run_spread_passes_even_beyond_relative_threshold(self):
        # 10 runs tightly clustered at ~0.10; candidate 0.105 is +5% (passes
        # a 10% rule anyway), but check the MAD rule alone tolerates it.
        stats = self._stats([0.100, 0.101, 0.099, 0.100, 0.101, 0.099, 0.100, 0.101, 0.099, 0.100])
        threshold = MetricThreshold(max_mad_multiples=3.0)
        result = compare_metric_distribution("ate_rmse", stats, 0.102, threshold)
        assert result.passed is True

    def test_beyond_run_spread_fails_even_within_relative_threshold(self):
        # Candidate is only +6% (inside a 10% relative rule) but 20x the MAD.
        stats = self._stats([0.100, 0.101, 0.099, 0.100, 0.101, 0.099, 0.100, 0.101, 0.099, 0.100])
        threshold = MetricThreshold(max_relative_regression_percent=10.0, max_mad_multiples=3.0)
        result = compare_metric_distribution("ate_rmse", stats, 0.106, threshold)
        assert result.passed is False
        assert "MAD" in result.note

    def test_invalid_distribution_rejected(self):
        with pytest.raises(MetricsError, match="distribution stats"):
            compare_metric_distribution("ate_rmse", {}, 0.1, MetricThreshold(max_mad_multiples=3.0))

    def test_classic_single_run_path_ignores_distributions(self):
        result = compare_metric(
            "ate_rmse", 0.10, 0.105, MetricThreshold(max_relative_regression_percent=10.0)
        )
        assert result.passed is True


class TestMadOnlyGate:
    """Audit P0: a MAD-only gate must count as an active gate (no 'no threshold' note)."""

    def _stats(self, values):
        ordered = sorted(values)
        n = len(ordered)
        median = ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
        devs = sorted(abs(v - median) for v in values)
        mad = devs[n // 2] if n % 2 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])
        return {"n": n, "median": median, "mad": mad}

    def test_mad_only_pass_has_no_no_threshold_note(self):
        stats = self._stats([0.100, 0.101, 0.099, 0.100, 0.101])
        result = compare_metric_distribution(
            "ate_rmse", stats, 0.101, MetricThreshold(max_mad_multiples=3.0)
        )
        assert result.passed is True
        assert result.note is None  # no "no threshold configured" note
        assert result.mad_budget == pytest.approx(0.100 + 3 * 0.001)
        assert result.max_mad_multiples == 3.0
        payload = result.to_dict()
        assert payload["mad_budget"] == pytest.approx(0.103)
        assert payload["max_mad_multiples"] == 3.0

    def test_mad_only_fail_reports_mad_budget(self):
        stats = self._stats([0.100, 0.101, 0.099, 0.100, 0.101])
        result = compare_metric_distribution(
            "ate_rmse", stats, 0.106, MetricThreshold(max_mad_multiples=3.0)
        )
        assert result.passed is False
        assert "MAD" in result.note
        assert result.mad_budget == pytest.approx(0.103)

    def test_mad_plus_relative_combined(self):
        stats = self._stats([0.100, 0.101, 0.099, 0.100, 0.101])
        threshold = MetricThreshold(
            max_relative_regression_percent=1.0, max_mad_multiples=3.0
        )
        # +2% relative: fails relative rule, passes MAD rule.
        result = compare_metric_distribution("ate_rmse", stats, 0.102, threshold)
        assert result.passed is False
        assert "relative change is undefined" not in (result.note or "")


class TestNumPairsDistribution:
    def test_multi_run_compare_reports_pair_distribution(self, multi_env, tmp_path):
        baseline_json = str(tmp_path / "baseline.json")
        assert run_record(multi_env["reference"], multi_env["runs"], baseline_json) == 0
        report_json = str(tmp_path / "report.json")
        run_compare(
            baseline_json,
            multi_env["reference"],
            multi_env["runs"][:2],
            extra=["--json", report_json],
        )
        payload = json.load(open(report_json))
        dist = payload["candidate"]["num_pairs_distribution"]
        assert dist["min"] == dist["median"] == dist["max"] == 30

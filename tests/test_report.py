import json

from slam_regression.cli import main
from slam_regression.policy import ComparisonResult, compare_metric
from slam_regression.report import ReportContext, render_markdown
from test_cli import fixed_noise, line_positions, write_tum


def make_context(**overrides):
    defaults = dict(
        tool_version="0.1.0",
        created_utc="2026-09-18T00:00:00Z",
        baseline_file="baseline_metrics.json",
        inputs={"reference": "reference.tum", "estimate": "candidate.tum"},
        settings={
            "association": {"max_timestamp_diff": 0.01},
            "alignment": {"enabled": True, "correct_scale": False},
            "rpe_delta": 1,
        },
        candidate_num_pairs=30,
        warnings=[],
    )
    defaults.update(overrides)
    return ReportContext(**defaults)


class TestRenderMarkdown:
    def test_passing_report_contains_verdict_and_table(self):
        result = ComparisonResult(
            passed=True,
            comparisons=[
                compare_metric("ate_rmse", 0.10, 0.105, 10.0),
                compare_metric("rpe_translation_rmse", 0.01, 0.0105, 10.0),
            ],
        )
        text = render_markdown(result, make_context())
        assert "**Verdict: PASS**" in text
        assert "| ATE RMSE | 0.100000 m | 0.105000 m | +5.00% | +10.00% | PASS |" in text
        assert "| RPE translation RMSE |" in text
        assert "- reference: `reference.tum`" in text
        assert "- matched pose pairs: 30" in text
        assert "- alignment: Umeyama (rigid SE(3))" in text

    def test_failing_report_marks_verdict_and_row(self):
        result = ComparisonResult(
            passed=False, comparisons=[compare_metric("ate_rmse", 0.10, 0.20, 10.0)]
        )
        text = render_markdown(result, make_context())
        assert "**Verdict: FAIL**" in text
        assert "| ATE RMSE | 0.100000 m | 0.200000 m | +100.00% | +10.00% | FAIL |" in text

    def test_note_and_warning_sections(self):
        result = ComparisonResult(
            passed=False, comparisons=[compare_metric("ate_rmse", 0.0, 0.02, 10.0)]
        )
        text = render_markdown(result, make_context(warnings=["baseline settings mismatch"]))
        assert "## Notes" in text
        assert "relative change is undefined" in text
        assert "- baseline settings mismatch" in text

    def test_unset_threshold_and_change_render_as_na(self):
        result = ComparisonResult(
            passed=True, comparisons=[compare_metric("ate_rmse", 0.1, 0.2, None)]
        )
        text = render_markdown(result, make_context())
        assert "| ATE RMSE | 0.100000 m | 0.200000 m | n/a | - | PASS |" in text

    def test_disabled_alignment_described(self):
        result = ComparisonResult(passed=True, comparisons=[])
        text = render_markdown(
            result,
            make_context(settings={"alignment": {"enabled": False, "correct_scale": False}}),
        )
        assert "- alignment: disabled" in text


class TestCliReportIntegration:
    def test_compare_writes_markdown_report(self, tmp_path):
        n = 30
        reference = write_tum(tmp_path / "reference.tum", line_positions(n, 0.1))
        baseline_est = write_tum(
            tmp_path / "baseline_est.tum", line_positions(n, 0.1, fixed_noise(n, 0.02, seed=7))
        )
        baseline_json = str(tmp_path / "baseline.json")
        assert main(["record", "--reference", reference, "--estimate", baseline_est, "--json", baseline_json]) == 0

        report_md = str(tmp_path / "report.md")
        report_json = str(tmp_path / "report.json")
        code = main(
            [
                "compare",
                "--baseline", baseline_json,
                "--reference", reference,
                "--estimate", baseline_est,
                "--report", report_md,
                "--json", report_json,
            ]
        )
        assert code == 0
        text = open(report_md).read()
        assert "# SLAM regression report" in text
        assert "**Verdict: PASS**" in text
        # JSON report mirrors the verdict and carries run settings.
        payload = json.load(open(report_json))
        assert payload["passed"] is True
        assert payload["settings"]["alignment"]["enabled"] is True

    def test_failing_run_writes_failing_markdown(self, tmp_path):
        n = 30
        reference = write_tum(tmp_path / "reference.tum", line_positions(n, 0.1))
        baseline_est = write_tum(
            tmp_path / "baseline_est.tum", line_positions(n, 0.1, fixed_noise(n, 0.02, seed=7))
        )
        degraded = write_tum(
            tmp_path / "degraded.tum", line_positions(n, 0.1, fixed_noise(n, 0.06, seed=8))
        )
        baseline_json = str(tmp_path / "baseline.json")
        assert main(
            ["record", "--reference", reference, "--estimate", baseline_est, "--json", baseline_json]
        ) == 0
        report_md = str(tmp_path / "report.md")
        code = main(
            [
                "compare", "--baseline", baseline_json, "--reference", reference,
                "--estimate", degraded, "--report", report_md,
            ]
        )
        assert code == 1
        assert "**Verdict: FAIL**" in open(report_md).read()

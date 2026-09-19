import json

import pytest

from slam_regression.errors import ConfigError
from slam_regression.suites import load_suite_config, suite_config_from_dict
from test_cli import fixed_noise, line_positions, run_record, write_tum


class TestSuiteConfigParsing:
    def test_minimal_valid_suite(self):
        config = suite_config_from_dict(
            {
                "sequences": [
                    {"name": "room1", "baseline": "b.json", "reference": "gt.tum", "estimate": "est.tum"}
                ]
            }
        )
        assert len(config.sequences) == 1
        assert config.sequences[0].estimates == ["est.tum"]
        assert config.policy.max_failed_sequences == 0

    def test_multi_estimate_sequence(self):
        config = suite_config_from_dict(
            {
                "sequences": [
                    {
                        "name": "room1",
                        "baseline": "b.json",
                        "reference": "gt.tum",
                        "estimate": ["r1.tum", "r2.tum"],
                    }
                ]
            }
        )
        assert config.sequences[0].estimates == ["r1.tum", "r2.tum"]

    def test_duplicate_names_rejected(self):
        with pytest.raises(ConfigError, match="duplicate sequence name"):
            suite_config_from_dict(
                {
                    "sequences": [
                        {"name": "a", "baseline": "b", "reference": "r", "estimate": "e"},
                        {"name": "a", "baseline": "b", "reference": "r", "estimate": "e"},
                    ]
                }
            )

    def test_unknown_top_level_key(self):
        with pytest.raises(ConfigError, match="unknown suite configuration"):
            suite_config_from_dict({"sequnces": []})

    def test_missing_required_key(self):
        with pytest.raises(ConfigError, match="missing required key 'baseline'"):
            suite_config_from_dict(
                {"sequences": [{"name": "a", "reference": "r", "estimate": "e"}]}
            )

    def test_empty_sequences_rejected(self):
        with pytest.raises(ConfigError, match="non-empty list"):
            suite_config_from_dict({"sequences": []})

    def test_negative_max_failed_rejected(self):
        with pytest.raises(ConfigError, match="max_failed_sequences"):
            suite_config_from_dict(
                {
                    "sequences": [
                        {"name": "a", "baseline": "b", "reference": "r", "estimate": "e"}
                    ],
                    "suite_policy": {"max_failed_sequences": -1},
                }
            )

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="no_such.yaml"):
            load_suite_config(str(tmp_path / "no_such.yaml"))

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("sequences: [unclosed")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_suite_config(str(path))


@pytest.fixture
def suite_env(tmp_path):
    """Two sequences sharing the circle example data: one passes, one fails."""
    n = 30
    reference = write_tum(tmp_path / "reference.tum", line_positions(n, 0.1))
    good = write_tum(tmp_path / "good.tum", line_positions(n, 0.1, fixed_noise(n, 0.02, seed=7)))
    degraded = write_tum(
        tmp_path / "degraded.tum", line_positions(n, 0.1, fixed_noise(n, 0.06, seed=8))
    )
    baseline_json = str(tmp_path / "baseline.json")
    assert run_record(reference, good, baseline_json) == 0

    def write_suite(max_failed=0, estimate_for_second=None):
        second_estimate = estimate_for_second if estimate_for_second else degraded
        path = tmp_path / "suite.yaml"
        path.write_text(
            "sequences:\n"
            "  - name: seq-good\n"
            f"    baseline: {baseline_json}\n"
            f"    reference: {reference}\n"
            f"    estimate: {good}\n"
            "  - name: seq-bad\n"
            f"    baseline: {baseline_json}\n"
            f"    reference: {reference}\n"
            f"    estimate: {second_estimate}\n"
            "suite_policy:\n"
            f"  max_failed_sequences: {max_failed}\n"
        )
        return str(path)

    return {
        "tmp": tmp_path,
        "reference": reference,
        "good": good,
        "degraded": degraded,
        "baseline_json": baseline_json,
        "write_suite": write_suite,
    }


class TestSuiteCommand:
    def test_all_pass(self, suite_env):
        suite = suite_env["write_suite"]()
        # Replace the failing sequence with a passing one: both use the good estimate.
        text = open(suite).read().replace(
            suite_env["degraded"], suite_env["good"]
        )
        open(suite, "w").write(text)
        from slam_regression.cli import main

        code = main(["suite", "--config", suite])
        assert code == 0

    def test_one_failure_fails_overall_with_worst_first(self, suite_env, capsys):
        from slam_regression.cli import main

        suite = suite_env["write_suite"]()
        code = main(["suite", "--config", suite])
        out = capsys.readouterr().out
        assert code == 1
        assert "worst regression first" in out
        assert out.index("seq-bad") < out.index("seq-good")
        assert "SUITE STATUS: FAIL (1 failed sequence(s), allowed: 0)" in out

    def test_max_failed_sequences_allowance(self, suite_env):
        from slam_regression.cli import main

        suite = suite_env["write_suite"](max_failed=1)
        code = main(["suite", "--config", suite])
        assert code == 0

    def test_suite_report_files(self, suite_env, tmp_path):
        from slam_regression.cli import main

        suite = suite_env["write_suite"]()
        report_md = str(tmp_path / "suite.md")
        report_json = str(tmp_path / "suite.json")
        main(["suite", "--config", suite, "--report", report_md, "--json", report_json])
        text = open(report_md).read()
        assert "| seq-bad | FAIL |" in text
        assert "| seq-good | PASS |" in text
        payload = json.load(open(report_json))
        assert payload["schema"] == "slam-regression-suite-report/v1"
        assert payload["passed"] is False
        assert payload["sequences"][0]["name"] == "seq-bad"

    def test_invalid_sequence_input_exits_2(self, suite_env, capsys):
        from slam_regression.cli import main

        suite = suite_env["write_suite"]()
        # Point one sequence's reference at a nonexistent file.
        text = open(suite).read()
        broken = "reference: missing.tum\n    estimate: " + suite_env["degraded"]
        original = "reference: " + suite_env["reference"] + "\n    estimate: " + suite_env["degraded"]
        open(suite, "w").write(text.replace(original, broken))
        code = main(["suite", "--config", suite])
        assert code == 2
        assert "sequence 'seq-bad'" in capsys.readouterr().err

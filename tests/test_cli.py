import json

import pytest

from slam_regression import __version__
from slam_regression.cli import main


def write_tum(path, positions, timestamps=None, quat=(0.0, 0.0, 0.0, 1.0)):
    """Write a straight-line TUM trajectory; positions is a list of [x, y, z]."""
    if timestamps is None:
        timestamps = [1.0 + 0.1 * i for i in range(len(positions))]
    with open(path, "w") as handle:
        for t, (x, y, z) in zip(timestamps, positions):
            handle.write(
                f"{t:.9f} {x:.9f} {y:.9f} {z:.9f} {quat[0]:.9f} {quat[1]:.9f} {quat[2]:.9f} {quat[3]:.9f}\n"
            )
    return str(path)


def line_positions(n, step, noise_fn=None):
    positions = [[step * i, 0.0, 0.0] for i in range(n)]
    if noise_fn is not None:
        positions = [
            [x + dx, y + dy, z + dz] for (x, y, z), (dx, dy, dz) in zip(positions, noise_fn)
        ]
    return positions


def fixed_noise(n, amplitude, seed=7):
    rng = __import__("random").Random(seed)
    return [
        (rng.uniform(-a, a), rng.uniform(-a, a), rng.uniform(-a, a))
        for a in [amplitude] * n
    ]


def _estimate_args(estimate):
    """Normalize str-or-list estimate input into repeated --estimate flags."""
    estimates = estimate if isinstance(estimate, (list, tuple)) else [estimate]
    args = []
    for item in estimates:
        args += ["--estimate", item]
    return args


def run_record(reference, estimate, baseline_json, config=None):
    """Call the record subcommand; returns its exit code."""
    args = ["record", "--reference", reference, *_estimate_args(estimate), "--json", baseline_json]
    if config is not None:
        args += ["--config", config]
    return main(args)


def run_compare(baseline_json, reference, estimate, extra=()):
    return main(
        ["compare", "--baseline", baseline_json, "--reference", reference, *_estimate_args(estimate), *extra]
    )


@pytest.fixture
def env(tmp_path):
    """Ground truth, noisy baseline estimate, and clearly degraded candidate."""
    n = 30
    reference = write_tum(tmp_path / "reference.tum", line_positions(n, 0.1))
    baseline = write_tum(
        tmp_path / "baseline_est.tum", line_positions(n, 0.1, fixed_noise(n, 0.02, seed=7))
    )
    degraded = write_tum(
        tmp_path / "degraded.tum", line_positions(n, 0.1, fixed_noise(n, 0.06, seed=8))
    )
    return {"reference": reference, "baseline_est": baseline, "degraded": degraded, "tmp": tmp_path}


class TestRecord:
    def test_record_writes_baseline_json(self, env, capsys):
        out = str(env["tmp"] / "baseline.json")
        code = run_record(env["reference"], env["baseline_est"], out)
        assert code == 0
        payload = json.load(open(out))
        assert payload["schema"] == "slam-regression-baseline/v1"
        assert payload["metrics"]["ate_rmse"] > 0
        assert payload["num_pairs"] == 30
        assert payload["settings"]["alignment"]["enabled"] is True
        assert "baseline recorded" in capsys.readouterr().out

    def test_record_with_config(self, env):
        config = str(env["tmp"] / "cfg.yaml")
        with open(config, "w") as handle:
            handle.write("alignment:\n  enabled: false\n")
        out = str(env["tmp"] / "baseline.json")
        code = run_record(env["reference"], env["baseline_est"], out, config=config)
        assert code == 0
        assert json.load(open(out))["settings"]["alignment"]["enabled"] is False

    def test_record_missing_estimate_exit_2(self, env, capsys):
        code = run_record(env["reference"], "missing.tum", str(env["tmp"] / "b.json"))
        assert code == 2
        assert "error:" in capsys.readouterr().err


class TestCompare:
    def test_passing_candidate_exits_0(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0

        # Same noise amplitude family: ~3% change, inside the default 10% gate.
        similar = write_tum(
            env["tmp"] / "similar.tum", line_positions(30, 0.1, fixed_noise(30, 0.0205, seed=9))
        )
        code = run_compare(baseline_json, env["reference"], similar)
        out = capsys.readouterr().out
        assert code == 0
        assert "STATUS: PASS" in out

    def test_regressed_candidate_exits_1(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        code = run_compare(baseline_json, env["reference"], env["degraded"])
        out = capsys.readouterr().out
        assert code == 1
        assert "STATUS: FAIL" in out
        assert "ATE RMSE:" in out
        assert "change:" in out

    def test_json_report_written_and_parseable(self, env):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        report_json = str(env["tmp"] / "report.json")
        run_compare(baseline_json, env["reference"], env["degraded"], extra=["--json", report_json])
        payload = json.load(open(report_json))
        assert payload["schema"] == "slam-regression-report/v1"
        assert payload["passed"] is False
        assert len(payload["comparisons"]) == 2
        assert payload["comparisons"][0]["metric"] == "ate_rmse"
        assert "threshold_percent" in payload["comparisons"][0]

    def test_missing_baseline_file_exit_2(self, env, capsys):
        code = run_compare("nope.json", env["reference"], env["degraded"])
        assert code == 2
        assert "error:" in capsys.readouterr().err

    def test_invalid_baseline_schema_exit_2(self, env, capsys):
        bad = env["tmp"] / "bad.json"
        bad.write_text('{"hello": "world"}')
        code = run_compare(str(bad), env["reference"], env["degraded"])
        assert code == 2
        assert "slam-regression record" in capsys.readouterr().err

    def test_malformed_trajectory_exit_2(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        broken = env["tmp"] / "broken.tum"
        broken.write_text("1.0 0 0 0 0 0 0\n")  # 7 columns
        code = run_compare(baseline_json, env["reference"], str(broken))
        assert code == 2
        assert "expected 8" in capsys.readouterr().err

    def test_invalid_config_exit_2(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        config = env["tmp"] / "bad.yaml"
        config.write_text("not_a_known_key: 1\n")
        code = run_compare(
            baseline_json, env["reference"], env["degraded"], extra=["--config", str(config)]
        )
        assert code == 2
        assert "unknown configuration key" in capsys.readouterr().err

    def test_alignment_mismatch_is_strict_error(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline_noalign.json")
        config = str(env["tmp"] / "noalign.yaml")
        with open(config, "w") as handle:
            handle.write("alignment:\n  enabled: false\n")
        assert run_record(env["reference"], env["baseline_est"], baseline_json, config=config) == 0
        code = run_compare(baseline_json, env["reference"], env["baseline_est"])
        assert code == 2
        assert "not comparable" in capsys.readouterr().err

    def test_alignment_mismatch_override_allows_run(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline_noalign.json")
        config = str(env["tmp"] / "noalign.yaml")
        with open(config, "w") as handle:
            handle.write("alignment:\n  enabled: false\n")
        assert run_record(env["reference"], env["baseline_est"], baseline_json, config=config) == 0
        code = run_compare(
            baseline_json,
            env["reference"],
            env["baseline_est"],
            extra=["--allow-incompatible-baseline"],
        )
        assert code == 0
        assert "incompatible baseline override" in capsys.readouterr().err


class TestBaselineIntegrity:
    def test_record_stores_input_fingerprints(self, env):
        out = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], out) == 0
        payload = json.load(open(out))
        assert payload["input_hashes"]["reference"]["path"] == "reference.tum"
        assert len(payload["input_hashes"]["reference"]["sha256"]) == 64
        assert payload["config_sha256"] is None

    def test_record_with_config_stores_config_hash(self, env):
        config = str(env["tmp"] / "cfg.yaml")
        with open(config, "w") as handle:
            handle.write("metrics:\n  ate_rmse:\n    max_relative_regression_percent: 5\n")
        out = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], out, config=config) == 0
        assert len(json.load(open(out))["config_sha256"]) == 64

    def test_modified_reference_rejected(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        # Same filename, different content: the old silent-comparison hazard.
        with open(env["reference"], "a") as handle:
            handle.write("99.0 0 0 0 0 0 0 1\n")
        code = run_compare(baseline_json, env["reference"], env["baseline_est"])
        assert code == 2
        assert "sha256 mismatch" in capsys.readouterr().err

    def test_modified_reference_override_warns_and_completes(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        with open(env["reference"], "a") as handle:
            handle.write("99.0 0 0 0 0 0 0 1\n")
        code = run_compare(
            baseline_json, env["reference"], env["baseline_est"],
            extra=["--allow-incompatible-baseline"],
        )
        assert code == 0
        assert "sha256 mismatch" in capsys.readouterr().err

    def test_rpe_delta_mismatch_rejected(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        config = str(env["tmp"] / "delta.yaml")
        with open(config, "w") as handle:
            handle.write("rpe_delta: 5\n")
        code = run_compare(
            baseline_json, env["reference"], env["baseline_est"], extra=["--config", config]
        )
        assert code == 2
        assert "rpe_delta" in capsys.readouterr().err

    def test_max_timestamp_diff_mismatch_rejected(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        config = str(env["tmp"] / "assoc.yaml")
        with open(config, "w") as handle:
            handle.write("association:\n  max_timestamp_diff: 0.02\n")
        code = run_compare(
            baseline_json, env["reference"], env["baseline_est"], extra=["--config", config]
        )
        assert code == 2
        assert "max_timestamp_diff" in capsys.readouterr().err

    def test_legacy_baseline_without_fingerprints_warns_but_works(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        payload = json.load(open(baseline_json))
        del payload["input_hashes"]  # simulate a v0.1.0 baseline
        with open(baseline_json, "w") as handle:
            json.dump(payload, handle)
        code = run_compare(baseline_json, env["reference"], env["baseline_est"])
        assert code == 0
        assert "input fingerprints" in capsys.readouterr().err


class TestGates:
    """Coverage gates and absolute threshold policies (end to end)."""

    def test_coverage_gate_fails_on_truncated_candidate(self, env, tmp_path, capsys):
        baseline_json = str(tmp_path / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        # Candidate tracks only the first half of the reference timeline.
        truncated = write_tum(
            tmp_path / "truncated.tum",
            line_positions(15, 0.1, fixed_noise(15, 0.02, seed=7)),
        )
        config = str(tmp_path / "coverage.yaml")
        with open(config, "w") as handle:
            handle.write("coverage:\n  min_matched_pose_ratio: 0.9\n")
        code = run_compare(
            baseline_json, env["reference"], truncated, extra=["--config", config]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "STATUS: FAIL" in out
        assert "Coverage: 15/30 poses (0.5000)" in out
        assert "below minimum 0.9" in out

    def test_no_coverage_gate_by_default_reports_only(self, env, tmp_path, capsys):
        baseline_json = str(tmp_path / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        truncated = write_tum(
            tmp_path / "truncated.tum",
            line_positions(15, 0.1, fixed_noise(15, 0.02, seed=7)),
        )
        code = run_compare(baseline_json, env["reference"], truncated)
        out = capsys.readouterr().out
        assert code == 0  # metrics on the matched subset still pass
        assert "Coverage: 15/30 poses (0.5000)" in out
        assert "coverage gate" not in out

    def test_coverage_values_in_json_report(self, env, tmp_path):
        baseline_json = str(tmp_path / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        truncated = write_tum(
            tmp_path / "truncated.tum",
            line_positions(15, 0.1, fixed_noise(15, 0.02, seed=7)),
        )
        report_json = str(tmp_path / "report.json")
        run_compare(
            baseline_json, env["reference"], truncated, extra=["--json", report_json]
        )
        payload = json.load(open(report_json))
        coverage = payload["coverage"]
        assert coverage["matched_pose_count"] == 15
        assert coverage["reference_pose_count"] == 30
        assert coverage["matched_pose_ratio"] == pytest.approx(0.5)
        assert coverage["passed"] is True  # no gate configured

    def test_time_coverage_gate(self, env, tmp_path, capsys):
        baseline_json = str(tmp_path / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        truncated = write_tum(
            tmp_path / "truncated.tum",
            line_positions(15, 0.1, fixed_noise(15, 0.02, seed=7)),
        )
        config = str(tmp_path / "timecov.yaml")
        with open(config, "w") as handle:
            handle.write("coverage:\n  min_time_coverage_ratio: 0.9\n")
        code = run_compare(
            baseline_json, env["reference"], truncated, extra=["--config", config]
        )
        assert code == 1
        assert "time coverage ratio" in capsys.readouterr().out

    def test_absolute_budget_rule(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        config = str(env["tmp"] / "absbudget.yaml")
        with open(config, "w") as handle:
            handle.write("metrics:\n  ate_rmse:\n    max_absolute_regression: 0.03\n")
        code = run_compare(
            baseline_json, env["reference"], env["degraded"], extra=["--config", config]
        )
        assert code == 1
        assert "absolute budget: 0.030000 m" in capsys.readouterr().out

    def test_ceiling_rule(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        config = str(env["tmp"] / "ceiling.yaml")
        with open(config, "w") as handle:
            handle.write("metrics:\n  ate_rmse:\n    max_value: 0.05\n")
        code = run_compare(
            baseline_json, env["reference"], env["degraded"], extra=["--config", config]
        )
        assert code == 1
        assert "max value: 0.050000 m" in capsys.readouterr().out

    def test_absolute_rules_pass_on_good_candidate(self, env, tmp_path):
        baseline_json = str(tmp_path / "baseline.json")
        assert run_record(env["reference"], env["baseline_est"], baseline_json) == 0
        config = str(tmp_path / "strict.yaml")
        with open(config, "w") as handle:
            handle.write(
                "metrics:\n  ate_rmse:\n    max_absolute_regression: 0.03\n    max_value: 0.05\n"
            )
        similar = write_tum(
            env["tmp"] / "similar.tum", line_positions(30, 0.1, fixed_noise(30, 0.0205, seed=9))
        )
        code = run_compare(
            baseline_json, env["reference"], similar, extra=["--config", config]
        )
        assert code == 0


class TestVersion:
    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0
        assert __version__ in capsys.readouterr().out

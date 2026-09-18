import json
import os

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
                "{:.9f} {:.9f} {:.9f} {:.9f} {:.9f} {:.9f} {:.9f} {:.9f}\n".format(
                    t, x, y, z, quat[0], quat[1], quat[2], quat[3]
                )
            )
    return str(path)


def line_positions(n, step, noise_fn=None):
    positions = [[step * i, 0.0, 0.0] for i in range(n)]
    if noise_fn is not None:
        positions = [[x + dx, y + dy, z + dz] for (x, y, z), (dx, dy, dz) in zip(positions, noise_fn)]
    return positions


def fixed_noise(n, amplitude, seed=7):
    rng = __import__("random").Random(seed)
    return [
        (rng.uniform(-amplitude, amplitude), rng.uniform(-amplitude, amplitude), rng.uniform(-amplitude, amplitude))
        for _ in range(n)
    ]


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
        code = main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", out])
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
        code = main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", out, "--config", config])
        assert code == 0
        assert json.load(open(out))["settings"]["alignment"]["enabled"] is False

    def test_record_missing_estimate_exit_2(self, env, capsys):
        code = main(["record", "--reference", env["reference"], "--estimate", "missing.tum", "--json", str(env["tmp"] / "b.json")])
        assert code == 2
        assert "error:" in capsys.readouterr().err


class TestCompare:
    def test_passing_candidate_exits_0(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", baseline_json]) == 0

        # Same noise amplitude family: ~3% change, inside the default 10% gate.
        similar = write_tum(env["tmp"] / "similar.tum", line_positions(30, 0.1, fixed_noise(30, 0.0205, seed=9)))
        code = main(["compare", "--baseline", baseline_json, "--reference", env["reference"], "--estimate", similar])
        out = capsys.readouterr().out
        assert code == 0
        assert "STATUS: PASS" in out

    def test_regressed_candidate_exits_1(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", baseline_json]) == 0
        code = main(["compare", "--baseline", baseline_json, "--reference", env["reference"], "--estimate", env["degraded"]])
        out = capsys.readouterr().out
        assert code == 1
        assert "STATUS: FAIL" in out
        assert "ATE RMSE:" in out
        assert "change:" in out

    def test_json_report_written_and_parseable(self, env):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", baseline_json]) == 0
        report_json = str(env["tmp"] / "report.json")
        main(["compare", "--baseline", baseline_json, "--reference", env["reference"], "--estimate", env["degraded"], "--json", report_json])
        payload = json.load(open(report_json))
        assert payload["schema"] == "slam-regression-report/v1"
        assert payload["passed"] is False
        assert len(payload["comparisons"]) == 2
        assert payload["comparisons"][0]["metric"] == "ate_rmse"
        assert "threshold_percent" in payload["comparisons"][0]

    def test_missing_baseline_file_exit_2(self, env, capsys):
        code = main(["compare", "--baseline", "nope.json", "--reference", env["reference"], "--estimate", env["degraded"]])
        assert code == 2
        assert "error:" in capsys.readouterr().err

    def test_invalid_baseline_schema_exit_2(self, env, capsys):
        bad = env["tmp"] / "bad.json"
        bad.write_text('{"hello": "world"}')
        code = main(["compare", "--baseline", str(bad), "--reference", env["reference"], "--estimate", env["degraded"]])
        assert code == 2
        assert "slam-regression record" in capsys.readouterr().err

    def test_malformed_trajectory_exit_2(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", baseline_json]) == 0
        broken = env["tmp"] / "broken.tum"
        broken.write_text("1.0 0 0 0 0 0 0\n")  # 7 columns
        code = main(["compare", "--baseline", baseline_json, "--reference", env["reference"], "--estimate", str(broken)])
        assert code == 2
        assert "expected 8" in capsys.readouterr().err

    def test_invalid_config_exit_2(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline.json")
        assert main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", baseline_json]) == 0
        config = env["tmp"] / "bad.yaml"
        config.write_text("not_a_known_key: 1\n")
        code = main(["compare", "--baseline", baseline_json, "--reference", env["reference"], "--estimate", env["degraded"], "--config", str(config)])
        assert code == 2
        assert "unknown configuration key" in capsys.readouterr().err

    def test_alignment_mismatch_warns_but_completes(self, env, capsys):
        baseline_json = str(env["tmp"] / "baseline_noalign.json")
        config = str(env["tmp"] / "noalign.yaml")
        with open(config, "w") as handle:
            handle.write("alignment:\n  enabled: false\n")
        assert main(["record", "--reference", env["reference"], "--estimate", env["baseline_est"], "--json", baseline_json, "--config", config]) == 0
        code = main(["compare", "--baseline", baseline_json, "--reference", env["reference"], "--estimate", env["baseline_est"]])
        assert code == 0
        err = capsys.readouterr().err
        assert "different alignment settings" in err


class TestVersion:
    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0
        assert __version__ in capsys.readouterr().out

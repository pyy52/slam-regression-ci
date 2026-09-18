import pytest

from slam_regression.config import config_from_dict, default_config, load_config
from slam_regression.errors import ConfigError


class TestDefaults:
    def test_default_config_gates_both_metrics_at_10_percent(self):
        config = default_config()
        assert config.metric_names == ["ate_rmse", "rpe_translation_rmse"]
        assert config.metrics["ate_rmse"].max_relative_regression_percent == 10.0
        assert config.metrics["rpe_translation_rmse"].max_relative_regression_percent == 10.0
        assert config.association.max_timestamp_diff == 0.01
        assert config.alignment.enabled is True
        assert config.alignment.correct_scale is False
        assert config.rpe_delta == 1

    def test_none_means_defaults(self):
        assert config_from_dict(None).metric_names == ["ate_rmse", "rpe_translation_rmse"]


class TestParsing:
    def test_minimal_valid_config(self):
        config = config_from_dict({"metrics": {"ate_rmse": {"max_relative_regression_percent": 5}}})
        assert config.metric_names == ["ate_rmse"]
        assert config.metrics["ate_rmse"].max_relative_regression_percent == 5.0

    def test_metric_without_threshold_is_informational(self):
        config = config_from_dict({"metrics": {"ate_rmse": None}})
        assert config.metrics["ate_rmse"].max_relative_regression_percent is None

    def test_zero_threshold_is_allowed(self):
        config = config_from_dict({"metrics": {"ate_rmse": {"max_relative_regression_percent": 0}}})
        assert config.metrics["ate_rmse"].max_relative_regression_percent == 0.0

    def test_full_config_round_trip(self):
        config = config_from_dict(
            {
                "metrics": {
                    "ate_rmse": {"max_relative_regression_percent": 1},
                    "rpe_translation_rmse": {"max_relative_regression_percent": 2},
                },
                "association": {"max_timestamp_diff": 0.05},
                "alignment": {"enabled": False, "correct_scale": True},
                "rpe_delta": 3,
            }
        )
        assert config.association.max_timestamp_diff == 0.05
        assert config.alignment.enabled is False
        assert config.alignment.correct_scale is True
        assert config.rpe_delta == 3


class TestValidation:
    def test_unknown_top_level_key(self):
        with pytest.raises(ConfigError, match="unknown configuration key"):
            config_from_dict({"metricks": {}})

    def test_unknown_metric_name_lists_valid_options(self):
        with pytest.raises(ConfigError, match="ate_rmse"):
            config_from_dict({"metrics": {"ate_mean": {"max_relative_regression_percent": 1}}})

    def test_unknown_metric_option(self):
        with pytest.raises(ConfigError, match="unknown option"):
            config_from_dict({"metrics": {"ate_rmse": {"max_value": 1}}})

    def test_empty_metrics_rejected(self):
        with pytest.raises(ConfigError, match="at least one"):
            config_from_dict({"metrics": {}})

    def test_threshold_must_be_number(self):
        with pytest.raises(ConfigError, match="must be a number"):
            config_from_dict({"metrics": {"ate_rmse": {"max_relative_regression_percent": "ten"}}})

    def test_threshold_must_not_be_negative(self):
        with pytest.raises(ConfigError, match=">= 0"):
            config_from_dict({"metrics": {"ate_rmse": {"max_relative_regression_percent": -1}}})

    def test_negative_timestamp_diff_rejected(self):
        with pytest.raises(ConfigError, match="association.max_timestamp_diff"):
            config_from_dict({"metrics": {"ate_rmse": None}, "association": {"max_timestamp_diff": -0.1}})

    def test_bool_is_not_a_number(self):
        with pytest.raises(ConfigError, match="must be a number"):
            config_from_dict({"metrics": {"ate_rmse": None}, "association": {"max_timestamp_diff": True}})

    def test_alignment_requires_bools(self):
        with pytest.raises(ConfigError, match="alignment.enabled"):
            config_from_dict({"metrics": {"ate_rmse": None}, "alignment": {"enabled": "yes"}})

    def test_rpe_delta_must_be_positive_int(self):
        with pytest.raises(ConfigError, match="rpe_delta"):
            config_from_dict({"metrics": {"ate_rmse": None}, "rpe_delta": 0})

    def test_non_mapping_top_level(self):
        with pytest.raises(ConfigError, match="mapping"):
            config_from_dict([1, 2, 3])


class TestLoadFile:
    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="no_such.yaml"):
            load_config(str(tmp_path / "no_such.yaml"))

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("metrics: [unclosed")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_config(str(path))

    def test_valid_file(self, tmp_path):
        path = tmp_path / "ok.yaml"
        path.write_text("metrics:\n  ate_rmse:\n    max_relative_regression_percent: 3\n")
        config = load_config(str(path))
        assert config.metrics["ate_rmse"].max_relative_regression_percent == 3.0

"""Configuration loading and validation.

Configuration is a YAML file. Unknown keys, unknown metric names, and wrong
value types are rejected with actionable messages instead of being silently
ignored::

    metrics:
      ate_rmse:
        max_relative_regression_percent: 10
      rpe_translation_rmse:
        max_relative_regression_percent: 10

    association:
      max_timestamp_diff: 0.01

    alignment:
      enabled: true
      correct_scale: false

    rpe_delta: 1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .errors import ConfigError

KNOWN_METRICS = ("ate_rmse", "rpe_translation_rmse")
METRIC_RULE_KEY = "max_relative_regression_percent"
KNOWN_TOP_LEVEL_KEYS = ("metrics", "association", "alignment", "rpe_delta")


@dataclass
class MetricThreshold:
    max_relative_regression_percent: Optional[float] = None


@dataclass
class AssociationConfig:
    max_timestamp_diff: float = 0.01


@dataclass
class AlignmentConfig:
    enabled: bool = True
    correct_scale: bool = False


@dataclass
class Config:
    metrics: Dict[str, MetricThreshold] = field(default_factory=dict)
    association: AssociationConfig = field(default_factory=AssociationConfig)
    alignment: AlignmentConfig = field(default_factory=AlignmentConfig)
    rpe_delta: int = 1

    @property
    def metric_names(self) -> List[str]:
        return list(self.metrics.keys())


def default_config() -> Config:
    """Sane defaults: gate both v0.1 metrics at 10% relative regression."""
    return Config(
        metrics={
            "ate_rmse": MetricThreshold(10.0),
            "rpe_translation_rmse": MetricThreshold(10.0),
        }
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_non_negative_number(value: Any, what: str) -> float:
    if not _is_number(value):
        raise ConfigError("{} must be a number, got {!r}".format(what, value))
    number = float(value)
    if number < 0.0:
        raise ConfigError("{} must be >= 0, got {}".format(what, value))
    return number


def _as_bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError("{} must be a boolean, got {!r}".format(what, value))
    return value


def _parse_metrics(raw: Any) -> Dict[str, MetricThreshold]:
    if not isinstance(raw, dict):
        raise ConfigError("'metrics' must be a mapping of metric name to threshold rule")
    if not raw:
        raise ConfigError(
            "'metrics' is empty; configure at least one of: {}".format(", ".join(KNOWN_METRICS))
        )

    metrics: Dict[str, MetricThreshold] = {}
    for name, rule in raw.items():
        if name not in KNOWN_METRICS:
            raise ConfigError(
                "unknown metric '{}'; valid metrics are: {}".format(name, ", ".join(KNOWN_METRICS))
            )
        if rule is None:
            metrics[name] = MetricThreshold(None)
            continue
        if not isinstance(rule, dict):
            raise ConfigError(
                "metric '{}' must be a mapping with key '{}'".format(name, METRIC_RULE_KEY)
            )
        unknown = [key for key in rule if key != METRIC_RULE_KEY]
        if unknown:
            raise ConfigError(
                "metric '{}' has unknown option(s): {}; only '{}' is supported".format(
                    name, ", ".join(sorted(unknown)), METRIC_RULE_KEY
                )
            )
        threshold_value = rule.get(METRIC_RULE_KEY)
        threshold = None
        if threshold_value is not None:
            threshold = _as_non_negative_number(
                threshold_value, "metrics.{}.{}".format(name, METRIC_RULE_KEY)
            )
        metrics[name] = MetricThreshold(threshold)
    return metrics


def _parse_association(raw: Any) -> AssociationConfig:
    if raw is None:
        return AssociationConfig()
    if not isinstance(raw, dict):
        raise ConfigError("'association' must be a mapping")
    unknown = [key for key in raw if key != "max_timestamp_diff"]
    if unknown:
        raise ConfigError(
            "'association' has unknown option(s): {}".format(", ".join(sorted(unknown)))
        )
    diff = _as_non_negative_number(
        raw.get("max_timestamp_diff", 0.01), "association.max_timestamp_diff"
    )
    return AssociationConfig(max_timestamp_diff=diff)


def _parse_alignment(raw: Any) -> AlignmentConfig:
    if raw is None:
        return AlignmentConfig()
    if not isinstance(raw, dict):
        raise ConfigError("'alignment' must be a mapping")
    unknown = [key for key in raw if key not in ("enabled", "correct_scale")]
    if unknown:
        raise ConfigError(
            "'alignment' has unknown option(s): {}".format(", ".join(sorted(unknown)))
        )
    return AlignmentConfig(
        enabled=_as_bool(raw.get("enabled", True), "alignment.enabled"),
        correct_scale=_as_bool(raw.get("correct_scale", False), "alignment.correct_scale"),
    )


def config_from_dict(raw: Optional[dict]) -> Config:
    """Build a validated Config from a parsed mapping (``None`` means defaults)."""
    if raw is None:
        return default_config()
    if not isinstance(raw, dict):
        raise ConfigError("configuration must be a YAML mapping")

    unknown = [key for key in raw if key not in KNOWN_TOP_LEVEL_KEYS]
    if unknown:
        raise ConfigError(
            "unknown configuration key(s): {}; valid keys are: {}".format(
                ", ".join(sorted(unknown)), ", ".join(KNOWN_TOP_LEVEL_KEYS)
            )
        )

    metrics_raw = raw.get("metrics")
    if metrics_raw is None:
        # Omitting 'metrics' keeps the default gates; only tweaks are overridden.
        metrics = default_config().metrics
    else:
        metrics = _parse_metrics(metrics_raw)
    association = _parse_association(raw.get("association"))
    alignment = _parse_alignment(raw.get("alignment"))

    rpe_delta_raw = raw.get("rpe_delta", 1)
    if not isinstance(rpe_delta_raw, int) or isinstance(rpe_delta_raw, bool) or rpe_delta_raw < 1:
        raise ConfigError("'rpe_delta' must be an integer >= 1, got {!r}".format(rpe_delta_raw))

    return Config(
        metrics=metrics,
        association=association,
        alignment=alignment,
        rpe_delta=rpe_delta_raw,
    )


def load_config(path: Optional[str]) -> Config:
    """Load and validate a YAML configuration file. ``None`` returns defaults."""
    if path is None:
        return default_config()
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        raise ConfigError("cannot read config file '{}': {}".format(path, exc.strerror or exc)) from None
    with handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigError("invalid YAML in '{}': {}".format(path, exc)) from None
    return config_from_dict(raw)

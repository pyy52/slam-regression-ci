"""Threshold policy: decide whether a candidate metric regressed.

All metrics produced by :mod:`slam_regression.metrics` are error measures where
lower is better, in meters. A metric fails when ANY of its configured rules is
exceeded:

- relative: ``(candidate - baseline) / baseline * 100`` must be at most
  ``max_relative_regression_percent`` (improvements always pass)
- absolute: ``candidate - baseline`` must be at most
  ``max_absolute_regression`` (robust for very small or very large baselines)
- ceiling: ``candidate`` itself must be at most ``max_value``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .errors import MetricsError


@dataclass
class MetricComparison:
    """Outcome of comparing one candidate metric against the baseline."""

    metric: str
    baseline: float
    candidate: float
    change_percent: Optional[float]
    threshold_percent: Optional[float]
    absolute_budget: Optional[float]
    absolute_excess: Optional[float]
    max_value: Optional[float]
    passed: bool
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "change_percent": self.change_percent,
            "threshold_percent": self.threshold_percent,
            "absolute_budget": self.absolute_budget,
            "absolute_excess": self.absolute_excess,
            "max_value": self.max_value,
            "passed": self.passed,
            "note": self.note,
        }


@dataclass
class ComparisonResult:
    """Overall gate outcome across all configured metrics."""

    passed: bool
    comparisons: List[MetricComparison] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    coverage: Optional[dict] = None

    def to_dict(self) -> dict:
        payload = {
            "passed": self.passed,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "warnings": list(self.warnings),
        }
        if self.coverage is not None:
            payload["coverage"] = self.coverage
        return payload


def _rule_notes(threshold) -> List[str]:
    notes = []
    if threshold.max_relative_regression_percent is None and \
            threshold.max_absolute_regression is None and threshold.max_value is None:
        notes.append("no threshold configured; metric reported without gating")
    return notes


def compare_metric(metric: str, baseline: float, candidate: float, threshold) -> MetricComparison:
    """Compare one metric against the baseline under its configured rules.

    ``threshold`` is a :class:`slam_regression.config.MetricThreshold`.
    """
    if baseline < 0.0 or candidate < 0.0:
        raise MetricsError(
            f"metric values must be non-negative ({metric}: baseline={baseline}, candidate={candidate})"
        )

    failures: List[str] = []
    change_percent: Optional[float] = None
    relative_ok = True
    absolute_excess: Optional[float] = None

    if threshold.max_relative_regression_percent is not None:
        if baseline == 0.0:
            if candidate == 0.0:
                change_percent = 0.0
                relative_ok = True
            else:
                change_percent = None
                relative_ok = False
                failures.append(
                    "baseline is 0 while candidate is > 0; relative change is undefined "
                    "and treated as a regression"
                )
        else:
            change_percent = (candidate - baseline) / abs(baseline) * 100.0
            relative_ok = change_percent <= threshold.max_relative_regression_percent

    if threshold.max_absolute_regression is not None:
        absolute_excess = candidate - baseline
        if absolute_excess > threshold.max_absolute_regression:
            failures.append(
                f"absolute regression {absolute_excess:.6f} m exceeds budget "
                f"{threshold.max_absolute_regression:.6f} m"
            )

    if threshold.max_value is not None and candidate > threshold.max_value:
        failures.append(f"candidate value {candidate:.6f} m exceeds ceiling {threshold.max_value:.6f} m")

    passed = relative_ok and not failures
    return MetricComparison(
        metric=metric,
        baseline=baseline,
        candidate=candidate,
        change_percent=change_percent,
        threshold_percent=threshold.max_relative_regression_percent,
        absolute_budget=threshold.max_absolute_regression,
        absolute_excess=absolute_excess,
        max_value=threshold.max_value,
        passed=passed,
        note="; ".join(failures) if failures else ("; ".join(_rule_notes(threshold)) or None),
    )


def compare_metric_distribution(
    metric: str, baseline_stats: dict, candidate: float, threshold
) -> MetricComparison:
    """Compare one candidate metric against a multi-run baseline distribution.

    ``baseline_stats`` is the baseline's stats block for this metric (keys
    ``median`` and ``mad`` at minimum, as produced by ``record`` with multiple
    runs). Rules work like :func:`compare_metric` with the median as the
    baseline value; ``max_mad_multiples`` additionally fails when the candidate
    exceeds ``median + k * MAD`` — i.e. more than the run-to-run spread.
    """
    if not isinstance(baseline_stats, dict) or "median" not in baseline_stats:
        raise MetricsError(f"baseline is missing distribution stats for '{metric}'")
    median = baseline_stats["median"]
    mad = baseline_stats.get("mad", 0.0) or 0.0
    if not isinstance(median, (int, float)) or isinstance(median, bool) or median < 0:
        raise MetricsError(f"baseline median for '{metric}' is invalid: {median!r}")

    failures: List[str] = []
    change_percent: Optional[float] = None
    relative_ok = True
    absolute_excess: Optional[float] = None

    if threshold.max_relative_regression_percent is not None:
        if median == 0.0:
            if candidate == 0.0:
                change_percent = 0.0
            else:
                relative_ok = False
                failures.append(
                    "baseline median is 0 while candidate is > 0; relative change is "
                    "undefined and treated as a regression"
                )
        else:
            change_percent = (candidate - median) / abs(median) * 100.0
            relative_ok = change_percent <= threshold.max_relative_regression_percent

    if threshold.max_absolute_regression is not None:
        absolute_excess = candidate - median
        if absolute_excess > threshold.max_absolute_regression:
            failures.append(
                f"absolute regression {absolute_excess:.6f} m exceeds budget "
                f"{threshold.max_absolute_regression:.6f} m"
            )

    if threshold.max_value is not None and candidate > threshold.max_value:
        failures.append(f"candidate value {candidate:.6f} m exceeds ceiling {threshold.max_value:.6f} m")

    if threshold.max_mad_multiples is not None:
        robust_budget = median + threshold.max_mad_multiples * mad
        if candidate > robust_budget:
            failures.append(
                f"candidate exceeds median + {threshold.max_mad_multiples:g} MAD "
                f"({robust_budget:.6f} m)"
            )

    passed = relative_ok and not failures
    return MetricComparison(
        metric=metric,
        baseline=median,
        candidate=candidate,
        change_percent=change_percent,
        threshold_percent=threshold.max_relative_regression_percent,
        absolute_budget=threshold.max_absolute_regression,
        absolute_excess=absolute_excess,
        max_value=threshold.max_value,
        passed=passed,
        note="; ".join(failures) if failures else ("; ".join(_rule_notes(threshold)) or None),
    )


def evaluate(
    baseline_metrics: dict,
    candidate_metrics: dict,
    metric_names: List[str],
    thresholds: dict,
    baseline_distributions: Optional[dict] = None,
) -> ComparisonResult:
    """Evaluate all configured metrics and combine into an overall verdict.

    ``thresholds`` maps metric name to its MetricThreshold rules object.
    ``baseline_distributions`` optionally maps metric name to a stats block
    (``median``/``mad``); when present, the distribution-aware comparison is
    used, enabling the ``max_mad_multiples`` rule.
    """
    comparisons: List[MetricComparison] = []
    for name in metric_names:
        if name not in baseline_metrics:
            raise MetricsError(f"baseline is missing metric '{name}'")
        if name not in candidate_metrics:
            raise MetricsError(f"candidate is missing metric '{name}'")
        distribution = (baseline_distributions or {}).get(name)
        if distribution is not None:
            comparisons.append(
                compare_metric_distribution(
                    name, distribution, candidate_metrics[name], thresholds.get(name)
                )
            )
        else:
            comparisons.append(
                compare_metric(name, baseline_metrics[name], candidate_metrics[name], thresholds.get(name))
            )
    passed = all(c.passed for c in comparisons)
    return ComparisonResult(passed=passed, comparisons=comparisons)

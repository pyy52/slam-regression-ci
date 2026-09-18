"""Threshold policy: decide whether a candidate metric regressed.

All metrics produced by :mod:`slam_regression.metrics` are error measures where
lower is better, so a positive relative change means a regression and a
negative change means an improvement. A candidate passes when its relative
change is less than or equal to the configured threshold.
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
    passed: bool
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "change_percent": self.change_percent,
            "threshold_percent": self.threshold_percent,
            "passed": self.passed,
            "note": self.note,
        }


@dataclass
class ComparisonResult:
    """Overall gate outcome across all configured metrics."""

    passed: bool
    comparisons: List[MetricComparison] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "warnings": list(self.warnings),
        }


def compare_metric(
    metric: str, baseline: float, candidate: float, threshold_percent: Optional[float]
) -> MetricComparison:
    """Compare one metric against the baseline under a relative threshold."""
    if baseline < 0.0 or candidate < 0.0:
        raise MetricsError(
            "metric values must be non-negative ({}: baseline={}, candidate={})".format(
                metric, baseline, candidate
            )
        )

    if threshold_percent is None:
        return MetricComparison(
            metric=metric,
            baseline=baseline,
            candidate=candidate,
            change_percent=None,
            threshold_percent=None,
            passed=True,
            note="no threshold configured; metric reported without gating",
        )

    if baseline == 0.0:
        if candidate == 0.0:
            return MetricComparison(
                metric=metric,
                baseline=baseline,
                candidate=candidate,
                change_percent=0.0,
                threshold_percent=threshold_percent,
                passed=True,
            )
        return MetricComparison(
            metric=metric,
            baseline=baseline,
            candidate=candidate,
            change_percent=None,
            threshold_percent=threshold_percent,
            passed=False,
            note=(
                "baseline is 0 while candidate is > 0; relative change is undefined "
                "and treated as a regression"
            ),
        )

    change_percent = (candidate - baseline) / abs(baseline) * 100.0
    return MetricComparison(
        metric=metric,
        baseline=baseline,
        candidate=candidate,
        change_percent=change_percent,
        threshold_percent=threshold_percent,
        passed=change_percent <= threshold_percent,
    )


def evaluate(baseline_metrics: dict, candidate_metrics: dict, metric_names: List[str], thresholds: dict) -> ComparisonResult:
    """Evaluate all configured metrics and combine into an overall verdict."""
    comparisons: List[MetricComparison] = []
    for name in metric_names:
        if name not in baseline_metrics:
            raise MetricsError("baseline is missing metric '{}'".format(name))
        if name not in candidate_metrics:
            raise MetricsError("candidate is missing metric '{}'".format(name))
        threshold = thresholds.get(name)
        comparisons.append(
            compare_metric(name, baseline_metrics[name], candidate_metrics[name], threshold)
        )
    passed = all(c.passed for c in comparisons)
    return ComparisonResult(passed=passed, comparisons=comparisons)

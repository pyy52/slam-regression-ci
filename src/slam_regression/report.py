"""Human-readable Markdown report rendering.

The JSON report (written by the CLI) is the machine-readable source of truth;
this module renders the same information as a compact Markdown document that
CI can attach to a pull request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .policy import ComparisonResult

METRIC_LABELS = {
    "ate_rmse": "ATE RMSE",
    "rpe_translation_rmse": "RPE translation RMSE",
}

METRIC_KEYS = (
    "ate_rmse",
    "ate_mean",
    "ate_max",
    "rpe_translation_rmse",
    "rpe_mean",
    "rpe_max",
)


@dataclass
class ReportContext:
    """Everything the report needs besides the comparison outcome."""

    tool_version: str
    created_utc: str
    baseline_file: str
    inputs: Dict[str, str]
    settings: Dict[str, object]
    candidate_num_pairs: int
    warnings: List[str] = field(default_factory=list)


def _format_change(change: Optional[float]) -> str:
    if change is None:
        return "n/a"
    return "{:+.2f}%".format(change)


def _format_threshold(threshold: Optional[float]) -> str:
    if threshold is None:
        return "-"
    return "{:+.2f}%".format(threshold)


def _format_alignment(settings: Dict[str, object]) -> str:
    alignment = settings.get("alignment", {}) if isinstance(settings, dict) else {}
    if not alignment.get("enabled", True):
        return "disabled"
    if alignment.get("correct_scale", False):
        return "Umeyama with scale correction"
    return "Umeyama (rigid SE(3))"


def render_markdown(result: ComparisonResult, context: ReportContext) -> str:
    """Render the comparison result and run context as a Markdown document."""
    verdict = "PASS" if result.passed else "FAIL"
    lines: List[str] = []
    lines.append("# SLAM regression report")
    lines.append("")
    lines.append("**Verdict: {}**".format(verdict))
    lines.append("")
    lines.append(
        "Generated {} by slam-regression {}".format(context.created_utc, context.tool_version)
    )
    lines.append("")
    lines.append("## Metric comparison")
    lines.append("")
    lines.append("| Metric | Baseline | Candidate | Change | Threshold | Status |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for comparison in result.comparisons:
        label = METRIC_LABELS.get(comparison.metric, comparison.metric)
        lines.append(
            "| {} | {:.6f} m | {:.6f} m | {} | {} | {} |".format(
                label,
                comparison.baseline,
                comparison.candidate,
                _format_change(comparison.change_percent),
                _format_threshold(comparison.threshold_percent),
                "PASS" if comparison.passed else "FAIL",
            )
        )
    lines.append("")
    lines.append("## Run details")
    lines.append("")
    lines.append("- baseline file: `{}`".format(context.baseline_file))
    lines.append("- reference: `{}`".format(context.inputs.get("reference", "n/a")))
    lines.append("- estimate: `{}`".format(context.inputs.get("estimate", "n/a")))
    lines.append("- matched pose pairs: {}".format(context.candidate_num_pairs))
    lines.append("- alignment: {}".format(_format_alignment(context.settings)))
    lines.append("- association max timestamp diff: {} s".format(
        context.settings.get("association", {}).get("max_timestamp_diff", "n/a")
        if isinstance(context.settings.get("association", {}), dict)
        else "n/a"
    ))

    notes: List[str] = []
    for comparison in result.comparisons:
        if comparison.note:
            notes.append("**{}**: {}".format(METRIC_LABELS.get(comparison.metric, comparison.metric), comparison.note))
    notes.extend(context.warnings)
    if notes:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for note in notes:
            lines.append("- {}".format(note))

    lines.append("")
    return "\n".join(lines)

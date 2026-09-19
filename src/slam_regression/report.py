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
    return f"{change:+.2f}%"


def _format_alignment(settings: Dict[str, object]) -> str:
    alignment = settings.get("alignment", {}) if isinstance(settings, dict) else {}
    if not alignment.get("enabled", True):
        return "disabled"
    if alignment.get("correct_scale", False):
        return "Umeyama with scale correction"
    return "Umeyama (rigid SE(3))"


def _format_rules(comparison) -> str:
    """Compact rendering of every configured rule for the table's Threshold cell."""
    parts: List[str] = []
    if comparison.threshold_percent is not None:
        parts.append(f"{comparison.threshold_percent:+.2f}%")
    if comparison.absolute_budget is not None:
        parts.append(f"Δ≤{comparison.absolute_budget:.6g} m")
    if comparison.max_value is not None:
        parts.append(f"≤{comparison.max_value:.6g} m")
    return " / ".join(parts) if parts else "-"


def _format_change_cell(comparison) -> str:
    if comparison.change_percent is not None:
        return _format_change(comparison.change_percent)
    if comparison.absolute_excess is not None:
        return f"Δ{comparison.absolute_excess:+.6g} m"
    return "n/a"


def render_markdown(result: ComparisonResult, context: ReportContext) -> str:
    """Render the comparison result and run context as a Markdown document."""
    verdict = "PASS" if result.passed else "FAIL"
    lines: List[str] = []
    lines.append("# SLAM regression report")
    lines.append("")
    lines.append(f"**Verdict: {verdict}**")
    lines.append("")
    lines.append(
        f"Generated {context.created_utc} by slam-regression {context.tool_version}"
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
                _format_change_cell(comparison),
                _format_rules(comparison),
                "PASS" if comparison.passed else "FAIL",
            )
        )
    lines.append("")
    lines.append("## Run details")
    lines.append("")
    lines.append(f"- baseline file: `{context.baseline_file}`")
    lines.append("- reference: `{}`".format(context.inputs.get("reference", "n/a")))
    lines.append("- estimate: `{}`".format(context.inputs.get("estimate", "n/a")))
    lines.append(f"- matched pose pairs: {context.candidate_num_pairs}")
    lines.append(f"- alignment: {_format_alignment(context.settings)}")
    lines.append("- association max timestamp diff: {} s".format(
        context.settings.get("association", {}).get("max_timestamp_diff", "n/a")
        if isinstance(context.settings.get("association", {}), dict)
        else "n/a"
    ))
    if result.coverage is not None:
        coverage = result.coverage
        pose_ratio = coverage.get("matched_pose_ratio")
        time_ratio = coverage.get("time_coverage_ratio")
        lines.append(
            "- coverage: {}/{} poses ({})".format(
                coverage.get("matched_pose_count", "n/a"),
                coverage.get("reference_pose_count", "n/a"),
                "n/a" if pose_ratio is None else f"{pose_ratio:.4f}",
            )
        )
        if time_ratio is not None:
            lines.append(f"- time coverage: {time_ratio:.4f}")
        for note in coverage.get("notes", []):
            lines.append(f"- coverage gate: {note}")

    notes: List[str] = []
    for comparison in result.comparisons:
        if comparison.note:
            notes.append(f"**{METRIC_LABELS.get(comparison.metric, comparison.metric)}**: {comparison.note}")
    notes.extend(context.warnings)
    if notes:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")

    lines.append("")
    return "\n".join(lines)

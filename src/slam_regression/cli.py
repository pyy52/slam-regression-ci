"""Command-line interface: ``slam-regression record`` and ``compare``.

Exit codes (designed for CI):

- ``0`` — comparison passed (or ``record`` succeeded)
- ``1`` — comparison finished and the candidate regressed beyond thresholds
- ``2`` — usage error, unreadable input, malformed trajectory/config, or other
  user-facing failure
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .config import Config, load_config
from .errors import ConfigError, SlamRegressionError
from .metrics import compute_metrics
from .policy import ComparisonResult, evaluate
from .report import METRIC_KEYS, METRIC_LABELS, ReportContext, render_markdown
from .trajectories import associate_trajectories, load_tum

BASELINE_SCHEMA = "slam-regression-baseline/v1"
BASELINE_SCHEMA_MULTI = "slam-regression-baseline/v2"
REPORT_SCHEMA = "slam-regression-report/v1"


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_hashes(reference_path: str, estimate_path: str) -> dict:
    return {
        "reference": {"path": os.path.basename(reference_path), "sha256": _sha256(reference_path)},
        "estimate": {"path": os.path.basename(estimate_path), "sha256": _sha256(estimate_path)},
    }


def _flatten_estimates(groups: List[List[str]]) -> List[str]:
    """`--estimate` uses append+nargs to accept both `--e a b` and repeated flags."""
    return [item for group in groups for item in group]


def _metric_stats(values: List[float]) -> dict:
    """Robust distribution stats for one metric over N runs."""
    if not values:
        raise ConfigError("cannot compute stats for an empty run list")
    ordered = sorted(values)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
    deviations = sorted(abs(v - median) for v in values)
    mad = deviations[n // 2] if n % 2 else 0.5 * (deviations[n // 2 - 1] + deviations[n // 2])
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return {
        "n": n,
        "median": median,
        "mad": mad,
        "mean": mean,
        "std": variance ** 0.5,
        "min": ordered[0],
        "max": ordered[-1],
    }


def _settings_dict(config: Config) -> dict:
    return {
        "association": {"max_timestamp_diff": config.association.max_timestamp_diff},
        "alignment": {
            "enabled": config.alignment.enabled,
            "correct_scale": config.alignment.correct_scale,
        },
        "rpe_delta": config.rpe_delta,
    }


def _compute_with_coverage(config: Config, reference_path: str, estimate_path: str) -> tuple:
    reference = load_tum(reference_path)
    estimate = load_tum(estimate_path)
    matched_ref, matched_est = associate_trajectories(
        reference, estimate, config.association.max_timestamp_diff
    )
    result = compute_metrics(
        matched_ref.positions,
        matched_ref.rotations,
        matched_est.positions,
        matched_est.rotations,
        align=config.alignment.enabled,
        correct_scale=config.alignment.correct_scale,
        rpe_delta=config.rpe_delta,
    )
    reference_span = float(reference.timestamps[-1] - reference.timestamps[0])
    matched_span = (
        float(matched_ref.timestamps[-1] - matched_ref.timestamps[0]) if matched_ref.count > 0 else 0.0
    )
    coverage = {
        "matched_pose_count": result.num_pairs,
        "reference_pose_count": reference.count,
        "matched_pose_ratio": (result.num_pairs / reference.count) if reference.count else None,
        "time_coverage_ratio": (matched_span / reference_span) if reference_span > 0 else None,
    }
    return result.to_dict(), coverage


def _evaluate_coverage(coverage: dict, coverage_config) -> dict:
    gated = dict(coverage)
    min_pose_ratio = coverage_config.min_matched_pose_ratio
    min_time_ratio = coverage_config.min_time_coverage_ratio
    gated["min_matched_pose_ratio"] = min_pose_ratio
    gated["min_time_coverage_ratio"] = min_time_ratio

    failures = []
    pose_ratio = coverage.get("matched_pose_ratio")
    if min_pose_ratio is not None:
        if pose_ratio is None or pose_ratio < min_pose_ratio:
            failures.append(
                "matched pose ratio {} below minimum {}".format(
                    "n/a" if pose_ratio is None else f"{pose_ratio:.4f}", min_pose_ratio
                )
            )
    time_ratio = coverage.get("time_coverage_ratio")
    if min_time_ratio is not None:
        if time_ratio is None or time_ratio < min_time_ratio:
            failures.append(
                "time coverage ratio {} below minimum {}".format(
                    "n/a" if time_ratio is None else f"{time_ratio:.4f}", min_time_ratio
                )
            )
    gated["passed"] = not failures
    gated["notes"] = failures
    return gated


def _load_baseline(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            baseline = json.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read baseline file '{path}': {exc.strerror or exc}") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"baseline file '{path}' is not valid JSON: {exc}") from None
    schema = baseline.get("schema") if isinstance(baseline, dict) else None
    if schema not in (BASELINE_SCHEMA, BASELINE_SCHEMA_MULTI):
        raise ConfigError(
            f"'{path}' is not a {BASELINE_SCHEMA} or {BASELINE_SCHEMA_MULTI} baseline file; "
            f"generate one with 'slam-regression record'"
        )
    metrics = baseline.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError(f"baseline file '{path}' contains no metrics")
    schema = baseline.get("schema")
    for key in ("ate_rmse", "rpe_translation_rmse"):
        value = metrics.get(key)
        if schema == BASELINE_SCHEMA_MULTI:
            if not isinstance(value, dict) or not isinstance(value.get("median"), (int, float)):
                raise ConfigError(
                    f"baseline file '{path}' has invalid distribution stats for '{key}'"
                )
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ConfigError(f"baseline file '{path}' has invalid metric '{key}'")
    if schema == BASELINE_SCHEMA_MULTI:
        runs = baseline.get("runs")
        if not isinstance(runs, dict) or not all(isinstance(v, list) for v in runs.values()):
            raise ConfigError(f"baseline file '{path}' has no per-run metric values")
    return baseline


def _write_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _format_change(change: Optional[float]) -> str:
    if change is None:
        return "n/a"
    return f"{change:+.2f}%"


def _print_comparisons(result: ComparisonResult) -> None:
    for comparison in result.comparisons:
        label = METRIC_LABELS.get(comparison.metric, comparison.metric)
        print(f"{label}:")
        print(f"  baseline:  {comparison.baseline:.6f} m")
        print(f"  candidate: {comparison.candidate:.6f} m")
        print(f"  change: {_format_change(comparison.change_percent)}")
        if comparison.threshold_percent is not None:
            print(f"  threshold: {comparison.threshold_percent:+.2f}%")
        if comparison.absolute_budget is not None:
            print(f"  absolute budget: {comparison.absolute_budget:.6f} m")
        if comparison.max_value is not None:
            print(f"  max value: {comparison.max_value:.6f} m")
        if comparison.note:
            print(f"  note: {comparison.note}")
    if result.coverage is not None:
        coverage = result.coverage
        print(
            "Coverage: {}/{} poses ({:.4f}), time {:.4f}".format(
                coverage["matched_pose_count"],
                coverage["reference_pose_count"],
                coverage["matched_pose_ratio"] if coverage["matched_pose_ratio"] is not None else 0.0,
                coverage["time_coverage_ratio"] if coverage["time_coverage_ratio"] is not None else 0.0,
            )
        )
        for note in coverage.get("notes", []):
            print(f"  coverage gate: {note}")
    print("STATUS: {}".format("PASS" if result.passed else "FAIL"))
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _command_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    estimates = _flatten_estimates(args.estimate)
    per_run = [_compute_with_coverage(config, args.reference, estimate) for estimate in estimates]
    metric_runs = {key: [metrics[key] for metrics, _ in per_run] for key in METRIC_KEYS}
    reference_hash = {"path": os.path.basename(args.reference), "sha256": _sha256(args.reference)}

    if len(estimates) == 1:
        metrics, coverage = per_run[0]
        payload = {
            "schema": BASELINE_SCHEMA,
            "tool_version": __version__,
            "created_utc": _utc_now_iso(),
            "metrics": {key: metrics[key] for key in METRIC_KEYS},
            "num_pairs": metrics["num_pairs"],
            "coverage": coverage,
            "settings": _settings_dict(config),
            "inputs": {
                "reference": os.path.basename(args.reference),
                "estimate": os.path.basename(estimates[0]),
            },
            "input_hashes": {
                "reference": reference_hash,
                "estimate": _input_hashes(args.reference, estimates[0])["estimate"],
            },
            "config_sha256": _sha256(args.config) if args.config else None,
        }
        summary = "ate_rmse={:.6f} m, rpe_translation_rmse={:.6f} m ({} pairs)".format(
            metrics["ate_rmse"], metrics["rpe_translation_rmse"], metrics["num_pairs"]
        )
    else:
        stats = {key: _metric_stats(values) for key, values in metric_runs.items()}
        payload = {
            "schema": BASELINE_SCHEMA_MULTI,
            "tool_version": __version__,
            "created_utc": _utc_now_iso(),
            "runs": metric_runs,
            "metrics": stats,
            "num_pairs": [metrics["num_pairs"] for metrics, _ in per_run],
            "coverage": [coverage for _, coverage in per_run],
            "settings": _settings_dict(config),
            "inputs": {
                "reference": os.path.basename(args.reference),
                "estimates": [os.path.basename(estimate) for estimate in estimates],
            },
            "input_hashes": {
                "reference": reference_hash,
                "estimates": [
                    {"path": os.path.basename(estimate), "sha256": _sha256(estimate)}
                    for estimate in estimates
                ],
            },
            "config_sha256": _sha256(args.config) if args.config else None,
        }
        summary = "{} runs: ate_rmse median={:.6f}+/-{:.6f} m (MAD), rpe median={:.6f}+/-{:.6f} m".format(
            len(estimates),
            stats["ate_rmse"]["median"], stats["ate_rmse"]["mad"],
            stats["rpe_translation_rmse"]["median"], stats["rpe_translation_rmse"]["mad"],
        )
    _write_json(args.json, payload)
    print(f"baseline recorded: {summary} -> {args.json}")
    return 0


# Settings that change what the metric numbers mean. A baseline must only be
# compared against candidates evaluated with identical values.
_SEMANTIC_SETTINGS = (
    ("alignment", "enabled"),
    ("alignment", "correct_scale"),
    ("association", "max_timestamp_diff"),
)


def _check_baseline_compatibility(
    baseline: dict, config: Config, reference_path: str, allow_incompatible: bool
) -> List[str]:
    """Raise ConfigError on incompatible baselines; return warnings for soft issues."""
    warnings: List[str] = []
    detail = (
        "re-record the baseline or re-run with --allow-incompatible-baseline to override"
    )

    baseline_settings = baseline.get("settings")
    if isinstance(baseline_settings, dict):
        for section, key in _SEMANTIC_SETTINGS:
            baseline_value = baseline_settings.get(section, {}).get(key)
            current_value = getattr(getattr(config, section), key)
            if baseline_value is not None and baseline_value != current_value:
                message = (
                    f"baseline was recorded with {section}.{key}={baseline_value!r} "
                    f"but compare uses {current_value!r}; the metric values are not "
                    f"comparable. {detail}"
                )
                if allow_incompatible:
                    warnings.append(f"incompatible baseline override: {message}")
                else:
                    raise ConfigError(message)
        baseline_rpe_delta = baseline_settings.get("rpe_delta")
        if baseline_rpe_delta is not None and baseline_rpe_delta != config.rpe_delta:
            message = (
                f"baseline was recorded with rpe_delta={baseline_rpe_delta!r} but compare "
                f"uses {config.rpe_delta!r}; the metric values are not comparable. {detail}"
            )
            if allow_incompatible:
                warnings.append(f"incompatible baseline override: {message}")
            else:
                raise ConfigError(message)
    else:
        warnings.append("baseline has no settings block; semantic compatibility cannot be checked")

    input_hashes = baseline.get("input_hashes")
    if isinstance(input_hashes, dict) and isinstance(input_hashes.get("reference"), dict):
        recorded = input_hashes["reference"].get("sha256")
        if recorded and recorded != _sha256(reference_path):
            message = (
                f"reference trajectory '{reference_path}' does not match the file the baseline "
                f"was recorded against (sha256 mismatch); the comparison would mix two "
                f"different ground truths. {detail}"
            )
            if allow_incompatible:
                warnings.append(f"incompatible baseline override: {message}")
            else:
                raise ConfigError(message)
    else:
        warnings.append(
            "baseline was recorded by an older version without input fingerprints; "
            "reference provenance cannot be verified"
        )
    return warnings


def _load_baseline_metrics(baseline: dict) -> tuple:
    """Return (single-value metrics, optional distributions) for either schema."""
    schema = baseline.get("schema")
    if schema == BASELINE_SCHEMA_MULTI:
        stats = baseline["metrics"]
        distributions = stats
        medians = {}
        for name, block in stats.items():
            if not isinstance(block, dict) or "median" not in block:
                raise ConfigError(f"baseline v2 metric '{name}' has no median block")
            medians[name] = block["median"]
        return medians, distributions
    return baseline["metrics"], None


def _command_compare(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    baseline = _load_baseline(args.baseline)
    provenance_warnings = _check_baseline_compatibility(
        baseline, config, args.reference, args.allow_incompatible_baseline
    )
    baseline_metrics, baseline_distributions = _load_baseline_metrics(baseline)

    estimates = _flatten_estimates(args.estimate)
    per_run = [_compute_with_coverage(config, args.reference, estimate) for estimate in estimates]
    metric_runs = {key: [metrics[key] for metrics, _ in per_run] for key in METRIC_KEYS}
    multi_candidate = len(estimates) > 1
    if multi_candidate:
        candidate_stats = {key: _metric_stats(values) for key, values in metric_runs.items()}
        candidate_values = {key: stats["median"] for key, stats in candidate_stats.items()}
        candidate_metrics = per_run[len(estimates) // 2][0]  # representative run for num_pairs
        coverage_infos = [coverage for _, coverage in per_run]
    else:
        candidate_metrics = per_run[0][0]
        candidate_values = {key: candidate_metrics[key] for key in METRIC_KEYS}
        candidate_stats = None
        coverage_infos = [per_run[0][1]]

    result = evaluate(
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_values,
        metric_names=config.metric_names,
        thresholds=config.metrics,
        baseline_distributions=baseline_distributions,
    )
    result.warnings.extend(provenance_warnings)

    # Coverage gates: conservative across runs (worst ratio must pass).
    gated = [
        _evaluate_coverage(coverage, config.coverage) for coverage in coverage_infos
    ]
    worst = min(gated, key=lambda c: (c["matched_pose_ratio"] or 0.0, c["time_coverage_ratio"] or 0.0))
    result.coverage = worst
    if not result.coverage["passed"]:
        result.passed = False

    inputs = {
        "reference": os.path.basename(args.reference),
        "estimate": (
            os.path.basename(estimates[0])
            if len(estimates) == 1
            else [os.path.basename(estimate) for estimate in estimates]
        ),
    }
    settings = _settings_dict(config)
    baseline_runs = None
    if baseline_distributions:
        first = next(iter(baseline_distributions.values()), None)
        if isinstance(first, dict) and "n" in first:
            baseline_runs = int(first["n"])
    context = ReportContext(
        tool_version=__version__,
        created_utc=_utc_now_iso(),
        baseline_file=os.path.basename(args.baseline),
        inputs=inputs,
        settings=settings,
        candidate_num_pairs=candidate_metrics["num_pairs"],
        warnings=list(result.warnings),
        baseline_runs=baseline_runs,
        candidate_runs=len(estimates) if multi_candidate else None,
    )
    payload = {
        "schema": REPORT_SCHEMA,
        "tool_version": __version__,
        "created_utc": context.created_utc,
        "passed": result.passed,
        "comparisons": [c.to_dict() for c in result.comparisons],
        "warnings": list(result.warnings),
        "settings": settings,
        "candidate": {
            "metrics": candidate_values,
            "num_pairs": candidate_metrics["num_pairs"],
            "runs": candidate_stats,
            "count": len(estimates),
        },
        "coverage": result.coverage,
        "baseline_file": context.baseline_file,
        "inputs": inputs,
    }
    if args.json:
        _write_json(args.json, payload)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(render_markdown(result, context))

    _print_comparisons(result)
    return 0 if result.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slam-regression",
        description="Lightweight regression gate for SLAM & odometry trajectories.",
    )
    parser.add_argument("--version", action="version", version="slam-regression " + __version__)
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    record = subparsers.add_parser(
        "record", help="compute metrics for one estimate and store them as a baseline JSON"
    )
    record.add_argument("--reference", required=True, help="ground-truth trajectory (TUM format)")
    record.add_argument(
        "--estimate",
        required=True,
        nargs="+",
        action="append",
        metavar="ESTIMATE",
        help="baseline estimate trajectory (TUM format); pass several (or repeat the "
        "flag) to record a multi-run baseline (schema v2 with median/MAD stats)",
    )
    record.add_argument("--json", required=True, help="output path for the baseline JSON")
    record.add_argument("--config", default=None, help="YAML config (defaults are used if omitted)")
    record.set_defaults(func=_command_record)

    compare = subparsers.add_parser(
        "compare", help="compare a candidate estimate against a recorded baseline"
    )
    compare.add_argument("--baseline", required=True, help="baseline JSON from 'slam-regression record'")
    compare.add_argument("--reference", required=True, help="ground-truth trajectory (TUM format)")
    compare.add_argument(
        "--estimate",
        required=True,
        nargs="+",
        action="append",
        metavar="ESTIMATE",
        help="candidate estimate trajectory (TUM format); pass several (or repeat the "
        "flag) to compare the median of repeated runs (robust against single-run noise)",
    )
    compare.add_argument("--config", default=None, help="YAML config (defaults are used if omitted)")
    compare.add_argument("--json", default=None, help="write a JSON report to this path")
    compare.add_argument("--report", default=None, help="write a Markdown report to this path")
    compare.add_argument(
        "--allow-incompatible-baseline",
        action="store_true",
        help="override the baseline compatibility checks (semantic settings and "
        "reference fingerprint); a warning is recorded in the report",
    )
    compare.set_defaults(func=_command_compare)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SlamRegressionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

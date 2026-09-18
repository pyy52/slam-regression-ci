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
REPORT_SCHEMA = "slam-regression-report/v1"


def _utc_now_iso() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _settings_dict(config: Config) -> dict:
    return {
        "association": {"max_timestamp_diff": config.association.max_timestamp_diff},
        "alignment": {
            "enabled": config.alignment.enabled,
            "correct_scale": config.alignment.correct_scale,
        },
        "rpe_delta": config.rpe_delta,
    }


def _compute_for_estimate(config: Config, reference_path: str, estimate_path: str) -> dict:
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
    return result.to_dict()


def _load_baseline(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            baseline = json.load(handle)
    except OSError as exc:
        raise ConfigError("cannot read baseline file '{}': {}".format(path, exc.strerror or exc)) from None
    except json.JSONDecodeError as exc:
        raise ConfigError("baseline file '{}' is not valid JSON: {}".format(path, exc)) from None
    if not isinstance(baseline, dict) or baseline.get("schema") != BASELINE_SCHEMA:
        raise ConfigError(
            "'{}' is not a {} baseline file; generate one with 'slam-regression record'".format(
                path, BASELINE_SCHEMA
            )
        )
    metrics = baseline.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError("baseline file '{}' contains no metrics".format(path))
    for key in ("ate_rmse", "rpe_translation_rmse"):
        value = metrics.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ConfigError("baseline file '{}' has invalid metric '{}'".format(path, key))
    return baseline


def _write_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _format_change(change: Optional[float]) -> str:
    if change is None:
        return "n/a"
    return "{:+.2f}%".format(change)


def _print_comparisons(result: ComparisonResult) -> None:
    for comparison in result.comparisons:
        label = METRIC_LABELS.get(comparison.metric, comparison.metric)
        print("{}:".format(label))
        print("  baseline:  {:.6f} m".format(comparison.baseline))
        print("  candidate: {:.6f} m".format(comparison.candidate))
        print("  change: {}".format(_format_change(comparison.change_percent)))
        if comparison.threshold_percent is not None:
            print("  threshold: {:+.2f}%".format(comparison.threshold_percent))
        if comparison.note:
            print("  note: {}".format(comparison.note))
    print("STATUS: {}".format("PASS" if result.passed else "FAIL"))
    for warning in result.warnings:
        print("warning: {}".format(warning), file=sys.stderr)


def _command_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    metrics = _compute_for_estimate(config, args.reference, args.estimate)
    payload = {
        "schema": BASELINE_SCHEMA,
        "tool_version": __version__,
        "created_utc": _utc_now_iso(),
        "metrics": {key: metrics[key] for key in METRIC_KEYS},
        "num_pairs": metrics["num_pairs"],
        "settings": _settings_dict(config),
        "inputs": {
            "reference": os.path.basename(args.reference),
            "estimate": os.path.basename(args.estimate),
        },
    }
    _write_json(args.json, payload)
    print(
        "baseline recorded: ate_rmse={:.6f} m, rpe_translation_rmse={:.6f} m ({} pairs) -> {}".format(
            metrics["ate_rmse"], metrics["rpe_translation_rmse"], metrics["num_pairs"], args.json
        )
    )
    return 0


def _command_compare(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    baseline = _load_baseline(args.baseline)

    candidate_metrics = _compute_for_estimate(config, args.reference, args.estimate)
    candidate_values = {key: candidate_metrics[key] for key in METRIC_KEYS}

    result = evaluate(
        baseline_metrics=baseline["metrics"],
        candidate_metrics=candidate_values,
        metric_names=config.metric_names,
        thresholds={name: rule.max_relative_regression_percent for name, rule in config.metrics.items()},
    )

    baseline_settings = baseline.get("settings")
    if isinstance(baseline_settings, dict):
        baseline_alignment = baseline_settings.get("alignment", {})
        if baseline_alignment.get("enabled") != config.alignment.enabled or baseline_alignment.get(
            "correct_scale"
        ) != config.alignment.correct_scale:
            result.warnings.append(
                "baseline was recorded with different alignment settings; "
                "values may not be directly comparable"
            )

    inputs = {
        "reference": os.path.basename(args.reference),
        "estimate": os.path.basename(args.estimate),
    }
    settings = _settings_dict(config)
    context = ReportContext(
        tool_version=__version__,
        created_utc=_utc_now_iso(),
        baseline_file=os.path.basename(args.baseline),
        inputs=inputs,
        settings=settings,
        candidate_num_pairs=candidate_metrics["num_pairs"],
        warnings=list(result.warnings),
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
        },
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
    record.add_argument("--estimate", required=True, help="baseline estimate trajectory (TUM format)")
    record.add_argument("--json", required=True, help="output path for the baseline JSON")
    record.add_argument("--config", default=None, help="YAML config (defaults are used if omitted)")
    record.set_defaults(func=_command_record)

    compare = subparsers.add_parser(
        "compare", help="compare a candidate estimate against a recorded baseline"
    )
    compare.add_argument("--baseline", required=True, help="baseline JSON from 'slam-regression record'")
    compare.add_argument("--reference", required=True, help="ground-truth trajectory (TUM format)")
    compare.add_argument("--estimate", required=True, help="candidate estimate trajectory (TUM format)")
    compare.add_argument("--config", default=None, help="YAML config (defaults are used if omitted)")
    compare.add_argument("--json", default=None, help="write a JSON report to this path")
    compare.add_argument("--report", default=None, help="write a Markdown report to this path")
    compare.set_defaults(func=_command_compare)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SlamRegressionError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2

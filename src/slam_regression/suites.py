"""Multi-sequence benchmark suites.

A suite YAML lists sequences (each with its own baseline/reference/estimate
and optional per-sequence config) plus a policy for combining the verdicts::

    sequences:
      - name: room1
        baseline: baselines/room1.json
        reference: data/room1_gt.tum
        estimate: results/room1_est.tum
      - name: room2
        baseline: baselines/room2.json
        reference: data/room2_gt.tum
        estimate: results/room2_est.tum
        estimate: [results/room2_run1.tum, results/room2_run2.tum]

    suite_policy:
      max_failed_sequences: 0

The overall verdict fails when more than ``max_failed_sequences`` sequences
fail. Reports order failed sequences by their worst metric regression first.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml

from .errors import ConfigError

KNOWN_TOP_LEVEL_KEYS = ("sequences", "suite_policy")


@dataclass
class SequenceSpec:
    name: str
    baseline: str
    reference: str
    estimates: List[str]
    config: Optional[str] = None


@dataclass
class SuitePolicy:
    max_failed_sequences: int = 0


@dataclass
class SuiteConfig:
    sequences: List[SequenceSpec] = field(default_factory=list)
    policy: SuitePolicy = field(default_factory=SuitePolicy)
    base_dir: str = "."

    def resolve(self, path: str) -> str:
        """Absolute paths pass through; relative paths resolve against the suite file."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)


def _parse_sequence(raw: object, index: int) -> SequenceSpec:
    where = f"sequences[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")
    unknown = [key for key in raw if key not in ("name", "baseline", "reference", "estimate", "config")]
    if unknown:
        raise ConfigError(f"{where} has unknown option(s): {', '.join(sorted(unknown))}")
    for required in ("name", "baseline", "reference", "estimate"):
        if raw.get(required) is None:
            raise ConfigError(f"{where} is missing required key '{required}'")
    name = raw["name"]
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where}.name must be a non-empty string")
    for key in ("baseline", "reference"):
        if not isinstance(raw[key], str):
            raise ConfigError(f"{where}.{key} must be a path string")
    estimate = raw["estimate"]
    if isinstance(estimate, str):
        estimates = [estimate]
    elif isinstance(estimate, list) and estimate and all(isinstance(item, str) for item in estimate):
        estimates = estimate
    else:
        raise ConfigError(f"{where}.estimate must be a path string or a list of path strings")
    config_path = raw.get("config")
    if config_path is not None and not isinstance(config_path, str):
        raise ConfigError(f"{where}.config must be a path string")
    return SequenceSpec(
        name=name, baseline=raw["baseline"], reference=raw["reference"], estimates=estimates, config=config_path
    )


def suite_config_from_dict(raw: Optional[dict]) -> SuiteConfig:
    if raw is None:
        raise ConfigError("suite configuration is empty")
    if not isinstance(raw, dict):
        raise ConfigError("suite configuration must be a YAML mapping")
    unknown = [key for key in raw if key not in KNOWN_TOP_LEVEL_KEYS]
    if unknown:
        raise ConfigError(
            f"unknown suite configuration key(s): {', '.join(sorted(unknown))}; "
            f"valid keys are: {', '.join(KNOWN_TOP_LEVEL_KEYS)}"
        )
    sequences_raw = raw.get("sequences")
    if not isinstance(sequences_raw, list) or not sequences_raw:
        raise ConfigError("'sequences' must be a non-empty list")
    sequences = [_parse_sequence(item, index) for index, item in enumerate(sequences_raw)]
    names = [spec.name for spec in sequences]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"duplicate sequence name(s): {', '.join(duplicates)}")

    policy_raw = raw.get("suite_policy") or {}
    if not isinstance(policy_raw, dict):
        raise ConfigError("'suite_policy' must be a mapping")
    unknown = [key for key in policy_raw if key != "max_failed_sequences"]
    if unknown:
        raise ConfigError(f"'suite_policy' has unknown option(s): {', '.join(sorted(unknown))}")
    max_failed = policy_raw.get("max_failed_sequences", 0)
    if not isinstance(max_failed, int) or isinstance(max_failed, bool) or max_failed < 0:
        raise ConfigError("'suite_policy.max_failed_sequences' must be an integer >= 0")
    return SuiteConfig(sequences=sequences, policy=SuitePolicy(max_failed_sequences=max_failed))


def load_suite_config(path: str) -> SuiteConfig:
    try:
        handle = open(path, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read suite file '{path}': {exc.strerror or exc}") from None
    with handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in '{path}': {exc}") from None
    config = suite_config_from_dict(raw)
    config.base_dir = os.path.dirname(os.path.abspath(path))
    return config

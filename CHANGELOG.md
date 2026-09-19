# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `associate()` now pairs each reference pose with the *nearest* estimate pose
  within `max_timestamp_diff`; the previous loop could pair with a
  first-within-tolerance pose that was not the closest (different rates,
  offsets, or dropped frames silently biased metrics). Association indices
  are parity-checked against evo in CI.

### Changed

- **Baseline compatibility is now strict.** `compare` exits with code 2 when
  the baseline was recorded with different metric-semantic settings
  (`alignment.enabled`, `alignment.correct_scale`, `rpe_delta`,
  `association.max_timestamp_diff`) or when the reference trajectory's sha256
  no longer matches the recorded baseline. Use the new
  `--allow-incompatible-baseline` flag to override explicitly (a warning is
  recorded in the report). Baselines from v0.1.0 (without fingerprints) still
  work, with a provenance warning.

### Added

- Trajectory-coverage gates: `compare` now reports matched pose ratio and
  time coverage ratio against the reference, with optional config gates
  (`coverage.min_matched_pose_ratio`, `coverage.min_time_coverage_ratio`).
  A candidate that loses tracking early can no longer look good on ATE.
- Absolute threshold policies per metric: `max_absolute_regression`
  (baseline-relative budget in meters) and `max_value` (absolute ceiling).
  A metric fails when any configured rule is exceeded, so percent-only,
  absolute-only, or combined policies are all expressible.
- Baselines now record sha256 fingerprints of the reference and estimate
  trajectories and of the config file (`input_hashes`, `config_sha256`),
  so a silently changed ground-truth file can no longer invalidate a
  comparison unnoticed.
- Composite GitHub Action (`action.yml`): downstream repositories can gate
  with `uses: pyy52/slam-regression-ci@v0.1`; exercised in CI via `uses: ./`.
- PyPI publish workflow (`release.yml`) using Trusted Publishing — no API
  tokens; maintainer registration documented in `PUBLISHING.md`.
- Committed sample Markdown report (`docs/sample_report.md`).

## [0.1.0] - 2026-09-18

First usable release: a minimal, dependency-light regression gate for SLAM and
odometry trajectories.

### Added

- `slam-regression record`: compute ATE/RPE metrics for one estimate/reference
  pair and persist them as a versionable baseline JSON
  (`slam-regression-baseline/v1`).
- `slam-regression compare`: gate a candidate estimate against a recorded
  baseline with per-metric thresholds, exiting `0` on pass, `1` on regression,
  `2` on input/config errors.
- TUM trajectory loading (`timestamp tx ty tz qx qy qz qw`) with strict
  validation, and greedy one-to-one timestamp association.
- ATE RMSE (Umeyama rigid alignment, optional uniform scale correction) and
  RPE translation RMSE (consecutive frames) following TUM/evo conventions.
- Strict YAML configuration with per-metric
  `max_relative_regression_percent`, association tolerance, alignment
  options, and `rpe_delta`.
- Markdown and JSON report output (`--report`, `--json`).
- Deterministic synthetic examples with a committed baseline JSON, generated
  by `scripts/gen_examples.py`.
- Metric parity check against evo (`scripts/evo_parity.py`, CI workflow
  pending) within 1e-6 relative tolerance on the bundled examples.
- Docker image (`docker/Dockerfile`, python:3.11-slim).
- CI running pytest on Python 3.8–3.12 (workflow pending), ruff lint, CLI
  smoke tests, and a Docker build job.

### Known limitations

- TUM input format only; KITTI poses are planned.
- Metrics limited to ATE RMSE and consecutive-frame RPE translation RMSE.
- Not yet published to PyPI (install from the Git tag).

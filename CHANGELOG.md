# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

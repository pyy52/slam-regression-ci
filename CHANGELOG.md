# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each section reflects the actual contents of the corresponding Git tag.

## [0.2.1] - 2026-09-19

Release-hygiene and correctness patch; no new features.

### Fixed

- A `max_mad_multiples`-only gate is now reported as an active gate; it no
  longer produced a misleading "no threshold configured" note on pass.
- Relative paths inside a suite YAML now resolve against the suite file's
  directory instead of the current working directory.
- Repeated candidate runs report `num_pairs` as a min/median/max distribution
  instead of an arbitrary representative run.
- Missing input files fail with clean error messages instead of tracebacks
  during baseline fingerprinting.

### Changed

- Release workflow hardening: tag/pyproject/package version consistency check,
  `twine check` on artifacts, wheel smoke test in a clean venv (one passing and
  one failing example), and publishing restricted to tag pushes —
  `workflow_dispatch` builds and verifies only.
- README positioning updated to "variance-aware regression gates"; install and
  Action examples reference current versions (`@v0` movable major tag).

## [0.2.0] - 2026-09-19

Second feature release: regression intelligence per the project audit.

### Added

- **Multi-run baselines** (baseline schema v2): `record --estimate a.tum b.tum
  ...` records per-run metric values plus median/MAD/mean/std; `compare
  --estimate c1.tum c2.tum` gates the median of repeated candidate runs. New
  optional robust rule `max_mad_multiples`: fail when the candidate leaves the
  baseline's natural run-to-run spread (`median + k * MAD`). Single-run v1
  baselines remain fully supported.
- **Multi-sequence suites**: `slam-regression suite` runs a list of sequences
  (each with its own baseline/reference/estimates and optional per-sequence
  config) and combines them under `suite_policy.max_failed_sequences`; suite
  reports order failed sequences worst-regression first.
- **GitHub job summary**: the composite action appends the Markdown report to
  `$GITHUB_STEP_SUMMARY` so verdicts render on the workflow summary page.

### Fixed

- Fair evo association comparison: the parity script previously called evo's
  matcher longer-side-first (not how evo's own `associate_trajectories` drives
  it). Called as evo intends, pair counts match ours exactly on real data;
  residual ≤0.3% metric differences are selection-order and documented.
- Missing input files fail with clean error messages instead of tracebacks.

## [0.1.1] - 2026-09-19

Correctness and trust release from the project audit. Upgrade recommended for
all 0.1.0 users.

### Fixed

- **Nearest-neighbor association**: each reference pose is now matched to the
  *nearest* estimate pose within `max_timestamp_diff`; the previous loop could
  pair with a first-within-tolerance pose that was not the closest (different
  rates, offsets, or dropped frames silently biased metrics). Association
  indices are parity-checked against evo in CI.
- PyPI upload: replaced the invalid trove classifier
  (`Topic :: Scientific/Engineering :: Robotics` is not in the official
  classifier list) that caused a 400 on publish.

### Changed

- **Baseline compatibility is now strict.** `compare` exits with code 2 when
  the baseline was recorded with different metric-semantic settings
  (`alignment.enabled`, `alignment.correct_scale`, `rpe_delta`,
  `association.max_timestamp_diff`) or when the reference trajectory's sha256
  no longer matches the recorded baseline. Use the new
  `--allow-incompatible-baseline` flag to override explicitly (a warning is
  recorded in the report). Baselines from 0.1.0 (without fingerprints) still
  work, with a provenance warning.

### Added

- **Baseline fingerprints**: `record` stores sha256 of the reference/estimate
  trajectories and of the config file (`input_hashes`, `config_sha256`), so a
  silently changed ground-truth file can no longer invalidate a comparison
  unnoticed.
- **Trajectory-coverage gates**: matched pose ratio and time coverage ratio
  against the reference, with optional config gates
  (`coverage.min_matched_pose_ratio`, `coverage.min_time_coverage_ratio`). A
  candidate that loses tracking early can no longer look good on ATE.
- **Absolute threshold policies**: per-metric `max_absolute_regression`
  (baseline-relative budget) and `max_value` (absolute ceiling) alongside the
  relative percent rule; a metric fails when any configured rule is exceeded.
- Composite GitHub Action (`action.yml`): downstream repositories can gate
  with `uses: pyy52/slam-regression-ci@v0`; exercised in CI via `uses: ./`.
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
- Metric parity check against evo (`scripts/evo_parity.py`) within 1e-6
  relative tolerance on the bundled examples.
- Docker image (`docker/Dockerfile`, python:3.11-slim).
- CI running pytest on Python 3.8–3.12, ruff lint, CLI smoke tests, and a
  Docker build job.

### Known limitations

- TUM input format only; KITTI poses are planned.
- Metrics limited to ATE RMSE and consecutive-frame RPE translation RMSE.

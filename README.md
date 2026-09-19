English | [简体中文](README.zh-CN.md)

# slam-regression-ci

[![CI](https://github.com/pyy52/slam-regression-ci/actions/workflows/ci.yml/badge.svg)](https://github.com/pyy52/slam-regression-ci/actions/workflows/ci.yml)
[![Metric parity](https://github.com/pyy52/slam-regression-ci/actions/workflows/parity.yml/badge.svg)](https://github.com/pyy52/slam-regression-ci/actions/workflows/parity.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](pyproject.toml)

A lightweight regression gate for SLAM & odometry trajectories: compare a
candidate trajectory against a recorded baseline, apply configurable
thresholds, and fail CI when localization accuracy got worse — with a
human-readable Markdown report and a machine-readable JSON report.

SLAM and odometry code changes can quietly degrade accuracy. Evaluation tools
like [evo](https://github.com/MichaelGrupp/evo) compute ATE/RPE, but they don't
decide **"is this PR a regression?"**. Hand-writing that policy per repository
is tedious and error-prone. This tool does exactly that, and nothing else:

```text
baseline JSON (committed) + ground truth + candidate estimate
        │
        ▼
ATE RMSE / RPE thresholds ──► exit 0 (pass) or exit 1 (regression)
        │
        ▼
report.md (for humans) + report.json (for CI/automation)
```

Early-stage project seeking real-world feedback — try it on your repository and
[open an issue](https://github.com/pyy52/slam-regression-ci/issues).

## Installation

Requires Python 3.8+ (works on ROS1 Noetic / Ubuntu 20.04) and only `numpy` +
`PyYAML` at runtime.

```bash
pip install git+https://github.com/pyy52/slam-regression-ci.git@v0.1.0
```

Or try it without installing:

```bash
git clone https://github.com/pyy52/slam-regression-ci.git
cd slam-regression-ci && pip install .
```

## 60-second quickstart

The repository ships deterministic synthetic examples (a circle trajectory, a
noisy "good" estimate, and a degraded candidate):

```bash
# 1) Passes: the baseline compared against itself (~0% change), exit code 0
slam-regression compare \
  --baseline examples/baseline_metrics.json \
  --reference examples/reference.tum \
  --estimate examples/baseline.tum \
  --config examples/regression.yaml

# 2) Fails: degraded candidate (ATE +282%), exit code 1
slam-regression compare \
  --baseline examples/baseline_metrics.json \
  --reference examples/reference.tum \
  --estimate examples/candidate_degraded.tum \
  --config examples/regression.yaml \
  --report report.md --json report.json
echo $?
```

For your own project, record a baseline once and commit it:

```bash
# After a known-good run of your SLAM system:
slam-regression record \
  --reference ground_truth.tum \
  --estimate my_slam_output.tum \
  --json baselines/room1_baseline.json
```

Then gate every change against it:

```bash
slam-regression compare \
  --baseline baselines/room1_baseline.json \
  --reference ground_truth.tum \
  --estimate my_slam_output.tum \
  --config regression.yaml \
  --report regression_report.md --json regression_report.json
```

### Example output

```text
ATE RMSE:
  baseline:  0.017247 m
  candidate: 0.065853 m
  change: +281.81%
  threshold: +10.00%
RPE translation RMSE:
  baseline:  0.025050 m
  candidate: 0.074284 m
  change: +196.60%
  threshold: +10.00%
STATUS: FAIL
```

Exit codes: `0` pass, `1` regression, `2` input/config error.

## Configuration

```yaml
metrics:
  # Relative increase over baseline allowed before failing, in percent.
  # Improvements (negative change) always pass. 0 rejects any increase.
  ate_rmse:
    max_relative_regression_percent: 10
  rpe_translation_rmse:
    max_relative_regression_percent: 10

association:
  max_timestamp_diff: 0.01   # seconds between paired poses

alignment:
  enabled: true              # Umeyama alignment of estimate to reference
  correct_scale: false       # also estimate a uniform scale (monocular)

rpe_delta: 1                 # frame gap for the relative pose error
```

Every key is optional: omitting `metrics` keeps the default gates, omitting
the whole file uses defaults for everything. Unknown keys and values are
rejected with actionable error messages.

## Use it as a CI gate in your repository

```yaml
# .github/workflows/slam-regression.yml in YOUR repository
name: SLAM regression
on: [pull_request]

jobs:
  regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install git+https://github.com/pyy52/slam-regression-ci.git@v0.1.0
      - name: Check trajectory regression
        run: |
          slam-regression compare \
            --baseline baselines/room1_baseline.json \
            --reference data/room1_gt.tum \
            --estimate results/room1_est.tum \
            --config regression.yaml \
            --report regression_report.md --json regression_report.json
      - name: Attach report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: regression-report
          path: |
            regression_report.md
            regression_report.json
```

Commit the baseline JSON (`baselines/room1_baseline.json`) once, and every
pull request that makes localization worse will fail — with an attached
Markdown report explaining exactly which metric moved.

Prefer a one-line action instead? The repository is also a composite action:

```yaml
      - uses: pyy52/slam-regression-ci@v0.1
        with:
          baseline: baselines/room1_baseline.json
          reference: data/room1_gt.tum
          estimate: results/room1_est.tum
```

See what the report looks like before installing: [sample report](docs/sample_report.md).

## Docker

```bash
docker build -f docker/Dockerfile -t slam-regression-ci .
docker run --rm -v "$PWD/examples:/data" slam-regression-ci compare \
  --baseline /data/baseline_metrics.json \
  --reference /data/reference.tum \
  --estimate /data/candidate_degraded.tum \
  --config /data/regression.yaml
```

## Metric trustworthiness

ATE/RPE are implemented on top of numpy following the TUM RGB-D benchmark
conventions, and CI verifies parity against
[evo](https://github.com/MichaelGrupp/evo) (the reference implementation) on
the bundled examples within `1e-6` relative tolerance
([parity workflow](.github/workflows/parity.yml)). evo remains the recommended
tool for advanced evaluation; this project deliberately stays minimal.

## Supported input formats

- **TUM text files**: `timestamp tx ty tz qx qy qz qw` (one pose per line,
  `#` comments allowed, quaternion order x y z w) — the format produced by
  the TUM RGB-D benchmark tools and consumed by evo.

## Limitations

- Trajectory input: TUM format only (KITTI poses planned).
- Metrics: ATE RMSE and RPE translation RMSE with consecutive frames
  (`delta = 1`); no per-axis breakdowns, no plots.
- Baselines are tied to a specific ground-truth file and dataset; changing
  the dataset means recording a new baseline.
- Reports are written to files; there is no PR-comment bot yet.

## Roadmap

- PyPI package (`slam-regression-ci`) — publish workflow ready, waiting on
  [Trusted Publishing registration](PUBLISHING.md)
- KITTI pose file support
- Additional metrics (RPE with configurable delta units, rotation error)
- Optional PR comment with the regression summary
- Baseline refresh helper (`record --update` policy)

## Contributing

Issues and pull requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Note that this project is maintained with
AI assistance for routine engineering work; all changes are reviewed before
merge.

## License

[MIT](LICENSE)

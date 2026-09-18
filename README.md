# slam-regression-ci

A lightweight CI regression gate for SLAM & odometry trajectories.

**Status: under active development — first release (v0.1.0) in progress.**

It compares a candidate trajectory against a committed baseline, applies
configurable per-metric thresholds (ATE RMSE, RPE translation RMSE), and fails
CI with a human-readable Markdown report plus a machine-readable JSON report.

See [CONTRIBUTING.md](CONTRIBUTING.md) to help out.

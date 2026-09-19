# SLAM regression report

**Verdict: FAIL**

Generated 2026-09-19T02:59:24Z by slam-regression 0.1.0

## Metric comparison

| Metric | Baseline | Candidate | Change | Threshold | Status |
|---|---:|---:|---:|---:|---|
| ATE RMSE | 0.017247 m | 0.065853 m | +281.81% | +10.00% | FAIL |
| RPE translation RMSE | 0.025050 m | 0.074284 m | +196.54% | +10.00% | FAIL |

## Run details

- baseline file: `baseline_metrics.json`
- reference: `reference.tum`
- estimate: `candidate_degraded.tum`
- matched pose pairs: 200
- alignment: Umeyama (rigid SE(3))
- association max timestamp diff: 0.01 s
- coverage: 200/200 poses (1.0000)
- time coverage: 1.0000

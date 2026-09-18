#!/usr/bin/env python3
"""Generate deterministic synthetic example trajectories for the repository.

Creates (in --out-dir, default: examples/):

- reference.tum            ground-truth trajectory (one full circle)
- baseline.tum             reference + small Gaussian noise
- candidate_degraded.tum   reference + larger noise + linear drift
- baseline_metrics.json    recorded baseline for the baseline.tum estimate

All outputs are fully determined by fixed seeds, so regenerated files stay
byte-identical apart from the JSON creation timestamp.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys

import numpy as np

N_POSES = 200
DT = 0.1
T0 = 1305031102.175304
RADIUS = 5.0
BASELINE_SIGMA = 0.01
DEGRADED_SIGMA = 0.03
DEGRADED_DRIFT_PER_POSE = 0.0008


def yaw_to_quaternion_xyzw(yaw: float) -> np.ndarray:
    half = yaw / 2.0
    return np.array([0.0, 0.0, math.sin(half), math.cos(half)])


def generate_reference() -> tuple:
    times = np.array([T0 + DT * i for i in range(N_POSES)])
    theta = 2.0 * math.pi * np.arange(N_POSES) / N_POSES
    positions = np.stack(
        [RADIUS * np.cos(theta), RADIUS * np.sin(theta), 0.5 * np.sin(3.0 * theta)], axis=1
    )
    quaternions = np.stack([yaw_to_quaternion_xyzw(t + math.pi / 2.0) for t in theta])
    return times, positions, quaternions


def write_tum(path: str, times: np.ndarray, positions: np.ndarray, quaternions: np.ndarray) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# synthetic example trajectory (deterministic, see scripts/gen_examples.py)\n")
        for t, pos, quat in zip(times, positions, quaternions):
            handle.write(
                f"{float(t):.9f} {pos[0]:.9f} {pos[1]:.9f} {pos[2]:.9f} "
                f"{quat[0]:.9f} {quat[1]:.9f} {quat[2]:.9f} {quat[3]:.9f}\n"
            )


def record_baseline(reference_path: str, estimate_path: str, out_path: str) -> None:
    code = subprocess.call(
        [
            sys.executable,
            "-c",
            "import sys; from slam_regression.cli import main; sys.exit(main())",
            "record",
            "--reference",
            reference_path,
            "--estimate",
            estimate_path,
            "--json",
            out_path,
        ]
    )
    if code != 0:
        raise SystemExit(f"record failed with exit code {code}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="examples", help="output directory (default: examples)")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    times, reference_positions, quaternions = generate_reference()

    baseline_noise = np.random.RandomState(1).normal(0.0, BASELINE_SIGMA, reference_positions.shape)
    degraded_noise = np.random.RandomState(2).normal(0.0, DEGRADED_SIGMA, reference_positions.shape)
    drift = np.zeros_like(reference_positions)
    drift[:, 0] = DEGRADED_DRIFT_PER_POSE * np.arange(N_POSES)

    write_tum(os.path.join(args.out_dir, "reference.tum"), times, reference_positions, quaternions)
    write_tum(
        os.path.join(args.out_dir, "baseline.tum"),
        times,
        reference_positions + baseline_noise,
        quaternions,
    )
    write_tum(
        os.path.join(args.out_dir, "candidate_degraded.tum"),
        times,
        reference_positions + degraded_noise + drift,
        quaternions,
    )
    record_baseline(
        os.path.join(args.out_dir, "reference.tum"),
        os.path.join(args.out_dir, "baseline.tum"),
        os.path.join(args.out_dir, "baseline_metrics.json"),
    )
    print(f"wrote reference.tum, baseline.tum, candidate_degraded.tum, baseline_metrics.json to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

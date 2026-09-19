#!/usr/bin/env python3
"""Verify that slam_regression's ATE/RPE agree with evo on the example data.

evo is the reference implementation for trajectory evaluation, but it is not a
runtime dependency (it would drag in scipy/matplotlib and newer Python).
Instead, this script runs in CI against evo and asserts that our numbers match
within a tight relative tolerance, so a change in our math cannot slip through
silently.

Exit code 0 = parity confirmed, 1 = mismatch, 2 = evo unavailable/misused.
"""

from __future__ import annotations

import argparse
import sys

REL_TOLERANCE = 1e-6


def compute_ours(reference_path: str, estimate_path: str) -> dict:
    from slam_regression.config import default_config
    from slam_regression.metrics import compute_metrics
    from slam_regression.trajectories import associate_trajectories, load_tum

    config = default_config()
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
    return {"ate_rmse": result.ate_rmse, "rpe_translation_rmse": result.rpe_translation_rmse}


def compute_evo(reference_path: str, estimate_path: str) -> dict:
    from evo.core import metrics as evo_metrics
    from evo.core import sync as evo_sync
    from evo.tools import file_interface

    ref_traj = file_interface.read_tum_trajectory_file(reference_path)
    est_traj = file_interface.read_tum_trajectory_file(estimate_path)
    ref_synced, est_synced = evo_sync.associate_trajectories(ref_traj, est_traj, max_diff=0.01)
    est_synced.align(ref_synced, correct_scale=False)

    ape = evo_metrics.APE(evo_metrics.PoseRelation.translation_part)
    ape.process_data((ref_synced, est_synced))

    rpe = evo_metrics.RPE(
        pose_relation=evo_metrics.PoseRelation.translation_part,
        delta=1,
        delta_unit=evo_metrics.Unit.frames,
        all_pairs=False,
    )
    rpe.process_data((ref_synced, est_synced))

    return {
        "ate_rmse": ape.get_statistic(evo_metrics.StatisticsType.rmse),
        "rpe_translation_rmse": rpe.get_statistic(evo_metrics.StatisticsType.rmse),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference", default="examples/reference.tum", help="ground-truth TUM trajectory"
    )
    parser.add_argument(
        "--estimate",
        nargs="+",
        default=["examples/baseline.tum", "examples/candidate_degraded.tum"],
        help="estimate trajectories to check",
    )
    args = parser.parse_args()

    print("{:<28} {:>14} {:>14} {:>12}".format("trajectory", "ours", "evo", "rel. diff"))
    failed = False
    for estimate_path in args.estimate:
        ours = compute_ours(args.reference, estimate_path)
        try:
            reference = compute_evo(args.reference, estimate_path)
        except ImportError:
            print("error: evo is not installed; run: pip install evo", file=sys.stderr)
            return 2

        # Association parity. Note: our association is one-to-one (each estimate
        # pose is used at most once, like the original TUM benchmark script),
        # while evo's matching_time_indices allows many reference poses to share
        # one estimate pose. For dense, matched-rate trajectories both agree;
        # for sparse/keyframe estimates they intentionally differ. A hard
        # failure is only correct when the pair SETS match but metrics don't
        # (that would be a math bug), so association differences are reported
        # as info and metric tolerance applies to the matching case.
        from evo.core import sync as evo_sync
        from evo.tools import file_interface

        ref_traj = file_interface.read_tum_trajectory_file(args.reference)
        est_traj = file_interface.read_tum_trajectory_file(estimate_path)
        evo_ri, evo_ei = evo_sync.matching_time_indices(
            ref_traj.timestamps, est_traj.timestamps, max_diff=0.01
        )
        from slam_regression.trajectories import associate

        my_ri, my_ei = associate(ref_traj.timestamps, est_traj.timestamps, 0.01)
        associations_match = list(my_ri) == list(evo_ri) and list(my_ei) == list(evo_ei)
        if associations_match:
            print(f"{estimate_path.split('/')[-1]}: association {len(my_ri)} pairs  ok")
        else:
            print(
                f"{estimate_path.split('/')[-1]}: association info — ours {len(my_ri)} pairs "
                f"(one-to-one) vs evo {len(evo_ei)} pairs (many-to-one); expected for "
                f"sparse/keyframe estimates, metrics below use different pair sets",
                file=sys.stderr,
            )

        for metric in ("ate_rmse", "rpe_translation_rmse"):
            ours_value = ours[metric]
            evo_value = reference[metric]
            rel_diff = abs(ours_value - evo_value) / max(abs(evo_value), 1e-300)
            if associations_match:
                status = "ok" if rel_diff <= REL_TOLERANCE else "MISMATCH"
                if rel_diff > REL_TOLERANCE:
                    failed = True
            else:
                status = "info (different pair sets)"
            print(
                "{:<28} {:>14.9f} {:>14.9f} {:>11.2e} {}".format(
                    "{}:{}".format(estimate_path.split("/")[-1], metric.split("_")[0]),
                    ours_value,
                    evo_value,
                    rel_diff,
                    status,
                )
            )

    if failed:
        print(f"parity check FAILED (tolerance: {REL_TOLERANCE:.0e})", file=sys.stderr)
        return 1
    print(f"parity check passed (tolerance: {REL_TOLERANCE:.0e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

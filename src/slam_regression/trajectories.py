"""Trajectory loading and timestamp association.

Currently supported input format: TUM text files, one pose per line::

    timestamp tx ty tz qx qy qz qw

Whitespace-separated, ``#`` starts a comment, blank lines are ignored.
Quaternion order is (x, y, z, w) as produced by the TUM RGB-D benchmark tools
and consumed by evo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from .errors import TrajectoryError

TUM_COLUMNS = 8
_QUAT_NORM_TOLERANCE = 1e-6


@dataclass
class Trajectory:
    """A timestamped trajectory with positions and quaternions (x, y, z, w)."""

    timestamps: np.ndarray  # (N,) float64, seconds, strictly ascending
    positions: np.ndarray  # (N, 3) float64
    rotations: np.ndarray  # (N, 4) float64, unit quaternions (x, y, z, w)

    def __post_init__(self) -> None:
        n = self.timestamps.shape[0]
        if self.timestamps.ndim != 1:
            raise TrajectoryError("timestamps must be a 1-D array")
        if self.positions.shape != (n, 3):
            raise TrajectoryError(
                "positions must have shape ({}, 3), got {}".format(n, self.positions.shape)
            )
        if self.rotations.shape != (n, 4):
            raise TrajectoryError(
                "rotations must have shape ({}, 4), got {}".format(n, self.rotations.shape)
            )
        if not np.all(np.isfinite(self.timestamps)):
            raise TrajectoryError("timestamps contain non-finite values")
        if not np.all(np.isfinite(self.positions)):
            raise TrajectoryError("positions contain non-finite values")
        if not np.all(np.isfinite(self.rotations)):
            raise TrajectoryError("rotations contain non-finite values")

    @property
    def count(self) -> int:
        return int(self.timestamps.shape[0])


def load_tum(path: str) -> Trajectory:
    """Load a TUM-format trajectory file, sorted by ascending timestamp."""
    rows: List[List[float]] = []
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        raise TrajectoryError("cannot read trajectory file '{}': {}".format(path, exc.strerror or exc)) from None

    with handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) != TUM_COLUMNS:
                raise TrajectoryError(
                    "{}:{}: expected {} whitespace-separated values, got {}: {!r}".format(
                        path, line_no, TUM_COLUMNS, len(tokens), line
                    )
                )
            try:
                rows.append([float(token) for token in tokens])
            except ValueError:
                raise TrajectoryError(
                    "{}:{}: could not parse numeric value in {!r}".format(path, line_no, line)
                ) from None

    if not rows:
        raise TrajectoryError("{}: file contains no poses".format(path))

    data = np.asarray(rows, dtype=np.float64)
    if not np.all(np.isfinite(data)):
        raise TrajectoryError("{}: file contains NaN or infinite values".format(path))

    order = np.argsort(data[:, 0], kind="stable")
    data = data[order]

    quaternions = data[:, 4:8]
    norms = np.linalg.norm(quaternions, axis=1, keepdims=True)
    if np.any(norms < _QUAT_NORM_TOLERANCE):
        raise TrajectoryError("{}: near-zero quaternion found; rotation is undefined".format(path))
    quaternions = quaternions / norms

    return Trajectory(
        timestamps=data[:, 0],
        positions=data[:, 1:4],
        rotations=quaternions,
    )


def save_tum(path: str, trajectory: Trajectory) -> None:
    """Write a trajectory in TUM format (quaternions x, y, z, w)."""
    lines = []
    for t, pos, quat in zip(trajectory.timestamps, trajectory.positions, trajectory.rotations):
        lines.append(
            "{:.9f} {:.9f} {:.9f} {:.9f} {:.9f} {:.9f} {:.9f} {:.9f}".format(
                float(t), pos[0], pos[1], pos[2], quat[0], quat[1], quat[2], quat[3]
            )
        )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def associate(
    ref_timestamps: np.ndarray,
    est_timestamps: np.ndarray,
    max_diff: float,
) -> Tuple[List[int], List[int]]:
    """Greedy one-to-one nearest-timestamp association (TUM benchmark style).

    Both inputs must be sorted ascending. Returns index lists ``(ref_idx, est_idx)``
    of matched pairs.
    """
    if max_diff < 0:
        raise TrajectoryError("max_diff must be non-negative, got {}".format(max_diff))

    ref_idx: List[int] = []
    est_idx: List[int] = []
    i = 0
    j = 0
    while i < len(ref_timestamps) and j < len(est_timestamps):
        diff = float(ref_timestamps[i] - est_timestamps[j])
        if abs(diff) <= max_diff:
            ref_idx.append(i)
            est_idx.append(j)
            i += 1
            j += 1
        elif diff < 0:
            i += 1
        else:
            j += 1
    return ref_idx, est_idx


def associate_trajectories(ref: Trajectory, est: Trajectory, max_diff: float) -> Tuple[Trajectory, Trajectory]:
    """Pair up poses by timestamp and return the matched sub-trajectories."""
    ref_idx, est_idx = associate(ref.timestamps, est.timestamps, max_diff)
    matched_ref = Trajectory(
        timestamps=ref.timestamps[ref_idx],
        positions=ref.positions[ref_idx],
        rotations=ref.rotations[ref_idx],
    )
    matched_est = Trajectory(
        timestamps=est.timestamps[est_idx],
        positions=est.positions[est_idx],
        rotations=est.rotations[est_idx],
    )
    return matched_ref, matched_est

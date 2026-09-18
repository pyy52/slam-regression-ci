"""ATE/RPE metrics and rigid alignment.

Conventions follow the TUM RGB-D benchmark and evo:

- ATE is the RMSE of the translation part of the absolute pose error, computed
  after aligning the estimate to the reference with Umeyama's method
  (rigid SE(3) by default, optional uniform scale correction).
- RPE is the RMSE of the translation part of the relative pose error over
  consecutive pose pairs (``delta = 1``), computed on the aligned estimate.
- Lower is better for every metric produced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .errors import MetricsError


@dataclass
class MetricsResult:
    """Metric values for one matched trajectory pair."""

    ate_rmse: float
    ate_mean: float
    ate_max: float
    rpe_translation_rmse: float
    rpe_mean: float
    rpe_max: float
    num_pairs: int
    aligned: bool
    correct_scale: bool
    scale: Optional[float]

    def to_dict(self) -> dict:
        return {
            "ate_rmse": self.ate_rmse,
            "ate_mean": self.ate_mean,
            "ate_max": self.ate_max,
            "rpe_translation_rmse": self.rpe_translation_rmse,
            "rpe_mean": self.rpe_mean,
            "rpe_max": self.rpe_max,
            "num_pairs": self.num_pairs,
            "alignment": {
                "enabled": self.aligned,
                "correct_scale": self.correct_scale,
                "scale": self.scale,
            },
        }


def quaternion_to_matrix(quaternions: np.ndarray) -> np.ndarray:
    """Convert (N, 4) quaternions in (x, y, z, w) order to (N, 3, 3) matrices."""
    quaternions = np.asarray(quaternions, dtype=np.float64)
    single = quaternions.ndim == 1
    if single:
        quaternions = quaternions[None, :]
    if quaternions.ndim != 2 or quaternions.shape[1] != 4:
        raise MetricsError("quaternions must have shape (N, 4)")
    x, y, z, w = quaternions[:, 0], quaternions[:, 1], quaternions[:, 2], quaternions[:, 3]

    matrices = np.empty((quaternions.shape[0], 3, 3), dtype=np.float64)
    matrices[:, 0, 0] = 1.0 - 2.0 * (y * y + z * z)
    matrices[:, 0, 1] = 2.0 * (x * y - w * z)
    matrices[:, 0, 2] = 2.0 * (x * z + w * y)
    matrices[:, 1, 0] = 2.0 * (x * y + w * z)
    matrices[:, 1, 1] = 1.0 - 2.0 * (x * x + z * z)
    matrices[:, 1, 2] = 2.0 * (y * z - w * x)
    matrices[:, 2, 0] = 2.0 * (x * z - w * y)
    matrices[:, 2, 1] = 2.0 * (y * z + w * x)
    matrices[:, 2, 2] = 1.0 - 2.0 * (x * x + y * y)

    return matrices[0] if single else matrices


def poses_to_transforms(positions: np.ndarray, quaternions: np.ndarray) -> np.ndarray:
    """Build (N, 4, 4) homogeneous transforms from positions and (x, y, z, w) quaternions."""
    positions = np.asarray(positions, dtype=np.float64)
    rotations = quaternion_to_matrix(quaternions)
    n = positions.shape[0]
    transforms = np.zeros((n, 4, 4), dtype=np.float64)
    transforms[:, 3, 3] = 1.0
    transforms[:, :3, :3] = rotations
    transforms[:, :3, 3] = positions
    return transforms


def invert_rigid(transforms: np.ndarray) -> np.ndarray:
    """Invert (N, 4, 4) rigid transforms (rotation transpose, no scaling)."""
    inverse = np.zeros_like(transforms)
    rotation = transforms[:, :3, :3]
    translation = transforms[:, :3, 3]
    inverse[:, :3, :3] = np.transpose(rotation, (0, 2, 1))
    inverse[:, :3, 3] = -np.einsum("nij,nj->ni", inverse[:, :3, :3], translation)
    inverse[:, 3, 3] = 1.0
    return inverse


def umeyama_alignment(
    src: np.ndarray, dst: np.ndarray, with_scale: bool = False
) -> Tuple[np.ndarray, np.ndarray, float]:
    """Least-squares alignment ``dst ~ c * R @ src + t`` (Umeyama, 1991).

    Mirrors evo's implementation so results are directly comparable. Returns
    ``(R, t, c)`` with ``c = 1`` unless ``with_scale`` is true. Reflections are
    rejected (det(R) is forced to +1).
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise MetricsError("src and dst must both have shape (N, 3)")
    if src.shape[0] < 3:
        raise MetricsError(f"alignment requires at least 3 matched poses, got {src.shape[0]}")

    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_centered = src - mu_src
    dst_centered = dst - mu_dst

    cov_src = (src_centered.T @ src_centered) / src.shape[0]
    cov_dst_src = (dst_centered.T @ src_centered) / src.shape[0]

    u, d, vt = np.linalg.svd(cov_dst_src)
    s = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s[2, 2] = -1.0
    rotation = u @ s @ vt

    if with_scale:
        denom = np.trace(cov_src)
        if denom < 1e-12:
            raise MetricsError("cannot estimate scale: reference poses are degenerate (collinear)")
        scale = float(np.trace(np.diag(d) @ s) / denom)
    else:
        scale = 1.0

    translation = mu_dst - scale * (rotation @ mu_src)
    return rotation, translation, scale


def _rmse_stats(errors: np.ndarray) -> Tuple[float, float, float]:
    if errors.size == 0:
        raise MetricsError("no error values to aggregate")
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    return rmse, float(np.mean(errors)), float(np.max(errors))


def compute_metrics(
    ref_positions: np.ndarray,
    ref_quaternions: np.ndarray,
    est_positions: np.ndarray,
    est_quaternions: np.ndarray,
    align: bool = True,
    correct_scale: bool = False,
    rpe_delta: int = 1,
) -> MetricsResult:
    """Compute ATE and RPE statistics for matched pose arrays.

    Inputs are timestamp-associated poses (same length, same ordering).
    """
    ref_positions = np.asarray(ref_positions, dtype=np.float64)
    est_positions = np.asarray(est_positions, dtype=np.float64)
    ref_quaternions = np.asarray(ref_quaternions, dtype=np.float64)
    est_quaternions = np.asarray(est_quaternions, dtype=np.float64)
    if not (ref_positions.shape == est_positions.shape and ref_positions.ndim == 2):
        raise MetricsError("reference and estimate positions must both have shape (N, 3)")
    if rpe_delta < 1:
        raise MetricsError(f"rpe_delta must be >= 1, got {rpe_delta}")

    n = ref_positions.shape[0]
    if n < rpe_delta + 1:
        raise MetricsError(
            f"RPE with delta={rpe_delta} needs at least {rpe_delta + 1} matched poses, got {n}"
        )

    scale = None
    if align:
        rotation, translation, scale = umeyama_alignment(est_positions, ref_positions, correct_scale)
        est_rot_mats = quaternion_to_matrix(est_quaternions)
        est_positions_aligned = scale * (rotation @ est_positions.T).T + translation
        # Build aligned transforms as pure rigid poses: rotate orientations by R,
        # keep the scale out of the rotation block so rigid inverses stay valid.
        est_transforms = np.zeros((n, 4, 4), dtype=np.float64)
        est_transforms[:, 3, 3] = 1.0
        est_transforms[:, :3, :3] = np.einsum("ij,njk->nik", rotation, est_rot_mats)
        est_transforms[:, :3, 3] = est_positions_aligned
    else:
        est_positions_aligned = est_positions
        est_transforms = poses_to_transforms(est_positions, est_quaternions)

    ate_errors = np.linalg.norm(est_positions_aligned - ref_positions, axis=1)
    ate_rmse, ate_mean, ate_max = _rmse_stats(ate_errors)

    ref_transforms = poses_to_transforms(ref_positions, ref_quaternions)
    ref_inverse = invert_rigid(ref_transforms)
    est_inverse = invert_rigid(est_transforms)
    # TUM/evo convention: relative motion from pose j to pose j+delta expressed
    # in the start frame, error E = (ref_rel)^-1 * est_rel, translation norm.
    m = n - rpe_delta
    ref_rel = np.einsum("nij,njk->nik", ref_inverse[:m], ref_transforms[rpe_delta:])
    est_rel = np.einsum("nij,njk->nik", est_inverse[:m], est_transforms[rpe_delta:])
    err_transforms = np.einsum("nij,njk->nik", invert_rigid(ref_rel), est_rel)
    rpe_errors = np.linalg.norm(err_transforms[:, :3, 3], axis=1)
    rpe_rmse, rpe_mean, rpe_max = _rmse_stats(rpe_errors)

    return MetricsResult(
        ate_rmse=ate_rmse,
        ate_mean=ate_mean,
        ate_max=ate_max,
        rpe_translation_rmse=rpe_rmse,
        rpe_mean=rpe_mean,
        rpe_max=rpe_max,
        num_pairs=n,
        aligned=align,
        correct_scale=correct_scale,
        scale=scale,
    )

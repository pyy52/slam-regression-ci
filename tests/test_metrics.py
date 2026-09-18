import numpy as np
import pytest

from slam_regression.errors import MetricsError
from slam_regression.metrics import (
    compute_metrics,
    invert_rigid,
    poses_to_transforms,
    quaternion_to_matrix,
    umeyama_alignment,
)

IDENTITY_QUAT = np.array([0.0, 0.0, 0.0, 1.0])


def axis_angle_quat(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    half = angle / 2.0
    return np.concatenate([axis * np.sin(half), [np.cos(half)]])


def straight_line(n, step=0.1, noise=0.0, seed=0):
    t = np.arange(n, dtype=float)
    positions = np.stack([t * step, np.zeros(n), np.zeros(n)], axis=1)
    if noise > 0.0:
        rng = np.random.RandomState(seed)
        positions = positions + rng.uniform(-noise, noise, positions.shape)
    quats = np.tile(IDENTITY_QUAT, (n, 1))
    return positions, quats


class TestQuaternionToMatrix:
    def test_identity(self):
        np.testing.assert_allclose(quaternion_to_matrix(IDENTITY_QUAT), np.eye(3), atol=1e-12)

    def test_z_rotation_90_degrees(self):
        quat = axis_angle_quat([0, 0, 1], np.pi / 2)
        rotation = quaternion_to_matrix(quat)
        np.testing.assert_allclose(rotation, [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=1e-12)

    def test_batch_shape(self):
        quats = np.stack([IDENTITY_QUAT, axis_angle_quat([0, 0, 1], np.pi / 2)])
        matrices = quaternion_to_matrix(quats)
        assert matrices.shape == (2, 3, 3)


class TestUmeyama:
    def test_recovers_known_rigid_transform(self):
        rng = np.random.RandomState(42)
        src = rng.uniform(-5, 5, (50, 3))
        angle = 0.7
        rotation = quaternion_to_matrix(axis_angle_quat([0.3, 0.5, 0.8], angle))
        translation = np.array([1.5, -2.0, 3.0])
        dst = src @ rotation.T + translation

        r_est, t_est, scale = umeyama_alignment(src, dst)
        np.testing.assert_allclose(r_est, rotation, atol=1e-9)
        np.testing.assert_allclose(t_est, translation, atol=1e-9)
        assert scale == 1.0
        assert np.linalg.det(r_est) == pytest.approx(1.0)

    def test_recovers_scale(self):
        rng = np.random.RandomState(7)
        src = rng.uniform(-2, 2, (30, 3))
        scale_true = 2.5
        dst = scale_true * src
        _, _, scale = umeyama_alignment(src, dst, with_scale=True)
        assert scale == pytest.approx(scale_true, rel=1e-9)

    def test_requires_three_poses(self):
        with pytest.raises(MetricsError, match="at least 3"):
            umeyama_alignment(np.zeros((2, 3)), np.zeros((2, 3)))


class TestRigidInverse:
    def test_inverse_round_trip(self):
        transforms = poses_to_transforms(
            np.array([[1.0, 2.0, 3.0]]), axis_angle_quat([0, 1, 0], 0.4)[None, :]
        )
        product = transforms @ invert_rigid(transforms)
        np.testing.assert_allclose(product, np.eye(4)[None, :, :], atol=1e-12)


class TestComputeMetrics:
    def test_identical_trajectories_give_zero_error(self):
        positions, quats = straight_line(20)
        result = compute_metrics(positions, quats, positions, quats)
        assert result.ate_rmse == pytest.approx(0.0, abs=1e-9)
        assert result.rpe_translation_rmse == pytest.approx(0.0, abs=1e-9)
        assert result.num_pairs == 20

    def test_constant_offset_ate(self):
        ref_positions, quats = straight_line(20)
        est_positions = ref_positions + np.array([0.5, 0.0, 0.0])
        result = compute_metrics(ref_positions, quats, est_positions, quats, align=False)
        assert result.ate_rmse == pytest.approx(0.5, abs=1e-12)

    def test_alignment_removes_rigid_offset(self):
        ref_positions, quats = straight_line(30)
        est_positions = ref_positions + np.array([10.0, -3.0, 2.0])
        result = compute_metrics(ref_positions, quats, est_positions, quats, align=True)
        assert result.ate_rmse == pytest.approx(0.0, abs=1e-9)

    def test_rpe_detects_drift(self):
        ref_positions, quats = straight_line(20, step=0.1)
        # Candidate moves 0.11 per step instead of 0.10: relative drift 0.01 per pair.
        est_positions = np.stack([np.arange(20) * 0.11, np.zeros(20), np.zeros(20)], axis=1)
        result = compute_metrics(ref_positions, quats, est_positions, quats, align=False)
        assert result.rpe_translation_rmse == pytest.approx(0.01, rel=1e-9)

    def test_rpe_ignores_global_offset(self):
        ref_positions, quats = straight_line(20, step=0.1)
        est_positions = ref_positions + np.array([5.0, 0.0, 0.0])
        result = compute_metrics(ref_positions, quats, est_positions, quats, align=False)
        assert result.rpe_translation_rmse == pytest.approx(0.0, abs=1e-9)

    def test_rpe_respects_rotation_drift(self):
        n = 10
        positions = np.stack([np.arange(n) * 0.1, np.zeros(n), np.zeros(n)], axis=1)
        quats = np.tile(IDENTITY_QUAT, (n, 1))
        # Growing rotation error: a constant rotation offset would cancel in
        # relative motion, but per-frame drift must show up in RPE.
        est_quats = np.stack([axis_angle_quat([0, 1, 0], 0.01 * i) for i in range(n)])
        result = compute_metrics(positions, quats, positions, est_quats, align=False)
        assert result.rpe_translation_rmse > 1e-3

    def test_too_few_poses_for_rpe(self):
        positions, quats = straight_line(1)
        with pytest.raises(MetricsError, match="at least 2"):
            compute_metrics(positions, quats, positions, quats)

    def test_result_to_dict_has_metric_and_alignment_fields(self):
        positions, quats = straight_line(5)
        result = compute_metrics(positions, quats, positions, quats)
        payload = result.to_dict()
        assert "ate_rmse" in payload and "rpe_translation_rmse" in payload
        assert payload["alignment"]["enabled"] is True
        assert payload["num_pairs"] == 5

    def test_scale_correction_recovers_scaled_estimate(self):
        ref_positions, quats = straight_line(40, step=0.2)
        est_positions = ref_positions * 0.9  # monocular-style scale drift
        rigid = compute_metrics(ref_positions, quats, est_positions, quats, align=True)
        corrected = compute_metrics(
            ref_positions, quats, est_positions, quats, align=True, correct_scale=True
        )
        assert corrected.ate_rmse < rigid.ate_rmse
        assert corrected.ate_rmse == pytest.approx(0.0, abs=1e-9)
        assert corrected.scale == pytest.approx(1 / 0.9, rel=1e-6)

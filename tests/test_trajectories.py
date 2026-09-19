import numpy as np
import pytest

from slam_regression.errors import TrajectoryError
from slam_regression.trajectories import associate, associate_trajectories, load_tum, save_tum

TUM_SAMPLE = """\
# a comment line

1305031102.175304 0.000000 0.000000 0.000000 0.000000 0.000000 0.000000 1.000000
1305031102.275304 0.100000 0.000000 0.000000 0.000000 0.000000 0.000000 1.000000
1305031102.375304 0.200000 0.000000 0.000000 0.000000 0.000000 0.000000 1.000000
"""


def write(tmp_path, text, name="traj.tum"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


class TestLoadTum:
    def test_loads_valid_file_with_comments_and_blanks(self, tmp_path):
        traj = load_tum(write(tmp_path, TUM_SAMPLE))
        assert traj.count == 3
        assert traj.timestamps[0] == pytest.approx(1305031102.175304, abs=1e-6)
        assert traj.positions[2] == pytest.approx([0.2, 0.0, 0.0])
        assert traj.rotations[0] == pytest.approx([0.0, 0.0, 0.0, 1.0])

    def test_sorts_by_timestamp(self, tmp_path):
        text = (
            "2.0 1 0 0 0 0 0 1\n"
            "1.0 0 0 0 0 0 0 1\n"
        )
        traj = load_tum(write(tmp_path, text))
        assert list(traj.timestamps) == [1.0, 2.0]
        assert traj.positions[0][0] == pytest.approx(0.0)

    def test_normalizes_quaternions(self, tmp_path):
        text = "1.0 0 0 0 0 0 0 2.0\n"
        traj = load_tum(write(tmp_path, text))
        assert traj.rotations[0] == pytest.approx([0.0, 0.0, 0.0, 1.0])

    def test_missing_file(self, tmp_path):
        with pytest.raises(TrajectoryError, match="no_such_file"):
            load_tum(str(tmp_path / "no_such_file.tum"))

    def test_wrong_column_count_reports_line(self, tmp_path):
        text = "1.0 0 0 0 0 0 0 1\n1.0 0 0 0\n"
        with pytest.raises(TrajectoryError, match=r"traj\.tum:2"):
            load_tum(write(tmp_path, text))

    def test_non_numeric_value(self, tmp_path):
        text = "1.0 0 0 0 0 0 0 abc\n"
        with pytest.raises(TrajectoryError, match="could not parse"):
            load_tum(write(tmp_path, text))

    def test_nan_value(self, tmp_path):
        text = "1.0 0 0 nan 0 0 0 1\n"
        with pytest.raises(TrajectoryError, match="NaN"):
            load_tum(write(tmp_path, text))

    def test_empty_file(self, tmp_path):
        with pytest.raises(TrajectoryError, match="no poses"):
            load_tum(write(tmp_path, "# only comments\n"))

    def test_zero_quaternion_rejected(self, tmp_path):
        text = "1.0 0 0 0 0 0 0 0\n"
        with pytest.raises(TrajectoryError, match="zero quaternion"):
            load_tum(write(tmp_path, text))


class TestSaveLoadRoundTrip:
    def test_round_trip_preserves_poses(self, tmp_path):
        traj = load_tum(write(tmp_path, TUM_SAMPLE))
        out = str(tmp_path / "round.tum")
        save_tum(out, traj)
        reloaded = load_tum(out)
        np.testing.assert_allclose(reloaded.timestamps, traj.timestamps, atol=1e-9)
        np.testing.assert_allclose(reloaded.positions, traj.positions, atol=1e-9)
        np.testing.assert_allclose(reloaded.rotations, traj.rotations, atol=1e-9)


def make_traj(times, xs):
    n = len(times)
    quats = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (n, 1))
    positions = np.stack([np.asarray(xs), np.zeros(n), np.zeros(n)], axis=1)
    return np.asarray(times, dtype=float), positions, quats


class TestAssociate:
    def test_exact_match(self):
        t, p, q = make_traj([1.0, 2.0, 3.0], [0, 0, 0])
        ref = t
        est = np.array([1.0, 2.0, 3.0])
        ri, ei = associate(ref, est, max_diff=0.01)
        assert ri == [0, 1, 2]
        assert ei == [0, 1, 2]

    def test_small_offset_matched(self):
        ri, ei = associate([1.0, 2.0], [1.005, 2.005], max_diff=0.01)
        assert ri == [0, 1]
        assert ei == [0, 1]

    def test_beyond_tolerance_dropped(self):
        ri, ei = associate([1.0, 2.0], [1.5, 2.0], max_diff=0.01)
        assert ri == [1]
        assert ei == [1]

    def test_extra_estimate_poses_skipped(self):
        ri, ei = associate([1.0, 2.0], [0.5, 1.0, 2.0, 2.5], max_diff=0.01)
        assert ri == [0, 1]
        assert ei == [1, 2]

    def test_negative_max_diff_rejected(self):
        with pytest.raises(TrajectoryError, match="non-negative"):
            associate([1.0], [1.0], max_diff=-0.1)

    def test_picks_nearest_when_two_candidates_in_tolerance(self):
        # Audit counterexample: 0.00 is within tolerance of 0.04 but 0.05 is nearer.
        ri, ei = associate([0.04], [0.00, 0.05], max_diff=0.05)
        assert ri == [0]
        assert ei == [1]

    def test_nearest_even_when_far_candidate_comes_first(self):
        ri, ei = associate([10.0], [9.8, 10.05], max_diff=0.2)
        assert ei == [1]

    def test_different_rates(self):
        # 5 Hz reference against 10 Hz estimate.
        ref = [i * 0.2 for i in range(6)]
        est = [i * 0.1 for i in range(11)]
        ri, ei = associate(ref, est, max_diff=0.01)
        assert [ref[i] for i in ri] == ref
        assert [est[j] for j in ei] == ref

    def test_timestamp_offset(self):
        ref = [1.0, 2.0, 3.0]
        est = [1.0 + 0.008, 2.0 + 0.008, 3.0 + 0.008]
        ri, ei = associate(ref, est, max_diff=0.01)
        assert ri == [0, 1, 2]
        assert ei == [0, 1, 2]

    def test_dropped_poses(self):
        ref = [1.0, 2.0, 3.0, 4.0]
        est = [1.0, 3.0, 4.0]  # estimate dropped its 2.0 pose
        ri, ei = associate(ref, est, max_diff=0.01)
        assert ri == [0, 2, 3]
        assert ei == [0, 1, 2]

    def test_near_duplicate_estimate_timestamps(self):
        # Near-duplicates: keep the first (no strictly closer neighbor).
        ri, ei = associate([2.0], [2.0, 2.0001], max_diff=0.01)
        assert ei == [0]

    def test_duplicate_estimate_timestamps_keeps_first(self):
        ri, ei = associate([2.0], [2.0, 2.0], max_diff=0.01)
        assert ei == [0]

    def test_boundary_equals_max_diff_is_inclusive(self):
        # 0.5 is exactly representable, so diff == max_diff holds bit-exactly.
        ri, ei = associate([1.0], [1.5], max_diff=0.5)
        assert ri == [0]
        assert ei == [0]

    def test_just_beyond_boundary_dropped(self):
        ri, ei = associate([1.0], [1.5001], max_diff=0.5)
        assert ri == []
        assert ei == []

    def test_reference_with_gap_matches_across_it(self):
        # Reference skips 2.0; estimate has poses at all times. The 2.0 estimate
        # pose must be skipped in favor of the strictly closer 2.9 for ref 2.9.
        ref = [1.0, 2.9]
        est = [1.0, 2.0, 2.9]
        ri, ei = associate(ref, est, max_diff=0.05)
        assert ei == [0, 2]

    def test_associate_trajectories_shapes(self):
        from slam_regression.trajectories import Trajectory

        t1, p1, q1 = make_traj([1.0, 2.0, 3.0], [0.0, 0.1, 0.2])
        t2, p2, q2 = make_traj([1.005, 1.995, 3.0], [0.0, 0.1, 0.2])
        traj_ref = Trajectory(timestamps=t1, positions=p1, rotations=q1)
        traj_est = Trajectory(timestamps=t2, positions=p2, rotations=q2)
        m_ref, m_est = associate_trajectories(traj_ref, traj_est, max_diff=0.01)
        assert m_ref.count == 3
        assert m_est.count == 3
        assert m_ref.timestamps[1] == pytest.approx(2.0)
        assert m_est.timestamps[1] == pytest.approx(1.995)

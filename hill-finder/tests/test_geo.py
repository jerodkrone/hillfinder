from app.utils.geo import compute_distance_m, compute_grades, compute_total_length_m


def test_compute_distance_m_known_pair():
    d = compute_distance_m((40.0, -75.0), (40.001, -75.0))
    assert 100 < d < 120, f"Expected ~111m, got {d}"


def test_compute_grades_uphill():
    avg, max_ = compute_grades([(40.0, -75.0), (40.001, -75.0)], [0.0, 10.0])
    assert 8 < avg < 10, f"Expected ~9%, got {avg}"


def test_compute_grades_flat():
    avg, max_ = compute_grades([(40.0, -75.0), (40.001, -75.0)], [100.0, 100.0])
    assert avg == 0.0 and max_ == 0.0


def test_compute_grades_downhill_excluded_from_avg():
    # Downhill segment: avg and max grade count only upward gain, so both should be 0
    avg, max_ = compute_grades([(40.0, -75.0), (40.001, -75.0)], [10.0, 0.0])
    assert avg == 0.0
    assert max_ == 0.0


def test_compute_grades_raises_on_length_mismatch():
    import pytest
    with pytest.raises(ValueError):
        compute_grades([(40.0, -75.0), (40.001, -75.0)], [0.0])


def test_compute_total_length_m():
    length = compute_total_length_m([(40.0, -75.0), (40.001, -75.0)])
    assert 100 < length < 120


def test_compute_grades_less_than_two_points_raises():
    import pytest
    with pytest.raises(ValueError, match="at least 2 points"):
        compute_grades([(40.0, -75.0)], [0.0])

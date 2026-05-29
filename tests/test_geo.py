import pytest

from app.utils.geo import compute_distance_m, compute_grades, compute_total_length_m, split_into_climbing_segments


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
    with pytest.raises(ValueError):
        compute_grades([(40.0, -75.0), (40.001, -75.0)], [0.0])


def test_compute_total_length_m():
    length = compute_total_length_m([(40.0, -75.0), (40.001, -75.0)])
    assert 100 < length < 120


def test_compute_grades_less_than_two_points_raises():
    with pytest.raises(ValueError, match="at least 2 points"):
        compute_grades([(40.0, -75.0)], [0.0])


# --- split_into_climbing_segments unit tests ---
# Base: (40.0, -75.0), 0.001° lat steps ≈ 111 m each.

_BASE = (40.0, -75.0)


def _lat(n: int) -> tuple[float, float]:
    return (40.0 + n * 0.001, -75.0)


def test_split_single_uphill_run():
    coords = [_lat(0), _lat(1), _lat(2)]
    elevs = [0.0, 20.0, 40.0]  # ~18% grade each pair
    result = split_into_climbing_segments(coords, elevs)
    assert len(result) == 1
    seg_coords, seg_elevs = result[0]
    assert seg_coords == coords
    assert seg_elevs == elevs


def test_split_flat_returns_empty():
    coords = [_lat(0), _lat(1), _lat(2)]
    elevs = [100.0, 100.0, 100.0]
    assert split_into_climbing_segments(coords, elevs) == []


def test_split_downhill_returns_empty():
    coords = [_lat(0), _lat(1), _lat(2)]
    elevs = [40.0, 20.0, 0.0]
    assert split_into_climbing_segments(coords, elevs) == []


def test_split_uphill_then_flat():
    coords = [_lat(0), _lat(1), _lat(2), _lat(3)]
    elevs = [0.0, 20.0, 40.0, 40.0]
    result = split_into_climbing_segments(coords, elevs)
    assert len(result) == 1
    seg_coords, _ = result[0]
    assert seg_coords == [_lat(0), _lat(1), _lat(2)]


def test_split_flat_then_uphill():
    coords = [_lat(0), _lat(1), _lat(2), _lat(3)]
    elevs = [0.0, 0.0, 20.0, 40.0]
    result = split_into_climbing_segments(coords, elevs)
    assert len(result) == 1
    seg_coords, _ = result[0]
    assert seg_coords == [_lat(1), _lat(2), _lat(3)]


def test_split_two_runs_separated_by_flat():
    coords = [_lat(0), _lat(1), _lat(2), _lat(3), _lat(4), _lat(5)]
    elevs = [0.0, 20.0, 40.0, 40.0, 60.0, 80.0]
    result = split_into_climbing_segments(coords, elevs)
    assert len(result) == 2


def test_split_too_short_excluded():
    # ~10 m apart — below 50 m minimum
    delta_lat = 10 / 111_111
    coords = [(40.0, -75.0), (40.0 + delta_lat, -75.0)]
    elevs = [0.0, 5.0]  # steep but too short
    assert split_into_climbing_segments(coords, elevs) == []


def test_split_exactly_at_min_length():
    # ~55 m apart — safely at/above 50 m minimum (WGS-84 meridian at 40°N ≈ 111,034 m/°)
    delta_lat = 55 / 111_111
    coords = [(40.0, -75.0), (40.0 + delta_lat, -75.0)]
    elevs = [0.0, 5.0]  # ~9% grade, well above threshold
    result = split_into_climbing_segments(coords, elevs)
    assert len(result) == 1


def test_split_raises_on_length_mismatch():
    with pytest.raises(ValueError):
        split_into_climbing_segments([(40.0, -75.0), (40.001, -75.0)], [0.0])


def test_split_raises_on_fewer_than_two_points():
    with pytest.raises(ValueError):
        split_into_climbing_segments([(40.0, -75.0)], [0.0])

import os

from geopy.distance import geodesic

_FLAT_GRADE_THRESHOLD_PCT = float(os.getenv("HILLFINDER_FLAT_THRESHOLD_PCT", "1.0"))
_MIN_SEGMENT_LENGTH_M = float(os.getenv("HILLFINDER_MIN_SEGMENT_M", "50.0"))


def compute_distance_m(coord_a: tuple[float, float], coord_b: tuple[float, float]) -> float:
    return geodesic(coord_a, coord_b).meters


def compute_grades(
    coordinates: list[tuple[float, float]],
    elevations: list[float],
) -> tuple[float, float]:
    if len(coordinates) != len(elevations):
        raise ValueError("coordinates and elevations must have the same length")
    if len(coordinates) < 2:
        raise ValueError("at least 2 points are required")

    total_distance = 0.0
    total_gain = 0.0
    max_grade = 0.0

    for i in range(len(coordinates) - 1):
        dist = compute_distance_m(coordinates[i], coordinates[i + 1])
        elev_diff = elevations[i + 1] - elevations[i]
        total_distance += dist
        if elev_diff > 0:
            total_gain += elev_diff
        if dist > 0 and elev_diff > 0:
            pair_grade = elev_diff / dist * 100
            if pair_grade > max_grade:
                max_grade = pair_grade

    if total_distance == 0:
        return (0.0, 0.0)

    avg_grade_pct = total_gain / total_distance * 100
    return (round(avg_grade_pct, 2), round(max_grade, 2))


def split_into_climbing_segments(
    coordinates: list[tuple[float, float]],
    elevations: list[float],
) -> list[tuple[list[tuple[float, float]], list[float]]]:
    if len(coordinates) != len(elevations):
        raise ValueError("coordinates and elevations must have the same length")
    if len(coordinates) < 2:
        raise ValueError("at least 2 points are required")

    run_coords: list[tuple[float, float]] = [coordinates[0]]
    run_elevs: list[float] = [elevations[0]]
    run_length_m = 0.0
    results: list[tuple[list[tuple[float, float]], list[float]]] = []

    for i in range(len(coordinates) - 1):
        dist = compute_distance_m(coordinates[i], coordinates[i + 1])
        elev_diff = elevations[i + 1] - elevations[i]
        pair_grade = (elev_diff / dist * 100) if dist > 0 else 0.0

        if pair_grade > _FLAT_GRADE_THRESHOLD_PCT:
            run_coords.append(coordinates[i + 1])
            run_elevs.append(elevations[i + 1])
            run_length_m += dist
        else:
            if len(run_coords) >= 2 and run_length_m >= _MIN_SEGMENT_LENGTH_M:
                results.append((list(run_coords), list(run_elevs)))
            run_coords = [coordinates[i + 1]]
            run_elevs = [elevations[i + 1]]
            run_length_m = 0.0

    if len(run_coords) >= 2 and run_length_m >= _MIN_SEGMENT_LENGTH_M:
        results.append((list(run_coords), list(run_elevs)))

    return results


def compute_total_length_m(coordinates: list[tuple[float, float]]) -> float:
    total = sum(
        compute_distance_m(coordinates[i], coordinates[i + 1])
        for i in range(len(coordinates) - 1)
    )
    return round(total, 2)

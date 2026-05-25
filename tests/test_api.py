import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services.geocoding import NOMINATIM_URL
from app.services.overpass import OVERPASS_URL
from app.services.elevation import ORS_ELEVATION_URL


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_with_key(monkeypatch):
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_openapi_docs_available(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_missing_ors_key_returns_500(client):
    response = client.get("/hills/", params={"address": "Philadelphia, PA"})
    assert response.status_code == 500
    assert "ORS_API_KEY" in response.json()["detail"]


def test_empty_address_returns_422(client):
    response = client.get("/hills/", params={"address": ""})
    assert response.status_code == 422


# --- T-4: router integration tests ---

_NOMINATIM_RESULT = [{"lat": "40.0", "lon": "-75.0"}]

_OVERPASS_TWO_WAYS = {
    "elements": [
        {
            "tags": {"name": "Steep Hill", "highway": "residential"},
            "geometry": [
                {"lat": 40.0, "lon": -75.0},
                {"lat": 40.001, "lon": -75.0},
            ],
        },
        {
            "tags": {"name": "Flat Road", "highway": "residential"},
            "geometry": [
                {"lat": 40.01, "lon": -75.01},
                {"lat": 40.011, "lon": -75.01},
            ],
        },
    ]
}

# Way 1: 0m → 20m elevation (steep); Way 2: 0m → 1m (gentle)
_ORS_ELEVATIONS = {
    "geometry": {
        "coordinates": [
            [-75.0, 40.0, 0.0],
            [-75.0, 40.001, 20.0],
            [-75.01, 40.01, 0.0],
            [-75.01, 40.011, 1.0],
        ]
    }
}


def test_get_hills_full_pipeline_returns_sorted_results(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=_OVERPASS_TWO_WAYS))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json=_ORS_ELEVATIONS))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Steep Hill"


def test_get_hills_empty_ways_returns_empty_list(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})

    assert response.status_code == 200
    assert response.json() == []


def test_get_hills_geocoding_failure_propagates(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(503))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})

    assert response.status_code == 502


def test_get_hills_overpass_failure_propagates(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(503))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})

    assert response.status_code == 502


def test_get_hills_elevation_failure_propagates(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=_OVERPASS_TWO_WAYS))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(503))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})

    assert response.status_code == 502


# --- Sprint 2 integration tests ---

# 1 way, 4 nodes; ORS elevations [0, 20, 20, 35]:
#   pair 0→1: +20m / ~111m ≈ 18% → climbing
#   pair 1→2: +0m → flat (breaks run)
#   pair 2→3: +15m / ~111m ≈ 13.5% → climbing
# Both runs are ~111m > 50m minimum.

_OVERPASS_ONE_WAY_4NODES = {
    "elements": [
        {
            "id": 1001,
            "tags": {"name": "Test Hill", "highway": "residential"},
            "geometry": [
                {"lat": 40.0, "lon": -75.0},
                {"lat": 40.001, "lon": -75.0},
                {"lat": 40.002, "lon": -75.0},
                {"lat": 40.003, "lon": -75.0},
            ],
        }
    ]
}

_ORS_ELEVATIONS_4NODES = {
    "geometry": {
        "coordinates": [
            [-75.0, 40.0, 0.0],
            [-75.0, 40.001, 20.0],
            [-75.0, 40.002, 20.0],
            [-75.0, 40.003, 35.0],
        ]
    }
}

_OVERPASS_ROAD_AND_TRAIL = {
    "elements": [
        {
            "id": 3001,
            "tags": {"name": "Road Hill", "highway": "residential"},
            "geometry": [
                {"lat": 40.0, "lon": -75.0},
                {"lat": 40.001, "lon": -75.0},
            ],
        },
        {
            "id": 3002,
            "tags": {"name": "Trail Hill", "highway": "footway"},
            "geometry": [
                {"lat": 40.01, "lon": -75.01},
                {"lat": 40.011, "lon": -75.01},
            ],
        },
    ]
}

_ORS_ROAD_AND_TRAIL = {
    "geometry": {
        "coordinates": [
            [-75.0, 40.0, 0.0],
            [-75.0, 40.001, 20.0],
            [-75.01, 40.01, 0.0],
            [-75.01, 40.011, 20.0],
        ]
    }
}


def _mock_one_way_4nodes(client_with_key, params):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=_OVERPASS_ONE_WAY_4NODES))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json=_ORS_ELEVATIONS_4NODES))
        return client_with_key.get("/hills/", params={"address": "Philadelphia, PA", **params})


def test_get_hills_one_way_two_segments(client_with_key):
    response = _mock_one_way_4nodes(client_with_key, {})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    assert all(s["name"] == "Test Hill" for s in results)


def test_get_hills_min_grade_filters_low(client_with_key):
    response = _mock_one_way_4nodes(client_with_key, {"min_grade_pct": 15})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["grade_avg_pct"] >= 15


def test_get_hills_min_grade_zero(client_with_key):
    response = _mock_one_way_4nodes(client_with_key, {"min_grade_pct": 0})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_hills_surface_road_filter(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=_OVERPASS_ROAD_AND_TRAIL))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json=_ORS_ROAD_AND_TRAIL))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA", "surface": "road"})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Road Hill"


def test_get_hills_surface_trail_filter(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=_OVERPASS_ROAD_AND_TRAIL))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json=_ORS_ROAD_AND_TRAIL))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA", "surface": "trail"})
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Trail Hill"


def test_get_hills_surface_none_returns_all(client_with_key):
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=_OVERPASS_ROAD_AND_TRAIL))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json=_ORS_ROAD_AND_TRAIL))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_hills_all_flat_returns_empty(client_with_key):
    overpass_flat = {
        "elements": [
            {
                "id": 4001,
                "tags": {"name": "Flat Road", "highway": "residential"},
                "geometry": [
                    {"lat": 40.0, "lon": -75.0},
                    {"lat": 40.001, "lon": -75.0},
                    {"lat": 40.002, "lon": -75.0},
                ],
            }
        ]
    }
    ors_flat = {
        "geometry": {
            "coordinates": [
                [-75.0, 40.0, 0.0],
                [-75.0, 40.001, 0.0],
                [-75.0, 40.002, 0.0],
            ]
        }
    }
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=overpass_flat))
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json=ors_flat))
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})
    assert response.status_code == 200
    assert response.json() == []


def test_get_hills_min_grade_invalid_422(client_with_key):
    response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA", "min_grade_pct": 150})
    assert response.status_code == 422


def test_get_hills_min_grade_boundary(client_with_key):
    r1 = _mock_one_way_4nodes(client_with_key, {"min_grade_pct": 0})
    assert r1.status_code == 200
    segments = r1.json()
    lower_grade = segments[1]["grade_avg_pct"]

    r2 = _mock_one_way_4nodes(client_with_key, {"min_grade_pct": lower_grade})
    assert r2.status_code == 200
    assert any(s["grade_avg_pct"] == lower_grade for s in r2.json()), \
        "segment with avg_grade == min_grade_pct must be included (>= semantics)"


def test_get_hills_zero_length_way_excluded(client_with_key):
    # Two coincident coordinates → length_m = 0 → filtered out by router
    overpass_coincident = {
        "elements": [
            {
                "tags": {"highway": "residential"},
                "geometry": [
                    {"lat": 40.0, "lon": -75.0},
                    {"lat": 40.0, "lon": -75.0},
                ],
            }
        ]
    }
    ors_coincident = {
        "geometry": {
            "coordinates": [[-75.0, 40.0, 10.0], [-75.0, 40.0, 10.0]]
        }
    }
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=_NOMINATIM_RESULT))
        respx.get(OVERPASS_URL).mock(
            return_value=httpx.Response(200, json=overpass_coincident)
        )
        respx.post(ORS_ELEVATION_URL).mock(
            return_value=httpx.Response(200, json=ors_coincident)
        )
        response = client_with_key.get("/hills/", params={"address": "Philadelphia, PA"})

    assert response.status_code == 200
    assert response.json() == []

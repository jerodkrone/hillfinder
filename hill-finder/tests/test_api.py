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
    assert len(results) == 2
    assert results[0]["name"] == "Steep Hill"
    assert results[0]["grade_avg_pct"] > results[1]["grade_avg_pct"]


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

import httpx
import pytest
import respx
from fastapi import HTTPException

from app.services.overpass import fetch_ways, _classify_surface, _compute_bbox, OVERPASS_URL


# --- _classify_surface (pure unit tests) ---

def test_classify_surface_road_surface_tag():
    assert _classify_surface({"surface": "asphalt"}) == "road"


def test_classify_surface_trail_surface_tag():
    assert _classify_surface({"surface": "dirt"}) == "trail"


def test_classify_surface_highway_fallback_trail():
    assert _classify_surface({"highway": "footway"}) == "trail"


def test_classify_surface_highway_fallback_road():
    assert _classify_surface({"highway": "residential"}) == "road"


def test_classify_surface_unknown():
    assert _classify_surface({}) == "unknown"


# --- _compute_bbox (pure unit tests) ---

def test_compute_bbox_edges():
    south, west, north, east = _compute_bbox(45.0, -93.0, 1000)
    # 1000 m latitude delta ≈ 0.009 degrees
    assert abs((north - south) / 2 - 1000 / 111_111) < 1e-6
    # bbox should be symmetric around the center
    assert abs(north - 45.0) == pytest.approx(abs(south - 45.0))
    assert abs(east - (-93.0)) == pytest.approx(abs(west - (-93.0)))
    # lon delta is wider than lat delta at lat 45 (cos(45°) ≈ 0.707)
    assert (east - west) > (north - south)


# --- fetch_ways (async, respx-mocked) ---

_VALID_OVERPASS_RESPONSE = {
    "elements": [
        {
            "tags": {"name": "Main St", "highway": "residential"},
            "geometry": [
                {"lat": 40.0, "lon": -75.0},
                {"lat": 40.001, "lon": -75.0},
            ],
        },
        {
            "tags": {"name": "Oak Trail", "highway": "footway"},
            "geometry": [
                {"lat": 40.01, "lon": -75.01},
                {"lat": 40.011, "lon": -75.01},
                {"lat": 40.012, "lon": -75.01},
            ],
        },
    ]
}


async def test_fetch_ways_returns_parsed_ways():
    with respx.mock:
        respx.get(OVERPASS_URL).mock(
            return_value=httpx.Response(200, json=_VALID_OVERPASS_RESPONSE)
        )
        async with httpx.AsyncClient() as client:
            ways = await fetch_ways(40.0, -75.0, client)
    assert len(ways) == 2
    assert ways[0]["name"] == "Main St"
    assert ways[0]["surface"] == "road"
    assert ways[0]["coordinates"] == [(40.0, -75.0), (40.001, -75.0)]
    assert ways[1]["surface"] == "trail"


async def test_fetch_ways_skips_ways_with_fewer_than_2_nodes():
    response = {
        "elements": [
            {
                "tags": {"highway": "residential"},
                "geometry": [{"lat": 40.0, "lon": -75.0}],  # only 1 node
            }
        ]
    }
    with respx.mock:
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(200, json=response))
        async with httpx.AsyncClient() as client:
            ways = await fetch_ways(40.0, -75.0, client)
    assert ways == []


async def test_fetch_ways_timeout_raises_504():
    with respx.mock:
        respx.get(OVERPASS_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await fetch_ways(40.0, -75.0, client)
    assert exc_info.value.status_code == 504


async def test_fetch_ways_http_error_raises_502():
    with respx.mock:
        respx.get(OVERPASS_URL).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await fetch_ways(40.0, -75.0, client)
    assert exc_info.value.status_code == 502


async def test_fetch_ways_malformed_json_raises_502():
    with respx.mock:
        respx.get(OVERPASS_URL).mock(
            return_value=httpx.Response(200, content=b"not-json")
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await fetch_ways(40.0, -75.0, client)
    assert exc_info.value.status_code == 502

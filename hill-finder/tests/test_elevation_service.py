import httpx
import pytest
import respx
from fastapi import HTTPException

from app.services.elevation import _get_elevations_ors, get_elevations, ORS_ELEVATION_URL, ORS_CHUNK_SIZE


def _ors_response(coords_with_elev: list[list]) -> dict:
    """Build a minimal ORS elevation response from [[lon, lat, elev], ...] triples."""
    return {"geometry": {"coordinates": coords_with_elev}}


async def test_get_elevations_single_chunk():
    input_coords = [(40.0, -75.0), (40.001, -75.0), (40.002, -75.0)]
    ors_coords = [[-75.0, 40.0, 10.0], [-75.0, 40.001, 15.0], [-75.0, 40.002, 20.0]]
    with respx.mock:
        respx.post(ORS_ELEVATION_URL).mock(
            return_value=httpx.Response(200, json=_ors_response(ors_coords))
        )
        async with httpx.AsyncClient() as client:
            elevations = await get_elevations(input_coords, client, "test-key")
    assert elevations == [10.0, 15.0, 20.0]


async def test_get_elevations_multi_chunk_deduplication():
    # 600 coords → 2 chunks (chunk_size=500): chunk 0 is [0:500], chunk 1 is [499:600]
    # boundary point at index 499 appears in both; reassembly skips it in chunk 1
    input_coords = [(float(i), float(i)) for i in range(600)]

    chunk0_elevs = [[float(i), float(i), float(i * 2)] for i in range(500)]
    # chunk 1 starts with the overlap point (index 499) plus 100 new points (500-599)
    chunk1_elevs = [[float(i), float(i), float(i * 2)] for i in range(499, 600)]

    call_count = 0

    def ors_side_effect(request, *args, **kwargs):
        nonlocal call_count
        if call_count == 0:
            call_count += 1
            return httpx.Response(200, json=_ors_response(chunk0_elevs))
        else:
            call_count += 1
            return httpx.Response(200, json=_ors_response(chunk1_elevs))

    with respx.mock:
        respx.post(ORS_ELEVATION_URL).mock(side_effect=ors_side_effect)
        async with httpx.AsyncClient() as client:
            elevations = await _get_elevations_ors(input_coords, client, "test-key")

    assert len(elevations) == 600
    assert elevations[0] == 0.0
    assert elevations[499] == 998.0
    assert elevations[599] == 1198.0


async def test_get_elevations_rate_limit_raises_429():
    input_coords = [(40.0, -75.0), (40.001, -75.0)]
    with respx.mock:
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(429))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await get_elevations(input_coords, client, "test-key")
    assert exc_info.value.status_code == 429


async def test_get_elevations_timeout_raises_504():
    input_coords = [(40.0, -75.0), (40.001, -75.0)]
    with respx.mock:
        respx.post(ORS_ELEVATION_URL).mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await get_elevations(input_coords, client, "test-key")
    assert exc_info.value.status_code == 504


async def test_get_elevations_http_error_raises_502():
    input_coords = [(40.0, -75.0), (40.001, -75.0)]
    with respx.mock:
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await get_elevations(input_coords, client, "test-key")
    assert exc_info.value.status_code == 502


async def test_get_elevations_malformed_response_raises_502():
    input_coords = [(40.0, -75.0), (40.001, -75.0)]
    with respx.mock:
        respx.post(ORS_ELEVATION_URL).mock(return_value=httpx.Response(200, json={}))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await get_elevations(input_coords, client, "test-key")
    assert exc_info.value.status_code == 502

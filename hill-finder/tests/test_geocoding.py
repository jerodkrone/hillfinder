import httpx
import pytest
import respx
from fastapi import HTTPException

from app.services.geocoding import geocode_address, NOMINATIM_URL


async def test_geocode_address_success():
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(
            return_value=httpx.Response(200, json=[{"lat": "40.0", "lon": "-75.0"}])
        )
        async with httpx.AsyncClient() as client:
            result = await geocode_address("Philadelphia, PA", client)
    assert result == (40.0, -75.0)


async def test_geocode_address_empty_result_raises_400():
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=[]))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await geocode_address("Nowhereville", client)
    assert exc_info.value.status_code == 400


async def test_geocode_address_timeout_raises_504():
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await geocode_address("Philadelphia, PA", client)
    assert exc_info.value.status_code == 504


async def test_geocode_address_http_error_raises_502():
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await geocode_address("Philadelphia, PA", client)
    assert exc_info.value.status_code == 502


async def test_geocode_address_connection_error_raises_502():
    with respx.mock:
        respx.get(NOMINATIM_URL).mock(side_effect=httpx.ConnectError("unreachable"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HTTPException) as exc_info:
                await geocode_address("Philadelphia, PA", client)
    assert exc_info.value.status_code == 502

import asyncio
import logging
import os
import time

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT = 10.0
NOMINATIM_MIN_INTERVAL = 1.0  # Nominatim usage policy: 1 req/sec

_contact = os.getenv("NOMINATIM_CONTACT_EMAIL", "contact@example.com")
NOMINATIM_USER_AGENT = f"HillFinder/0.1 ({_contact})"

_nominatim_lock = asyncio.Lock()
_last_nominatim_call: float = 0.0


async def _rate_limit_nominatim() -> None:
    global _last_nominatim_call
    async with _nominatim_lock:
        elapsed = time.monotonic() - _last_nominatim_call
        if elapsed < NOMINATIM_MIN_INTERVAL:
            await asyncio.sleep(NOMINATIM_MIN_INTERVAL - elapsed)
        _last_nominatim_call = time.monotonic()


async def geocode_address(address: str, client: httpx.AsyncClient) -> tuple[float, float]:
    logger.info("Geocoding address: %r", address)
    await _rate_limit_nominatim()
    try:
        response = await client.get(
            NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=NOMINATIM_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        logger.warning("Nominatim timed out for address: %r", address)
        raise HTTPException(504, "Geocoding service timed out")
    except httpx.HTTPStatusError:
        logger.warning("Nominatim HTTP error for address: %r", address)
        raise HTTPException(502, "Geocoding service returned an error")
    except httpx.RequestError:
        logger.warning("Nominatim unreachable for address: %r", address)
        raise HTTPException(502, "Geocoding service unreachable")

    logger.debug("Nominatim raw response (%d result(s)): %s", len(data), data)
    if not data:
        logger.warning("No geocoding result for address: %r", address)
        raise HTTPException(400, detail=f"No location found for: {address}")

    lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
    logger.info("Geocoded %r → (%.6f, %.6f)", address, lat, lon)
    return lat, lon

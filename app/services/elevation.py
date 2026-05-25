import logging
import os

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

ORS_ELEVATION_URL = "https://api.openrouteservice.org/elevation/line"
ORS_TIMEOUT = float(os.getenv("ORS_TIMEOUT_S", "15"))
ORS_CHUNK_SIZE = 500


def _chunk_coordinates(coordinates: list[tuple[float, float]], chunk_size: int = 500) -> list[list[tuple[float, float]]]:
    if len(coordinates) <= chunk_size:
        return [coordinates]

    chunks = []
    start = 0
    while start < len(coordinates):
        end = start + chunk_size
        if end >= len(coordinates) or (start > 0 and len(coordinates) - end <= 1):
            chunks.append(coordinates[start:])
            break
        chunks.append(coordinates[start:end])
        start = end - 1  # overlap by one for elevation continuity at boundaries

    return chunks


async def _get_elevations_ors(
    coordinates: list, client: httpx.AsyncClient, api_key: str
) -> list[float]:
    chunks = _chunk_coordinates(coordinates, ORS_CHUNK_SIZE)
    logger.info(
        "Fetching elevations: %d coordinates in %d chunk(s)", len(coordinates), len(chunks)
    )
    all_elevations: list[float] = []

    for i, chunk in enumerate(chunks):
        logger.info(
            "ORS elevation chunk %d/%d: %d points → %s",
            i + 1,
            len(chunks),
            len(chunk),
            ORS_ELEVATION_URL,
        )
        # ORS uses GeoJSON coordinate order: [lon, lat] — internal data is (lat, lon)
        geojson_coords = [[lon, lat] for lat, lon in chunk]
        payload = {
            "format_in": "geojson",
            "format_out": "geojson",
            "geometry": {"coordinates": geojson_coords, "type": "LineString"},
        }
        try:
            response = await client.post(
                ORS_ELEVATION_URL,
                json=payload,
                headers={"Authorization": api_key, "Content-Type": "application/json"},
                timeout=ORS_TIMEOUT,
            )
            if response.status_code == 429:
                logger.warning(
                    "ORS elevation rate limit hit on chunk %d/%d", i + 1, len(chunks)
                )
                raise HTTPException(429, "ORS elevation API rate limit exceeded")
            response.raise_for_status()
            result = response.json()
        except HTTPException:
            raise
        except httpx.TimeoutException:
            logger.warning("ORS elevation timed out on chunk %d/%d", i + 1, len(chunks))
            raise HTTPException(504, "ORS elevation service timed out")
        except httpx.HTTPStatusError:
            logger.warning("ORS elevation HTTP error on chunk %d/%d", i + 1, len(chunks))
            raise HTTPException(502, "ORS elevation service returned an error")
        except httpx.RequestError:
            logger.warning("ORS elevation unreachable on chunk %d/%d", i + 1, len(chunks))
            raise HTTPException(502, "ORS elevation service unreachable")

        try:
            chunk_elevations = [pt[2] for pt in result["geometry"]["coordinates"]]
        except (KeyError, IndexError, TypeError):
            logger.error(
                "ORS elevation unexpected response format on chunk %d/%d", i + 1, len(chunks)
            )
            raise HTTPException(502, "ORS elevation service returned an unexpected response format")

        if i == 0:
            all_elevations.extend(chunk_elevations)
        else:
            all_elevations.extend(chunk_elevations[1:])  # skip duplicate boundary point

    logger.info("Elevation fetch complete: %d points returned", len(all_elevations))
    return all_elevations


async def get_elevations(
    coordinates: list[tuple[float, float]], client: httpx.AsyncClient, api_key: str
) -> list[float]:
    return await _get_elevations_ors(coordinates, client, api_key)

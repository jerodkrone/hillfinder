import logging
import math
import os

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

OVERPASS_TIMEOUT = float(os.getenv("OVERPASS_TIMEOUT_S", "180"))

OVERPASS_URL = "https://overpass.private.coffee/api/interpreter"

# Global bbox is applied before tag filtering, letting Overpass use its spatial
# index instead of the per-element distance check that `around` requires.
OVERPASS_QUERY_TEMPLATE = """
[out:json][bbox:{south},{west},{north},{east}];
(
  way["highway"~"^(primary|secondary|tertiary|residential|unclassified|path|footway|track|cycleway)$"];
);
out geom;
"""


def _compute_bbox(lat: float, lon: float, radius_m: int) -> tuple[float, float, float, float]:
    delta_lat = radius_m / 111_111
    delta_lon = radius_m / (111_111 * math.cos(math.radians(lat)))
    return (lat - delta_lat, lon - delta_lon, lat + delta_lat, lon + delta_lon)

_ROAD_SURFACES = {"asphalt", "concrete", "paved", "cobblestone", "sett"}
_TRAIL_SURFACES = {"gravel", "dirt", "grass", "unpaved", "compacted", "fine_gravel", "ground", "mud", "sand"}
_TRAIL_HIGHWAYS = {"path", "footway", "track", "bridleway"}
_ROAD_HIGHWAYS = {"primary", "secondary", "tertiary", "residential", "unclassified", "cycleway", "service", "living_street"}


def _classify_surface(tags: dict) -> str:
    surface = tags.get("surface")
    if surface in _ROAD_SURFACES:
        return "road"
    if surface in _TRAIL_SURFACES:
        return "trail"
    highway = tags.get("highway")
    if highway in _TRAIL_HIGHWAYS:
        return "trail"
    if highway in _ROAD_HIGHWAYS:
        return "road"
    return "unknown"


async def fetch_ways(
    lat: float,
    lon: float,
    client: httpx.AsyncClient,
    radius_m: int = 3000,
) -> list[dict]:
    logger.info("Fetching ways at (%.6f, %.6f) radius=%dm", lat, lon, radius_m)
    south, west, north, east = _compute_bbox(lat, lon, radius_m)
    logger.debug("Bbox: S=%.6f W=%.6f N=%.6f E=%.6f", south, west, north, east)
    query = OVERPASS_QUERY_TEMPLATE.format(south=south, west=west, north=north, east=east)
    logger.debug("Overpass query: %s", query)
    try:
        response = await client.get(
            OVERPASS_URL,
            params={"data": query},
            timeout=OVERPASS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        logger.warning("Overpass timed out at (%.6f, %.6f)", lat, lon)
        raise HTTPException(504, "Overpass service timed out")
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Overpass HTTP %d at (%.6f, %.6f): %s",
            exc.response.status_code, lat, lon, exc.response.text[:500],
        )
        raise HTTPException(502, "Overpass service returned an error")
    except httpx.RequestError:
        logger.warning("Overpass unreachable", exc_info=True)
        raise HTTPException(502, "Overpass service unreachable")
    except ValueError:
        logger.error("Failed to parse Overpass response")
        raise HTTPException(502, "Failed to parse Overpass response")

    ways = []
    for element in data.get("elements", []):
        geometry = element.get("geometry", [])
        if len(geometry) < 2:
            continue
        tags = element.get("tags", {})
        coords = [(node["lat"], node["lon"]) for node in geometry]
        ways.append({
            "name": tags.get("name"),
            "way_id": element.get("id"),
            "surface": _classify_surface(tags),
            "coordinates": coords,
        })

    logger.info("Overpass returned %d ways after geometry filter", len(ways))
    return ways

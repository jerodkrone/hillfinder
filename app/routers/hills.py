import logging
import os

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.hill import HillSegment
from app.services.geocoding import geocode_address
from app.services.overpass import fetch_ways
from app.services.elevation import get_elevations
from app.utils.geo import compute_grades, compute_total_length_m

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_WAYS = int(os.getenv("HILLFINDER_MAX_WAYS", "200"))


@router.get("/hills/", response_model=list[HillSegment])
async def get_hills(
    request: Request,
    address: str = Query(min_length=1),
    radius_m: int = Query(default=3000, ge=100, le=10000),
):
    logger.info("GET /hills/ address=%r radius_m=%d", address, radius_m)
    api_key = request.app.state.ors_api_key
    if not api_key:
        raise HTTPException(500, "ORS_API_KEY not configured")
    client = request.app.state.http_client

    lat, lon = await geocode_address(address, client)
    ways = await fetch_ways(lat, lon, client, radius_m)

    if not ways:
        logger.info("No ways found for address=%r, returning empty result", address)
        return []

    if len(ways) > _MAX_WAYS:
        logger.warning(
            "Way count capped: %d → %d (set HILLFINDER_MAX_WAYS to change)",
            len(ways),
            _MAX_WAYS,
        )
        ways = ways[:_MAX_WAYS]

    all_coords = []
    way_slices = []
    for way in ways:
        start = len(all_coords)
        all_coords.extend(way["coordinates"])
        way_slices.append((start, len(all_coords)))

    logger.debug(
        "Elevation call: %d ways, %d total coordinates", len(ways), len(all_coords)
    )
    all_elevations = await get_elevations(all_coords, client, api_key)

    results = []
    for way, (start, end) in zip(ways, way_slices):
        coords = way["coordinates"]
        elevations = all_elevations[start:end]
        try:
            avg_grade, max_grade = compute_grades(coords, elevations)
        except ValueError as exc:
            raise HTTPException(500, f"Grade computation failed: {exc}") from exc
        length_m = compute_total_length_m(coords)
        if length_m == 0.0:
            logger.debug("Skipping zero-length way: %r", way.get("name"))
            continue
        logger.debug(
            "Way %r: avg_grade=%.2f%% max_grade=%.2f%% length=%.1fm surface=%s",
            way.get("name"), avg_grade, max_grade, length_m, way.get("surface"),
        )
        results.append(HillSegment(
            name=way["name"],
            grade_avg_pct=avg_grade,
            grade_max_pct=max_grade,
            length_m=length_m,
            surface=way["surface"],
            coordinates=coords,
        ))

    results.sort(key=lambda s: s.grade_avg_pct, reverse=True)
    logger.info("Returning %d hills for address=%r", len(results), address)
    return results

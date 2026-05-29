import logging
import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.hill import HillSegment
from app.services.geocoding import geocode_address
from app.services.overpass import fetch_ways
from app.services.elevation import get_elevations
from app.utils.geo import compute_grades, compute_total_length_m, split_into_climbing_segments

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_WAYS = int(os.getenv("HILLFINDER_MAX_WAYS", "200"))


@router.get(
    "/hills/",
    response_model=list[HillSegment],
    responses={
        400: {"description": "Address could not be geocoded"},
        429: {"description": "Upstream rate limit (ORS)"},
        502: {"description": "Upstream service error (Nominatim / Overpass / ORS)"},
        504: {"description": "Upstream service timed out"},
    },
)
async def get_hills(
    request: Request,
    address: str = Query(min_length=1),
    radius_m: int = Query(default=3000, ge=100, le=10000),
    min_grade_pct: float = Query(default=3.0, ge=0.0, le=100.0),
    surface: Literal["road", "trail", "unknown"] | None = Query(default=None),
):
    logger.info(
        "GET /hills/ address=%r radius_m=%d min_grade_pct=%.1f surface=%r",
        address, radius_m, min_grade_pct, surface,
    )
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
        if surface is not None and way["surface"] != surface:
            continue

        coords = way["coordinates"]
        elevations = all_elevations[start:end]

        try:
            climbing_runs = split_into_climbing_segments(coords, elevations)
        except ValueError as exc:
            logger.warning("Segment split failed for way %r: %s", way.get("name"), exc)
            continue

        if not climbing_runs:
            logger.debug("No climbing segments found for way %r", way.get("name"))
            continue

        for seg_index, (seg_coords, seg_elevs) in enumerate(climbing_runs):
            try:
                avg_grade, max_grade = compute_grades(seg_coords, seg_elevs)
            except ValueError as exc:
                logger.warning(
                    "Grade compute failed for segment %d of way %r: %s",
                    seg_index, way.get("name"), exc,
                )
                continue

            if avg_grade < min_grade_pct:
                continue

            length_m = compute_total_length_m(seg_coords)

            results.append(HillSegment(
                name=way["name"],
                way_id=way["way_id"],
                grade_avg_pct=avg_grade,
                grade_max_pct=max_grade,
                length_m=length_m,
                surface=way["surface"],
                coordinates=seg_coords,
                way_segment_index=seg_index,
            ))

    results.sort(key=lambda s: s.grade_avg_pct, reverse=True)
    logger.info("Returning %d segments (from %d ways) for address=%r", len(results), len(ways), address)
    return results

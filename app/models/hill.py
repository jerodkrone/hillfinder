from typing import Literal
from pydantic import BaseModel


class HillSegment(BaseModel):
    name: str | None = None
    way_id: int | None = None
    grade_avg_pct: float
    grade_max_pct: float
    length_m: float
    surface: Literal["road", "trail", "unknown"]
    coordinates: list[tuple[float, float]]
    way_segment_index: int = 0

from typing import Literal
from pydantic import BaseModel


class HillSegment(BaseModel):
    name: str | None = None
    grade_avg_pct: float       # total upward gain / total distance × 100
    grade_max_pct: float       # steepest single consecutive node pair
    length_m: float
    surface: Literal["road", "trail", "unknown"]
    coordinates: list[tuple[float, float]]

"""The size translator: a brand's sizes, expressed in the platform standard.

Arithmetic on measurements. Each size is reduced to the middle of its chest,
waist and hip ranges, and matched to the standard size whose middles are
closest on the measurements both charts give. Within 2 cm on average is a
close match; anything further is an approximate one, and a size with no
shared measurement, or no chart at all, is shown as it is with no guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.errors import ValidationFailed
from ..models import Lot, SizeChartRow, StandardSize, User
from . import audit_service

DIMENSIONS = ("chest", "waist", "hip")
AUDIENCES = ("women", "men", "kids", "unisex")
CLOSE_CM = 2.0
ALIASES = {
    "small": "S",
    "sm": "S",
    "medium": "M",
    "med": "M",
    "large": "L",
    "lg": "L",
    "extra large": "XL",
    "xlarge": "XL",
    "2xl": "XXL",
    "xxlarge": "XXL",
    "extra small": "XS",
}


@dataclass(slots=True)
class SizeGuide:
    size: str
    standard: str | None
    match: str
    measurements: str


def normalise_label(label: str) -> str:
    cleaned = " ".join(label.strip().lower().replace("-", " ").split())
    return ALIASES.get(cleaned, label.strip().upper())


def _middles(row: Any) -> dict[str, float]:
    out = {}
    for dimension in DIMENSIONS:
        low = getattr(row, f"{dimension}_min_cm")
        high = getattr(row, f"{dimension}_max_cm")
        if low is not None and high is not None:
            out[dimension] = (float(low) + float(high)) / 2
    return out


def _describe(row: Any) -> str:
    parts = []
    for dimension in DIMENSIONS:
        low = getattr(row, f"{dimension}_min_cm")
        high = getattr(row, f"{dimension}_max_cm")
        if low is not None and high is not None:
            parts.append(f"{dimension} {float(low):g} to {float(high):g} cm")
    return ", ".join(parts)


def nearest(row: Any, standards: list[StandardSize]) -> tuple[StandardSize | None, float | None]:
    mine = _middles(row)
    best: StandardSize | None = None
    best_distance: float | None = None
    for standard in standards:
        theirs = _middles(standard)
        shared = [d for d in DIMENSIONS if d in mine and d in theirs]
        if not shared:
            continue
        distance = sum(abs(mine[d] - theirs[d]) for d in shared) / len(shared)
        if best_distance is None or distance < best_distance:
            best, best_distance = standard, distance
    return best, best_distance


def guide_for(db: Session, lot: Lot) -> list[SizeGuide]:
    """Each size in a lot's manifest, with its standard equivalent where known."""
    chart = list(db.scalars(select(SizeChartRow).where(SizeChartRow.brand_id == lot.brand_id)))
    standards = list(db.scalars(select(StandardSize)))
    sizes = sorted({line.size for line in lot.manifest_lines})
    out = []
    for size in sizes:
        wanted = normalise_label(size)
        row = next((r for r in chart if normalise_label(r.label) == wanted), None)
        if row is None:
            out.append(SizeGuide(size=size, standard=None, match="no chart", measurements=""))
            continue
        pool = [s for s in standards if s.audience == row.audience] or standards
        match, distance = nearest(row, pool)
        if match is None or distance is None:
            out.append(
                SizeGuide(size=size, standard=None, match="no chart", measurements=_describe(row))
            )
            continue
        out.append(
            SizeGuide(
                size=size,
                standard=match.label,
                match="close" if distance <= CLOSE_CM else "approximate",
                measurements=_describe(row),
            )
        )
    return out


def replace_chart(
    db: Session, *, brand_id: str, actor: User, rows: list[dict[str, Any]]
) -> list[SizeChartRow]:
    """Replace the brand's whole chart. Every range must run low to high."""
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row["audience"] not in AUDIENCES:
            raise ValidationFailed(f"Audience must be one of {', '.join(AUDIENCES)}.")
        key = (row["audience"], normalise_label(row["label"]))
        if key in seen:
            raise ValidationFailed(f"{row['label']} is listed twice for {row['audience']}.")
        seen.add(key)
        for dimension in DIMENSIONS:
            low, high = row.get(f"{dimension}_min_cm"), row.get(f"{dimension}_max_cm")
            if (low is None) != (high is None):
                raise ValidationFailed(
                    f"Give both ends of the {dimension} range for {row['label']}."
                )
            if low is not None and high is not None and float(low) > float(high):
                raise ValidationFailed(f"The {dimension} range for {row['label']} runs backwards.")
    db.execute(delete(SizeChartRow).where(SizeChartRow.brand_id == brand_id))
    created = [SizeChartRow(brand_id=brand_id, **row) for row in rows]
    db.add_all(created)
    db.flush()
    audit_service.record(
        db,
        action="size_chart.replaced",
        entity_type="brand",
        entity_id=brand_id,
        brand_id=brand_id,
        actor_user_id=actor.id,
        actor_role=actor.role,
        after={"rows": len(created)},
    )
    return created

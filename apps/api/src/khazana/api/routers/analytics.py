"""Reports for brands and administrators.

Returned as plain dictionaries with documented shapes, because each report is
read whole by one screen and changes with it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ...core.tenancy import assert_owns
from ...services import analytics_service
from ..deps import AdminOnly, CurrentBrand, Db

router = APIRouter(tags=["analytics"])


@router.get("/brands/{brand_id}/analytics", operation_id="brand_analytics")
def brand_analytics(
    brand_id: str,
    principal: CurrentBrand,
    db: Db,
    days: int = Query(default=90, ge=7, le=730),
) -> dict[str, Any]:
    """What this brand sold, where, in which categories, at what price."""
    assert_owns(principal, brand_id)
    return analytics_service.brand_report(db, brand_id=brand_id, days=days)


@router.get("/brands/{brand_id}/impact", operation_id="brand_impact")
def brand_impact(
    brand_id: str,
    principal: CurrentBrand,
    db: Db,
    days: int = Query(default=365, ge=7, le=1_825),
) -> dict[str, Any]:
    """Pieces kept from waste, and the weight, water and carbon that represents."""
    assert_owns(principal, brand_id)
    return analytics_service.impact_report(db, brand_id=brand_id, days=days)


@router.get("/admin/analytics", operation_id="admin_analytics")
def platform(_: AdminOnly, db: Db, days: int = Query(default=30, ge=7, le=365)) -> dict[str, Any]:
    """GMV, orders, commission, buyers and growth against the period before."""
    return analytics_service.platform_report(db, days=days)


@router.get("/admin/ai-costs", operation_id="admin_ai_costs")
def ai_costs(_: AdminOnly, db: Db, days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    """AI spend per feature, and the AI cost per listing and per order."""
    return analytics_service.ai_costs(db, days=days)

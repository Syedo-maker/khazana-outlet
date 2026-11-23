"""The fraud and counterfeit review queue. Administrators only."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...core.errors import NotFound
from ...models import Lot, Order, ReviewCase, User
from ...models.enums import ReviewStatus
from ...services import risk_service
from ..deps import AdminOnly, Db

router = APIRouter(prefix="/admin", tags=["admin"])


class SignalOut(BaseModel):
    code: str
    weight: int
    detail: str


class CaseOut(BaseModel):
    id: str
    subject_type: str
    subject_id: str
    subject_label: str
    subject_link: str | None
    score: int
    signals: list[SignalOut]
    status: ReviewStatus
    decision_note: str | None
    decided_at: datetime | None
    scored_at: datetime


class DecisionIn(BaseModel):
    outcome: ReviewStatus
    action: str = Field(default="none", pattern="^(none|suspend_account|pause_listing)$")
    note: str = Field(min_length=3, max_length=1_000)


class RunOut(BaseModel):
    open_cases: int


def _subject(db: Db, case: ReviewCase) -> tuple[str, str | None]:
    """A name a reviewer recognises, and where to look at it."""
    if case.subject_type == "listing":
        lot = db.get(Lot, case.subject_id)
        if lot is not None:
            return f"{lot.lot_code} {lot.title}", "/admin/listings"
    if case.subject_type == "order":
        order = db.get(Order, case.subject_id)
        if order is not None:
            return order.order_code, f"/orders/{order.id}"
    if case.subject_type == "account":
        user = db.get(User, case.subject_id)
        if user is not None:
            profile = user.reseller_profile
            name = profile.business_name if profile else user.full_name
            return f"{name}, {user.phone}", "/admin/verification"
    return case.subject_id, None


def _out(case: ReviewCase, db: Db) -> CaseOut:
    label, link = _subject(db, case)
    return CaseOut(
        id=case.id,
        subject_type=case.subject_type,
        subject_id=case.subject_id,
        subject_label=label,
        subject_link=link,
        score=case.score,
        signals=[SignalOut(**s) for s in (case.signals or {}).get("signals", [])],
        status=case.status,
        decision_note=case.decision_note,
        decided_at=case.decided_at,
        scored_at=case.scored_at,
    )


@router.get("/review-cases", response_model=list[CaseOut], operation_id="admin_review_cases")
def cases(
    _: AdminOnly, db: Db, status: ReviewStatus = Query(default=ReviewStatus.OPEN)
) -> list[CaseOut]:
    """Cases by status, highest score first."""
    rows = db.scalars(
        select(ReviewCase)
        .where(ReviewCase.status == status)
        .order_by(ReviewCase.score.desc(), ReviewCase.scored_at.desc())
        .limit(200)
    )
    return [_out(row, db) for row in rows]


@router.post(
    "/review-cases/{case_id}/decision",
    response_model=CaseOut,
    operation_id="admin_review_decision",
)
def decide(case_id: str, body: DecisionIn, principal: AdminOnly, db: Db) -> CaseOut:
    """Clear a case, or act on it with the action you choose. Always with a note."""
    admin = db.get(User, principal.user_id)
    if admin is None:
        raise NotFound("That account no longer exists.")
    case = risk_service.decide(
        db, case_id=case_id, admin=admin, outcome=body.outcome, action=body.action, note=body.note
    )
    db.commit()
    return _out(case, db)


@router.post("/jobs/risk", response_model=RunOut, operation_id="admin_run_risk")
def run(_: AdminOnly, db: Db) -> RunOut:
    """Score accounts, recent orders and live listings now."""
    open_cases = risk_service.run(db)
    db.commit()
    return RunOut(open_cases=open_cases)

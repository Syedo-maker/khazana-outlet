"""The fraud and counterfeit review queue. Administrators only."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...core.errors import NotFound
from ...models import ReviewCase, User
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


def _out(case: ReviewCase) -> CaseOut:
    return CaseOut(
        id=case.id,
        subject_type=case.subject_type,
        subject_id=case.subject_id,
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
    return [_out(row) for row in rows]


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
    return _out(case)


@router.post("/jobs/risk", response_model=RunOut, operation_id="admin_run_risk")
def run(_: AdminOnly, db: Db) -> RunOut:
    """Score accounts, recent orders and live listings now."""
    open_cases = risk_service.run(db)
    db.commit()
    return RunOut(open_cases=open_cases)

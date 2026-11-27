"""Monthly commission invoices for brands paid directly by cash on delivery.

A brand reads its own invoices; admins issue them, read them all and record
payment. See services/commission_service.py for the rules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...core.tenancy import assert_owns
from ...models import Brand, CommissionInvoice, User
from ...models.enums import CommissionInvoiceStatus
from ...services import commission_service
from ..deps import AdminOnly, CurrentBrand, Db, client_ip

router = APIRouter(tags=["commissions"])


class CommissionInvoiceOut(BaseModel):
    id: str
    number: str
    brand_id: str
    brand_name: str
    period_start: datetime
    period_end: datetime
    order_count: int
    sales_pkr: int
    commission_pkr: int
    status: CommissionInvoiceStatus
    issued_at: datetime
    due_at: datetime
    paid_at: datetime | None
    paid_reference: str | None


class InvoiceLineOut(BaseModel):
    order_id: str
    order_code: str
    confirmed_at: datetime | None
    subtotal_pkr: int
    refunded_pkr: int
    commission_percent: float
    commission_pkr: int


class CommissionInvoiceDetailOut(CommissionInvoiceOut):
    lines: list[InvoiceLineOut]


class BrandCommissionSummaryOut(BaseModel):
    """Accrued on confirmed orders and not yet on an invoice."""

    unbilled_commission_pkr: int


class IssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=2026, le=2100)
    month: int = Field(ge=1, le=12)


class PaidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=3, max_length=120)


def _out(db: Session, invoice: CommissionInvoice) -> CommissionInvoiceOut:
    brand = db.get(Brand, invoice.brand_id)
    return CommissionInvoiceOut(
        id=invoice.id,
        number=invoice.number,
        brand_id=invoice.brand_id,
        brand_name=brand.name if brand else "",
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        order_count=invoice.order_count,
        sales_pkr=invoice.sales_pkr,
        commission_pkr=invoice.commission_pkr,
        status=invoice.status,
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
        paid_at=invoice.paid_at,
        paid_reference=invoice.paid_reference,
    )


def _detail(db: Session, invoice: CommissionInvoice) -> CommissionInvoiceDetailOut:
    return CommissionInvoiceDetailOut(
        **_out(db, invoice).model_dump(),
        lines=[
            InvoiceLineOut(
                order_id=line.order_id,
                order_code=line.order_code,
                confirmed_at=line.confirmed_at,
                subtotal_pkr=line.subtotal_pkr,
                refunded_pkr=line.refunded_pkr,
                commission_percent=float(line.commission_percent),
                commission_pkr=line.commission_pkr,
            )
            for line in commission_service.lines(db, invoice)
        ],
    )


@router.get(
    "/brands/{brand_id}/commission-invoices",
    response_model=list[CommissionInvoiceOut],
    operation_id="brands_commission_invoices",
)
def brand_invoices(brand_id: str, principal: CurrentBrand, db: Db) -> list[CommissionInvoiceOut]:
    assert_owns(principal, brand_id)
    return [_out(db, row) for row in commission_service.list_invoices(db, brand_id=brand_id)]


@router.get(
    "/brands/{brand_id}/commission-summary",
    response_model=BrandCommissionSummaryOut,
    operation_id="brands_commission_summary",
)
def brand_summary(brand_id: str, principal: CurrentBrand, db: Db) -> BrandCommissionSummaryOut:
    assert_owns(principal, brand_id)
    return BrandCommissionSummaryOut(
        unbilled_commission_pkr=commission_service.unbilled_total(db, brand_id=brand_id)
    )


@router.get(
    "/commission-invoices/{invoice_id}",
    response_model=CommissionInvoiceDetailOut,
    operation_id="commission_invoices_detail",
)
def get_invoice(invoice_id: str, principal: CurrentBrand, db: Db) -> CommissionInvoiceDetailOut:
    invoice = commission_service.get_invoice(db, invoice_id)
    assert_owns(principal, invoice.brand_id)
    return _detail(db, invoice)


@router.get(
    "/admin/commission-invoices",
    response_model=list[CommissionInvoiceOut],
    operation_id="admin_commission_invoices",
)
def admin_invoices(
    _: AdminOnly,
    db: Db,
    invoice_status: Annotated[CommissionInvoiceStatus | None, Query(alias="status")] = None,
) -> list[CommissionInvoiceOut]:
    return [_out(db, row) for row in commission_service.list_invoices(db, status=invoice_status)]


@router.post(
    "/admin/commission-invoices/issue",
    response_model=list[CommissionInvoiceOut],
    operation_id="admin_issue_commission_invoices",
)
def issue(body: IssueIn, _: AdminOnly, db: Db) -> list[CommissionInvoiceOut]:
    """Issue a month's invoices now. The scheduler does this on the first of
    each month for the month before; running it again issues nothing twice."""
    created = commission_service.issue_month(db, year=body.year, month=body.month)
    db.commit()
    return [_out(db, row) for row in created]


@router.post(
    "/admin/commission-invoices/{invoice_id}/paid",
    response_model=CommissionInvoiceOut,
    operation_id="admin_commission_invoice_paid",
)
def mark_paid(
    invoice_id: str, body: PaidIn, principal: AdminOnly, db: Db, request: Request
) -> CommissionInvoiceOut:
    admin = db.get(User, principal.user_id)
    if admin is None:
        raise NotFound("That account no longer exists.")
    invoice = commission_service.mark_paid(
        db, invoice_id=invoice_id, admin=admin, reference=body.reference, ip=client_ip(request)
    )
    db.commit()
    return _out(db, invoice)

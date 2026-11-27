"""The commission a brand owes on its direct orders, and the monthly invoice.

Under direct settlement the brand's courier collects the cash, so the money
flows the other way from a platform settled order: instead of a payout to the
brand, the platform bills its commission.

- **Accrual.** When a direct order is confirmed, the commission due is fixed
  on the order: the commission rate copied when it was placed, applied to what
  the buyer kept, which is the goods less any refund the brand made after a
  dispute. A full refund means no sale and no commission.
- **Invoice.** On the first of each month, every brand with confirmed, unbilled
  direct orders from the month before gets one invoice. Each order points at
  its invoice, so running the job twice bills nothing twice.
- **Payment.** The brand pays by bank transfer outside the platform, and an
  admin records it with the bank reference. Nothing here moves money and no
  model is involved anywhere in this module.

Months are Pakistan calendar months.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..models import CommissionInvoice, Order, User
from ..models.base import as_utc, utcnow
from ..models.enums import CommissionInvoiceStatus, OrderStatus, SettlementMode
from . import audit_service

PKT = timezone(timedelta(hours=5), "PKT")


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    order_id: str
    order_code: str
    confirmed_at: datetime | None
    subtotal_pkr: int
    refunded_pkr: int
    commission_percent: Decimal
    commission_pkr: int


def refunded_by_brand(order: Order) -> int:
    """What the brand gave back to the buyer after disputes on this order."""
    return sum(dispute.refund_pkr or 0 for dispute in order.disputes)


def commission_on(amount_pkr: int, percent: Decimal | float) -> int:
    rate = Decimal(str(percent))
    return int(
        (Decimal(max(0, amount_pkr)) * rate / Decimal(100)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def accrue(db: Session, order: Order) -> int:
    """Fix the commission due on a confirmed direct order."""
    if SettlementMode(order.settlement_mode) != SettlementMode.DIRECT:
        raise Conflict("Commission is invoiced only on orders paid directly to the brand.")
    kept = order.subtotal_pkr - refunded_by_brand(order)
    order.commission_due_pkr = commission_on(kept, order.commission_percent)
    db.flush()
    audit_service.record(
        db,
        action="commission.accrued",
        entity_type="order",
        entity_id=order.id,
        brand_id=order.brand_id,
        actor_kind=audit_service.ACTOR_SYSTEM,
        after={"order": order.order_code, "commission_due_pkr": order.commission_due_pkr},
    )
    return order.commission_due_pkr


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """The start of the month and of the next, Pakistan time, in UTC."""
    if not 1 <= month <= 12:
        raise ValidationFailed("Month must be between 1 and 12.")
    start = datetime(year, month, 1, tzinfo=PKT)
    end = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=PKT)
    return start.astimezone(UTC), end.astimezone(UTC)


def previous_month(moment: datetime | None = None) -> tuple[int, int]:
    local = as_utc(moment or utcnow()).astimezone(PKT)
    if local.month == 1:
        return local.year - 1, 12
    return local.year, local.month - 1


def issue_month(
    db: Session, *, year: int, month: int, now: datetime | None = None
) -> list[CommissionInvoice]:
    """One invoice per brand for its unbilled direct orders confirmed that month.

    Returns only the invoices this call created, so a second run returns none.
    """
    start, end = month_bounds(year, month)
    issued_at = now or utcnow()
    orders = db.scalars(
        select(Order)
        .where(
            Order.settlement_mode == SettlementMode.DIRECT,
            Order.status == OrderStatus.CONFIRMED,
            Order.commission_invoice_id.is_(None),
            Order.commission_due_pkr.is_not(None),
            Order.confirmed_at >= start,
            Order.confirmed_at < end,
        )
        .order_by(Order.brand_id, Order.confirmed_at)
    ).all()

    by_brand: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        by_brand[order.brand_id].append(order)

    created: list[CommissionInvoice] = []
    sequence = _next_sequence(db, year, month)
    for brand_id in sorted(by_brand):
        already = db.scalars(
            select(CommissionInvoice.id).where(
                CommissionInvoice.brand_id == brand_id, CommissionInvoice.period_start == start
            )
        ).first()
        if already is not None:
            # Cannot happen for confirmed orders, which are confirmed once,
            # but an invoice once issued is never silently changed.
            continue
        rows = by_brand[brand_id]
        invoice = CommissionInvoice(
            brand_id=brand_id,
            number=f"KO-{year:04d}-{month:02d}-{sequence:03d}",
            period_start=start,
            period_end=end,
            order_count=len(rows),
            sales_pkr=sum(row.subtotal_pkr - refunded_by_brand(row) for row in rows),
            commission_pkr=sum(row.commission_due_pkr or 0 for row in rows),
            status=CommissionInvoiceStatus.ISSUED,
            issued_at=issued_at,
            due_at=issued_at + timedelta(days=get_settings().commission_invoice_due_days),
        )
        db.add(invoice)
        db.flush()
        for row in rows:
            row.commission_invoice_id = invoice.id
        audit_service.record(
            db,
            action="commission_invoice.issued",
            entity_type="commission_invoice",
            entity_id=invoice.id,
            brand_id=brand_id,
            actor_kind=audit_service.ACTOR_SYSTEM,
            after={
                "number": invoice.number,
                "orders": invoice.order_count,
                "commission_pkr": invoice.commission_pkr,
            },
        )
        created.append(invoice)
        sequence += 1
    db.flush()
    return created


def issue_previous_month(db: Session, *, now: datetime | None = None) -> int:
    year, month = previous_month(now)
    return len(issue_month(db, year=year, month=month, now=now))


def mark_paid(
    db: Session, *, invoice_id: str, admin: User, reference: str, ip: str | None = None
) -> CommissionInvoice:
    """An admin has seen the brand's transfer arrive."""
    invoice = get_invoice(db, invoice_id)
    if CommissionInvoiceStatus(invoice.status) != CommissionInvoiceStatus.ISSUED:
        raise Conflict(f"This invoice is already {invoice.status}.")
    cleaned = " ".join(reference.split())
    if len(cleaned) < 3:
        raise ValidationFailed("Enter the bank reference of the brand's payment.")
    invoice.status = CommissionInvoiceStatus.PAID
    invoice.paid_at = utcnow()
    invoice.paid_reference = cleaned[:120]
    invoice.recorded_by_user_id = admin.id
    db.flush()
    audit_service.record(
        db,
        action="commission_invoice.paid",
        entity_type="commission_invoice",
        entity_id=invoice.id,
        brand_id=invoice.brand_id,
        actor_user_id=admin.id,
        actor_role=admin.role,
        after={"number": invoice.number, "reference": invoice.paid_reference},
        ip=ip,
    )
    return invoice


def get_invoice(db: Session, invoice_id: str) -> CommissionInvoice:
    invoice = db.get(CommissionInvoice, invoice_id)
    if invoice is None:
        raise NotFound("That invoice does not exist.")
    return invoice


def list_invoices(
    db: Session,
    *,
    brand_id: str | None = None,
    status: CommissionInvoiceStatus | None = None,
    limit: int = 100,
) -> list[CommissionInvoice]:
    statement = select(CommissionInvoice)
    if brand_id is not None:
        statement = statement.where(CommissionInvoice.brand_id == brand_id)
    if status is not None:
        statement = statement.where(CommissionInvoice.status == status)
    return list(
        db.scalars(
            statement.order_by(
                CommissionInvoice.period_start.desc(), CommissionInvoice.number
            ).limit(limit)
        ).all()
    )


def lines(db: Session, invoice: CommissionInvoice) -> list[InvoiceLine]:
    orders = db.scalars(
        select(Order)
        .where(Order.commission_invoice_id == invoice.id)
        .order_by(Order.confirmed_at, Order.order_code)
    ).all()
    return [
        InvoiceLine(
            order_id=order.id,
            order_code=order.order_code,
            confirmed_at=order.confirmed_at,
            subtotal_pkr=order.subtotal_pkr,
            refunded_pkr=refunded_by_brand(order),
            commission_percent=Decimal(str(order.commission_percent)),
            commission_pkr=order.commission_due_pkr or 0,
        )
        for order in orders
    ]


def unbilled_total(db: Session, *, brand_id: str) -> int:
    """Commission accrued on confirmed orders not yet on an invoice."""
    rows = db.scalars(
        select(Order.commission_due_pkr).where(
            Order.brand_id == brand_id,
            Order.settlement_mode == SettlementMode.DIRECT,
            Order.commission_invoice_id.is_(None),
            Order.commission_due_pkr.is_not(None),
        )
    ).all()
    return sum(value or 0 for value in rows)


def _next_sequence(db: Session, year: int, month: int) -> int:
    prefix = f"KO-{year:04d}-{month:02d}-"
    numbers = db.scalars(
        select(CommissionInvoice.number).where(CommissionInvoice.number.like(f"{prefix}%"))
    ).all()
    taken = [
        int(number.removeprefix(prefix)) for number in numbers if number[len(prefix) :].isdigit()
    ]
    return max(taken, default=0) + 1

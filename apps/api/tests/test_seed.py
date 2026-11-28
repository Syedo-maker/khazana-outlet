"""The demonstration data has to be usable by every role."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from khazana.models import Dispute, Lot, Order, Payout, Shipment
from khazana.models.enums import LotStatus, OrderStatus, Visibility
from khazana.seed import seed
from khazana.services import payment_service, photo_protection_service
from khazana.storage import get_backend


def test_the_seed_builds_a_working_marketplace(db: Session) -> None:
    counts = seed(db)

    assert counts["orders"] > 0
    statuses = {OrderStatus(status) for status in db.scalars(select(Order.status)).all()}
    assert {
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.CONFIRMED,
        OrderStatus.DISPUTED,
    } <= statuses
    assert db.scalar(select(func.count()).select_from(Shipment))
    assert db.scalar(select(func.count()).select_from(Dispute))
    assert db.scalar(select(func.count()).select_from(Payout))
    assert payment_service.reconciliation(db) == []


def test_every_live_unbranded_photo_is_ready_for_buyers(db: Session) -> None:
    seed(db)
    lots = db.scalars(
        select(Lot).where(Lot.status == LotStatus.LIVE, Lot.visibility == Visibility.UNBRANDED)
    ).all()
    assert lots
    for lot in lots:
        shown = photo_protection_service.buyer_photos(lot)
        assert len(shown) == len(lot.photos)
        for photo in shown:
            key = photo_protection_service.buyer_file_key(lot, photo)
            assert key is not None
            assert get_backend().exists(key)


def test_the_seed_shows_cash_on_delivery_paid_to_the_brand(db: Session) -> None:
    from khazana.models import CommissionInvoice, Payment
    from khazana.models.enums import SettlementMode

    seed(db)
    direct = db.scalars(select(Order).where(Order.settlement_mode == SettlementMode.DIRECT)).all()
    assert {OrderStatus(order.status) for order in direct} >= {
        OrderStatus.PREPARING,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELLED,
    }
    ids = [order.id for order in direct]
    assert not db.scalars(select(Payment).where(Payment.order_id.in_(ids))).all()
    assert db.scalar(select(func.count()).select_from(CommissionInvoice)) == 1

"""The upcycle and donation route: matching, offering, and what brands see."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from commerce_helpers import auth, live_lot
from khazana.core.errors import Conflict, ValidationFailed
from khazana.models import AuditLog, Lot, Partner
from khazana.models.enums import LotStatus, RedirectStatus
from khazana.services import redirect_service


def _partner(db: Session, **overrides: object) -> Partner:
    values: dict[str, object] = {
        "name": "Multan Tailors Collective",
        "kind": "tailor",
        "city": "Lahore",
        "categories": {"words": ["womenswear"]},
        "grades": {"grades": []},
        "min_pieces": 10,
        "max_pieces": None,
        "contact_name": "Coordinator",
        "contact_phone": "03009990000",
    }
    values.update(overrides)
    partner = Partner(**values)
    db.add(partner)
    db.commit()
    return partner


@pytest.fixture
def lot(db: Session, two_brands, category) -> Lot:  # type: ignore[no-untyped-def]
    (brand, owner), _ = two_brands
    return live_lot(db, brand, owner, category.id)


class TestMatching:
    def test_partners_in_the_stock_city_who_take_the_category_come_first(
        self, db: Session, lot: Lot
    ) -> None:
        far = _partner(db, name="Karachi NGO", kind="ngo", city="Karachi")
        near = _partner(db, name="Lahore Artisans", kind="artisan")
        _partner(db, name="Shoe recycler", kind="recycler", categories={"words": ["footwear"]})
        _partner(db, name="Small studio", max_pieces=20)
        ranked = redirect_service.matches(db, lot)
        names = [m.partner.name for m in ranked]
        assert names[0] == near.name
        assert far.name in names
        assert "Shoe recycler" not in names, "does not take this category"
        assert "Small studio" not in names, "too many pieces for them"
        assert "In Lahore, where the stock is" in ranked[0].reasons

    def test_a_partner_can_take_only_some_grades(self, db: Session, lot: Lot) -> None:
        _partner(db, grades={"grades": ["C"]})
        assert redirect_service.matches(db, lot) == []


class TestOffering:
    def test_offer_accept_and_collect(self, db: Session, lot: Lot, two_brands, admin_user) -> None:  # type: ignore[no-untyped-def]
        (_, owner), _ = two_brands
        partner = _partner(db)
        offered = redirect_service.propose(
            db, lot=lot, partner_id=partner.id, route="donation", price_pkr=0, actor=owner
        )
        assert offered.pieces == lot.available_pieces
        redirect_service.move(
            db, redirection_id=offered.id, to=RedirectStatus.ACCEPTED, actor=admin_user
        )
        assert lot.status == LotStatus.WITHDRAWN, "given away stock cannot also be sold"
        redirect_service.move(
            db, redirection_id=offered.id, to=RedirectStatus.COLLECTED, actor=admin_user
        )
        assert offered.collected_at is not None
        actions = {
            a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity_id == offered.id))
        }
        assert actions == {"redirection.proposed", "redirection.accepted", "redirection.collected"}

    def test_a_donation_has_no_price(self, db: Session, lot: Lot, two_brands) -> None:  # type: ignore[no-untyped-def]
        (_, owner), _ = two_brands
        with pytest.raises(ValidationFailed, match="no price"):
            redirect_service.propose(
                db,
                lot=lot,
                partner_id=_partner(db).id,
                route="donation",
                price_pkr=500,
                actor=owner,
            )

    def test_one_offer_at_a_time(self, db: Session, lot: Lot, two_brands) -> None:  # type: ignore[no-untyped-def]
        (_, owner), _ = two_brands
        partner = _partner(db)
        redirect_service.propose(
            db, lot=lot, partner_id=partner.id, route="upcycle_sale", price_pkr=2000, actor=owner
        )
        with pytest.raises(Conflict, match="already been offered"):
            redirect_service.propose(
                db, lot=lot, partner_id=partner.id, route="donation", price_pkr=0, actor=owner
            )

    def test_a_lot_with_orders_in_progress_cannot_be_given_away(
        self,
        db: Session,
        lot: Lot,
        two_brands,  # type: ignore[no-untyped-def]
    ) -> None:
        (_, owner), _ = two_brands
        lot.reserved_pieces = 10
        db.commit()
        with pytest.raises(Conflict, match="orders in progress"):
            redirect_service.propose(
                db, lot=lot, partner_id=_partner(db).id, route="donation", price_pkr=0, actor=owner
            )


class TestEndpoints:
    def test_brands_never_see_partner_contacts(
        self,
        client: TestClient,
        db: Session,
        lot: Lot,
        two_brands,  # type: ignore[no-untyped-def]
    ) -> None:
        (_, owner), (_, other_owner) = two_brands
        _partner(db)
        matches = client.get(f"/lots/{lot.id}/partner-matches", headers=auth(owner))
        assert matches.status_code == 200, matches.text
        assert "03009990000" not in matches.text and "Coordinator" not in matches.text
        assert (
            client.get(f"/lots/{lot.id}/partner-matches", headers=auth(other_owner)).status_code
            == 404
        )

    def test_admin_records_the_outcome(
        self,
        client: TestClient,
        db: Session,
        lot: Lot,
        two_brands,
        admin_user,  # type: ignore[no-untyped-def]
    ) -> None:
        (_, owner), _ = two_brands
        partner = _partner(db)
        offered = client.post(
            f"/lots/{lot.id}/redirections",
            json={"partner_id": partner.id, "route": "donation"},
            headers=auth(owner),
        )
        assert offered.status_code == 201, offered.text
        moved = client.post(
            f"/admin/redirections/{offered.json()['id']}/status",
            json={"status": "accepted"},
            headers=auth(admin_user),
        )
        assert moved.json()["status"] == "accepted"
        skipped = client.post(
            f"/admin/redirections/{offered.json()['id']}/status",
            json={"status": "proposed"},
            headers=auth(admin_user),
        )
        assert skipped.status_code == 409

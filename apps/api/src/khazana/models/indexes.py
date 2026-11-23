"""Indexes on the columns queries filter and join by.

Declared here, in one place, rather than scattered over the model classes,
so the list can be read as a whole. Brand scoped tables are indexed on
``brand_id`` because the tenancy filter and the row level security policies
both read it, and foreign keys that queries look up by are indexed because
PostgreSQL does not index a foreign key column on its own. Migration 0016
creates them.
"""

from __future__ import annotations

from sqlalchemy import Index

from .ai import AiOutput, AiSpend, Embedding
from .catalog import ListingApproval, Lot, LotDefect, LotExcludedCity, LotPhoto, ManifestLine
from .commerce import Dispute, OrderEvent, OrderLine, OrderReturn, Payout, Shipment, ShipmentEvent
from .forecast import LotForecast, ProductionWarning
from .negotiation import Negotiation, NegotiationMessage
from .pool import Pool
from .redirect import Redirection
from .review import ReviewCase

QUERY_INDEXES: tuple[Index, ...] = (
    Index("ix_lots_category_id", Lot.category_id),
    Index("ix_disputes_order_id", Dispute.order_id),
    Index("ix_ai_outputs_job_id", AiOutput.job_id),
    Index("ix_ai_spend_brand_id", AiSpend.brand_id),
    Index("ix_payouts_run_id", Payout.run_id),
    Index("ix_embeddings_brand_id", Embedding.brand_id),
    Index("ix_manifest_lines_brand_id", ManifestLine.brand_id),
    Index("ix_lot_photos_brand_id", LotPhoto.brand_id),
    Index("ix_lot_excluded_cities_brand_id", LotExcludedCity.brand_id),
    Index("ix_listing_approvals_brand_id", ListingApproval.brand_id),
    Index("ix_lot_defects_brand_id", LotDefect.brand_id),
    Index("ix_order_lines_brand_id", OrderLine.brand_id),
    Index("ix_order_events_brand_id", OrderEvent.brand_id),
    Index("ix_order_returns_brand_id", OrderReturn.brand_id),
    Index("ix_shipments_brand_id", Shipment.brand_id),
    Index("ix_shipment_events_brand_id", ShipmentEvent.brand_id),
    Index("ix_disputes_brand_id", Dispute.brand_id),
    Index("ix_negotiations_lot_id", Negotiation.lot_id),
    Index("ix_negotiations_buyer_user_id", Negotiation.buyer_user_id),
    Index("ix_negotiations_brand_id", Negotiation.brand_id),
    Index("ix_negotiation_messages_negotiation_id", NegotiationMessage.negotiation_id),
    Index("ix_negotiation_messages_brand_id", NegotiationMessage.brand_id),
    Index("ix_pools_lot_id", Pool.lot_id),
    Index("ix_redirections_brand_id", Redirection.brand_id),
    Index("ix_redirections_lot_id", Redirection.lot_id),
    Index("ix_lot_forecasts_brand_id", LotForecast.brand_id),
    Index("ix_production_warnings_brand_id", ProductionWarning.brand_id),
    Index("ix_review_cases_status", ReviewCase.status),
)

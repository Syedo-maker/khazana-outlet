"""Indexes on the columns queries filter and join by.

An audit of every foreign key without an index, kept to the ones queries
actually use: brand_id on brand scoped tables, which the tenancy filter and the
row level security policies read, and the lookups the services make. Columns
that only record who reviewed or acted on something are left unindexed.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_lots_category_id", "lots", ["category_id"])
    op.create_index("ix_disputes_order_id", "disputes", ["order_id"])
    op.create_index("ix_ai_outputs_job_id", "ai_outputs", ["job_id"])
    op.create_index("ix_ai_spend_brand_id", "ai_spend", ["brand_id"])
    op.create_index("ix_payouts_run_id", "payouts", ["run_id"])
    op.create_index("ix_embeddings_brand_id", "embeddings", ["brand_id"])
    op.create_index("ix_manifest_lines_brand_id", "manifest_lines", ["brand_id"])
    op.create_index("ix_lot_photos_brand_id", "lot_photos", ["brand_id"])
    op.create_index("ix_lot_excluded_cities_brand_id", "lot_excluded_cities", ["brand_id"])
    op.create_index("ix_listing_approvals_brand_id", "listing_approvals", ["brand_id"])
    op.create_index("ix_lot_defects_brand_id", "lot_defects", ["brand_id"])
    op.create_index("ix_order_lines_brand_id", "order_lines", ["brand_id"])
    op.create_index("ix_order_events_brand_id", "order_events", ["brand_id"])
    op.create_index("ix_order_returns_brand_id", "order_returns", ["brand_id"])
    op.create_index("ix_shipments_brand_id", "shipments", ["brand_id"])
    op.create_index("ix_shipment_events_brand_id", "shipment_events", ["brand_id"])
    op.create_index("ix_disputes_brand_id", "disputes", ["brand_id"])
    op.create_index("ix_negotiations_lot_id", "negotiations", ["lot_id"])
    op.create_index("ix_negotiations_buyer_user_id", "negotiations", ["buyer_user_id"])
    op.create_index("ix_negotiations_brand_id", "negotiations", ["brand_id"])
    op.create_index(
        "ix_negotiation_messages_negotiation_id", "negotiation_messages", ["negotiation_id"]
    )
    op.create_index("ix_pools_lot_id", "pools", ["lot_id"])
    op.create_index("ix_redirections_brand_id", "redirections", ["brand_id"])
    op.create_index("ix_redirections_lot_id", "redirections", ["lot_id"])
    op.create_index("ix_lot_forecasts_brand_id", "lot_forecasts", ["brand_id"])
    op.create_index("ix_production_warnings_brand_id", "production_warnings", ["brand_id"])
    op.create_index("ix_review_cases_status", "review_cases", ["status"])


def downgrade() -> None:
    op.drop_index("ix_review_cases_status", table_name="review_cases")
    op.drop_index("ix_production_warnings_brand_id", table_name="production_warnings")
    op.drop_index("ix_lot_forecasts_brand_id", table_name="lot_forecasts")
    op.drop_index("ix_redirections_lot_id", table_name="redirections")
    op.drop_index("ix_redirections_brand_id", table_name="redirections")
    op.drop_index("ix_pools_lot_id", table_name="pools")
    op.drop_index("ix_negotiation_messages_brand_id", table_name="negotiation_messages")
    op.drop_index("ix_negotiation_messages_negotiation_id", table_name="negotiation_messages")
    op.drop_index("ix_negotiations_brand_id", table_name="negotiations")
    op.drop_index("ix_negotiations_buyer_user_id", table_name="negotiations")
    op.drop_index("ix_negotiations_lot_id", table_name="negotiations")
    op.drop_index("ix_disputes_brand_id", table_name="disputes")
    op.drop_index("ix_shipment_events_brand_id", table_name="shipment_events")
    op.drop_index("ix_shipments_brand_id", table_name="shipments")
    op.drop_index("ix_order_returns_brand_id", table_name="order_returns")
    op.drop_index("ix_order_events_brand_id", table_name="order_events")
    op.drop_index("ix_order_lines_brand_id", table_name="order_lines")
    op.drop_index("ix_lot_defects_brand_id", table_name="lot_defects")
    op.drop_index("ix_listing_approvals_brand_id", table_name="listing_approvals")
    op.drop_index("ix_lot_excluded_cities_brand_id", table_name="lot_excluded_cities")
    op.drop_index("ix_lot_photos_brand_id", table_name="lot_photos")
    op.drop_index("ix_manifest_lines_brand_id", table_name="manifest_lines")
    op.drop_index("ix_embeddings_brand_id", table_name="embeddings")
    op.drop_index("ix_payouts_run_id", table_name="payouts")
    op.drop_index("ix_ai_spend_brand_id", table_name="ai_spend")
    op.drop_index("ix_ai_outputs_job_id", table_name="ai_outputs")
    op.drop_index("ix_disputes_order_id", table_name="disputes")
    op.drop_index("ix_lots_category_id", table_name="lots")

"""Generate docs/database-schema.md from the SQLAlchemy metadata.

Written rather than drawn by hand so the diagram cannot drift from the code.
Re run it whenever the models change:

    python scripts/generate-erd.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from khazana.models import BRAND_SCOPED_TABLES, Base  # noqa: E402

PURPOSES = {
    "saved_searches": "A buyer's saved catalogue search.",
    "cart_items": "What a buyer intends to order, before checkout.",
    "order_events": "Append only history of every order status change.",
    "order_returns": "Returned pieces recorded against an order.",
    "payment_events": "Provider callbacks, stored once per event id.",
    "payout_runs": "A batch of brand payouts released together.",
    "couriers": "Delivery companies; one is the default.",
    "shipping_rates": "Configured delivery prices between city groups.",
    "shipment_events": "Tracking updates for a shipment.",
    "assistant_conversations": "A thread with the buyer or brand assistant.",
    "assistant_messages": "One message in a thread, with its cost and grounding.",
    "whatsapp_messages": "Every WhatsApp message in or out, idempotent by provider id.",
    "resale_benchmarks": "Resale value as a share of retail, for the profit helper.",
    "resell_kits": "The generated resell kit for a paid order.",
    "pools": "Committee pools: shops in one city buying one lot together.",
    "pool_members": "One member's sizes, delivery and resulting order.",
    "negotiations": "One buyer bargaining over one lot, with the floor kept server side.",
    "negotiation_messages": "Each round, with what the model proposed and whether it was clamped.",
    "season_events": "The season and event calendar that lifts demand.",
    "demand_forecasts": "Expected pieces per category, city and week.",
    "lot_forecasts": "How long a live lot will take to sell, and whether it is stuck.",
    "production_warnings": "A brand holding more of a category than the market buys.",
    "standard_sizes": "The platform's reference size chart.",
    "size_chart_rows": "A brand's own size chart in centimetres.",
    "partners": "Tailors, artisans, NGOs and recyclers who take unsellable stock.",
    "redirections": "A lot offered to a partner, and what happened.",
    "impact_factors": "Weight, water and carbon per piece for the impact report.",
    "review_cases": "Fraud and counterfeit flags for a person to decide.",
    "users": "One row per phone number. The identity anchor.",
    "otp_challenges": "Pending phone verifications, code stored hashed.",
    "sessions": "Refresh tokens, stored hashed.",
    "reseller_profiles": "Buyer side business profile and verification.",
    "brands": "The selling brand. The tenant boundary.",
    "brand_policies": "Commission, discount band, protection defaults, AI budget.",
    "brand_members": "Links users to brands. How tenancy is resolved.",
    "verification_documents": "NTN, incorporation certificate, CNIC, with a review trail.",
    "brand_excluded_cities": "Default region lock per brand.",
    "categories": "Two level taxonomy. The fixed list the AI must map into.",
    "lots": "A quantity of one product sold as a single unit.",
    "manifest_lines": "Size and colour breakdown. Must sum to total pieces.",
    "lot_defects": "Itemised defects, required for grade C.",
    "lot_photos": "Photographs, and the input to the AI listing feature.",
    "lot_excluded_cities": "Per lot region lock, overriding the brand default.",
    "listing_approvals": "Append only record of every approval decision.",
    "orders": "One purchase of one lot, whole or part.",
    "order_lines": "What was actually bought, by size and colour.",
    "payments": "Money in, and the escrow state machine.",
    "payouts": "Money out to a brand, one per order.",
    "alerts": "Operator alerts waiting to be emailed, one per kind per cooldown.",
    "invites": "Single use sign in links an admin sends by hand, in place of SMS codes.",
    "commission_invoices": "A brand's monthly bill for commission on orders it was paid for directly.",
    "shipments": "Courier consignments.",
    "disputes": "A buyer says the goods do not match the manifest.",
    "ai_jobs": "One row per unit of AI work, including blocked ones.",
    "ai_outputs": "What the model produced, what it cost, what the human changed.",
    "ai_spend": "Daily spend per feature and brand. Caps are enforced on it.",
    "ai_response_cache": "A validated AI reply kept so an identical request is not paid twice.",
    "embeddings": "Vectors for visual and semantic search.",
    "audit_log": "Append only before and after snapshots of consequential actions.",
}

TYPE_NAMES = (
    ("VARCHAR", "string"),
    ("DATETIME", "datetime"),
    ("INTEGER", "int"),
    ("NUMERIC", "decimal"),
    ("BOOLEAN", "bool"),
    ("DATE", "date"),
    ("JSON", "json"),
    ("TEXT", "text"),
)


def column_type(column: Any) -> str:
    text = str(column.type).upper()
    for long_name, short_name in TYPE_NAMES:
        if text.startswith(long_name):
            return short_name
    return text.lower().replace(" ", "_")


def mermaid() -> str:
    lines = ["erDiagram"]

    for table_name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[table_name]
        lines.append(f"    {table_name} {{")
        for column in table.columns:
            flags = []
            if column.primary_key:
                flags.append("PK")
            if column.foreign_keys:
                flags.append("FK")
            if not column.nullable and not column.primary_key:
                flags.append("required")
            suffix = f' "{", ".join(flags)}"' if flags else ""
            lines.append(f"        {column_type(column)} {column.name}{suffix}")
        lines.append("    }")

    seen: set[tuple[str, str, str]] = set()
    for table_name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[table_name]
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                target = foreign_key.column.table.name
                key = (target, table_name, column.name)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"    {target} ||--o{{ {table_name} : {column.name}")

    return "\n".join(lines)


def table_summary() -> str:
    rows = [
        "| Table | Columns | Brand scoped | Purpose |",
        "| --- | --- | --- | --- |",
    ]
    for name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[name]
        scoped = "yes" if name in BRAND_SCOPED_TABLES else "no"
        rows.append(
            f"| `{name}` | {len(table.columns)} | {scoped} | {PURPOSES.get(name, '')} |"
        )
    return "\n".join(rows)


HEADER = """# Database schema

Generated from the SQLAlchemy models by `scripts/generate-erd.py`. Do not edit
this file by hand: change the models in `apps/api/src/khazana/models/` and run
the script again, so the diagram cannot drift from the code.

PostgreSQL in every environment except the test suite, which runs on SQLite
for speed. The PostgreSQL only parts, meaning the deferred manifest trigger,
the append only triggers, the row level security policies and the pgvector
index, are created in migration 0001 and verified by the migration job in CI.

## Tables

TABLE_SUMMARY

## Design decisions worth knowing

**Tenancy is denormalised on purpose.** Every brand owned table carries a
`brand_id`, even where it could be reached through a join. One WHERE clause
isolates a tenant, the row level policies need no recursive joins, and the
isolation tests are cheap to write. A multi tenant leak is the one bug that
would end this business, so the schema pays a small normalisation price to
make it hard.

**The manifest rule is enforced three times.** The sum of `manifest_lines`
must equal `lots.total_pieces` once a lot leaves draft. It is checked in the
service layer so the brand gets a clear message, by a deferred constraint
trigger so a background job or a direct SQL fix cannot break it, and by a test
so neither of those can be removed quietly.

**A lot cannot be live without approval.** A CHECK constraint requires
`approved_at` to be set before the status can be live. The brand protection
promise is a database constraint, not a convention.

**Order arithmetic is constrained.** The subtotal, the total and the brand
payout each have a CHECK constraint tying them to the other columns, so no
code path can persist an order whose totals do not add up.

**Commission is snapshotted onto the order.** Reading it live from the brand
policy would mean that changing a rate silently rewrites the history of what
was owed on past orders.

**Money is integer rupees.** Never a float. Paisa are not used, because this
market prices these goods in whole rupees.

**Two tables are append only.** Listing approvals and the audit log have
triggers that reject UPDATE and DELETE. An audit trail that can be edited
proves nothing.

**AI outputs store the correction as well as the draft.** The pair is the
quality metric now and the training corpus later, and it costs nothing to
collect if the column exists from the start instead of being added in year two
when the data is already lost.

## Entity relationship diagram

```mermaid
MERMAID_DIAGRAM
```
"""


def main() -> int:
    out = ROOT / "docs" / "database-schema.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = HEADER.replace("TABLE_SUMMARY", table_summary()).replace(
        "MERMAID_DIAGRAM", mermaid()
    )
    out.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(Base.metadata.tables)} tables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

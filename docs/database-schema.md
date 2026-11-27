# Database schema

Generated from the SQLAlchemy models by `scripts/generate-erd.py`. Do not edit
this file by hand: change the models in `apps/api/src/khazana/models/` and run
the script again, so the diagram cannot drift from the code.

PostgreSQL in every environment except the test suite, which runs on SQLite
for speed. The PostgreSQL only parts, meaning the deferred manifest trigger,
the append only triggers, the row level security policies and the pgvector
index, are created in migration 0001 and verified by the migration job in CI.

## Tables

| Table | Columns | Brand scoped | Purpose |
| --- | --- | --- | --- |
| `ai_jobs` | 17 | no | One row per unit of AI work, including blocked ones. |
| `ai_outputs` | 19 | no | What the model produced, what it cost, what the human changed. |
| `ai_response_cache` | 8 | no | A validated AI reply kept so an identical request is not paid twice. |
| `ai_spend` | 8 | no | Daily spend per feature and brand. Caps are enforced on it. |
| `alerts` | 10 | no | Operator alerts waiting to be emailed, one per kind per cooldown. |
| `assistant_conversations` | 8 | no | A thread with the buyer or brand assistant. |
| `assistant_messages` | 12 | no | One message in a thread, with its cost and grounding. |
| `audit_log` | 15 | no | Append only before and after snapshots of consequential actions. |
| `brand_excluded_cities` | 6 | yes | Default region lock per brand. |
| `brand_members` | 6 | yes | Links users to brands. How tenancy is resolved. |
| `brand_policies` | 25 | yes | Commission, discount band, protection defaults, AI budget. |
| `brands` | 16 | no | The selling brand. The tenant boundary. |
| `cart_items` | 7 | no | What a buyer intends to order, before checkout. |
| `categories` | 8 | no | Two level taxonomy. The fixed list the AI must map into. |
| `commission_invoices` | 16 | yes | A brand's monthly bill for commission on orders it was paid for directly. |
| `couriers` | 7 | no | Delivery companies; one is the default. |
| `demand_forecasts` | 11 | no | Expected pieces per category, city and week. |
| `disputes` | 14 | yes | A buyer says the goods do not match the manifest. |
| `embeddings` | 10 | no | Vectors for visual and semantic search. |
| `impact_factors` | 8 | no | Weight, water and carbon per piece for the impact report. |
| `invites` | 15 | no | Single use sign in links an admin sends by hand, in place of SMS codes. |
| `listing_approvals` | 11 | yes | Append only record of every approval decision. |
| `lot_defects` | 8 | yes | Itemised defects, required for grade C. |
| `lot_excluded_cities` | 6 | yes | Per lot region lock, overriding the brand default. |
| `lot_forecasts` | 10 | yes | How long a live lot will take to sell, and whether it is stuck. |
| `lot_photos` | 18 | yes | Photographs, and the input to the AI listing feature. |
| `lots` | 30 | yes | A quantity of one product sold as a single unit. |
| `manifest_lines` | 8 | yes | Size and colour breakdown. Must sum to total pieces. |
| `negotiation_messages` | 10 | yes | Each round, with what the model proposed and whether it was clamped. |
| `negotiations` | 16 | yes | One buyer bargaining over one lot, with the floor kept server side. |
| `order_events` | 10 | yes | Append only history of every order status change. |
| `order_lines` | 9 | yes | What was actually bought, by size and colour. |
| `order_returns` | 8 | yes | Returned pieces recorded against an order. |
| `orders` | 30 | yes | One purchase of one lot, whole or part. |
| `otp_challenges` | 10 | no | Pending phone verifications, code stored hashed. |
| `partners` | 13 | no | Tailors, artisans, NGOs and recyclers who take unsellable stock. |
| `payment_events` | 8 | no | Provider callbacks, stored once per event id. |
| `payments` | 15 | no | Money in, and the escrow state machine. |
| `payout_runs` | 9 | no | A batch of brand payouts released together. |
| `payouts` | 13 | yes | Money out to a brand, one per order. |
| `pool_members` | 11 | no | One member's sizes, delivery and resulting order. |
| `pools` | 9 | no | Committee pools: shops in one city buying one lot together. |
| `production_warnings` | 10 | yes | A brand holding more of a category than the market buys. |
| `redirections` | 12 | yes | A lot offered to a partner, and what happened. |
| `resale_benchmarks` | 9 | no | Resale value as a share of retail, for the profit helper. |
| `resell_kits` | 7 | no | The generated resell kit for a paid order. |
| `reseller_profiles` | 14 | no | Buyer side business profile and verification. |
| `review_cases` | 13 | no | Fraud and counterfeit flags for a person to decide. |
| `saved_searches` | 7 | no | A buyer's saved catalogue search. |
| `season_events` | 10 | no | The season and event calendar that lifts demand. |
| `sessions` | 9 | no | Refresh tokens, stored hashed. |
| `shipment_events` | 9 | yes | Tracking updates for a shipment. |
| `shipments` | 15 | yes | Courier consignments. |
| `shipping_rates` | 10 | no | Configured delivery prices between city groups. |
| `size_chart_rows` | 12 | yes | A brand's own size chart in centimetres. |
| `standard_sizes` | 11 | no | The platform's reference size chart. |
| `users` | 16 | no | One row per phone number. The identity anchor. |
| `verification_documents` | 14 | yes | NTN, incorporation certificate, CNIC, with a review trail. |
| `whatsapp_messages` | 14 | no | Every WhatsApp message in or out, idempotent by provider id. |

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
erDiagram
    ai_jobs {
        string feature "required"
        string status "required"
        string mode "required"
        string entity_type
        string entity_id
        string brand_id "FK"
        string requested_by_user_id "FK"
        string blocked_reason
        datetime started_at
        datetime finished_at
        int attempts "required"
        text error
        string batch_id
        string prompt_ref
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    ai_outputs {
        string job_id "FK, required"
        string model "required"
        string prompt_name "required"
        int prompt_version "required"
        string effort
        int input_tokens "required"
        int output_tokens "required"
        int cache_read_tokens "required"
        int cache_write_tokens "required"
        decimal cost_usd "required"
        int latency_ms
        json output
        bool accepted
        json human_corrected
        string reviewed_by_user_id "FK"
        datetime reviewed_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    ai_response_cache {
        string key "PK"
        string feature "required"
        string model "required"
        json output "required"
        datetime expires_at "required"
        int hits "required"
        datetime created_at "required"
        datetime updated_at "required"
    }
    ai_spend {
        date day "required"
        string feature "required"
        string brand_id "FK"
        int calls "required"
        decimal cost_usd "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    alerts {
        string kind "required"
        string subject "required"
        text body "required"
        string status "required"
        int attempts "required"
        string last_error
        datetime delivered_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    assistant_conversations {
        string user_id "FK, required"
        string brand_id "FK"
        string channel "required"
        string title "required"
        datetime last_message_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    assistant_messages {
        string conversation_id "FK, required"
        string user_id "FK, required"
        string role "required"
        text body "required"
        string language
        json tools_used "required"
        bool grounded
        bool declined
        decimal cost_usd "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    audit_log {
        string actor_user_id "FK"
        string actor_role
        string actor_kind "required"
        string action "required"
        string entity_type "required"
        string entity_id
        string brand_id "FK"
        json before
        json after
        text note
        string ip
        string user_agent
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    brand_excluded_cities {
        string brand_id "FK, required"
        string city "required"
        string reason
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    brand_members {
        string brand_id "FK, required"
        string user_id "FK, required"
        string role_in_brand "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    brand_policies {
        string brand_id "FK, required"
        decimal commission_percent "required"
        int payout_terms_days "required"
        int dispute_window_days "required"
        int min_lot_value_pkr "required"
        decimal min_discount_percent "required"
        decimal max_discount_percent "required"
        string default_visibility "required"
        bool require_brand_approval "required"
        bool allow_cod "required"
        string settlement_mode "required"
        bool allow_part_lot_orders "required"
        bool allow_pooled_orders "required"
        bool allow_bargaining "required"
        decimal bargain_floor_percent
        decimal bargain_step_percent "required"
        bool allow_auto_markdown "required"
        decimal markdown_step_percent "required"
        int markdown_interval_days "required"
        decimal markdown_floor_percent
        bool auto_apply_ai_draft "required"
        decimal ai_monthly_budget_usd "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    brands {
        string name "required"
        string legal_name
        string slug "required"
        string ntn
        string city "required"
        string status "required"
        string unbranded_label
        string contact_phone
        string contact_email
        string reviewed_by_user_id "FK"
        datetime reviewed_at
        string review_note
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
        datetime deleted_at
    }
    cart_items {
        string user_id "FK, required"
        string lot_id "FK, required"
        bool whole_lot "required"
        json selection
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    categories {
        string parent_id "FK"
        string name "required"
        string slug "required"
        bool requires_expiry "required"
        int sort_order "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    commission_invoices {
        string brand_id "FK, required"
        string number "required"
        datetime period_start "required"
        datetime period_end "required"
        int order_count "required"
        int sales_pkr "required"
        int commission_pkr "required"
        string status "required"
        datetime issued_at "required"
        datetime due_at "required"
        datetime paid_at
        string paid_reference
        string recorded_by_user_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    couriers {
        string code "required"
        string name "required"
        bool is_active "required"
        bool is_default "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    demand_forecasts {
        string category_id "FK, required"
        string city "required"
        date week_start "required"
        decimal expected_pieces "required"
        decimal base_weekly_pieces "required"
        decimal factor "required"
        json events "required"
        datetime computed_at "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    disputes {
        string order_id "FK, required"
        string brand_id "FK, required"
        string raised_by_user_id "FK, required"
        string reason "required"
        text detail
        json evidence_keys
        string status "required"
        text resolution
        int refund_pkr
        string resolved_by_user_id "FK"
        datetime resolved_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    embeddings {
        string owner_type "required"
        string owner_id "required"
        string brand_id "FK"
        string lot_id "FK"
        string model "required"
        int dim "required"
        json vector "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    impact_factors {
        string keyword "required"
        decimal kg_per_piece "required"
        decimal water_litres_per_kg "required"
        decimal co2_kg_per_kg "required"
        string source "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    invites {
        string token_hash "required"
        string purpose "required"
        string phone "required"
        string full_name
        string role "required"
        string brand_id "FK"
        string note
        string created_by_user_id "FK"
        datetime expires_at "required"
        datetime used_at
        string used_by_user_id "FK"
        datetime revoked_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    listing_approvals {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string action "required"
        string actor_user_id "FK"
        string actor_role "required"
        string visibility_at_action "required"
        string note
        json snapshot
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    lot_defects {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string issue "required"
        int pieces_affected "required"
        string photo_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    lot_excluded_cities {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string city "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    lot_forecasts {
        string lot_id "FK, required"
        string brand_id "FK, required"
        decimal weekly_pieces "required"
        decimal weeks_to_clear
        bool at_risk "required"
        string reason "required"
        datetime computed_at "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    lot_photos {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string file_key "required"
        string kind "required"
        int sort_order "required"
        int width
        int height
        int bytes_stored
        bool is_optimised "required"
        string checksum
        string protection_status "required"
        string blurred_file_key
        json protection_detail
        datetime protection_reviewed_at
        string protection_reviewed_by_user_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    lots {
        string lot_code "required"
        string brand_id "FK, required"
        string category_id "FK, required"
        string title "required"
        text description
        string season
        string condition_grade "required"
        int total_pieces "required"
        int reserved_pieces "required"
        int retail_price_per_piece_pkr "required"
        int lot_price_pkr "required"
        int min_order_pieces "required"
        string stock_city "required"
        decimal weight_kg
        int cartons
        date expiry_date
        date available_until
        string status "required"
        bool bargaining_enabled
        bool auto_markdown_enabled
        datetime last_markdown_at
        string visibility "required"
        datetime approved_at
        string approved_by_user_id "FK"
        string created_by_user_id "FK"
        int version "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
        datetime deleted_at
    }
    manifest_lines {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string size "required"
        string color "required"
        int pieces "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    negotiation_messages {
        string negotiation_id "FK, required"
        string brand_id "FK, required"
        string role "required"
        text body "required"
        int offer_pkr
        int proposed_pkr
        bool clamped "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    negotiations {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string buyer_user_id "FK, required"
        string status "required"
        int pieces "required"
        int list_price_pkr "required"
        int floor_price_pkr "required"
        int step_pkr "required"
        int asking_price_pkr "required"
        int rounds "required"
        int agreed_price_pkr
        datetime agreed_until
        string order_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    order_events {
        string order_id "FK, required"
        string brand_id "FK, required"
        string from_status
        string to_status "required"
        string actor_user_id "FK"
        string actor_role "required"
        string note
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    order_lines {
        string order_id "FK, required"
        string brand_id "FK, required"
        string size "required"
        string color "required"
        int pieces "required"
        int unit_price_pkr "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    order_returns {
        string order_id "FK, required"
        string brand_id "FK, required"
        int pieces "required"
        string reason "required"
        string recorded_by_user_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    orders {
        string order_code "required"
        string lot_id "FK, required"
        string brand_id "FK, required"
        string buyer_user_id "FK, required"
        int pieces "required"
        int unit_price_pkr "required"
        int rounding_adjustment_pkr "required"
        int subtotal_pkr "required"
        int shipping_pkr "required"
        int total_pkr "required"
        decimal commission_percent "required"
        int commission_pkr "required"
        int brand_payout_pkr "required"
        string settlement_mode "required"
        int commission_due_pkr
        string commission_invoice_id "FK"
        string status "required"
        string payment_method "required"
        string delivery_city "required"
        string delivery_address "required"
        string delivery_phone "required"
        datetime dispute_window_ends_at
        datetime delivered_at
        datetime confirmed_at
        datetime cancelled_at
        string cancellation_reason
        int version "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    otp_challenges {
        string phone "required"
        string code_hash "required"
        string purpose "required"
        int attempts "required"
        datetime expires_at "required"
        datetime consumed_at
        string request_ip
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    partners {
        string name "required"
        string kind "required"
        string city "required"
        json categories "required"
        json grades "required"
        int min_pieces "required"
        int max_pieces
        string contact_name "required"
        string contact_phone "required"
        bool is_active "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    payment_events {
        string provider "required"
        string event_id "required"
        string payment_id "FK"
        string outcome "required"
        json payload "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    payments {
        string order_id "FK, required"
        string method "required"
        string status "required"
        int amount_pkr "required"
        int refunded_pkr "required"
        string provider
        string provider_reference
        datetime held_at
        datetime released_at
        datetime refunded_at
        string failure_reason
        json provider_payload
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    payout_runs {
        string created_by_user_id "FK"
        string status "required"
        int payout_count "required"
        int total_pkr "required"
        string reference
        datetime paid_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    payouts {
        string order_id "FK, required"
        string brand_id "FK, required"
        int amount_pkr "required"
        string status "required"
        datetime scheduled_for
        datetime paid_at
        string reference
        string note
        string approved_by_user_id "FK"
        string run_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    pool_members {
        string pool_id "FK, required"
        string user_id "FK, required"
        json requested "required"
        json allocated
        string delivery_address "required"
        string delivery_phone "required"
        string payment_method "required"
        string order_id "FK"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    pools {
        string lot_id "FK, required"
        string organiser_user_id "FK, required"
        string city "required"
        string status "required"
        datetime closes_at "required"
        datetime ordered_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    production_warnings {
        string brand_id "FK, required"
        string category_id "FK, required"
        int live_pieces "required"
        decimal weekly_demand "required"
        decimal weeks_of_demand
        string message "required"
        datetime computed_at "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    redirections {
        string lot_id "FK, required"
        string brand_id "FK, required"
        string partner_id "FK, required"
        string route "required"
        int pieces "required"
        int price_pkr "required"
        string status "required"
        string note "required"
        datetime collected_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    resale_benchmarks {
        string category_id "FK"
        string city
        decimal low_percent "required"
        decimal typical_percent "required"
        decimal high_percent "required"
        string note "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    resell_kits {
        string order_id "FK, required"
        string user_id "FK, required"
        int selling_price_pkr "required"
        json copy "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    reseller_profiles {
        string user_id "FK, required"
        string business_name "required"
        string city "required"
        string ntn
        string status "required"
        int monthly_purchase_pkr
        string shop_address
        string reviewed_by_user_id "FK"
        datetime reviewed_at
        string review_note
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
        datetime deleted_at
    }
    review_cases {
        string subject_type "required"
        string subject_id "required"
        string brand_id "FK"
        int score "required"
        json signals "required"
        string status "required"
        string decided_by_user_id "FK"
        text decision_note
        datetime decided_at
        datetime scored_at "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    saved_searches {
        string user_id "FK, required"
        string name "required"
        json filters "required"
        datetime last_run_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    season_events {
        string name "required"
        date starts_on "required"
        date ends_on "required"
        int lead_days "required"
        decimal demand_factor "required"
        json keywords "required"
        string note "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    sessions {
        string user_id "FK, required"
        string token_hash "required"
        datetime expires_at "required"
        datetime revoked_at
        string user_agent
        string ip
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    shipment_events {
        string shipment_id "FK, required"
        string brand_id "FK, required"
        string status "required"
        string location
        string note
        string provider_event_id
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    shipments {
        string order_id "FK, required"
        string brand_id "FK, required"
        string courier "required"
        string tracking_number
        string status "required"
        int cost_pkr
        int cartons
        decimal weight_kg
        string label_key
        datetime pickup_scheduled_for
        datetime picked_up_at
        datetime delivered_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    shipping_rates {
        string courier_id "FK, required"
        string origin_city
        string destination_city
        int base_pkr "required"
        int per_kg_pkr "required"
        int default_piece_grams "required"
        bool is_active "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    size_chart_rows {
        string brand_id "FK, required"
        string audience "required"
        string label "required"
        decimal chest_min_cm
        decimal chest_max_cm
        decimal waist_min_cm
        decimal waist_max_cm
        decimal hip_min_cm
        decimal hip_max_cm
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    standard_sizes {
        string audience "required"
        string label "required"
        decimal chest_min_cm
        decimal chest_max_cm
        decimal waist_min_cm
        decimal waist_max_cm
        decimal hip_min_cm
        decimal hip_max_cm
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    users {
        string phone "required"
        string email
        string full_name "required"
        string role "required"
        string password_hash
        bool is_active "required"
        datetime phone_verified_at
        datetime last_login_at
        string preferred_language "required"
        datetime tokens_valid_after
        string terms_version
        datetime terms_accepted_at
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
        datetime deleted_at
    }
    verification_documents {
        string brand_id "FK, required"
        string doc_type "required"
        string file_key "required"
        string original_filename
        string content_type
        int size_bytes
        string status "required"
        string uploaded_by_user_id "FK"
        string reviewed_by_user_id "FK"
        datetime reviewed_at
        string review_note
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    whatsapp_messages {
        string direction "required"
        string phone "required"
        text body "required"
        string provider "required"
        string provider_message_id "required"
        string user_id "FK"
        string conversation_id "FK"
        string media_key
        double transcript_confidence
        string transcript_language
        string status "required"
        string id "PK"
        datetime created_at "required"
        datetime updated_at "required"
    }
    brands ||--o{ ai_jobs : brand_id
    users ||--o{ ai_jobs : requested_by_user_id
    ai_jobs ||--o{ ai_outputs : job_id
    users ||--o{ ai_outputs : reviewed_by_user_id
    brands ||--o{ ai_spend : brand_id
    users ||--o{ assistant_conversations : user_id
    brands ||--o{ assistant_conversations : brand_id
    assistant_conversations ||--o{ assistant_messages : conversation_id
    users ||--o{ assistant_messages : user_id
    users ||--o{ audit_log : actor_user_id
    brands ||--o{ audit_log : brand_id
    brands ||--o{ brand_excluded_cities : brand_id
    brands ||--o{ brand_members : brand_id
    users ||--o{ brand_members : user_id
    brands ||--o{ brand_policies : brand_id
    users ||--o{ brands : reviewed_by_user_id
    users ||--o{ cart_items : user_id
    lots ||--o{ cart_items : lot_id
    categories ||--o{ categories : parent_id
    brands ||--o{ commission_invoices : brand_id
    users ||--o{ commission_invoices : recorded_by_user_id
    categories ||--o{ demand_forecasts : category_id
    orders ||--o{ disputes : order_id
    brands ||--o{ disputes : brand_id
    users ||--o{ disputes : raised_by_user_id
    users ||--o{ disputes : resolved_by_user_id
    brands ||--o{ embeddings : brand_id
    lots ||--o{ embeddings : lot_id
    brands ||--o{ invites : brand_id
    users ||--o{ invites : created_by_user_id
    users ||--o{ invites : used_by_user_id
    lots ||--o{ listing_approvals : lot_id
    brands ||--o{ listing_approvals : brand_id
    users ||--o{ listing_approvals : actor_user_id
    lots ||--o{ lot_defects : lot_id
    brands ||--o{ lot_defects : brand_id
    lot_photos ||--o{ lot_defects : photo_id
    lots ||--o{ lot_excluded_cities : lot_id
    brands ||--o{ lot_excluded_cities : brand_id
    lots ||--o{ lot_forecasts : lot_id
    brands ||--o{ lot_forecasts : brand_id
    lots ||--o{ lot_photos : lot_id
    brands ||--o{ lot_photos : brand_id
    users ||--o{ lot_photos : protection_reviewed_by_user_id
    brands ||--o{ lots : brand_id
    categories ||--o{ lots : category_id
    users ||--o{ lots : approved_by_user_id
    users ||--o{ lots : created_by_user_id
    lots ||--o{ manifest_lines : lot_id
    brands ||--o{ manifest_lines : brand_id
    negotiations ||--o{ negotiation_messages : negotiation_id
    brands ||--o{ negotiation_messages : brand_id
    lots ||--o{ negotiations : lot_id
    brands ||--o{ negotiations : brand_id
    users ||--o{ negotiations : buyer_user_id
    orders ||--o{ negotiations : order_id
    orders ||--o{ order_events : order_id
    brands ||--o{ order_events : brand_id
    users ||--o{ order_events : actor_user_id
    orders ||--o{ order_lines : order_id
    brands ||--o{ order_lines : brand_id
    orders ||--o{ order_returns : order_id
    brands ||--o{ order_returns : brand_id
    users ||--o{ order_returns : recorded_by_user_id
    lots ||--o{ orders : lot_id
    brands ||--o{ orders : brand_id
    users ||--o{ orders : buyer_user_id
    commission_invoices ||--o{ orders : commission_invoice_id
    payments ||--o{ payment_events : payment_id
    orders ||--o{ payments : order_id
    users ||--o{ payout_runs : created_by_user_id
    orders ||--o{ payouts : order_id
    brands ||--o{ payouts : brand_id
    users ||--o{ payouts : approved_by_user_id
    payout_runs ||--o{ payouts : run_id
    pools ||--o{ pool_members : pool_id
    users ||--o{ pool_members : user_id
    orders ||--o{ pool_members : order_id
    lots ||--o{ pools : lot_id
    users ||--o{ pools : organiser_user_id
    brands ||--o{ production_warnings : brand_id
    categories ||--o{ production_warnings : category_id
    lots ||--o{ redirections : lot_id
    brands ||--o{ redirections : brand_id
    partners ||--o{ redirections : partner_id
    categories ||--o{ resale_benchmarks : category_id
    orders ||--o{ resell_kits : order_id
    users ||--o{ resell_kits : user_id
    users ||--o{ reseller_profiles : user_id
    users ||--o{ reseller_profiles : reviewed_by_user_id
    brands ||--o{ review_cases : brand_id
    users ||--o{ review_cases : decided_by_user_id
    users ||--o{ saved_searches : user_id
    users ||--o{ sessions : user_id
    shipments ||--o{ shipment_events : shipment_id
    brands ||--o{ shipment_events : brand_id
    orders ||--o{ shipments : order_id
    brands ||--o{ shipments : brand_id
    couriers ||--o{ shipping_rates : courier_id
    brands ||--o{ size_chart_rows : brand_id
    brands ||--o{ verification_documents : brand_id
    users ||--o{ verification_documents : uploaded_by_user_id
    users ||--o{ verification_documents : reviewed_by_user_id
    users ||--o{ whatsapp_messages : user_id
    assistant_conversations ||--o{ whatsapp_messages : conversation_id
```

# API reference

Generated from the code by `scripts/generate-api-reference.py`; do not edit
by hand. The machine readable version is [`openapi.json`](openapi.json), and
a running API serves the same spec at `/openapi.json` with interactive docs
at `/docs`.

Version 1.0.0. 185 operations.

## Conventions

- **Authentication.** Send `Authorization: Bearer <access token>` on every
  operation marked *signed in*. Tokens come from `POST /auth/otp/verify` and
  last an hour; `POST /auth/refresh` exchanges the refresh token for a new
  pair. A refresh token works once.
- **Errors.** Every refusal is a 4XX with `{"code": ..., "message": ...}`.
  `message` is meant for a person; `code` is stable for code to branch on.
- **Money** is whole rupees as integers, in fields ending `_pkr`.
- **Times** are ISO 8601 in UTC.

## Contents

- [ops](#ops) (5)
- [auth](#auth) (10)
- [brands](#brands) (12)
- [catalog](#catalog) (29)
- [search](#search) (10)
- [orders](#orders) (13)
- [payments](#payments) (4)
- [commissions](#commissions) (6)
- [logistics](#logistics) (8)
- [pools](#pools) (6)
- [bargaining](#bargaining) (11)
- [resell-kits](#resell-kits) (3)
- [assistant](#assistant) (10)
- [ai](#ai) (6)
- [forecasts](#forecasts) (6)
- [redirections](#redirections) (7)
- [analytics](#analytics) (4)
- [resellers](#resellers) (3)
- [admin](#admin) (32)

## ops

Health, readiness and the AI gateway status. Open without sign in.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness, without touching the database | open |
| `GET` | `/ready` | Readiness, including a database check | open |
| `GET` | `/demo` | Whether this is a public demo, and its sample accounts | open |
| `GET` | `/features` | Which optional features this deployment has switched on | open |
| `GET` | `/ai/status` | AI mode, routed models, spend cap and feature switches | open |

### `GET /health`

`ops_health`

Liveness, without touching the database

Returns `200` with `HealthOut`.

### `GET /ready`

`ops_ready`

Readiness, including a database check

Returns `200`.

### `GET /demo`

`ops_demo`

The sample accounts the login page offers on a demo, one per role.

Empty unless DEMO_MODE is on, so a real deployment never lists accounts.

Returns `200` with `DemoOut`.

### `GET /features`

`ops_features`

Which optional features this deployment has switched on

Returns `200` with `FeaturesOut`.

### `GET /ai/status`

`ops_ai_status`

What the AI layer is doing right now.

Exposed from Phase 1 because a platform whose AI spend and kill
switches are invisible is a platform that will surprise you with an
invoice.

Returns `200`.

## auth

Sign in with a one time code, refresh a session, sign out everywhere.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/auth/otp/request` | Send a one time code to a mobile number | open |
| `POST` | `/auth/otp/verify` | Exchange a one time code for tokens | open |
| `POST` | `/auth/refresh` | Rotate a refresh token | open |
| `POST` | `/auth/logout` | Revoke every session for this user | signed in |
| `GET` | `/auth/me` | The signed in user and their brands | signed in |
| `POST` | `/admin/invites` | Create Invite | signed in |
| `GET` | `/admin/invites` | List Invites | signed in |
| `POST` | `/admin/invites/{invite_id}/revoke` | Revoke Invite | signed in |
| `GET` | `/auth/invites/{token}` | What an invite link is for, before it is used | open |
| `POST` | `/auth/invites/{token}/accept` | Use an invite link once, accepting the beta terms, and sign in | open |

### `POST /auth/otp/request`

`auth_otp_request`

Send a one time code to a mobile number

Request body: `OtpRequestIn`

Returns `200` with `OtpRequestOut`.

### `POST /auth/otp/verify`

`auth_otp_verify`

Exchange a one time code for tokens

Request body: `OtpVerifyIn`

Returns `200` with `TokenPair`.

### `POST /auth/refresh`

`auth_refresh`

Rotate a refresh token

Request body: `RefreshIn`

Returns `200` with `TokenPair`.

### `POST /auth/logout`

`auth_logout`

Revoke every session for this user, not only the current one.

Logging out of one device while a stolen token still works elsewhere is
not logging out.

Returns `204`.

### `GET /auth/me`

`auth_me`

The signed in user and their brands

Returns `200` with `MeOut`.

### `POST /admin/invites`

`admin_create_invite`

A single use link for one person, to send by hand. The link is in this
response only.

Request body: `InviteIn`

Returns `201` with `CreatedInviteOut`.

### `GET /admin/invites`

`admin_invites`

List Invites

Returns `200` with `list of InviteOut`.

### `POST /admin/invites/{invite_id}/revoke`

`admin_revoke_invite`

Revoke Invite

| Parameter | In | Required |
| --- | --- | --- |
| `invite_id` | path | yes |

Returns `200` with `InviteOut`.

### `GET /auth/invites/{token}`

`auth_invite_preview`

What an invite link is for, before it is used

| Parameter | In | Required |
| --- | --- | --- |
| `token` | path | yes |

Returns `200` with `InvitePreviewOut`.

### `POST /auth/invites/{token}/accept`

`auth_invite_accept`

Use an invite link once, accepting the beta terms, and sign in

| Parameter | In | Required |
| --- | --- | --- |
| `token` | path | yes |

Request body: `AcceptIn`

Returns `200` with `TokenPair`.

## brands

Brand profiles, staff, verification documents and policy.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/brands` | Register a brand | signed in |
| `GET` | `/brands/{brand_id}/dashboard` | Everything the brand portal home screen needs | signed in |
| `POST` | `/brands/{brand_id}/documents` | Upload a verification document | signed in |
| `POST` | `/brands/{brand_id}/request-verification` | Submit the brand for admin review | signed in |
| `PATCH` | `/brands/{brand_id}/profile` | Set the label buyers see on unbranded listings | signed in |
| `PATCH` | `/brands/{brand_id}/policy` | Change the brand's commercial terms | signed in |
| `PUT` | `/brands/{brand_id}/region-lock` | Replace the cities this brand excludes by default | signed in |
| `GET` | `/brands/admin/verification-queue` | Brands waiting for an admin decision | signed in |
| `POST` | `/brands/{brand_id}/review` | Approve or reject a brand | signed in |
| `POST` | `/brands/{brand_id}/suspend` | Suspend a brand and pause its live listings | signed in |
| `GET` | `/brands/{brand_id}/size-chart` | Size Chart | signed in |
| `PUT` | `/brands/{brand_id}/size-chart` | Replace Size Chart | signed in |

### `POST /brands`

`brands_register`

Create a brand, its policy row and the caller's membership.

The caller becomes a brand user, because otherwise they would register a
brand and immediately be unable to see it.

Request body: `BrandRegisterIn`

Returns `201` with `BrandOut`.

### `GET /brands/{brand_id}/dashboard`

`brands_dashboard`

Everything the brand portal home screen needs

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `DashboardOut`.

### `POST /brands/{brand_id}/documents`

`brands_upload_document`

Store one document. Replacing a document resets its review.

An admin who already approved the previous file has not seen the new one.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `Body_brands_upload_document`

Returns `201` with `khazana__api__routers__brands__DocumentOut`.

### `POST /brands/{brand_id}/request-verification`

`brands_request_verification`

Submit the brand for admin review

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `BrandOut`.

### `PATCH /brands/{brand_id}/profile`

`brands_update_profile`

Set the label buyers see on unbranded listings

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `BrandProfileIn`

Returns `200` with `BrandOut`.

### `PATCH /brands/{brand_id}/policy`

`brands_update_policy`

Commission, discount band, payout terms and lot minimum are all data.

Brand approval is not offered here. It is pinned true in the schema,
because the protection it gives is the reason a brand is willing to list.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `PolicyUpdateIn`

Returns `200` with `PolicyOut`.

### `PUT /brands/{brand_id}/region-lock`

`brands_set_region_lock`

Cities every new lot inherits as excluded. A lot can still override.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `khazana__api__routers__brands__RegionLockIn`

Returns `200`.

### `GET /brands/admin/verification-queue`

`brands_verification_queue`

Oldest first, because a brand waiting longest has waited longest.

Returns `200` with `list of BrandOut`.

### `POST /brands/{brand_id}/review`

`brands_review`

A rejection must carry a reason, so the brand can fix it.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `khazana__api__routers__brands__ReviewIn`

Returns `200` with `BrandOut`.

### `POST /brands/{brand_id}/suspend`

`brands_suspend`

Live listings are paused too, or a suspended brand keeps taking orders.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `SuspendIn`

Returns `200` with `BrandOut`.

### `GET /brands/{brand_id}/size-chart`

`brands_size_chart`

The brand's own chart, each row with the standard size it maps to.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `list of SizeRowOut`.

### `PUT /brands/{brand_id}/size-chart`

`brands_replace_size_chart`

Replace the whole chart, so it is always one consistent set.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `list of SizeRowIn`

Returns `200` with `list of SizeRowOut`.

## catalog

Lots: creating, photographs, manifests, approval and the buyer catalogue.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/lots` | Create Lot | signed in |
| `GET` | `/lots` | List Lots | signed in |
| `GET` | `/lots/queue` | Approval Queue | signed in |
| `GET` | `/lots/{lot_id}` | Get Lot | signed in |
| `PATCH` | `/lots/{lot_id}` | Update Lot | signed in |
| `GET` | `/lots/{lot_id}/readiness` | Lot Readiness | signed in |
| `PUT` | `/lots/{lot_id}/manifest` | Set Manifest | signed in |
| `POST` | `/lots/{lot_id}/manifest/import` | Import Manifest | signed in |
| `PUT` | `/lots/{lot_id}/defects` | Set Defects | signed in |
| `POST` | `/lots/{lot_id}/photos` | Add Photo | signed in |
| `PUT` | `/lots/{lot_id}/photos/order` | Reorder Photos | signed in |
| `DELETE` | `/lots/{lot_id}/photos/{photo_id}` | Remove Photo | signed in |
| `GET` | `/lots/{lot_id}/photos/{photo_id}/image` | Owner Photo Image | signed in |
| `POST` | `/lots/{lot_id}/photos/protection/scan` | Scan Photos | signed in |
| `PUT` | `/lots/{lot_id}/photos/{photo_id}/protection` | Review Photo Protection | signed in |
| `POST` | `/lots/{lot_id}/submit` | Submit Lot | signed in |
| `POST` | `/lots/{lot_id}/approve` | Approve Lot | signed in |
| `POST` | `/lots/{lot_id}/reject` | Reject Lot | signed in |
| `POST` | `/lots/{lot_id}/publish` | Publish Lot | signed in |
| `POST` | `/lots/{lot_id}/pause` | Pause Lot | signed in |
| `POST` | `/lots/{lot_id}/resume` | Resume Lot | signed in |
| `POST` | `/lots/{lot_id}/withdraw` | Withdraw Lot | signed in |
| `PUT` | `/lots/{lot_id}/visibility` | Set Visibility | signed in |
| `PUT` | `/lots/{lot_id}/region-lock` | Set Region Lock | signed in |
| `GET` | `/lots/{lot_id}/approvals` | Approval Trail | signed in |
| `GET` | `/catalog` | Browse Catalog | signed in |
| `GET` | `/catalog/{lot_id}` | Catalog Detail | signed in |
| `GET` | `/catalog/{lot_id}/profit` | Profit Estimate | signed in |
| `GET` | `/catalog/{lot_id}/photos/{photo_id}` | Catalog Photo Image | signed in |

### `POST /lots`

`lots_create`

Create a draft lot.

Starts in draft at the brand's default protection level. Nothing reaches a
buyer until it has been through approval.

Request body: `LotCreateIn`

Returns `201` with `LotDetailOut`.

### `GET /lots`

`lots_list`

The caller's own lots, newest first. An admin sees every brand's.

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |
| `search` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `LotListOut`.

### `GET /lots/queue`

`lots_approval_queue`

Lots awaiting approval, riskiest first.

The risk score orders the queue and decides nothing. See
`docs/ai-architecture.md` section 2.

Declared before `/lots/{lot_id}` so that "queue" is not read as an
identifier.

| Parameter | In | Required |
| --- | --- | --- |
| `limit` | query | no |

Returns `200` with `list of QueueItemOut`.

### `GET /lots/{lot_id}`

`lots_detail`

Get Lot

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `LotDetailOut`.

### `PATCH /lots/{lot_id}`

`lots_update`

Edit a lot.

A material change to an approved lot resets it to draft, because the brand
approved a specific payload. The response status tells the caller that
happened.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `LotUpdateIn`

Returns `200` with `LotDetailOut`.

### `GET /lots/{lot_id}/readiness`

`lots_readiness`

What still stands between this lot and a buyer seeing it.

A checklist rather than one error at a time, so the editor can show
progress while the brand works through it.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `ReadinessOut`.

### `PUT /lots/{lot_id}/manifest`

`lots_set_manifest`

Replace the manifest.

The whole table is sent, not a patch. A per row API would let a half
applied edit leave the sum wrong between requests, and the sum matching
the lot total is the rule buyers judge a manifest on.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `ManifestIn`

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/manifest/import`

`lots_import_manifest`

Read a brand spreadsheet into manifest rows, without saving them.

Returns a proposal. The brand reviews it and commits it with
PUT /manifest. Two endpoints rather than one because the extraction is an
AI suggestion and the manifest is a commitment to a buyer, and collapsing
them would make the model's reading of a spreadsheet binding.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `Body_lots_import_manifest`

Returns `200` with `ManifestImportOut`.

### `PUT /lots/{lot_id}/defects`

`lots_set_defects`

Replace the itemised defect list. Required for grade C.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `DefectsIn`

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/photos`

`lots_add_photo`

Upload one photograph.

The file is validated on its own bytes rather than its declared type, then
resized and recompressed. Only the processed version is stored.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `Body_lots_add_photo`

Returns `201` with `PhotoOut`.

### `PUT /lots/{lot_id}/photos/order`

`lots_reorder_photos`

Set the gallery order. The first photograph is the one buyers see.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `PhotoOrderIn`

Returns `200` with `list of PhotoOut`.

### `DELETE /lots/{lot_id}/photos/{photo_id}`

`lots_remove_photo`

Remove Photo

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |
| `photo_id` | path | yes |

Returns `204`.

### `GET /lots/{lot_id}/photos/{photo_id}/image`

`lots_photo_image`

A photograph for its owner, either as uploaded or as buyers would see it.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |
| `photo_id` | path | yes |
| `variant` | query | no |
| `size` | query | no |

Returns `200`.

### `POST /lots/{lot_id}/photos/protection/scan`

`lots_scan_photos_for_marks`

Look for brand marks on an unbranded lot. One paid model call per new photo.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `list of PhotoOut`.

### `PUT /lots/{lot_id}/photos/{photo_id}/protection`

`lots_review_photo_protection`

Accept a result, or choose exactly which areas buyers must not see.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |
| `photo_id` | path | yes |

Request body: `PhotoReviewIn`

Returns `200` with `PhotoOut`.

### `POST /lots/{lot_id}/submit`

`lots_submit`

Submit a draft for approval. Refused if the readiness checks fail.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/approve`

`lots_approve`

Approve a submitted lot, and by default put it live.

Writes an append only approval record holding the exact listing as
approved, so a later edit cannot change what the brand agreed to.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `ApproveIn`

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/reject`

`lots_reject`

Send a submitted lot back to draft with a reason.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `RejectIn`

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/publish`

`lots_publish`

Publish Lot

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/pause`

`lots_pause`

Take a live lot out of the catalogue, keeping its approval.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `NoteIn`

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/resume`

`lots_resume`

Resume Lot

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `LotDetailOut`.

### `POST /lots/{lot_id}/withdraw`

`lots_withdraw`

Pull a lot out of the catalogue for good. Not a delete.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `NoteIn`

Returns `200` with `LotDetailOut`.

### `PUT /lots/{lot_id}/visibility`

`lots_set_visibility`

Change the protection level. Allowed while the lot is live.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `VisibilityIn`

Returns `200` with `LotDetailOut`.

### `PUT /lots/{lot_id}/region-lock`

`lots_set_region_lock`

Replace this lot's excluded cities, overriding the brand default.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `khazana__api__routers__catalog__RegionLockIn`

Returns `200` with `LotDetailOut`.

### `GET /lots/{lot_id}/approvals`

`lots_approval_trail`

Every decision ever recorded against this lot, oldest first.

Append only, enforced by a database trigger, so this is what happened
rather than what the current state implies.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `list of ApprovalOut`.

### `GET /catalog`

`catalog_browse`

The buyer facing catalogue.

The only endpoint here that does not check ownership. It applies the
visibility rules instead: live and approved only, private lots for
verified resellers only, and the region lock against `city`.

`city` defaults to the reseller's own city and can be overridden, because
a reseller in Karachi legitimately buys for a shop in Multan. The region
lock applies to whichever city is being bought for, which is the thing the
brand is protecting.

| Parameter | In | Required |
| --- | --- | --- |
| `city` | query | no |
| `category_id` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `BrowseOut`.

### `GET /catalog/{lot_id}`

`catalog_detail`

One listing, under the same rules as the catalogue.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |
| `city` | query | no |

Returns `200` with `CatalogDetailOut`.

### `GET /catalog/{lot_id}/profit`

`catalog_profit_estimate`

What this lot could make if resold in the buyer's city.

An estimate from the real delivery quote and an administrator maintained
resale benchmark, with every assumption listed. It is not a promise.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |
| `city` | query | no |
| `pieces` | query | no |
| `selling_price_pkr` | query | no |

Returns `200` with `ProfitOut`.

### `GET /catalog/{lot_id}/photos/{photo_id}`

`catalog_photo_image`

A photograph as buyers may see it, and never the original of a protected one.

``size=thumb`` is a 400 pixel copy for catalogue cards.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |
| `photo_id` | path | yes |
| `city` | query | no |
| `size` | query | no |

Returns `200`.

## search

Catalogue search, saved searches, photo search and recommendations.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/catalog/categories` | Categories | signed in |
| `GET` | `/catalog/recommendations` | Recommendations | signed in |
| `POST` | `/catalog/mixed-lots` | Build Mixed Lot | signed in |
| `POST` | `/catalog/mixed-lots/cart` | Mixed Lot To Cart | signed in |
| `GET` | `/catalog/search` | Search Catalog | signed in |
| `POST` | `/catalog/search/photo` | Search Catalog By Photo | signed in |
| `GET` | `/catalog/saved-searches` | List Saved Searches | signed in |
| `POST` | `/catalog/saved-searches` | Save Search | signed in |
| `GET` | `/catalog/saved-searches/{saved_id}/results` | Run Saved Search | signed in |
| `DELETE` | `/catalog/saved-searches/{saved_id}` | Delete Saved Search | signed in |

### `GET /catalog/categories`

`catalog_categories`

Categories

Returns `200` with `list of CategoryOut`.

### `GET /catalog/recommendations`

`catalog_recommendations`

Lots this buyer is likely to want, each with the reasons it was chosen.

Ranked from the buyer's own orders, saved searches and city. Only lots the
buyer may open are considered.

| Parameter | In | Required |
| --- | --- | --- |
| `limit` | query | no |

Returns `200` with `list of RecommendationOut`.

### `POST /catalog/mixed-lots`

`catalog_build_mixed_lot`

Propose slow stock from several brands that fits a budget and piece count.

Each part is an ordinary part lot purchase from its own brand, priced by
the same rules as checkout. Nothing is reserved until checkout.

Request body: `MixedLotIn`

Returns `200` with `MixedLotOut`.

### `POST /catalog/mixed-lots/cart`

`catalog_mixed_lot_to_cart`

Build the proposal again from current stock and put every part in the cart.

Request body: `MixedLotIn`

Returns `200` with `MixedLotOut`.

### `GET /catalog/search`

`catalog_search`

Filter, sort and search the listings this viewer may see.

| Parameter | In | Required |
| --- | --- | --- |
| `q` | query | no |
| `mode` | query | no |
| `category_id` | query | no |
| `city` | query | no |
| `stock_city` | query | no |
| `grade` | query | no |
| `season` | query | no |
| `min_price_per_piece_pkr` | query | no |
| `max_price_per_piece_pkr` | query | no |
| `min_lot_price_pkr` | query | no |
| `max_lot_price_pkr` | query | no |
| `min_discount_percent` | query | no |
| `min_pieces` | query | no |
| `max_pieces` | query | no |
| `sort` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `khazana__api__routers__search__SearchOut`.

### `POST /catalog/search/photo`

`catalog_search_photo`

Find listings that look like a photograph. The image is not stored.

Off unless VISUAL_SEARCH_ENABLED, because a real image model is a paid
service. Switched off, it answers with no results and the reason.

| Parameter | In | Required |
| --- | --- | --- |
| `city` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Request body: `Body_catalog_search_photo`

Returns `200` with `khazana__api__routers__search__SearchOut`.

### `GET /catalog/saved-searches`

`catalog_saved_searches`

List Saved Searches

Returns `200` with `list of SavedSearchOut`.

### `POST /catalog/saved-searches`

`catalog_save_search`

Save Search

Request body: `SavedSearchIn`

Returns `201` with `SavedSearchOut`.

### `GET /catalog/saved-searches/{saved_id}/results`

`catalog_run_saved_search`

Run a saved search and mark its current matches as seen.

| Parameter | In | Required |
| --- | --- | --- |
| `saved_id` | path | yes |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `SavedSearchRunOut`.

### `DELETE /catalog/saved-searches/{saved_id}`

`catalog_remove_saved_search`

Delete Saved Search

| Parameter | In | Required |
| --- | --- | --- |
| `saved_id` | path | yes |

Returns `204`.

## orders

Cart, checkout, the order lifecycle, disputes and returns.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/cart` | View Cart | signed in |
| `PUT` | `/cart/items/{lot_id}` | Set Cart Item | signed in |
| `DELETE` | `/cart/items/{lot_id}` | Remove Cart Item | signed in |
| `POST` | `/cart/checkout` | Checkout | signed in |
| `POST` | `/orders/quote` | Quote Order | signed in |
| `POST` | `/orders` | Create Order | signed in |
| `GET` | `/orders` | List Orders | signed in |
| `GET` | `/orders/{order_id}` | Get Order | signed in |
| `POST` | `/orders/{order_id}/cancel` | Cancel Order | signed in |
| `POST` | `/orders/{order_id}/prepare` | Prepare Order | signed in |
| `POST` | `/orders/{order_id}/confirm` | Confirm Order | signed in |
| `POST` | `/orders/{order_id}/disputes` | Open Dispute | signed in |
| `POST` | `/orders/{order_id}/returns` | Record Return | signed in |

### `GET /cart`

`cart_view`

The cart, priced for a delivery city. Nothing is reserved yet.

| Parameter | In | Required |
| --- | --- | --- |
| `delivery_city` | query | no |

Returns `200` with `CartOut`.

### `PUT /cart/items/{lot_id}`

`cart_set_item`

Set Cart Item

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `CartItemIn`

Returns `200` with `CartItemOut`.

### `DELETE /cart/items/{lot_id}`

`cart_remove_item`

Remove Cart Item

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `204`.

### `POST /cart/checkout`

`cart_checkout`

Turn the cart into orders, one per lot, all of them or none.

Request body: `DeliveryIn`

Returns `201` with `list of OrderOut`.

### `POST /orders/quote`

`orders_quote`

What this purchase would cost, delivered. Reserves nothing.

Request body: `QuoteIn`

Returns `200` with `QuoteOut`.

### `POST /orders`

`orders_create`

Create Order

Request body: `khazana__api__routers__orders__OrderIn`

Returns `201` with `OrderDetailOut`.

### `GET /orders`

`orders_list`

A buyer's purchases, a brand's sales, or everything for an admin.

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `list of OrderOut`.

### `GET /orders/{order_id}`

`orders_detail`

Get Order

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `200` with `OrderDetailOut`.

### `POST /orders/{order_id}/cancel`

`orders_cancel`

Cancel Order

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `ReasonIn`

Returns `200` with `OrderDetailOut`.

### `POST /orders/{order_id}/prepare`

`orders_prepare`

The brand starts packing a paid order.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `200` with `OrderDetailOut`.

### `POST /orders/{order_id}/confirm`

`orders_confirm_delivery`

The buyer accepts the goods, which ends the dispute window early.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `200` with `OrderDetailOut`.

### `POST /orders/{order_id}/disputes`

`orders_open_dispute`

Open Dispute

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `DisputeIn`

Returns `201` with `OrderDetailOut`.

### `POST /orders/{order_id}/returns`

`orders_record_return`

Record Return

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `ReturnIn`

Returns `201` with `OrderDetailOut`.

## payments

Starting a payment, provider callbacks and brand payouts.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/orders/{order_id}/payment` | Start Payment | signed in |
| `POST` | `/orders/{order_id}/payment/sandbox-complete` | Complete Sandbox Payment | signed in |
| `POST` | `/orders/{order_id}/payment/bank-reference` | Submit Bank Reference | signed in |
| `POST` | `/payments/webhooks/{provider}` | Provider Callback | open |

### `POST /orders/{order_id}/payment`

`orders_start_payment`

Begin paying, or return the attempt already open.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `200` with `PaymentOut`.

### `POST /orders/{order_id}/payment/sandbox-complete`

`orders_complete_sandbox_payment`

Play the wallet's part in development. Refused in production.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `SandboxOutcomeIn`

Returns `200` with `PaymentOut`.

### `POST /orders/{order_id}/payment/bank-reference`

`orders_submit_bank_reference`

Submit Bank Reference

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `BankReferenceIn`

Returns `200` with `PaymentOut`.

### `POST /payments/webhooks/{provider}`

`payments_provider_callback`

Receive a provider event. A repeated event is accepted and ignored.

| Parameter | In | Required |
| --- | --- | --- |
| `provider` | path | yes |
| `x-sandbox-signature` | header | no |

Returns `200`.

## commissions

Monthly commission invoices for brands paid directly by cash on delivery.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/brands/{brand_id}/commission-invoices` | Brand Invoices | signed in |
| `GET` | `/brands/{brand_id}/commission-summary` | Brand Summary | signed in |
| `GET` | `/commission-invoices/{invoice_id}` | Get Invoice | signed in |
| `GET` | `/admin/commission-invoices` | Admin Invoices | signed in |
| `POST` | `/admin/commission-invoices/issue` | Issue | signed in |
| `POST` | `/admin/commission-invoices/{invoice_id}/paid` | Mark Paid | signed in |

### `GET /brands/{brand_id}/commission-invoices`

`brands_commission_invoices`

Brand Invoices

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `list of CommissionInvoiceOut`.

### `GET /brands/{brand_id}/commission-summary`

`brands_commission_summary`

Brand Summary

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `BrandCommissionSummaryOut`.

### `GET /commission-invoices/{invoice_id}`

`commission_invoices_detail`

Get Invoice

| Parameter | In | Required |
| --- | --- | --- |
| `invoice_id` | path | yes |

Returns `200` with `CommissionInvoiceDetailOut`.

### `GET /admin/commission-invoices`

`admin_commission_invoices`

Admin Invoices

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |

Returns `200` with `list of CommissionInvoiceOut`.

### `POST /admin/commission-invoices/issue`

`admin_issue_commission_invoices`

Issue a month's invoices now. The scheduler does this on the first of
each month for the month before; running it again issues nothing twice.

Request body: `IssueIn`

Returns `200` with `list of CommissionInvoiceOut`.

### `POST /admin/commission-invoices/{invoice_id}/paid`

`admin_commission_invoice_paid`

Mark Paid

| Parameter | In | Required |
| --- | --- | --- |
| `invoice_id` | path | yes |

Request body: `PaidIn`

Returns `200` with `CommissionInvoiceOut`.

## logistics

Shipments, pickups, labels, tracking and courier callbacks.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/orders/{order_id}/shipments` | Book Shipment | signed in |
| `POST` | `/orders/{order_id}/shipments/manual` | Enter Shipment | signed in |
| `POST` | `/shipments/{shipment_id}/manual-status` | Enter Outcome | signed in |
| `GET` | `/orders/{order_id}/tracking` | Order Tracking | signed in |
| `PUT` | `/shipments/{shipment_id}/pickup` | Schedule Pickup | signed in |
| `GET` | `/shipments/{shipment_id}/label` | Shipment Label | signed in |
| `POST` | `/shipments/{shipment_id}/sandbox-advance` | Sandbox Advance | signed in |
| `POST` | `/shipments/webhooks/{courier}` | Courier Callback | open |

### `POST /orders/{order_id}/shipments`

`orders_book_shipment`

Book Shipment

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `201` with `ShipmentOut`.

### `POST /orders/{order_id}/shipments/manual`

`orders_enter_shipment`

Cash on delivery to the brand: record the brand's own courier and
tracking number. The order becomes shipped.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `ManualShipmentIn`

Returns `201` with `ShipmentOut`.

### `POST /shipments/{shipment_id}/manual-status`

`shipments_enter_outcome`

Cash on delivery to the brand: what the courier reported. Delivered
starts the buyer's window to report a problem; returned cancels the order
and puts the pieces back on sale.

| Parameter | In | Required |
| --- | --- | --- |
| `shipment_id` | path | yes |

Request body: `ManualStatusIn`

Returns `200` with `ShipmentOut`.

### `GET /orders/{order_id}/tracking`

`orders_tracking`

Order Tracking

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `200` with `list of ShipmentOut`.

### `PUT /shipments/{shipment_id}/pickup`

`shipments_schedule_pickup`

Schedule Pickup

| Parameter | In | Required |
| --- | --- | --- |
| `shipment_id` | path | yes |

Request body: `PickupIn`

Returns `200` with `ShipmentOut`.

### `GET /shipments/{shipment_id}/label`

`shipments_label`

Shipment Label

| Parameter | In | Required |
| --- | --- | --- |
| `shipment_id` | path | yes |

Returns `200`.

### `POST /shipments/{shipment_id}/sandbox-advance`

`shipments_sandbox_advance`

Play the courier's next step in development. Refused in production.

| Parameter | In | Required |
| --- | --- | --- |
| `shipment_id` | path | yes |

Returns `200` with `ShipmentOut`.

### `POST /shipments/webhooks/{courier}`

`shipments_courier_callback`

Courier Callback

| Parameter | In | Required |
| --- | --- | --- |
| `courier` | path | yes |
| `x-sandbox-signature` | header | no |

Returns `200`.

## pools

Committee pools: several shops buying one lot together.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/pools` | Open Pools | signed in |
| `POST` | `/pools` | Open Pool | signed in |
| `GET` | `/pools/{pool_id}` | Pool Detail | signed in |
| `POST` | `/pools/{pool_id}/join` | Join Pool | signed in |
| `POST` | `/pools/{pool_id}/leave` | Leave Pool | signed in |
| `POST` | `/pools/{pool_id}/place` | Place Pool | signed in |

### `GET /pools`

`pools_open_in_my_city`

Open pools in the caller's own city, soonest closing first.

Returns `200` with `list of PoolOut`.

### `POST /pools`

`pools_open`

Start a pool on a lot, with the caller as its first member and organiser.

Request body: `OpenPoolIn`

Returns `201` with `PoolOut`.

### `GET /pools/{pool_id}`

`pools_detail`

Pool Detail

| Parameter | In | Required |
| --- | --- | --- |
| `pool_id` | path | yes |

Returns `200` with `PoolOut`.

### `POST /pools/{pool_id}/join`

`pools_join`

Join Pool

| Parameter | In | Required |
| --- | --- | --- |
| `pool_id` | path | yes |

Request body: `MembershipIn`

Returns `200` with `PoolOut`.

### `POST /pools/{pool_id}/leave`

`pools_leave`

Leave Pool

| Parameter | In | Required |
| --- | --- | --- |
| `pool_id` | path | yes |

Returns `200` with `PoolOut`.

### `POST /pools/{pool_id}/place`

`pools_place`

Create every member's order together. Organiser only.

| Parameter | In | Required |
| --- | --- | --- |
| `pool_id` | path | yes |

Returns `200` with `PlacedOut`.

## bargaining

Negotiating a price inside the brand's band, and the markdown agent.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/negotiations` | Start | signed in |
| `GET` | `/negotiations/{negotiation_id}` | Detail | signed in |
| `POST` | `/negotiations/{negotiation_id}/messages` | Reply | signed in |
| `POST` | `/negotiations/{negotiation_id}/accept` | Accept | signed in |
| `POST` | `/negotiations/{negotiation_id}/order` | Order | signed in |
| `GET` | `/brands/{brand_id}/negotiations` | Brand Negotiations | signed in |
| `PATCH` | `/lots/{lot_id}/agents` | Set Agents | signed in |
| `GET` | `/lots/{lot_id}/price-history` | Price History | signed in |
| `POST` | `/admin/jobs/markdowns` | Run Markdowns | signed in |
| `POST` | `/admin/jobs/markdowns/batch` | Submit Markdown Batch | signed in |
| `POST` | `/admin/jobs/markdowns/collect` | Collect Markdown Batch | signed in |

### `POST /negotiations`

`negotiations_start`

Start bargaining over a whole lot whose brand allows it.

Request body: `StartIn`

Returns `201` with `NegotiationOut`.

### `GET /negotiations/{negotiation_id}`

`negotiations_detail`

Detail

| Parameter | In | Required |
| --- | --- | --- |
| `negotiation_id` | path | yes |

Returns `200` with `NegotiationOut`.

### `POST /negotiations/{negotiation_id}/messages`

`negotiations_reply`

Reply

| Parameter | In | Required |
| --- | --- | --- |
| `negotiation_id` | path | yes |

Request body: `TurnIn`

Returns `200` with `NegotiationOut`.

### `POST /negotiations/{negotiation_id}/accept`

`negotiations_accept`

Take the current asking price. It is held for 48 hours.

| Parameter | In | Required |
| --- | --- | --- |
| `negotiation_id` | path | yes |

Returns `200` with `NegotiationOut`.

### `POST /negotiations/{negotiation_id}/order`

`negotiations_order`

Order the whole lot at the agreed price.

| Parameter | In | Required |
| --- | --- | --- |
| `negotiation_id` | path | yes |

Request body: `khazana__api__routers__negotiations__OrderIn`

Returns `200` with `NegotiationOut`.

### `GET /brands/{brand_id}/negotiations`

`brand_negotiations`

Every negotiation on this brand's lots, with each clamp the code applied.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `list of BrandNegotiationOut`.

### `PATCH /lots/{lot_id}/agents`

`lots_set_agents`

Turn the bargaining bot or the markdown agent on or off for one lot.

Only the fields sent are changed. Sending null returns that lot to the
brand's own setting.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `AgentsIn`

Returns `200` with `AgentsOut`.

### `GET /lots/{lot_id}/price-history`

`lots_price_history`

Every automatic markdown and agent switch on this lot, newest first.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `list of PriceMoveOut`.

### `POST /admin/jobs/markdowns`

`admin_run_markdowns`

Run the markdown agent now, live, at the full price.

For a decision someone wants to see straight away. The daily schedule
uses the batch endpoints below instead.

Returns `200` with `list of MarkdownRunOut`.

### `POST /admin/jobs/markdowns/batch`

`admin_submit_markdown_batch`

Send today's markdown decisions as one batch, at half the price.

Daily, from the scheduler. Returns nothing until the batch comes back,
except offline, where the batch answers at once.

Returns `200` with `list of MarkdownRunOut`.

### `POST /admin/jobs/markdowns/collect`

`admin_collect_markdown_batch`

Apply every markdown decision whose batch has ended. Every half hour.

Returns `200` with `list of MarkdownRunOut`.

## resell-kits

Captions, posts and price tags for a paid order.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/orders/{order_id}/resell-kit` | Generate Kit | signed in |
| `GET` | `/orders/{order_id}/resell-kit` | View Kit | signed in |
| `GET` | `/orders/{order_id}/resell-kit/photos/{photo_id}` | Kit Photo | signed in |

### `POST /orders/{order_id}/resell-kit`

`resell_kit_generate`

Write the kit for this order at the buyer's selling price, replacing any earlier one.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `KitIn`

Returns `200` with `KitOut`.

### `GET /orders/{order_id}/resell-kit`

`resell_kit_view`

The order's kit, or null when none has been made yet.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Returns `200`.

### `GET /orders/{order_id}/resell-kit/photos/{photo_id}`

`resell_kit_photo`

A photograph of the lot as buyers may see it, cropped square for posting.

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |
| `photo_id` | path | yes |

Returns `200`.

## assistant

The buyer and brand assistants, on the web and on WhatsApp.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/assistant/conversations` | List Conversations | signed in |
| `GET` | `/assistant/conversations/{conversation_id}` | Get Conversation | signed in |
| `GET` | `/assistant/usage` | Usage | signed in |
| `POST` | `/assistant/messages` | Send Message | signed in |
| `GET` | `/brands/{brand_id}/assistant/conversations` | Brand Conversations | signed in |
| `GET` | `/brands/{brand_id}/assistant/conversations/{conversation_id}` | Brand Conversation | signed in |
| `POST` | `/brands/{brand_id}/assistant/messages` | Brand Send Message | signed in |
| `POST` | `/whatsapp/webhooks/{provider}` | Whatsapp Inbound | open |
| `POST` | `/admin/whatsapp/sandbox/inbound` | Sandbox Inbound | signed in |
| `GET` | `/admin/whatsapp/messages` | Whatsapp Log | signed in |

### `GET /assistant/conversations`

`assistant_list_conversations`

The caller's own conversations, most recent first.

Returns `200` with `list of ConversationOut`.

### `GET /assistant/conversations/{conversation_id}`

`assistant_conversation_detail`

Get Conversation

| Parameter | In | Required |
| --- | --- | --- |
| `conversation_id` | path | yes |

Returns `200` with `ConversationDetailOut`.

### `GET /assistant/usage`

`assistant_usage`

How many assistant messages the caller has left today.

Returns `200` with `UsageOut`.

### `POST /assistant/messages`

`assistant_send_message`

Send a message and get the assistant's reply, in a new or existing thread.

Request body: `SendIn`

Returns `200` with `SendOut`.

### `GET /brands/{brand_id}/assistant/conversations`

`brand_assistant_conversations`

The caller's own threads with the assistant about this brand.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `list of ConversationOut`.

### `GET /brands/{brand_id}/assistant/conversations/{conversation_id}`

`brand_assistant_conversation_detail`

Brand Conversation

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |
| `conversation_id` | path | yes |

Returns `200` with `ConversationDetailOut`.

### `POST /brands/{brand_id}/assistant/messages`

`brand_assistant_send_message`

Ask about this brand's own stock and sales.

Every lookup is restricted to this brand by code. The assistant suggests
and never changes a price.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `BrandSendIn`

Returns `200` with `SendOut`.

### `POST /whatsapp/webhooks/{provider}`

`whatsapp_inbound`

Receive one WhatsApp message. The signature is the authentication.

A repeated delivery is accepted and not answered twice.

| Parameter | In | Required |
| --- | --- | --- |
| `provider` | path | yes |
| `x-sandbox-signature` | header | no |

Returns `200` with `InboundOut`.

### `POST /admin/whatsapp/sandbox/inbound`

`admin_whatsapp_sandbox_inbound`

Pretend to be a buyer messaging the WhatsApp number, for testing.

A voice transcript makes the message a voice note, with the given
confidence standing in for what a speech model would report.

Request body: `SandboxInboundIn`

Returns `200` with `SandboxInboundOut`.

### `GET /admin/whatsapp/messages`

`admin_whatsapp_messages`

The most recent WhatsApp traffic, both directions.

Returns `200` with `list of WhatsAppLogOut`.

## ai

The AI features a brand drives directly: listing drafts, manifests, pricing, risk.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `POST` | `/ai/listings/draft` | Draft a listing from photographs | signed in |
| `POST` | `/ai/manifests/extract` | Extract a manifest from a spreadsheet | signed in |
| `POST` | `/ai/lots/{lot_id}/price-suggestion` | Suggest a discount band for a lot | signed in |
| `GET` | `/ai/search` | Search lots by meaning rather than keywords | signed in |
| `POST` | `/ai/assistant/ask` | Ask the buyer assistant a question | signed in |
| `POST` | `/ai/lots/{lot_id}/risk-score` | Score a listing for review priority | signed in |

### `POST /ai/listings/draft`

`ai_listing_draft`

Produce a draft listing from photographs of one lot.

The result is always a draft. Title, description and category come back
for the brand to correct, and the piece count, price and manifest are
never touched by a model.

Request body: `Body_ai_listing_draft`

Returns `200` with `ListingDraftOut`.

### `POST /ai/manifests/extract`

`ai_manifest_extract`

Turn a brand spreadsheet into manifest lines.

Nothing is reconciled silently. When the rows do not sum to the total the
file states, the difference is reported and the lines come back exactly as
read, for a person to accept or reject.

Request body: `Body_ai_manifest_extract`

Returns `200` with `ManifestExtractOut`.

### `POST /ai/lots/{lot_id}/price-suggestion`

`ai_price_suggest`

Suggest a discount band, with the reasoning and the evidence behind it.

Always a band, never a single number, and always held inside the brand's
own policy band. When there are too few comparable sales the suggestion is
marked as rules based so the interface can label it honestly.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `PriceSuggestionOut`.

### `GET /ai/search`

`ai_search_lots`

Find lots by meaning.

Only live, approved, non private lots are searchable, and that filter is
inside the query rather than applied afterwards.

| Parameter | In | Required |
| --- | --- | --- |
| `q` | query | yes |
| `limit` | query | no |

Returns `200` with `khazana__api__routers__ai__SearchOut`.

### `POST /ai/assistant/ask`

`ai_assistant_ask`

Answer one buyer question in English, Urdu or Roman Urdu.

The reply is grounded: every factual claim comes from a database lookup
made during this request. When no lookup could answer the question, the
assistant says so rather than guessing, and ``grounded`` reports it.

Request body: `AssistantIn`

Returns `200` with `AssistantOut`.

### `POST /ai/lots/{lot_id}/risk-score`

`ai_risk_score`

Score one listing for how much human attention it needs.

Orders the review queue. It never approves or rejects anything, and the
structural checks are computed rather than judged, so a reassuring model
cannot talk a broken listing down the queue.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `RiskScoreOut`.

## forecasts

Demand forecasts and production warnings for a brand.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/brands/{brand_id}/forecast` | Brand Forecast | signed in |
| `GET` | `/admin/forecast/demand` | Demand | signed in |
| `POST` | `/admin/jobs/forecast` | Run Forecast | signed in |
| `GET` | `/admin/season-events` | Events | signed in |
| `POST` | `/admin/season-events` | Add Event | signed in |
| `PUT` | `/admin/season-events/{event_id}` | Edit Event | signed in |

### `GET /brands/{brand_id}/forecast`

`brand_forecast`

This brand's lots heading nowhere, its over production warnings, and the
seasons coming up. From the last scheduled run.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `BrandForecastOut`.

### `GET /admin/forecast/demand`

`admin_demand_forecast`

Expected pieces by category and week, for one city or the whole platform.

| Parameter | In | Required |
| --- | --- | --- |
| `city` | query | no |

Returns `200` with `list of DemandOut`.

### `POST /admin/jobs/forecast`

`admin_run_forecast`

Run the forecast now. In production a scheduler calls the same function.

Returns `200` with `khazana__api__routers__forecasts__RunOut`.

### `GET /admin/season-events`

`admin_events`

Events

Returns `200` with `list of EventOut`.

### `POST /admin/season-events`

`admin_add_event`

Add Event

Request body: `EventIn`

Returns `201` with `EventOut`.

### `PUT /admin/season-events/{event_id}`

`admin_edit_event`

Correct an event, for example once Eid's date is announced.

| Parameter | In | Required |
| --- | --- | --- |
| `event_id` | path | yes |

Request body: `EventIn`

Returns `200` with `EventOut`.

## redirections

Sending unsold stock to upcycling or donation partners.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/lots/{lot_id}/partner-matches` | Partner Matches | signed in |
| `POST` | `/lots/{lot_id}/redirections` | Offer | signed in |
| `GET` | `/brands/{brand_id}/redirections` | Brand Redirections | signed in |
| `GET` | `/admin/partners` | Partners | signed in |
| `POST` | `/admin/partners` | Add Partner | signed in |
| `GET` | `/admin/redirections` | All Redirections | signed in |
| `POST` | `/admin/redirections/{redirection_id}/status` | Set Status | signed in |

### `GET /lots/{lot_id}/partner-matches`

`lots_partner_matches`

Partners who could use this lot, best fit first, with the reasons.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Returns `200` with `list of MatchOut`.

### `POST /lots/{lot_id}/redirections`

`lots_offer_to_partner`

Offer the rest of this lot to a partner. Khazana Outlet arranges the handover.

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `ProposeIn`

Returns `201` with `RedirectionOut`.

### `GET /brands/{brand_id}/redirections`

`brand_redirections`

Brand Redirections

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Returns `200` with `list of RedirectionOut`.

### `GET /admin/partners`

`admin_partners`

Partners

Returns `200` with `list of PartnerOut`.

### `POST /admin/partners`

`admin_add_partner`

Add Partner

Request body: `PartnerIn`

Returns `201` with `PartnerOut`.

### `GET /admin/redirections`

`admin_redirections`

All Redirections

Returns `200` with `list of RedirectionOut`.

### `POST /admin/redirections/{redirection_id}/status`

`admin_redirection_status`

Record that a partner accepted, collected, or that the offer fell through.

| Parameter | In | Required |
| --- | --- | --- |
| `redirection_id` | path | yes |

Request body: `StatusIn`

Returns `200` with `RedirectionOut`.

## analytics

Brand and platform reports.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/brands/{brand_id}/analytics` | Brand Analytics | signed in |
| `GET` | `/brands/{brand_id}/impact` | Brand Impact | signed in |
| `GET` | `/admin/analytics` | Platform | signed in |
| `GET` | `/admin/ai-costs` | Ai Costs | signed in |

### `GET /brands/{brand_id}/analytics`

`brand_analytics`

What this brand sold, where, in which categories, at what price.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |
| `days` | query | no |

Returns `200`.

### `GET /brands/{brand_id}/impact`

`brand_impact`

Pieces kept from waste, and the weight, water and carbon that represents.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |
| `days` | query | no |

Returns `200`.

### `GET /admin/analytics`

`admin_analytics`

GMV, orders, commission, buyers and growth against the period before.

| Parameter | In | Required |
| --- | --- | --- |
| `days` | query | no |

Returns `200`.

### `GET /admin/ai-costs`

`admin_ai_costs`

AI spend per feature, and the AI cost per listing and per order.

| Parameter | In | Required |
| --- | --- | --- |
| `days` | query | no |

Returns `200`.

## resellers

Reseller profiles and verification.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/resellers/me` | My Profile | signed in |
| `PUT` | `/resellers/me` | Save Profile | signed in |
| `GET` | `/payouts` | Brand Payouts | signed in |

### `GET /resellers/me`

`resellers_my_profile`

My Profile

Returns `200`.

### `PUT /resellers/me`

`resellers_save_profile`

Save Profile

Request body: `ResellerProfileIn`

Returns `200` with `ResellerProfileOut`.

### `GET /payouts`

`payouts_for_brand`

Brand Payouts

Returns `200` with `list of PayoutOut`.

## admin

Moderation, payments, payouts, disputes, settings and scheduled jobs.

| Method | Path | Summary | Access |
| --- | --- | --- | --- |
| `GET` | `/admin/review-cases` | Cases | signed in |
| `POST` | `/admin/review-cases/{case_id}/decision` | Decide | signed in |
| `POST` | `/admin/jobs/risk` | Run | signed in |
| `GET` | `/admin/overview` | Overview | signed in |
| `GET` | `/admin/resellers` | Resellers | signed in |
| `POST` | `/admin/resellers/{profile_id}/review` | Review Reseller | signed in |
| `GET` | `/admin/brands` | Brands | signed in |
| `GET` | `/admin/documents/{document_id}` | Document File | signed in |
| `PATCH` | `/admin/brands/{brand_id}/terms` | Update Terms | signed in |
| `GET` | `/admin/listings` | Listings | signed in |
| `POST` | `/admin/listings/{lot_id}/take-down` | Take Down | signed in |
| `GET` | `/admin/payments` | Payments | signed in |
| `POST` | `/admin/payments/{payment_id}/confirm-transfer` | Confirm Transfer | signed in |
| `GET` | `/admin/reconciliation` | Reconciliation | signed in |
| `POST` | `/admin/orders/{order_id}/refund` | Refund Order | signed in |
| `POST` | `/admin/jobs/close-dispute-windows` | Close Dispute Windows | signed in |
| `POST` | `/admin/jobs/expire-pools` | Expire Pools | signed in |
| `POST` | `/admin/jobs/purge-ai-cache` | Purge Ai Cache | signed in |
| `GET` | `/admin/disputes` | Disputes | signed in |
| `POST` | `/admin/disputes/{dispute_id}/review` | Start Dispute Review | signed in |
| `POST` | `/admin/disputes/{dispute_id}/resolve` | Resolve Dispute | signed in |
| `GET` | `/admin/payouts` | Payouts | signed in |
| `GET` | `/admin/payout-runs` | Payout Runs | signed in |
| `POST` | `/admin/payout-runs` | Create Payout Run | signed in |
| `POST` | `/admin/payout-runs/{run_id}/paid` | Mark Run Paid | signed in |
| `GET` | `/admin/couriers` | Couriers | signed in |
| `PATCH` | `/admin/couriers/{courier_id}` | Update Courier | signed in |
| `POST` | `/admin/couriers/{courier_id}/rates` | Add Rate | signed in |
| `PATCH` | `/admin/shipping-rates/{rate_id}` | Update Rate | signed in |
| `GET` | `/admin/resale-benchmarks` | Resale Benchmarks | signed in |
| `PUT` | `/admin/resale-benchmarks` | Save Resale Benchmark | signed in |
| `GET` | `/admin/audit` | Audit Log | signed in |

### `GET /admin/review-cases`

`admin_review_cases`

Cases by status, highest score first.

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |

Returns `200` with `list of CaseOut`.

### `POST /admin/review-cases/{case_id}/decision`

`admin_review_decision`

Clear a case, or act on it with the action you choose. Always with a note.

| Parameter | In | Required |
| --- | --- | --- |
| `case_id` | path | yes |

Request body: `DecisionIn`

Returns `200` with `CaseOut`.

### `POST /admin/jobs/risk`

`admin_run_risk`

Score accounts, recent orders and live listings now.

Returns `200` with `khazana__api__routers__review__RunOut`.

### `GET /admin/overview`

`admin_overview`

Overview

Returns `200`.

### `GET /admin/resellers`

`admin_resellers`

Resellers

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |

Returns `200` with `list of ResellerReviewOut`.

### `POST /admin/resellers/{profile_id}/review`

`admin_review_reseller`

Review Reseller

| Parameter | In | Required |
| --- | --- | --- |
| `profile_id` | path | yes |

Request body: `khazana__api__routers__admin__ReviewIn`

Returns `200` with `ResellerReviewOut`.

### `GET /admin/brands`

`admin_brands`

Brands

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |
| `limit` | query | no |

Returns `200` with `list of AdminBrandOut`.

### `GET /admin/documents/{document_id}`

`admin_document_file`

Document File

| Parameter | In | Required |
| --- | --- | --- |
| `document_id` | path | yes |

Returns `200`.

### `PATCH /admin/brands/{brand_id}/terms`

`admin_update_brand_terms`

Change commission or payout terms. Existing orders keep their rate.

| Parameter | In | Required |
| --- | --- | --- |
| `brand_id` | path | yes |

Request body: `CommercialTermsIn`

Returns `200` with `AdminBrandOut`.

### `GET /admin/listings`

`admin_listings`

Listings with their risk score, highest first. The score decides nothing.

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |
| `search` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `list of ModerationItemOut`.

### `POST /admin/listings/{lot_id}/take-down`

`admin_take_down_listing`

Take Down

| Parameter | In | Required |
| --- | --- | --- |
| `lot_id` | path | yes |

Request body: `TakeDownIn`

Returns `200` with `LotOut`.

### `GET /admin/payments`

`admin_payments`

Payments

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |
| `method` | query | no |
| `limit` | query | no |

Returns `200` with `list of AdminPaymentOut`.

### `POST /admin/payments/{payment_id}/confirm-transfer`

`admin_confirm_bank_transfer`

Confirm Transfer

| Parameter | In | Required |
| --- | --- | --- |
| `payment_id` | path | yes |

Returns `200` with `AdminPaymentOut`.

### `GET /admin/reconciliation`

`admin_reconciliation`

Reconciliation

Returns `200` with `list of ReconciliationOut`.

### `POST /admin/orders/{order_id}/refund`

`admin_refund_order`

Refund Order

| Parameter | In | Required |
| --- | --- | --- |
| `order_id` | path | yes |

Request body: `RefundIn`

Returns `204`.

### `POST /admin/jobs/close-dispute-windows`

`admin_close_dispute_windows`

Confirm delivered orders whose dispute window has ended.

Returns `200`.

### `POST /admin/jobs/expire-pools`

`admin_expire_pools`

Close committee pools that passed their closing time without being placed.

Hourly, from the scheduler. Until this ran, an expired pool stayed open.

Returns `200`.

### `POST /admin/jobs/purge-ai-cache`

`admin_purge_ai_cache`

Delete expired entries from the AI response cache. Daily.

Returns `200`.

### `GET /admin/disputes`

`admin_disputes`

Disputes

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |

Returns `200` with `list of AdminDisputeOut`.

### `POST /admin/disputes/{dispute_id}/review`

`admin_start_dispute_review`

Start Dispute Review

| Parameter | In | Required |
| --- | --- | --- |
| `dispute_id` | path | yes |

Returns `200` with `AdminDisputeOut`.

### `POST /admin/disputes/{dispute_id}/resolve`

`admin_resolve_dispute`

Resolve Dispute

| Parameter | In | Required |
| --- | --- | --- |
| `dispute_id` | path | yes |

Request body: `ResolveDisputeIn`

Returns `200` with `AdminDisputeOut`.

### `GET /admin/payouts`

`admin_payouts`

Payouts

| Parameter | In | Required |
| --- | --- | --- |
| `status` | query | no |

Returns `200` with `list of PayoutOut`.

### `GET /admin/payout-runs`

`admin_payout_runs`

Payout Runs

Returns `200` with `list of PayoutRunOut`.

### `POST /admin/payout-runs`

`admin_create_payout_run`

Create Payout Run

Request body: `PayoutRunIn`

Returns `201` with `PayoutRunOut`.

### `POST /admin/payout-runs/{run_id}/paid`

`admin_mark_payout_run_paid`

Mark Run Paid

| Parameter | In | Required |
| --- | --- | --- |
| `run_id` | path | yes |

Request body: `PayoutRunPaidIn`

Returns `200` with `PayoutRunOut`.

### `GET /admin/couriers`

`admin_couriers`

Couriers

Returns `200` with `list of CourierOut`.

### `PATCH /admin/couriers/{courier_id}`

`admin_update_courier`

Update Courier

| Parameter | In | Required |
| --- | --- | --- |
| `courier_id` | path | yes |

Request body: `CourierUpdateIn`

Returns `200` with `CourierOut`.

### `POST /admin/couriers/{courier_id}/rates`

`admin_add_shipping_rate`

Add Rate

| Parameter | In | Required |
| --- | --- | --- |
| `courier_id` | path | yes |

Request body: `ShippingRateIn`

Returns `201` with `ShippingRateOut`.

### `PATCH /admin/shipping-rates/{rate_id}`

`admin_update_shipping_rate`

Update Rate

| Parameter | In | Required |
| --- | --- | --- |
| `rate_id` | path | yes |

Request body: `ShippingRateUpdateIn`

Returns `200` with `ShippingRateOut`.

### `GET /admin/resale-benchmarks`

`admin_resale_benchmarks`

The resale assumptions the profit helper shows buyers.

Returns `200` with `list of ResaleBenchmarkOut`.

### `PUT /admin/resale-benchmarks`

`admin_save_resale_benchmark`

Create or replace the benchmark for one category and city.

Request body: `ResaleBenchmarkIn`

Returns `200` with `ResaleBenchmarkOut`.

### `GET /admin/audit`

`admin_audit_log`

Audit Log

| Parameter | In | Required |
| --- | --- | --- |
| `action` | query | no |
| `entity_type` | query | no |
| `entity_id` | query | no |
| `brand_id` | query | no |
| `actor_user_id` | query | no |
| `limit` | query | no |
| `offset` | query | no |

Returns `200` with `list of AuditEntryOut`.

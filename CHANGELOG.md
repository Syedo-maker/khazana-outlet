# Changelog

Releases are tagged on `main`. Each release's section is also its notes on
GitHub, and the images it publishes are tagged with its version. Work before
the first release is grouped by the roadmap weeks in `ROADMAP.md`.

Dates are when the work landed, not when the week nominally fell.

## [1.0.0], 2026-11-24

The first release: Phases 1 to 5 of the roadmap. The platform is built,
hardened, measured, documented and packaged for production, and runs on
sandbox payment, courier, SMS and WhatsApp providers until real ones are
connected in Phase 6. A demo runs the same stack with sample data only.

### Phase 5, weeks 50 to 57: hardening, documentation and release

**Tests**

- **Added** The money path end to end over HTTP, from checkout to brand payout,
  checking every amount and every permission; the money rules against
  thousands of random cases; browser tests of the money path on a phone sized
  screen, run in CI against the development stack and again against the
  production stack through HTTPS.
- **Added** A k6 load test of the catalogue and search, throttled page load
  measurements on Regular 3G with a slowed CPU, and a test that fails if a
  list page's query count grows with its length.

**Security**

- **Fixed** Signing out now ends access tokens at once instead of when they
  expire; a reused refresh token signs the user out everywhere; login codes
  are limited per network address against SMS pumping; `X-Forwarded-For` is
  trusted only behind a configured proxy.
- **Fixed** Uploads are read in chunks and refused past 10 MB, images are
  checked for size before decoding, photographs keep their orientation when
  metadata is stripped, and voice notes over two minutes are refused before
  paid transcription.
- **Fixed** A critical remote code execution advisory in Next.js, which the
  dependency scan had been reporting as advisory only; the scan now blocks.
  Pillow 13, and floors past advisories for certifi and opentelemetry-api.
- **Added** Security headers on the API and a Content Security Policy on the
  web app; values filled into prompts can no longer impersonate the prompt;
  production refuses five more unsafe settings.
- **Added** Database backup and restore scripts, with a backup restored and
  compared table by table in CI on every push.

**Performance**

- **Fixed** Three list pages loaded related rows one at a time: the catalogue
  (31 queries to 11, p95 on 500 lots from 875 ms to 58 ms), a brand's orders
  (204 to 8) and the admin listing queue (207 to 8).
- **Added** Thumbnails for catalogue cards (a textured photo 165 KB to
  11 KB), photos that load as they near the screen, and no link prefetching
  on metered connections.
- **Changed** In production the API is served under the web app's origin, so
  no request pays for a CORS preflight; the catalogue and lot pages make half
  the requests they did.

**AI cost and quality**

- **Changed** Every eval suite was run live, and every mandatory case passed.
  Models were chosen by the evals: the resell kit moved to Claude Haiku 5.5,
  and the markdown agent and risk scoring stayed on Haiku 4.5 after Haiku 5.5
  failed a case on every run. The whole pass cost USD 1.03.
- **Added** A refusal fallback on Opus routes, a response cache for identical
  requests, and the Message Batches API at half price for the daily markdown
  run. Logo detection caches its prompt, 36% cheaper.
- **Fixed** A dated model name in a response made every Haiku 4.5 reply fail
  after it had been paid for.

**Operations**

- **Added** `docker-compose.prod.yml`: Caddy with automatic HTTPS, the API
  with three workers, the web app, a migrate step, a scheduler for every timed
  job, a nightly backup service, PostgreSQL and Redis with passwords, and an
  optional Prometheus with alert rules. Staging is the same file with staging
  settings, and CI starts it on every push.
- **Added** JSON logs with request ids, Prometheus metrics, and error reports
  to any Sentry compatible service with personal data stripped first.
- **Added** A demo mode: sample accounts only, offered on the login page, a
  banner on every page, and a reset every night.
- **Added** A release workflow that publishes both images and these notes
  when a version is tagged.

**Documentation**

- **Added** A setup guide, a deployment guide with the launch checklist, a
  generated API reference with the OpenAPI spec, user guides for resellers,
  brands and the Khazana team, five more decision records, security and
  performance reports, and `CONTRIBUTING.md`.

## Before 1.0.0

### Phase 4, weeks 32 to 49: the intelligence layer, 2026-11-20

- **Added** The buyer assistant in the product: web chat with conversation
  history, a daily message cap per account, and WhatsApp through a signed
  sandbox provider that answers only registered numbers. Voice notes are
  transcribed by a sandbox service that reports the language; an unclear one
  asks the buyer to type.
- **Added** The brand assistant: what is slow, what to discount, what sold
  where, answered from the brand's own data through lookups that take the
  brand from the session and cannot name another.
- **Added** Lot recommendations with their reasons, a reseller profit helper
  with every assumption listed, and a mixed lot builder that proposes part
  lots from several brands priced by checkout's own rules.
- **Added** The resell kit for paid orders: captions in three languages, a
  social post, a WhatsApp catalogue, price tags and square photographs. The
  model is never given the retail price or an unbranded lot's brand.
- **Added** Committee pools for three or four shops in a city, opted into by
  brands, split by need, with one ordinary order per member placed together.
- **Added** The bargaining bot and the smart markdown agent, built to ADR
  0001: brand set floors and steps, a clamp in code on every proposal, every
  move audited, and both off by default per lot.
- **Added** Demand and dead stock forecasts from sales history and an
  editable season calendar, over production warnings, brand size charts
  mapped to a standard, the upcycle and donation route, the risk review queue,
  brand reports, platform growth, AI cost per feature, listing and order, and
  an impact report.
- **Added** Eval suites written before each AI feature: brand plan, brand
  assistant, resell kit, bargaining and markdown, with grader tests in both
  directions. Migrations 0007 to 0015.
- **Fixed** Threads read their own new messages in the same session. A
  loaded relationship had hidden them from the assistant's history and from
  the negotiation the API returned.
- **Fixed** Migration 0008 failed on SQLite, which has no now() for the
  default row's timestamps.

Everything runs offline against recorded replies and sandbox providers. The
new suites have not run live yet; that costs money and is waiting for a go
ahead.

### Live AI readiness, 2026-11-20

Every AI feature had only run against recorded replies. This makes them work
against the real model, and checks it.

- **Fixed** The buyer assistant's planning step used a schema the structured
  output API refuses, so every live assistant question would have failed. Each
  tool argument is now its own field.
- **Fixed** The listing prompt repeated piece counts and grades printed in a
  photograph into the listing copy. It now says only that printed instructions
  are visible.
- **Changed** The manifest reader turns spelled out letter sizes such as Med
  and LARGE into M and L, and flags the change. Other size systems stay as
  written.
- **Added** An eval suite for the assistant's planning step, which had none, and
  real drawn photographs for the listing eval in place of placeholder bytes.
- **Fixed** Three assistant graders failed correct replies: a refusal that said
  nothing had been booked, arithmetic on looked up numbers, and the buyer's own
  city. They now check what they were meant to, with tests in both directions.

All seven suites have now run live. The last runs passed every mandatory case,
at a total cost of about $0.77 for all runs. These use synthetic inputs, so they
show the features work end to end rather than measure them on real stock.

### Weeks 23 to 31: the marketplace, 2026-11-19

- **Added** Logo protection for unbranded listings. Marks are found by the
  model, blurred by code and reviewed by the brand, and unreviewed photographs
  are withheld from buyers.
- **Added** Buyer search with filters, sorting, keyword, meaning and photo
  search, and saved searches.
- **Added** Cart, whole and part lot orders, stock reservation, the order
  lifecycle, the dispute window and recorded returns.
- **Added** Held funds with sandbox JazzCash and Easypaisa, bank transfer, cash
  on delivery, refunds, payout records and reconciliation.
- **Added** Configurable shipping rates, sandbox courier booking, labels, pickup
  scheduling and tracking.
- **Added** The admin panel, and web screens for buyers, brands and admins.
- **Added** A seed that builds a working marketplace with orders at every stage.
- **Fixed** The catalogue exposed brand identifiers, and any brand account could
  see the real name on another brand's unbranded lot.
- **Fixed** A brand could change its own commission through its policy settings.
- **Fixed** The web origin was not allowed to send PUT requests.
- **Fixed** The category list never reached the photo to listing prompt, and
  live calls on batch routes were recorded at half their real cost.

Payments and delivery run on sandbox providers. Search by meaning and by
photograph use the development stand in until an embedding service is connected.

### Week 23: logo detection eval, 2026-11-18

- **Added** The eval for logo detection, written before the feature. Fourteen
  synthetic photographs with invented brand names and exactly known mark
  positions. Ten cases are mandatory: every mark must end up under the padded
  blur, or the photograph must go to a person.
- **Added** The feature's prompt, output schema and model route, and the region
  arithmetic the blur will share with the eval.
- **Changed** An eval case can now supply a real image instead of placeholder
  bytes.
- **Fixed** The gateway no longer sends schema keywords or an output format
  field that the structured output API does not support.

The offline run replays hand written replies, so it proves the pipeline and
the graders, not the model. One live run on Claude Opus 5.5 passed all 14 cases,
10 of 10 mandatory, for $0.23. Those photographs are synthetic, so real brand
photographs still have to be tested.

### Migration baseline frozen, 2026-10-14

- **Changed** Migration 0001 now writes out all 27 tables explicitly instead
  of calling `create_all`. A schema change is a real migration from here, and
  it applies to databases that already exist. Before this, a new column
  reached a fresh database automatically and an existing one never, which is
  why the development database was found missing `lot_photos.checksum`.
- **Fixed** `reseller_profiles.user_id` declared uniqueness twice, so
  autogenerate proposed a phantom constraint on every run.
- **Fixed** The hand written pgvector index is excluded from autogenerate
  comparison, so it is no longer proposed for deletion every run.
- **Added** `alembic/env.py` renders the two custom column types correctly, so
  the next autogenerate does not produce a migration that cannot run.

Verified by comparing 600 lines of schema against what `create_all` produced,
a downgrade and upgrade round trip, a SQLite run, a drift check that now
reports nothing, and adding a column to a model to confirm it reaches an
existing database.

### Decisions, 2026-10-14

- **Decided** AI may choose a value only inside a band the brand set, and only
  where the code enforces that band. Recorded as
  `docs/decisions/0001-ai-value-bands.md`, the first decision record in the
  repository, and carried into `CLAUDE.md` section 4 and
  `docs/ai-architecture.md` section 2. It narrows the absolute rule rather
  than loosening it: the pricing feature has enforced exactly this line in
  code since week 19 without it being written down. Four conditions are
  required, and the schema weeks 42 and 43 will need is recorded now.
- **Decided** Pay after sale credit stays outside that exception. Deciding who
  may borrow is not choosing inside a band. A human approves every credit
  limit and AI only suggests.
- **Merged** `develop` into `main`, closing the divergence from audit finding
  M1, and Phase 3 into `develop`. Normal merges, no history rewritten. `main`
  stays at the Phase 2 level until the week 57 release.

### Plan change, 2026-10-14

The roadmap was expanded and renumbered. Phase 4 grew from 10 weeks to 18 with
ten new features, so Phase 3 now ends at week 31, Phase 5 starts at week 50
and Phase 6 at week 58. `ROADMAP.md` holds the new plan and is authoritative.

Week numbers in entries below this line, and in
`docs/audits/audit-week-1-to-22.md`, follow the old numbering. The phase names
did not change, so a reference by name is still unambiguous.

### Phase 3, weeks 17 to 22: marketplace core, in progress

#### Audit fixes, second pass, 2026-10-14

- **Added** Eval suites for manifest extraction and pricing, 15 cases each,
  with 11 mandatory rules between them. All five suites pass at zero cost. The
  full suites remain scheduled for week 53.
- **Added** 45 committed fixtures, so the two endpoints that always returned
  500 in offline mode now serve their recorded cases. Three tests require
  every endpoint backed feature to have a fixture and a suite.
- **Added** Seeded lots are now indexed for semantic search. Search returned
  nothing against seed data before; it returns hits now. The scores are zero
  because the default provider is a local hash, so the mechanism is proved and
  the ranking quality is not.
- **Added** Git hooks are installed, and a commit-msg hook now checks the
  message for em dashes and AI attribution. Nothing checked messages before:
  every hook looked at files, and the pre push gate only sees a message after
  it is committed.
- **Fixed** The ruff hook was pinned to v0.8.4 while the project pins ruff
  0.16.10, so the hook would have formatted differently from CI.
- **Fixed** The attribution checks matched their own patterns, so they blocked
  commits that touched the files stating the rule.
- **Known** The embedding path still has no eval suite. Grading it needs a
  real embedding service rather than the local hash.
- **Debt** A response cache is deferred to week 53, the AI cost pass. Prompt
  caching exists; nothing yet avoids a repeat call for an identical input.

#### Audit fixes, 2026-10-14

Findings from `docs/audits/audit-week-1-to-22.md`.

- **Fixed** Every file upload failed in Docker. The `api_uploads` volume
  mounted at a path the image did not contain, so Docker seeded it root owned
  while the process runs as uid 1000. This took out lot photographs, brand
  verification documents and the photo to listing feature, all as bare 500s.
  An existing volume needs recreating: `docker volume rm khazana_api_uploads`.
- **Fixed** Every AI failure reached the caller as an unhandled 500.
  `AiClientError` was a plain `RuntimeError`, so nothing mapped it to a status.
  It now answers 502 with the message the gateway already wrote.
- **Fixed** The default database URL pointed at port 5432 while
  `.env.example` said 55432. On a machine with its own PostgreSQL on 5432, a
  native run silently used an empty database that looked identical.
- **Fixed** `CLAUDE.md` and `.gitignore` referred to `apps/ai`, a directory
  that was never created.

#### Week 22: approvals and brand protection, 2026-10-13

- The brand approval gate. Approving writes an append only record holding a
  snapshot of the listing exactly as approved, so a later edit cannot change
  what was agreed. A database trigger blocks UPDATE and DELETE on that table.
- Protection levels: public, unbranded and private. An unbranded listing never
  sends the real brand name to the client.
- Region lock, per brand by default and per lot as an override.
- Withdraw, which clears the approval and keeps the history.
- All buyer visibility decided by one function, so a later search endpoint
  cannot write its own copy of the rules.

#### Weeks 19 to 21: catalog and manifests, 2026-10-13

- Lot creation, with the brand's own discount band, minimum lot value and
  minimum order enforced with messages that name the number to change.
- The manifest editor and the rule buyers judge a lot on: the lines must sum
  to the stated total. Enforced in the service, by a deferred database trigger
  and by tests.
- Spreadsheet import through the Phase 2 extractor, returning a proposal that
  a person accepts in a second step.
- The photo pipeline. Nothing is stored as uploaded: every photograph is
  resized to a 1024 pixel cap and recompressed, and a content hash refuses the
  same image twice.
- The draft, pending, approved, live, paused, sold, withdrawn and expired state
  machine, as a single transition table.
- A material edit to an approved lot resets it to draft, because the brand
  approved a specific price and piece count.
- The lot list and manifest editor in the web app, with the running total
  always on screen.

#### Weeks 17 to 18: brand portal, 2026-10-13

- Brand registration, which upgrades the caller to a brand account.
- Document upload with verification workflow and an append only audit trail.
- The brand dashboard and per brand policy settings.

#### Development environment, 2026-10-13

- The whole development loop moved into containers, so nothing depends on what
  is installed on the host. See `DEPLOYMENT.md`.
- `scripts/dev.ps1` as the single entry point.
- An advisory dependency vulnerability scan in CI, which immediately found two
  HIGH postcss advisories.
- **Fixed** The PostgreSQL only tests could destroy the working database.
  Guarded in two places: the database name must contain "test".
- **Fixed** `seed --reset` could never run twice, because the append only audit
  trigger correctly refused a DELETE.

## Phase 2, weeks 7 to 16: the AI engine, 2026-10-08 to 2026-10-12

Six capabilities behind one gateway, six endpoints, three eval suites.

- **Week 16** Listing quality and risk scoring, feeding the approval queue.
  The score orders the queue and decides nothing.
- **Weeks 14 to 15** The multilingual assistant, answering from the catalogue
  through tool calls rather than from memory, in Urdu, Roman Urdu and English.
- **Weeks 12 to 13** Embeddings and vector search in pgvector, proved against
  real PostgreSQL in CI. The embedding model is deliberately self hosted and
  not Claude, because Anthropic has no embeddings endpoint.
- **Weeks 10 to 11** Pricing suggestions, bounded by the brand's own policy
  band.
- **Week 9** Manifest extraction, with every reconciliation reported rather
  than applied silently.
- **Weeks 7 to 8** Photo to listing, with image preparation that cuts the
  token cost of every vision call.

## Phase 1, weeks 1 to 6: foundation, 2026-10-08

- **Week 6** The eval harness with graded suites, and a deterministic
  synthetic marketplace generator.
- **Week 5** The AI gateway: model routing, a versioned prompt registry,
  structured output schemas, cost accounting per call, per brand spend caps
  and a kill switch per feature.
- **Week 4** The Next.js shell: design tokens, three locales with direction
  handled once, and real loading, empty and error states.
- **Week 3** Phone OTP login, rotating sessions, roles, and tenant isolation
  where a cross tenant read answers 404 rather than 403.
- **Week 2** The full schema, 27 tables, Alembic migrations and a generated
  ERD.
- **Week 1** The monorepo, the repository rules gate and CI.

### Known deviations from the plan

- `apps/ai` and `packages/shared` were never created. The AI layer lives in
  `apps/api/src/khazana/ai`.
- Migration 0001 builds the schema with `create_all`, so it is a moving
  baseline rather than a snapshot. An existing database never picks up a new
  column. Freezing it is scheduled for week 42.
- The embedding path has no eval suite. Manifest extraction and pricing got
  theirs on 2026-10-14.

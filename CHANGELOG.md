# Changelog

Grouped by the roadmap weeks in `ROADMAP.md` rather than by release, because
nothing has been released yet. Versions begin at `v1.0.0` in week 48.

Dates are when the work landed, not when the week nominally fell. Several
weeks of planned work landed on the same day early on, and padding the dates
to match the plan would be a nicer looking lie.

## Unreleased

### Phase 3, weeks 17 to 22: marketplace core, in progress

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
- Three of the six AI features have no eval suite: manifest extraction,
  pricing and embeddings.

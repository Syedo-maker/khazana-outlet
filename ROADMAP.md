# Khazana Outlet: roadmap

AI native marketplace for Pakistani brand surplus stock. Build the platform
first, bring brands on at the end.

## The order, and why it is this way

The original plan validated the market first and treated AI as a feature to
add in year 2. This roadmap inverts both: the platform is built first, AI is
the architecture rather than a feature, and brand recruitment is the last
phase.

What that buys you: a complete, working, documented, AI native platform you
can demonstrate to anyone, including a brand, an examiner or an investor,
before you ask a single brand for stock.

What it costs you: you will build some things nobody asked for. Three rules
keep that cost low, and they are binding on every phase below.

1. **Policy is data, not code.** Commission rates, discount bands, protection
   rules, lot minimums, verification requirements and courier choice are all
   configurable per brand in the database. When a brand in Phase 6 wants
   something different, you change a row, not a module.
2. **Seed data instead of real data.** Phase 1 builds a realistic synthetic
   dataset: brands, lots, manifests, resellers, orders. Every later phase is
   developed and demonstrated against it, so nothing waits on a real brand.
3. **Every AI feature ships with an eval.** An AI feature with no eval is a
   demo, not a product. The eval is written before the feature.

## Phases at a glance

| Phase | Weeks | Name | Output |
| --- | --- | --- | --- |
| 1 | 1 to 6 | Foundation | Repository, schema, auth, UI shell, AI gateway, eval harness, seed data |
| 2 | 7 to 16 | AI engine | The six AI capabilities that make this platform different |
| 3 | 17 to 30 | Marketplace core | Catalog, search, orders, payments, logistics, admin |
| 4 | 31 to 40 | Intelligence layer | Assistant, demand prediction, fraud, analytics, brand agent |
| 5 | 41 to 48 | Hardening and release | Tests, security, performance, full documentation, deployment, v1.0.0 |
| 6 | 49 onward | Brands and launch | Brand recruitment, pilot sales, public launch |

48 weeks of computer work, then launch. Inside a 2 to 3 year window that
leaves real slack, which you will need.

## Default stack

| Layer | Choice | Reason |
| --- | --- | --- |
| Web | Next.js and Tailwind CSS | Server rendering helps on slow connections, large hiring pool |
| API | FastAPI (Python) | The AI layer is the core of this platform, and Python is where that work is easiest |
| Database | PostgreSQL with pgvector | Relational data plus vector search in one database, one thing to operate |
| Search | PostgreSQL full text first, Meilisearch when it is not enough | Do not add a second datastore in week 19 for a catalogue of 500 lots |
| Queue | Redis and RQ or Celery | AI jobs are slow, they belong in a queue, never in a web request |
| Images | Cloudflare R2 or S3 with a CDN, server side compression | Phone first audience |
| AI | Claude API, Anthropic Python SDK | See `docs/ai-architecture.md` |
| Image embeddings | Self hosted open model, SigLIP or CLIP class, vectors in pgvector | Anthropic has no embeddings endpoint, so this part is not Claude |
| Hosting | Vercel for web, a single VPS or DigitalOcean droplet for API and workers | Cheap, and enough until real traffic exists |

The one decision to confirm before Phase 1 week 1: API in Python with FastAPI
as above, or in TypeScript with NestJS to keep one language across the stack.
The roadmap assumes FastAPI because of the AI workload. Say if you want
NestJS instead and the plan adapts.

---

# Phase 1: Foundation (weeks 1 to 6)

**Status: complete.** 27 tables, 90 passing tests, CI with five jobs, the
AI gateway with cost accounting and spend caps, an eval harness, a seed
generator, and a Next.js shell that builds clean. See `README.md` for how
to run it and `docs/architecture.md` for what was built and what was
knowingly left out.

Goal: a repository where every later phase can be built without stopping to
make an architectural decision. Nothing user visible ships this phase, and
that is correct.

| Week | Work | Output |
| --- | --- | --- |
| 1 | Repository and tooling: monorepo layout `apps/web`, `apps/api`, `apps/ai`, `packages/shared`, `docs`. Git, branches, Conventional Commits, `.gitignore`, `.env.example`, linting, formatting, pre commit hooks, GitHub Actions CI running lint, type check and tests | A repository that refuses bad commits |
| 2 | Database schema, full, including every table the later phases need: users, roles, brands, brand policies, lots, manifest lines, defects, photos, listings, approvals, orders, order lines, payments, payouts, shipments, disputes, ai_jobs, ai_outputs, embeddings, audit_log. Migrations with Alembic. Mermaid ERD in `docs/database-schema.md` | Schema and ERD, reviewable before a single endpoint exists |
| 3 | Auth and roles: phone OTP, email, sessions, role based access for brand, reseller, admin. Row level access rules with tests proving no brand can read another brand's data | M1 complete, with the access control test suite |
| 4 | UI shell: design tokens, layout, navigation, form components, empty, loading and error states, mobile first at 360px, Urdu and English text direction handled in the component layer from the start | A component library, not screens |
| 5 | AI gateway: one service every AI call goes through. Model routing, prompt registry with versioned prompts, structured output schemas, retries, timeouts, token and cost logging per call, per brand spend caps, a cache layer, and a kill switch per feature | `apps/ai` skeleton, no features yet |
| 6 | Eval harness and seed data: a runnable eval per planned AI feature with a graded test set, plus a generator that creates realistic brands, lots, manifests, resellers and orders | `make seed` gives you a populated marketplace to develop against |

Week 5 is the week that decides whether this is really an AI platform or an
app with some AI bolted on. Details in `docs/ai-architecture.md`.

Phase 1 exit: CI green, schema migrated, seed data loads, a protected page
renders behind login, an AI call can be made end to end and its cost appears
in the log.

---

# Phase 2: AI engine (weeks 7 to 16)

Goal: build the intelligence before the marketplace, because the marketplace
modules in Phase 3 are written to consume it rather than to have it inserted
later.

Each capability follows the same four steps: write the eval, build it behind
the gateway, measure cost per call, then expose it as an API endpoint.

| Weeks | Capability | What it does | Notes |
| --- | --- | --- | --- |
| 7 to 8 | Photo to listing | One or more product photos in, a complete draft listing out: title, description, category, subcategory, colour, material, apparent condition, suggested tags | Vision plus a strict output schema. The single highest value feature in the platform, because it removes the work brands hate most |
| 9 | Manifest extraction and repair | A messy brand Excel or CSV in, clean manifest lines out, with the size and colour breakdown reconciled against the stated total and every change flagged for human review | Batch processed, never a blocking request |
| 10 to 11 | Pricing engine | Suggests a discount band and an expected days to sell, from category, age, season, condition, original price and comparable past sales | Rules plus model at first. It cannot learn from your own data until Phase 6 produces sales, and the roadmap says so honestly |
| 12 to 13 | Visual and semantic search | Image and text embeddings in pgvector, so a buyer can search by photo or by a sentence instead of by filters | Self hosted embedding model, not Claude. This is the part people wrongly assume is free |
| 14 to 15 | Multilingual assistant core | Understands Urdu, Roman Urdu and English, and answers from the catalogue using tools rather than from memory | Tool calling against real catalogue functions. No tool, no answer, so it cannot invent stock that does not exist |
| 16 | Listing quality and risk scoring | Scores a draft listing for completeness, manifest consistency, photo quality, counterfeit signals and price plausibility, and routes anything doubtful to admin review | Feeds the Phase 3 approval queue |

Phase 2 exit: every capability has a passing eval, a measured cost per call,
a documented prompt version and a working endpoint, all demonstrable against
seed data.

---

# Phase 3: Marketplace core (weeks 17 to 30)

Goal: the marketplace, built on top of the AI engine. Every module below
calls Phase 2 rather than duplicating it.

| Weeks | Module | Scope |
| --- | --- | --- |
| 17 to 18 | M2 Brand portal | Registration, NTN and document upload, verification workflow, brand dashboard, per brand policy settings |
| 19 to 21 | M3 Catalog and manifests | Lot creation driven by photo upload, the manifest editor with the sum must match total rule, bulk upload through the Phase 2 extractor, photo pipeline with compression and ordering, condition grading, draft, pending, approved and live states |
| 22 | Approvals and protection | The brand approval gate with a full audit record, private listings, unbranded listings, region lock, withdraw |
| 23 to 24 | M4 Search and discovery | Filters, sort, text search, semantic search and photo search wired to Phase 2, saved searches |
| 25 to 26 | M5 Cart and orders | Lot and part lot ordering, minimum order value, order lifecycle, buyer confirmation, dispute window, returns recorded |
| 27 | M6 Payments | Bank transfer, JazzCash, Easypaisa, COD, held funds and brand payout records. Integration kept behind one interface so a sandbox implementation works until merchant accounts exist |
| 28 | M7 Logistics | One courier integration behind a provider interface, label and tracking, shipping cost rules, pickup scheduling |
| 29 to 30 | M8 Admin panel | Verification queue, listing moderation with the Phase 2 risk score shown, orders, disputes, commission settings, payout runs, audit log viewer |

Two deliberate constraints in this phase. Payments and logistics sit behind
interfaces with sandbox implementations, so no week is blocked waiting for a
merchant account or a courier contract, both of which depend on the company
existing. And the money path is boring on purpose: see the non negotiables in
`docs/ai-architecture.md`.

Phase 3 exit: a reseller can find a lot by photo, order it, pay in sandbox,
track it and confirm delivery, and an admin can see all of it, all against
seed data.

---

# Phase 4: Intelligence layer (weeks 31 to 40)

Goal: the features that make the platform feel like it is run by software
rather than by a person with a spreadsheet.

| Weeks | Feature | What it does |
| --- | --- | --- |
| 31 to 32 | Buyer assistant in the product | The Phase 2 assistant exposed in the web UI and on WhatsApp, with conversation history, catalogue tools, and an explicit refusal to quote a price or stock level it has not read from the database |
| 33 to 34 | Brand assistant | A brand can ask which of my stock is slow, what should I discount, what sold in Karachi last month, answered from that brand's own data only, with the access boundary tested |
| 35 | Recommendations | Lot recommendations for resellers from purchase history and embeddings |
| 36 | Reseller profit helper | Estimates resale value and margin for a lot in the buyer's own city |
| 37 to 38 | Demand and dead stock prediction | Scheduled batch jobs over sales history that predict what will sell where, flag lots heading nowhere, and give brands an over production warning |
| 39 | Fraud and counterfeit detection | Risk scoring for accounts, listings and orders, with human review for anything consequential |
| 40 | M10 Analytics | Brand reporting on what sold, where and at what price, admin reporting on GMV, users and growth, plus an AI cost dashboard per feature |

Phase 4 exit: every AI surface is behind an eval and a cost budget, and the
AI cost dashboard shows what the platform spends per listing and per order.

---

# Phase 5: Hardening, documentation and release (weeks 41 to 48)

Goal: stop building and make it real. Most student and solo projects skip
this phase and it is the one that separates a demo from a platform.

| Weeks | Work |
| --- | --- |
| 41 | Test coverage pass: unit, integration and end to end on the money path and the access boundaries. Load test the catalogue and search |
| 42 | Security pass: authentication and session handling, rate limits, file upload validation, prompt injection defences on every user text that reaches a model, secret handling, dependency audit, backup and tested restore |
| 43 | Performance pass on a throttled 3G profile and a mid range Android device. Image sizes, bundle size, query plans, N plus 1 queries, cache hit rates |
| 44 | AI cost and quality pass: re run every eval, tune model choice and effort per feature, verify prompt caching is actually being hit, move everything that can wait to the Batch API |
| 45 to 46 | Documentation, written to match the code as it is: `README.md`, `docs/architecture.md`, `docs/database-schema.md`, `docs/api-reference.md` with an OpenAPI spec, `docs/ai-features.md` with prompts, models, costs, limits and eval results, `docs/setup-guide.md`, `docs/deployment.md`, `docs/user-guides/` for brand, reseller and admin, `docs/decisions/` for the architecture decision records, `CHANGELOG.md`, `CONTRIBUTING.md` |
| 47 | Deployment: production environment, domain, HTTPS, monitoring, error tracking, log aggregation, database backups, a staging environment that mirrors production |
| 48 | Release `v1.0.0`, tagged, with a seeded public demo, a recorded walkthrough, and a demo mode that shows the platform working without exposing real brand data |

Phase 5 exit: someone who has never seen the project can clone it, follow
`docs/setup-guide.md`, and have it running locally in under 30 minutes.

---

# Phase 6: Brands and launch (weeks 49 onward)

Goal: now put real brands and real buyers on a platform that already works.

The complete kit for this phase already exists in
[phase-6-brands-and-launch/](phase-6-brands-and-launch/): brand target list
and contact sourcing, outreach templates, brand and reseller interview
guides, category scoring, business model and unit economics, company
registration and trademark checklists, the manual sales playbook, and the
waiting list landing page in [landing/](landing/).

One thing changes now that the platform exists before the conversation. You
are no longer asking a brand to imagine something. You open the laptop, show
a working platform with the brand's own name hidden, a real manifest, a real
approval gate and a real audit trail, and ask for one lot. That is a far
stronger conversation than the one in the original plan, and it is the main
benefit of this build first order.

| Weeks | Work |
| --- | --- |
| 49 to 50 | Register the company, NTN, bank account, merchant account applications, publish the landing page |
| 51 to 52 | Brand outreach, demonstrate the live platform, target 10 brands committed in writing |
| 53 to 54 | Reseller recruitment, target 100 on the waiting list, verification of the first 20 |
| 55 to 56 | Pilot: the first real lots listed by real brands, the first real orders, swap the payment and courier sandbox implementations for live credentials |
| 57 to 60 | Fix what the pilot breaks, then public launch |

Phase 6 exit: real brands, real buyers, real money, and the pricing and demand
models finally training on your own data instead of on rules.

---

## What is deliberately not in this roadmap

Named so they do not creep in:

- A mobile app. The web app is mobile first. Build the app when web traffic
  justifies it, which is after Phase 6.
- A B2C storefront. B2B first, as in the original plan.
- Your own warehouse or logistics operation.
- International brands, import and customs. That was Phase 4 of the original
  plan and it still belongs after a domestic track record.
- Training your own models from scratch. You will not have enough data until
  well after launch, and the honest version is in `docs/ai-architecture.md`.

## Where the plan can fail, and the honest warnings

| Risk | Why it matters here | Mitigation in the plan |
| --- | --- | --- |
| Building for a year with no user feedback | The biggest risk of this order | Seed data plus demo mode, and policy as configuration so Phase 6 findings do not force a rebuild |
| AI cost at scale | Vision calls on every photo add up fast | Model routing, prompt caching, the Batch API at half price, per brand spend caps, all built in Phase 1 week 5 |
| AI that is impressive and wrong | A confident wrong price or a hallucinated stock level destroys trust faster than a missing feature | Evals before features, tool grounded answers, and humans on every consequential decision |
| Scope creep across 48 weeks | Solo projects die here | The not in this roadmap list above, and a phase exit gate that must pass before the next phase starts |
| Brands say no in Phase 6 | The platform exists but has no supply | The Phase 6 kit tests this properly, and the fallback, buying lots outright and reselling, is recorded in `phase-6-brands-and-launch/week-08-mvp-scope/go-no-go-review.md` |

## How to work this plan

At the start of each phase, ask for that phase to be broken into weekly tasks
with code, tests, documentation and commits. At the end of each phase, the
exit criteria are checked before the next phase starts. Nothing in a later
phase begins while an earlier phase's exit gate is open.

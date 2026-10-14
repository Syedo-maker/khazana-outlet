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
| 3 | 17 to 31 | Marketplace core | Brand portal, catalog, approvals, search, orders, payments, logistics, admin |
| 4 | 32 to 49 | Intelligence layer | Assistants, voice ordering, pooling, negotiation, markdown, prediction, analytics |
| 5 | 50 to 57 | Hardening and release | Tests, security, performance, AI cost, full documentation, deployment, v1.0.0 |
| 6 | 58 onward | Brands and launch | Brand recruitment, pilot sales, public launch |
| Later | After launch | Pay after sale credit | Gated on legal advice, see the end of this file |

57 weeks of computer work, then launch. Inside a 2 to 3 year window that
leaves real slack, which you will need.

This plan was expanded on 2026-10-14. Phase 4 grew from 10 weeks to 18 with
ten new features, and everything after it moved later. Week numbers quoted in
older commits, documents and the audit report follow the previous numbering,
where Phase 3 ended at week 30 and Phase 5 began at week 41. The phase names
did not change, so a reference to "the AI cost pass" is unambiguous even when
the week number beside it is stale.

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

**Status: complete.** Six capabilities behind the gateway, six endpoints,
three eval suites with nine mandatory rules, and 214 passing tests. See
`docs/ai-features.md` for what each one costs and what it is allowed to
decide.

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

# Phase 3: Marketplace core (weeks 17 to 31)

**Status: in progress, weeks 17 to 22 complete.** 356 passing tests, six CI
jobs.

- **M2 brand portal, weeks 17 to 18.** Registration, document upload, the
  verification workflow, the brand dashboard, per brand policy settings and an
  append only audit trail, over nine endpoints.
- **M3 catalog and manifests, weeks 19 to 21.** Lot creation, the manifest
  editor with the sum must match total rule, spreadsheet import through the
  Phase 2 extractor as a two step accept, the photo pipeline with compression
  and ordering, condition grading, and the draft to live state machine as a
  single transition table.
- **Approvals and protection, week 22.** The brand approval gate with an
  append only snapshot of the listing as approved, public, unbranded and
  private protection levels, the region lock per brand and per lot, and
  withdraw. All buyer visibility goes through one function.

The development environment also moved into containers during this phase, so
lint, types, tests, migrations and seeding all run in the same images CI uses.
See `DEPLOYMENT.md`.

Goal: the marketplace, built on top of the AI engine. Every module below
calls Phase 2 rather than duplicating it.

| Weeks | Module | Scope |
| --- | --- | --- |
| 17 to 18 | M2 Brand portal | Done. Registration, NTN and document upload, verification workflow, brand dashboard, per brand policy settings |
| 19 to 21 | M3 Catalog and manifests | Done. Lot creation from photo upload, the manifest editor with the sum must match total rule, bulk upload through the Phase 2 extractor, photo pipeline with compression and ordering, condition grading, draft to pending to approved to live states |
| 22 to 23 | Approvals and protection | Week 22 done. Brand approval gate with full audit record, private listings, unbranded listings, region lock, withdraw. Week 23 is new work: automatic logo blur on unbranded listings, and brand reviews before publish |
| 24 to 25 | M4 Search and discovery | Filters, sort, text search, semantic and photo search wired to Phase 2, saved searches |
| 26 to 27 | M5 Cart and orders | Lot and part lot ordering, minimum order value, order lifecycle, buyer confirmation, dispute window, returns recorded |
| 28 | M6 Payments | Bank transfer, JazzCash, Easypaisa, COD, held funds and brand payout records. Integration kept behind one interface so a sandbox implementation works until merchant accounts exist |
| 29 | M7 Logistics | One courier integration behind a provider interface, label and tracking, shipping cost rules, pickup scheduling |
| 30 to 31 | M8 Admin panel | Verification queue, listing moderation with the Phase 2 risk score shown, orders, disputes, commission settings, payout runs, audit log viewer |

Two deliberate constraints in this phase. Payments and logistics sit behind
interfaces with sandbox implementations, so no week is blocked waiting for a
merchant account or a courier contract, both of which depend on the company
existing. And the money path is boring on purpose: see the non negotiables in
`docs/ai-architecture.md`.

Phase 3 exit: a reseller can find a lot by photo, order it, pay in sandbox,
track it and confirm delivery, and an admin can see all of it, all against
seed data.

---

# Phase 4: Intelligence layer (weeks 32 to 49)

Goal: the features that make the platform feel like it is run by software
rather than by a person with a spreadsheet.

Ten of these eighteen weeks are new work added on 2026-10-14, and most of the
new items are the ones that fit this market rather than a generic
marketplace: voice notes because many buyers would rather talk than type,
pooling and mixed lots because a single shop cannot absorb a whole lot, and a
resell kit because the buyer's next problem after buying is selling.

| Weeks | Feature | What it does |
| --- | --- | --- |
| 32 to 33 | Buyer assistant in the product | The Phase 2 assistant exposed in the web UI and on WhatsApp, with conversation history, catalogue tools, and an explicit refusal to quote a price or stock level it has not read from the database |
| 34 | Voice note ordering | New. WhatsApp voice notes in Urdu, Punjabi, Sindhi and Pashto, built on the buyer assistant |
| 35 to 36 | Brand assistant | A brand can ask which of my stock is slow, what should I discount, what sold in Karachi last month, answered from that brand's own data only, with the access boundary tested |
| 37 | Recommendations | Lot recommendations for resellers from purchase history and embeddings |
| 38 | Reseller profit helper | Estimates resale value and margin for a lot in the buyer's own city |
| 39 | Mixed lot builder | New. Combines slow stock from several brands into one lot matched to a reseller's shop and city |
| 40 | Resell kit generator | New. Social posts, cleaned photos, Urdu and Roman Urdu captions, price tags and a WhatsApp catalogue for every purchased lot |
| 41 | Committee lot pooling | New. Matches 3 to 4 resellers in one city to buy a large lot together and splits it by their needs |
| 42 | Bargaining bot | New. Negotiates in Urdu, never below the brand's floor price, every deal logged |
| 43 | Smart markdown agent | New. Lowers unsold lot prices on a schedule, never below the brand's floor price |
| 44 to 45 | Demand and dead stock prediction | Scheduled batch jobs over sales history that predict what will sell where, flag lots heading nowhere, and give brands an over production warning. New: a season and event calendar covering Eid, Ramzan, wedding season, school opening and monsoon |
| 46 | Size translator | New. Maps sizes across brands to cut returns |
| 47 | Upcycle and donation route | New. Matches unsellable stock with tailors, artisans and NGOs |
| 48 | Fraud and counterfeit detection | Risk scoring for accounts, listings and orders, with human review for anything consequential |
| 49 | M10 Analytics | Brand reporting on what sold, where and at what price, admin reporting on GMV, users and growth, plus an AI cost dashboard per feature. New: an impact report per brand covering waste, water and CO2 saved |

Two of the new features need a decision before they are built, because they
sit against the rule in `CLAUDE.md` section 4 and
`docs/ai-architecture.md` section 2 that AI never decides money:

- The **bargaining bot** in week 42 negotiates a price with a buyer.
- The **smart markdown agent** in week 43 changes a listing price on a
  schedule with nobody watching.

Both descriptions already carry the right instinct, "never below the brand's
floor price" and "every deal logged". The way to keep them inside the rule is
to make the floor a thing the code enforces rather than a thing the model is
asked to respect: the floor and the step size are brand policy rows, the
service clamps every proposal to them before it is ever shown or applied, and
every move is written to the append only audit trail with the brand able to
switch the agent off per lot. Then the model is choosing within a band the
brand set, which is the same authority the pricing feature already has, rather
than deciding what a thing is worth. That needs confirming before week 42
rather than discovered during it.

Phase 4 exit: every AI surface is behind an eval and a cost budget, and the
AI cost dashboard shows what the platform spends per listing and per order.

---

# Phase 5: Hardening, documentation and release (weeks 50 to 57)

Goal: stop building and make it real. Most student and solo projects skip
this phase and it is the one that separates a demo from a platform.

| Weeks | Work |
| --- | --- |
| 50 | Test coverage pass: unit, integration and end to end on the money path and the access boundaries. Load test the catalogue and search. Also the new money adjacent paths: pooling splits, the bargaining floor and the markdown floor |
| 51 | Security pass: authentication and session handling, rate limits, file upload validation including voice notes, prompt injection defences on every user text that reaches a model and on the bargaining bot in particular, secret handling, dependency audit, backup and tested restore |
| 52 | Performance pass on a throttled 3G profile and a mid range Android device. Image sizes, bundle size, query plans, N plus 1 queries, cache hit rates |
| 53 | AI cost and quality pass: re run every eval including the new features, tune model choice and effort per feature, verify prompt caching is actually being hit, add the response cache, move everything that can wait to the Batch API |
| 54 to 55 | Documentation, written to match the code as it is: `README.md`, `docs/architecture.md`, `docs/database-schema.md`, `docs/api-reference.md` with an OpenAPI spec, `docs/ai-features.md` with prompts, models, costs, limits and eval results, `docs/setup-guide.md`, `docs/deployment.md`, `docs/user-guides/` for brand, reseller and admin, `docs/decisions/` for the architecture decision records, `CHANGELOG.md`, `CONTRIBUTING.md` |
| 56 | Deployment: production environment, domain, HTTPS, monitoring, error tracking, log aggregation, database backups, a staging environment that mirrors production |
| 57 | Release `v1.0.0`, tagged, with a seeded public demo, a recorded walkthrough, and a demo mode that shows the platform working without exposing real brand data |

Phase 5 exit: someone who has never seen the project can clone it, follow
`docs/setup-guide.md`, and have it running locally in under 30 minutes.

---

# Phase 6: Brands and launch (weeks 58 onward)

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
| 58 to 59 | Register the company, NTN, bank account, merchant account applications, publish the landing page |
| 60 to 61 | Brand outreach, demonstrate the live platform, target 10 brands committed in writing |
| 62 to 63 | Reseller recruitment, target 100 on the waiting list, verification of the first 20 |
| 64 to 65 | Pilot: the first real lots listed by real brands, the first real orders, swap the payment and courier sandbox implementations for live credentials |
| 66 to 69 | Fix what the pilot breaks, then public launch |

Phase 6 exit: real brands, real buyers, real money, and the pricing and demand
models finally training on your own data instead of on rules.

---

# After launch: pay after sale credit

Added to the plan on 2026-10-14 and deliberately placed outside the numbered
weeks.

An AI trust score that lets a trusted reseller take stock now and pay after
they sell it.

**This one has a legal gate before any build work starts.** Lending money, or
anything a regulator would read as lending money, is governed by State Bank of
Pakistan rules, and a lawyer has to confirm what is permitted before a line of
code is written. Not after a prototype exists, because a prototype creates
pressure to ship it.

Two further notes worth writing down now while it is still cheap to say:

- An AI trust score that decides who gets credit is the furthest thing in this
  whole plan from the rule that AI never decides money. If it is built, the
  score belongs in front of a human approving a credit limit, with the reasons
  shown and recorded.
- Credit turns a marketplace into a lender, which changes the capital the
  company needs and the risk it carries. That is a business decision rather
  than a feature decision.

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

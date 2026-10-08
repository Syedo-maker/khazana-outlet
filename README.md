# Khazana Outlet

An AI native B2B marketplace for Pakistani brand surplus stock. Brands clear
previous season, over produced and season end inventory in bulk lots; verified
resellers and small shops buy original branded goods at wholesale prices.

**Status: Phase 1 complete.** The foundation is built and tested. The AI
features are Phase 2, the marketplace modules are Phase 3, and brand
recruitment is Phase 6. See [ROADMAP.md](ROADMAP.md).

## Why this exists

When a Pakistani brand has leftover stock today, it usually goes to one dealer
in a wholesale market, for cash, with no paperwork and no control over where
it ends up. That is fast, which is why it happens, and it costs the brand both
margin and control of its own name.

This platform gives the brand many competing buyers instead of one dealer, an
approval gate on every listing, the choice of hiding its name or locking
cities where it has stores, and a documented invoiced sale instead of an
undocumented cash one.

## What makes it AI native

AI is in the critical path of the work the platform exists to do, not beside
it. A brand photographs a lot and gets a complete draft listing. A messy
spreadsheet becomes a reconciled manifest with every proposed change flagged.
A buyer searches with a sentence or a photograph, in Urdu, Roman Urdu or
English. Every listing is risk scored before a human sees it.

Equally important is what AI is never allowed to decide: price, payouts,
approvals, bans, or any stock level quoted to a user. It drafts, suggests,
scores and flags. [docs/ai-architecture.md](docs/ai-architecture.md) has the
full boundary and the cost model.

## Stack

| Layer | Choice |
| --- | --- |
| Web | Next.js 15, React 19, Tailwind CSS, TypeScript |
| API | FastAPI, Python 3.11 |
| Database | PostgreSQL 16 with pgvector |
| Migrations | Alembic |
| Queue | Redis |
| AI | Claude API through a single gateway service |
| Embeddings | Self hosted open model, SigLIP or CLIP class |

## Repository layout

```
apps/
  api/                    FastAPI service
    src/khazana/
      models/             SQLAlchemy models, 27 tables
      core/               security, errors, tenancy
      services/           domain logic
      api/                routers, dependencies, schemas
      ai/
        gateway/          the only code that talks to a model
        prompts/          versioned prompt files
        evals/            one suite per AI feature, runs in CI
      seed.py             synthetic marketplace generator
    alembic/              migrations
    tests/                90 tests
  web/                    Next.js application
docs/                     architecture, schema, AI design
phase-6-brands-and-launch/  the brand and market work, runs last
landing/                  waiting list page
scripts/                  repository rules gate, ERD generator
```

## Getting started

Requirements: Python 3.11 or newer, Node 20 or newer, Docker for PostgreSQL
and Redis.

```bash
# 1. Install everything
make setup

# 2. Start PostgreSQL and Redis
make up

# 3. Create the schema
make migrate

# 4. Load a realistic synthetic marketplace
make seed

# 5. Run the API and the web app in two terminals
make api
make web
```

The API is on http://localhost:8000 with interactive documentation at
http://localhost:8000/docs. The web app is on http://localhost:3000.

Copy `.env.example` to `.env` first. The defaults work for local development
with no API keys at all, because the AI layer starts in offline mode and reads
recorded fixtures.

### Signing in locally

There is no SMS gateway until Phase 6, so `OTP_DEV_ECHO=true` returns the
code in the API response and prints it in the log. The login page shows it.
Production refuses to start with that setting on.

## Everyday commands

```bash
make test       # the test suite
make cov        # with a coverage report
make lint       # ruff and mypy
make fix        # auto fix what can be auto fixed
make evals      # AI eval suites against recorded fixtures, free
make migration m="add something"
make prepush    # the repository rules gate
make help       # every target
```

## The AI gateway in one paragraph

Every model call goes through `apps/api/src/khazana/ai/gateway`. Nothing else
constructs an Anthropic client. One call checks the kill switch and the spend
caps before spending anything, records a job row, loads a versioned prompt,
calls the model or a recorded fixture, validates the reply against a strict
schema, prices it from the returned token counts, writes the spend to a
ledger, and stores the output ready for a human to accept or correct. That
structure is what makes model choice, cost and quality all changeable in one
place instead of scattered through the codebase.

`GET /ai/status` shows the current mode, the routed models, the daily cap and
every feature switch.

## Testing

```
90 tests, covering:
  authentication      OTP single use, attempt caps, rate limits, token rotation
  tenant isolation    cross brand reads, the empty membership case, 404 not 403
  schema rules        manifest sum, approval gate, order arithmetic
  AI gateway          pricing, caps, kill switches, routing, schema validation
  seed data           every generated lot obeys the platform's own rules
```

The suite runs on SQLite for speed. The PostgreSQL specific parts, meaning the
deferred manifest trigger, the append only triggers and the row level security
policies, are verified by the migration job in CI, which applies every
migration, rolls it back and applies it again.

## Documentation

| Document | What is in it |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | The six phases, week by week, and what is deliberately out of scope |
| [docs/ai-architecture.md](docs/ai-architecture.md) | Model routing, cost control with arithmetic, the hard limits on what AI decides |
| [docs/database-schema.md](docs/database-schema.md) | Generated ERD and the design decisions behind it |
| [CLAUDE.md](CLAUDE.md) | Working rules for this repository |
| [phase-6-brands-and-launch/](phase-6-brands-and-launch/) | Brand outreach, interviews, unit economics, company registration, the manual sales playbook |

## Contributing rules that matter

- No em dashes or en dashes anywhere. Use a comma, a colon, a full stop or a
  plain hyphen. `make prepush` enforces it.
- Commission rates, discount bands, protection rules and lot minimums are
  rows in `brand_policies`, never constants in code.
- Every AI feature ships with an eval, and the eval is written first.
- Every model call goes through the gateway.
- A brand owned table carries a `brand_id` and is listed in
  `BRAND_SCOPED_TABLES`, or the isolation test fails.

## Licence

Copyright Muhammad Ibrahim. All rights reserved.

The source is public so the work can be read and reviewed. It is not open
source: no licence is granted to use, copy, modify or distribute it. If you
want to use any of it, ask.

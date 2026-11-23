# Khazana Outlet

An AI native B2B marketplace for Pakistani brand surplus stock. Brands clear
previous season, over produced and season end inventory in bulk lots; verified
resellers and small shops buy original branded goods at wholesale prices.

**Status: Phases 1 to 4 built.** The foundation, the AI engine, the
marketplace and the intelligence layer are built and tested, on sandbox
payment, courier and WhatsApp providers. Phase 5 hardens and releases it, and
brand recruitment is Phase 6. See [ROADMAP.md](ROADMAP.md), and
[DEPLOYMENT.md](DEPLOYMENT.md) for what a real deployment still needs.

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
English, and asks an assistant on the web or WhatsApp. Every listing is risk
scored before a human sees it.

Equally important is what AI is never allowed to decide: price, payouts,
approvals, bans, or any stock level quoted to a user. It drafts, suggests,
scores and flags. The one narrow exception is choosing a price inside a band
the brand set and code enforces, for the bargaining bot and the markdown agent,
recorded in [docs/decisions/0001-ai-value-bands.md](docs/decisions/0001-ai-value-bands.md).
[docs/ai-architecture.md](docs/ai-architecture.md) has the full boundary and
the cost model.

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
      models/             SQLAlchemy models, 55 tables
      core/               security, errors, tenancy
      services/           domain logic
      api/                routers, dependencies, schemas
      ai/
        features/         one module per AI feature
        tools/            the lookups the assistants may run
        gateway/          the only code that talks to a model
        prompts/          versioned prompt files
        evals/            one suite per AI feature, runs in CI
      seed.py             synthetic marketplace generator
    alembic/              migrations 0001 to 0016
    tests/                about 810 tests
  web/                    Next.js application
docs/                     architecture, schema, AI design
phase-6-brands-and-launch/  the brand and market work, runs last
landing/                  waiting list page
scripts/                  repository rules gate, ERD generator
```

## Getting started

The whole stack runs in containers, so the only requirement is Docker Desktop.
Nothing has to be installed on the machine, and nothing depends on what the
machine's security policy allows to run.

```powershell
.\scripts\dev.ps1 build     # once, and after changing pyproject.toml or package.json
.\scripts\dev.ps1 migrate   # create the schema
.\scripts\dev.ps1 seed      # load a realistic synthetic marketplace
.\scripts\dev.ps1 up        # start the API and the web app
```

The API is on http://localhost:8000 with interactive documentation at
http://localhost:8000/docs. The web app is on http://localhost:3000.

`DEPLOYMENT.md` has every command, the troubleshooting list and what is still
left to do before a real deployment.

Running it on the host instead needs Python 3.11 or newer and Node 20 or newer,
and the `make` targets below. Note that `make` is not installed on the
development machine, so the containerised path above is the supported one.

Copy `.env.example` to `.env` first. The defaults work for local development
with no API keys at all, because the AI layer starts in offline mode and reads
recorded fixtures.

### Signing in locally

There is no SMS gateway until Phase 6, so `OTP_DEV_ECHO=true` returns the
code in the API response and prints it in the log. The login page shows it.
Production refuses to start with that setting on.

## Everyday commands

In containers:

```powershell
.\scripts\dev.ps1 check     # lint, format, types and tests, which is what CI runs
.\scripts\dev.ps1 test      # the test suite
.\scripts\dev.ps1 fix       # auto fix what can be auto fixed
.\scripts\dev.ps1 evals     # AI eval suites against recorded fixtures, free
.\scripts\dev.ps1 logs      # follow the logs
.\scripts\dev.ps1 shell     # a shell inside the API container
bash scripts/prepush-check.sh   # the repository rules gate
```

On the host, if the tooling is installed there:

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
About 810 tests, covering:
  authentication      OTP single use, attempt caps, rate limits, token rotation,
                      and every route refusing an anonymous caller
  tenant isolation    cross brand reads on every brand scoped route, 404 not 403
  money               order arithmetic, held funds, payouts, the ADR 0001 clamps
  marketplace         catalogue, orders, payments, logistics, admin, pools
  AI gateway          pricing, caps, kill switches, routing, schema validation,
                      and every prompt and schema the API is sent
  seed data           every generated lot obeys the platform's own rules
```

Every AI feature also has an eval suite, run against recorded replies in CI and
against the live model on demand.

The suite runs on SQLite for speed. The PostgreSQL specific parts, meaning the
deferred manifest trigger, the append only triggers, the row level security
policies and vector search, have their own tests on a disposable PostgreSQL
database (`.\scripts\dev.ps1 pgtest`), and the migration job in CI applies
every migration, rolls it back and applies it again.

## Documentation

| Document | What is in it |
| --- | --- |
| [ROADMAP.md](ROADMAP.md) | The six phases, week by week, and what is deliberately out of scope |
| [docs/ai-architecture.md](docs/ai-architecture.md) | Model routing, cost control with arithmetic, the hard limits on what AI decides |
| [docs/decisions/](docs/decisions/) | Decision records, starting with 0001 on AI value bands |
| [DEPLOYMENT.md](DEPLOYMENT.md) | The development environment, every command, and what production still needs |
| [CHANGELOG.md](CHANGELOG.md) | What landed, grouped by roadmap weeks |
| [docs/database-schema.md](docs/database-schema.md) | Generated ERD and the design decisions behind it |
| [CLAUDE.md](CLAUDE.md) | Working rules for this repository |
| [phase-6-brands-and-launch/](phase-6-brands-and-launch/) | Brand outreach, interviews, unit economics, company registration, the manual sales playbook |

## Contributing rules that matter

- No em dashes or en dashes anywhere. Use a comma, a colon, a full stop or a
  plain hyphen. `bash scripts/prepush-check.sh` enforces it.
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

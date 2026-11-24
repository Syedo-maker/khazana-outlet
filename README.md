# Khazana Outlet

An AI native B2B marketplace for Pakistani brand surplus stock. Brands clear
previous season, over produced and season end inventory in bulk lots; verified
resellers and small shops buy original branded goods at wholesale prices.

**Status: version 1.0, Phases 1 to 5 complete.** The foundation, the AI
engine, the marketplace and the intelligence layer are built, then hardened:
tested end to end, security reviewed, load tested, measured on a slow phone
connection, costed against live models, documented, and packaged as a
production stack with HTTPS, backups and monitoring. It runs on sandbox
payment, courier, SMS and WhatsApp providers until Phase 6 connects real ones.
See [ROADMAP.md](ROADMAP.md), and [docs/deployment.md](docs/deployment.md)
for the launch checklist.

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
| Production | Docker Compose behind Caddy with automatic HTTPS |
| Observability | JSON logs, Prometheus metrics, Sentry compatible error reports |

## Repository layout

```
apps/
  api/                    FastAPI service
    src/khazana/
      models/             SQLAlchemy models, 56 tables
      core/               security, errors, tenancy
      services/           domain logic
      api/                routers, dependencies, schemas
      ai/
        features/         one module per AI feature
        tools/            the lookups the assistants may run
        gateway/          the only code that talks to a model
        prompts/          versioned prompt files
        evals/            one suite per AI feature, runs in CI
      scheduler.py        the timed jobs, run as their own service
      observability.py    logs, request ids, metrics, error reports
      seed.py             synthetic marketplace generator
    alembic/              migrations 0001 to 0018
    tests/                about 935 tests
  web/                    Next.js application
e2e/                      browser end to end tests and throttled page timings
loadtest/                 k6 load test of the catalogue and search
deploy/                   Caddyfile, Prometheus configuration and alert rules
docs/                     setup, deployment, architecture, API, AI, security, guides
phase-6-brands-and-launch/  the brand and market work, runs last
landing/                  waiting list page
scripts/                  dev commands, rules gate, backups, doc generators
```

## Getting started

The whole stack runs in containers, so the only requirement is Docker.
[docs/setup-guide.md](docs/setup-guide.md) takes a fresh clone to a running
platform with a sample marketplace in about 30 minutes:

```powershell
.\scripts\dev.ps1 build     # once, and after changing pyproject.toml or package.json
.\scripts\dev.ps1 migrate   # create the schema
.\scripts\dev.ps1 seed      # load a realistic synthetic marketplace
.\scripts\dev.ps1 up        # start the API and the web app
```

The web app is on http://localhost:3000, the API on http://localhost:8000
with interactive documentation at `/docs`. The AI layer starts offline and
answers from recorded replies, so no API key is needed.
[docs/development.md](docs/development.md) has every command and the
troubleshooting list.

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
About 935 API tests, covering:
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
against the live model on demand; the last live run passed every mandatory
case. Beyond the unit suite, CI walks one order from checkout to payout over
HTTP, checks the money rules against thousands of random cases, runs the
money path in a phone sized browser, backs up and restores the database, and
starts the production stack as staging and tests it through HTTPS.

The suite runs on SQLite for speed. The PostgreSQL specific parts, meaning the
deferred manifest trigger, the append only triggers, the row level security
policies and vector search, have their own tests on a disposable PostgreSQL
database (`.\scripts\dev.ps1 pgtest`), and the migration job in CI applies
every migration, rolls it back and applies it again.

## Documentation

| Document | What is in it |
| --- | --- |
| [docs/setup-guide.md](docs/setup-guide.md) | From a fresh clone to running locally |
| [docs/development.md](docs/development.md) | Every command, the stack, CI, troubleshooting |
| [docs/deployment.md](docs/deployment.md) | Production and staging, backups, monitoring, the launch checklist |
| [docs/architecture.md](docs/architecture.md) | How the platform is put together |
| [docs/api-reference.md](docs/api-reference.md) | Every endpoint, generated from the code, with [openapi.json](docs/openapi.json) |
| [docs/database-schema.md](docs/database-schema.md) | Generated ERD and the design decisions behind it |
| [docs/ai-architecture.md](docs/ai-architecture.md) | Model routing, cost control, the hard limits on what AI decides |
| [docs/ai-features.md](docs/ai-features.md) | Each AI feature, its model, eval results and measured cost |
| [docs/security.md](docs/security.md) | Every control and the test that proves it |
| [docs/performance.md](docs/performance.md) | Load tests, slow connection timings and what they changed |
| [docs/user-guides/](docs/user-guides/) | For resellers, brands and the Khazana team |
| [docs/decisions/](docs/decisions/) | Architecture decision records |
| [ROADMAP.md](ROADMAP.md) | The six phases, week by week, and what is deliberately out of scope |
| [CHANGELOG.md](CHANGELOG.md) | What landed, by release |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How work gets into the repository |
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

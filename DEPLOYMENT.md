# Deployment and the development environment

Everything runs in containers. Nothing here depends on what is installed on
the machine, or on what the machine's security policy allows to run. That is
the point: the API, the web app, PostgreSQL and Redis all start from one
command, and the linter, the type checker, the tests and the migrations run
inside the same images that CI uses.

## What is in the stack

| Service | Image or build | Port | Notes |
| --- | --- | --- | --- |
| `db` | `pgvector/pgvector:pg16` | 127.0.0.1:5432 | PostgreSQL 16 with the vector extension, so visual search needs no second datastore |
| `redis` | `redis:7-alpine` | 127.0.0.1:6379 | OTP store and job queue, append only persistence |
| `api` | `apps/api/Dockerfile`, target `dev` | 8000 | FastAPI with reload, docs at `/docs` |
| `web` | `apps/web/Dockerfile`, target `dev` | 3000 | Next.js dev server |

Both database ports are bound to `127.0.0.1` on purpose. Publishing them as
`5432:5432` binds `0.0.0.0`, which puts a database with a known development
password on whatever network this machine joins. They are still published so a
GUI client on this machine can connect. The API reaches them over the compose
network, not through the published port.

## First run

Docker Desktop has to be running. Then, from the repository root:

```powershell
.\scripts\dev.ps1 build     # once, and after changing pyproject.toml or package.json
.\scripts\dev.ps1 migrate
.\scripts\dev.ps1 seed
.\scripts\dev.ps1 up
```

The API is then on http://localhost:8000 and the web app on
http://localhost:3000. `up` runs in the background, so `logs` is how you watch
it.

The first build downloads the dependencies. Every run after that downloads
nothing, because the dependencies live in the image rather than in a cache that
is rebuilt per run. A container therefore starts in a couple of seconds.

## Every command

```powershell
.\scripts\dev.ps1 <command>
```

| Command | What it does |
| --- | --- |
| `build` | Build the API and web images |
| `up` | Start everything in the background |
| `down` | Stop everything, keep the data |
| `reset` | Stop everything and delete the data volumes, with a confirmation prompt |
| `test` | The test suite |
| `pgtest` | The PostgreSQL only tests, in a disposable database |
| `lint` | Ruff check and format check |
| `fix` | Apply the automatic lint and format fixes |
| `types` | Mypy |
| `check` | Lint, format, types and tests together, which is what CI runs |
| `evals` | The AI eval suites, against recorded fixtures |
| `migrate` | Apply database migrations |
| `seed` | Load the synthetic marketplace |
| `logs` | Follow the logs |
| `shell` | A shell inside the API container |
| `status` | What is running |

Arguments pass through, so `.\scripts\dev.ps1 test tests/test_brand_portal.py -k verify`
works, and so does `.\scripts\dev.ps1 seed --reset`.

`Get-Help .\scripts\dev.ps1 -Full` prints the same list.

## Before pushing

Two gates, both of which CI also runs as required jobs:

```powershell
.\scripts\dev.ps1 check          # lint, format, types, tests
bash scripts/prepush-check.sh    # the repository rules in CLAUDE.md
```

The second one checks tracked files and the commits being pushed for em
dashes, en dashes and AI attribution lines, and checks the commit author. It
exits non zero on any violation.

`make` is not installed on this machine, so the `make` targets in the README do
not run here. Use the commands above.

## The disposable test database

`tests/test_search_postgres.py` calls `drop_all()`, so it needs a database it
is allowed to destroy. Two guards stand in front of it:

- The test module skips itself unless `TEST_DATABASE_URL` names a database
  whose name contains `test`.
- The fixture checks the same thing again before it touches a schema.

`.\scripts\dev.ps1 pgtest` creates `khazana_test` if it is missing and points
the tests at it. CI creates the same database. Pointing those tests at the
working database destroys it, which is what the guards exist to prevent, so do
not set `TEST_DATABASE_URL` to anything else by hand.

## Secrets

The compose file carries literal values for `POSTGRES_PASSWORD`, `SECRET_KEY`
and the database URL. They are development throwaways for a localhost only
stack, and a static audit will flag them as hardcoded credentials. They are
deliberate: a fresh clone has to come up with no setup step. None of them is
valid anywhere else, and none of them may be reused in a deployed environment.

The one real key is `ANTHROPIC_API_KEY`. It is read from the host environment
and passed through, so it is never written into a file in this repository:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\scripts\dev.ps1 up
```

Without it the API runs with `AI_OFFLINE=true`, which serves the recorded
fixtures and makes no network calls. That is the default, and it is what the
eval suites use.

`.env.example` lists every variable the application reads. The repository is
public, so `.env` is gitignored and stays that way.

## The postcss override

`apps/web/package.json` forces `postcss` to `^8.5.18` through an `overrides`
block. Next pins `postcss` to exactly `8.4.31`, which carries two HIGH
advisories, CVE-2026-45623 and CVE-2026-73646. Every Next 15 release up to
15.5.27 pins the same version, so upgrading Next does not help and the
override is the only way out. npm refuses an override the direct dependency
range does not satisfy, which is why the `devDependencies` entry moved to the
same range.

The production build and the lint both pass against the overridden version,
and the scan job is clean. Do not drop the override to silence a dependency
warning without checking the advisories again.

## CI

`.github/workflows/ci.yml` runs on `main`, `develop` and `feature/**`:

| Job | Required | What it covers |
| --- | --- | --- |
| `repo-rules` | yes | `scripts/prepush-check.sh` |
| `api` | yes | Ruff, mypy, pytest against a PostgreSQL service container |
| `migrations` | yes | Migrations apply from empty, and the PostgreSQL only tests |
| `web` | yes | Next.js lint and production build |
| `evals` | yes | AI eval suites against fixtures, never the live API |
| `scan` | no | Trivy, filesystem vulnerabilities and secrets, advisory only |

The scan job is advisory because a finding there is usually a transitive
dependency with no fixed version yet, which is not something the pull request
that triggered the run can do anything about.

When a formatting check fails, the `api` job prints the exact diff in a log
group called "formatting diff" and uploads it as a `format-patch` artifact, so
a CI only failure can be reproduced without guessing at tool versions. Ruff and
mypy are pinned to exact versions in `apps/api/pyproject.toml` for the same
reason. When upgrading either, change the pin, reformat, and update the image
tag in `scripts/lint.ps1` in the same commit.

## Production, still to do

The images have production targets already. The `runtime` target in each
Dockerfile is slim, runs as an unprivileged user at uid 1000, carries no test
or lint tooling, and has a health check. Neither is wired to anything yet.
Before a deployment:

- Push the `runtime` images to a registry. GHCR needs no secret beyond
  `GITHUB_TOKEN`.
- Replace every development credential. `SECRET_KEY` must be a long random
  string, the database must have a real password, and Redis needs one too.
- Set `OTP_DEV_ECHO=false`. Left true, it prints login codes to the log.
- Put TLS in front of the stack. Nothing here terminates it.
- Move uploads off the local volume. `STORAGE_LOCAL_PATH` is a development
  convenience, not durable storage.
- Decide on backups for the `db_data` volume. There are none at the moment.
- Set the AI spend guards for real. `AI_DAILY_SPEND_LIMIT_USD` and
  `AI_BRAND_MONTHLY_SPEND_LIMIT_USD` default to development sized numbers.

## When something is wrong

**"Docker is not running."** Start Docker Desktop and wait for the whale icon
to settle. The script checks before it does anything.

**A dependency change is not picked up.** `build` again. Dependencies are
baked into the image on purpose, so `pyproject.toml` and `package.json` changes
need a rebuild. Source changes do not: both source folders are bind mounted.

**The web app does not notice an edit.** Bind mounts on Windows do not deliver
file change events to Linux, so the dev server polls instead. That is what
`WATCHPACK_POLLING` is for. It is slower than a native watch, not broken.

**Permission errors on `.next` or `node_modules`.** Those are anonymous
volumes, which Docker seeds from the image including the ownership. The web
Dockerfile creates and chowns them before switching to the `node` user for
exactly this reason. If it comes back, `down` then `up` recreates the volumes.

**`npm run build` fails on /404 with "`<Html>` should not be imported
outside of pages/_document".** That is a production build running inside the
dev container, where `NODE_ENV=development`. Next prerenders the error page
differently and the build dies on a page nobody wrote. Pass the right
environment, or build the image target that already sets it:

```powershell
docker compose run --rm --no-deps -e NODE_ENV=production web npm run build
docker build --target build .pps\web      # what CI effectively does
```

**The seed fails on a second run.** It should not: `seed --reset` truncates
with `RESTART IDENTITY CASCADE` on PostgreSQL. A plain `DELETE` cannot work
there, because the audit tables are append only and a trigger enforces it.

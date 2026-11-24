# Setup guide

From a fresh clone to the whole platform running on your machine: the web
app, the API, PostgreSQL and Redis, with a synthetic marketplace loaded and
every account ready to sign in. Everything runs in Docker, so nothing else
needs installing for the app itself.

Budget about 30 minutes, most of it the first image build downloading
dependencies. Measured on 2026-11-24, following these steps from a fresh
clone with Docker's build cache disabled: 3 minutes 54 seconds to the web app
and the API answering, on a machine that already had the base images. A new
machine downloads those too, a few hundred MB more.

## 1. What you need

| Tool | Version | Why |
| --- | --- | --- |
| Git | any recent | To clone |
| Docker Desktop, or Docker Engine with Compose v2 | 4.30 or later | Runs everything |
| About 8 GB of free memory and 10 GB of disk | | The images, the database and the dev servers |

On Windows the commands below use `scripts\dev.ps1` in PowerShell. On macOS
and Linux the same steps are plain `docker compose` commands, shown beside
each one.

Node.js 22 is needed only for the browser end to end tests in step 6.

## 2. Clone

```bash
git clone https://github.com/Syedo-maker/khazana-outlet.git
cd khazana-outlet
```

## 3. Build the images

About 10 to 20 minutes the first time, depending on the connection: it
downloads the Python and Node dependencies into the images. Later builds reuse
them and take seconds.

```powershell
.\scripts\dev.ps1 build
```

```bash
docker compose build
```

## 4. Create the database and load the sample marketplace

```powershell
.\scripts\dev.ps1 migrate
.\scripts\dev.ps1 seed
.\scripts\dev.ps1 up
```

```bash
docker compose up -d db redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m khazana.seed
docker compose up -d
```

The seed loads 18 categories, sample brands with 30 lots, resellers and
orders. Every brand and shop name is synthetic and marked `(sample)`.

## 5. Open it

- Web app: http://localhost:3000
- API and its interactive docs: http://localhost:8000/docs

Sign in with one of the seeded phone numbers. In development the login page
shows the one time code itself, under the code field, so no SMS is needed.

| Role | Phone | What to try |
| --- | --- | --- |
| Reseller | `03020000000` | Browse the catalogue, order a lot, pay in the sandbox, ask the assistant |
| Brand owner | `03010000000` | Dashboard, lots, approvals, book a courier for a paid order |
| Admin | `03000000001` | Moderation queue, payments, payouts, disputes, settings |

The AI features run offline by default: they answer from recorded replies and
make no network calls, so nothing is spent. To use the live models, set
`ANTHROPIC_API_KEY` in your environment before `up`; see
[ai-features.md](ai-features.md).

## 6. Check it works

```powershell
.\scripts\dev.ps1 check        # lint, types and the full test suite
.\scripts\dev.ps1 evals        # every AI eval suite, offline
.\scripts\dev.ps1 e2e          # the money path in a phone sized browser
```

```bash
docker compose run --rm --no-deps api sh -c "ruff check . && mypy src && pytest -q"
docker compose run --rm --no-deps api python -m khazana.ai.evals.run --offline
cd e2e && npm ci && npx playwright install chromium && npx playwright test
```

The test suite takes about ten minutes. The browser tests buy one seeded lot
each run, so reseed (`seed --reset`) after a few runs.

## Ports

| Port | Service |
| --- | --- |
| 3000 | Web app |
| 8000 | API |
| 55432 | PostgreSQL, bound to localhost |
| 56379 | Redis, bound to localhost |

PostgreSQL is on 55432 rather than 5432 so it does not collide with a native
PostgreSQL install. Inside the containers it is `db:5432`.

## When something goes wrong

[development.md](development.md) has the full list. The common ones:

- **Docker is not running.** Start Docker Desktop and wait for it to settle.
- **A port is already in use.** Something else holds 3000, 8000, 55432 or
  56379. Stop it, or change the host side of the port in `docker-compose.yml`.
- **The seed fails because data exists.** `seed --reset` replaces it.
- **The web app shows "Could not reach the server".** The API is not up yet,
  or stopped: `docker compose ps`, then `docker compose logs api`.

## Next

- [development.md](development.md): every command and how the stack is put together
- [architecture.md](architecture.md): how the platform is built
- [deployment.md](deployment.md): production, staging and the launch checklist
- [user-guides/](user-guides/): how brands, resellers and admins use it

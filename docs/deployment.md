# Deployment

How Khazana Outlet runs in production and in staging, how to deploy and
update it, back it up and restore it, watch it, and what is still needed
before real brands and buyers use it.

The local development stack is a different thing, described in
[development.md](development.md). For the zero budget pilot on a free Oracle
Cloud machine, follow [oracle-free-tier.md](oracle-free-tier.md); this page is
the reference behind it.

## The zero budget pilot

The defaults in [`.env.production.example`](../.env.production.example) run
the pilot with no paid service at all:

| Area | Pilot setting | Instead of |
| --- | --- | --- |
| Getting paid | `DEFAULT_SETTLEMENT_MODE=direct`: the buyer pays the brand's own courier in cash on delivery; the brand enters the tracking number; the platform invoices its commission on the 1st of each month ([ADR 0007](decisions/0007-direct-settlement-for-the-pilot.md)) | Merchant accounts and a courier contract |
| Signing in | `SMS_LOGIN_ENABLED=false`: an admin makes a single use invite link and sends it by hand | An SMS gateway |
| WhatsApp, voice notes, photo search | `WHATSAPP_ENABLED`, `SPEECH_TO_TEXT_ENABLED`, `VISUAL_SEARCH_ENABLED` all false; the interface explains each | A WhatsApp Business provider, a speech service, an image model |
| AI | `AI_DAILY_SPEND_LIMIT_USD=1`, then every feature works by hand until tomorrow; `AI_ENABLED=false` with no key | A larger budget |
| Alerts | Plain email through a free SMTP account | A monitoring service |
| Hosting | One Oracle Cloud Always Free ARM machine, or a laptop with a Cloudflare quick tunnel for demos | A paid server |

`GET /api/features` reports what is switched on, and the web app reads it.
Each switch is the only change needed when the matching provider is
connected.

## The shape of it

One server runs everything with Docker Compose from
[`docker-compose.prod.yml`](../docker-compose.prod.yml):

| Service | What it does |
| --- | --- |
| `caddy` | The only service with public ports. HTTPS with automatic certificates, the web app at `/`, the API at `/api` |
| `web` | The Next.js standalone build |
| `migrate` | Applies database migrations, then exits. The API waits for it |
| `api` | FastAPI under uvicorn, two worker processes, one per CPU |
| `scheduler` | Runs the timed jobs: markdowns, pool expiry, dispute windows, risk, forecasts, cache purge, monthly commission invoices, and the self checks that email alerts |
| `backup` | Dumps the database every 24 hours into `./backups` |
| `db` | PostgreSQL 16 with pgvector, no published port |
| `redis` | Redis 7 with a password, no published port |
| `prometheus` | Optional, `--profile monitoring`: scrapes the API's metrics and evaluates alert rules |

The web app and the API share one origin on purpose. On a slow phone
connection a separate API origin cost a CORS preflight round trip before every
call; on one origin there are none ([performance.md](performance.md)).

Every service has a memory limit, 4.4 GB in total, so one cannot starve the
others. Measured under load the whole stack peaked at about 650 MB
([oracle-free-tier.md](oracle-free-tier.md#measured)). A server with 2 CPUs
and 4 GB of memory is enough; the free Oracle machine has 12 GB. The images
are published for amd64 and arm64.

## Staging

Staging is the same compose file with staging settings, so it mirrors
production by construction. It runs on any machine with Docker:

```bash
cp .env.staging.example .env.staging
docker compose -f docker-compose.prod.yml --env-file .env.staging up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.staging exec api python -m khazana.seed --reset
```

Then open https://localhost. Caddy issues the certificate from its own local
authority, so the browser warns once. Staging shows the login code on the page
and runs the AI layer offline, which is what makes it safe for demonstrations.

CI starts exactly this stack on every push and runs the browser money path
through it.

## Deploying to production

### Once

1. **A server and a domain.** Point the domain's A record (and AAAA, if the
   server has IPv6) at the server. Open ports 80 and 443 and nothing else.
2. **Docker.** Install Docker Engine with the Compose plugin.
3. **The code.** `git clone` the repository onto the server, on the `main`
   branch or a release tag.
4. **The settings.** `cp .env.production.example .env.production` and fill in
   every value. Generate each secret with
   `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. The file
   stays on the server; it is git ignored.

### Start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Caddy obtains the certificate on first start, which needs the DNS record to
be live. The API refuses to start if any setting is unsafe for production, and
says which: the example secret, a printed login code, offline AI, the
development database password, a Redis without a password, plain HTTP, the
sandbox bank account, or no trusted proxy.

To use the published images instead of building on the server, set
`IMAGE_PREFIX=ghcr.io/syedo-maker/khazana` and `VERSION` to a release in
`.env.production`, then `docker compose ... pull` before `up -d`.

### Update

```bash
git pull                       # or check out the next release tag
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

The `migrate` service applies any new migrations before the API restarts.
Every migration has a tested downgrade, so a bad release can be rolled back
with `alembic downgrade <revision>` from inside the API container, then the
previous release's images.

### First data

A new production database is empty. Load the categories and make the first
admin on the server; the second command prints a single use sign in link:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -m khazana.manage load-categories
docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -m khazana.manage create-admin --phone 03001234567 --name "Your name"
```

`python -m khazana.manage login-link --phone ...` makes a new link for an
existing admin. Everyone else gets their link from the admin panel's Invites
page. `khazana.seed` is sample data for demos and never belongs here.

## Backups and restoring

The `backup` service writes a compressed, restorable dump of the whole
database to `./backups` on the server when it starts and every 24 hours after,
and keeps 14 days (`BACKUP_KEEP_DAYS`).

**A backup on the same disk as the database is not a backup.** Copy
`./backups` off the server every day, to object storage or another machine,
for example with `rclone sync ./backups r2:khazana-backups` from cron. This
needs an account with a storage provider, which is why it is on the launch
checklist rather than built in.

Uploaded photographs live in the `uploads` volume until object storage is
connected, and need the same treatment.

To restore, into a scratch database first, never straight over the live one:

```bash
bash scripts/restore.sh backups/khazana-<stamp>.dump khazana_restore_check
```

`scripts/verify-restore.sh` does a full backup, restore and table by table
comparison, and CI runs it on every push.

## Watching it

- **Health.** `GET /api/health` answers without touching the database;
  `GET /api/ready` checks it. Point an uptime monitor at the second.
- **Logs.** Every service logs to stdout, bounded to 50 MB per container. The
  API and the scheduler write one JSON object per line with a request id, which
  the API also returns as `X-Request-ID`, so a buyer's complaint can be traced
  to its log lines. `docker compose logs -f api` reads them; to keep them,
  point Docker's logging driver at a log service.
- **Metrics.** The API exports request counts and latency by route at
  `/metrics`, which Caddy refuses from the internet. Start Prometheus with
  `--profile monitoring` and reach it through an SSH tunnel on port 9090. The
  alert rules in [`deploy/prometheus/alerts.yml`](../deploy/prometheus/alerts.yml)
  fire when the API is down, when server errors pass 2%, and when the
  catalogue misses its latency budget.
- **Errors.** Set `SENTRY_DSN` to send unhandled errors to Sentry or a self
  hosted GlitchTip. Every report is stripped of the user, headers, cookies,
  body and query string first.
- **AI spend.** `GET /api/ai/status` shows the mode, the routed models and the
  spend cap, and the admin panel's AI costs page shows spend by feature and
  brand. The caps in `.env.production` stop spending before it happens.

## Alerts by email

The platform emails one address when something needs a person: a scheduled
job failed, the AI budget ran out for the day, the newest backup is more than
26 hours old, the API stopped answering `/ready`, the disk is nearly full, or
the API returned a server error. One email per kind every three hours at most
(`ALERT_COOLDOWN_MINUTES`). Alerts carry no personal data: a path, a request
id, an error type, a job name.

**Recommended: Gmail's SMTP server, free.** It needs a Google account with
2 Step Verification on, and an app password:

1. Turn on 2 Step Verification for the Google account, if it is not on.
2. Create an app password (Google account, Security, App passwords), named for
   example "Khazana alerts". Google shows 16 characters once.
3. In `.env.production`:

   ```
   ALERT_EMAIL_TO=you@example.com
   ALERT_EMAIL_FROM=the.gmail.address@gmail.com
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=the.gmail.address@gmail.com
   SMTP_PASSWORD=the 16 character app password
   ```

4. Restart: `docker compose ... up -d`. The scheduler sends pending alerts every
   five minutes.

Gmail allows about 500 messages a day, far more than alerts need. If you
would rather not use a personal Google account, Brevo's free plan (300 emails
a day, an account and a verified sender address) works the same way with
`SMTP_HOST=smtp-relay.brevo.com`. With no SMTP settings at all, alerts are
written to the log only.

## Running from a laptop

For demonstrating to a brand without a server, `scripts/tunnel.ps1` runs the
stack on the laptop with [`docker-compose.tunnel.yml`](../docker-compose.tunnel.yml)
and shares it through a Cloudflare quick tunnel: a public HTTPS address, no
account, nothing opened on the router. The address changes on every start and
the tunnel has no uptime guarantee, so it is for demos. Details at the end of
[oracle-free-tier.md](oracle-free-tier.md#running-from-a-laptop-for-a-demo).

## The launch checklist

What the code cannot do by itself. Each needs an account, a contract or a
decision. For the zero budget pilot, only the free steps in
[pilot-manual-steps.md](pilot-manual-steps.md) are needed; the rest of this
list is for moving beyond the pilot.

**Infrastructure**

- [ ] A server and a domain, with DNS pointing at it. Free for the pilot:
      Oracle Cloud Always Free and an sslip.io name.
- [ ] Off server backups: object storage and a daily copy of `./backups`.
- [ ] Object storage for uploads, replacing the local `uploads` volume.
- [ ] SMTP settings for the email alerts. Optionally, an outside uptime
      service watching `/api/ready`, since the scheduler cannot report its own
      server being down.
- [ ] Optional: an error tracking project for `SENTRY_DSN`.

**Providers**, each behind an interface that already has a sandbox
implementation production refuses:

- [ ] An SMS gateway for login codes, then `SMS_LOGIN_ENABLED=true`. Until
      then, invite links.
- [ ] Payment providers: JazzCash, Easypaisa and a card acquirer, in
      `services/payment_providers.py`. Each needs merchant documents. Until
      then, brands are settled directly by cash on delivery.
- [ ] A courier, in `services/courier_providers.py`. Until then, brands use
      their own couriers and enter the tracking number.
- [ ] A WhatsApp Business provider, with a verified business, an approved
      number and approved message templates, in `services/whatsapp_providers.py`.
- [ ] A speech to text service that handles Urdu, Punjabi, Sindhi and Pashto,
      as a `Transcriber`.
- [ ] An image embedding model for visual search, at `EMBEDDING_SERVICE_URL`.

**Settings and data**

- [ ] `BANK_ACCOUNT_TITLE` and `BANK_ACCOUNT_IBAN` for bank transfers, once
      any brand is settled through the platform.
- [ ] AI spend caps sized for real traffic.
- [ ] Real reference data: resale benchmarks, the standard size chart, impact
      factors, and the season calendar, whose Islamic dates are estimates to
      correct each year.
- [ ] Row level policies for buyers, before the API connects as anything
      other than the table owner. Today the application's own checks protect
      buyer data; the policies cover brand staff and admins.

**People**

- [ ] The decisions listed as open in [security.md](security.md) and the
      items the Phase 0 to 4 audit left for a product decision.
- [ ] A penetration test by someone other than the people who built it.

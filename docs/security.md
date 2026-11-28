# Security

How the platform protects accounts, money, data and the AI layer, what the
week 51 security pass found, and what is still open. Each control names the
code that enforces it and the test that proves it, because a control nobody
tests is a control nobody can rely on.

To report a vulnerability, open a private security advisory on the GitHub
repository rather than a public issue.

## Accounts and sessions

| Control | Where | Proved by |
| --- | --- | --- |
| Login by one time code, five codes an hour per phone, one a minute | `services/auth_service.py` | `tests/test_auth.py` |
| Twenty codes an hour per network address, across all phones, against SMS pumping | `request_otp` | `tests/test_session_hardening.py` |
| Five wrong guesses end a code | `verify_otp_and_login` | `tests/test_auth.py` |
| No one can register themselves as an admin | `verify_otp_and_login` | `tests/test_auth.py` |
| Refresh tokens stored as keyed hashes, rotated on every use | `issue_session`, `refresh_session` | `tests/test_session_hardening.py` |
| A rotated refresh token seen again after 60 seconds signs the user out everywhere | `refresh_session` | `tests/test_session_hardening.py` |
| Signing out, reuse and suspension end access tokens at once, not at expiry | `users.tokens_valid_after`, `api/deps.py` | `tests/test_session_hardening.py` |
| Brand memberships re read from the database on every request | `api/deps.py` | `tests/test_tenancy.py` |
| `X-Forwarded-For` ignored unless `TRUSTED_PROXY_COUNT` says how many proxies to trust | `client_ip` | `tests/test_session_hardening.py` |
| With SMS off, sign in is by an invite link: 32 random bytes, only a hash stored, single use under a row lock, expires after 72 hours, revocable | `services/invite_service.py` | `tests/test_invites.py` |
| Links are made only by admins, never for an admin role; the first admin's link is printed on the server by `khazana.manage` | `invite_service.create`, `manage.py` | `tests/test_invites.py` |
| A link never changes an existing account's role, and a new reseller stays unverified until an admin checks the business | `invite_service.accept` | `tests/test_invites.py` |
| Login codes are refused, with the reason, when they could only be sent by SMS and SMS is off | `auth_service.sms_codes_available` | `tests/test_invites.py` |

Tokens live in `sessionStorage` in the browser, so they do not survive the tab
and are not sent automatically with cross site requests. Moving the refresh
token to an httpOnly cookie is recorded as a later improvement in
`apps/web/lib/session.ts`.

## Access between tenants

Every route is checked twice by the test suite: once anonymously, which must
be refused unless the route is on a short public list, and once as another
brand's owner, which must not see the first brand's data
(`tests/test_route_auth.py`, `tests/test_route_tenancy.py`). PostgreSQL row
level policies are a second line behind the application's own checks, and the
session variables they read are proved to be set by
`tests/test_search_postgres.py`.

## Money

Money is integers in rupees, with database check constraints that the order
total, the commission and the brand's payout add up
(`models/commerce.py`). `tests/test_money_path_http.py` walks one order from
checkout to brand payout over HTTP and checks every amount and every
permission on the way. The value band rules of ADR 0001, the bargaining floor
and the markdown floor, are checked against thousands of random cases in
`tests/test_money_properties.py`.

In the pilot brands are settled directly ([ADR 0007](decisions/0007-direct-settlement-for-the-pilot.md)):
the platform holds no money, so there is no balance to steal. A direct order
takes cash on delivery only and creates no payment record; only the brand's
own staff or an admin can enter its tracking number or delivery outcome; a
tracking number is used once; commission is fixed on confirmation and billed
once per order; only admins issue invoices or mark them paid, and a brand sees
only its own (`tests/test_direct_cod.py`).

## Uploads

| Control | Where |
| --- | --- |
| Read in chunks, refused with 413 past 10 MB before the rest is read | `api/uploads.py` |
| Declared type checked against the file's own first bytes | `storage.validate_upload` |
| Images over 50 megapixels refused from the header, before decoding | `ai/images.py` |
| Every photograph re-encoded: GPS and all other metadata dropped, orientation applied first | `ai/images.prepare` |
| Voice notes over two minutes, empty, or not audio refused before paid transcription | `services/whatsapp_service.py` |
| Manifests capped at 400 rows and 60,000 characters | `ai/features/manifest_extract.py` |

Tests: `tests/test_upload_limits.py`.

## The AI layer and prompt injection

The rule in `docs/ai-architecture.md` holds: the model drafts, suggests,
scores and flags, and never decides money, approvals, bans or quoted stock.
Prompt injection is therefore a nuisance rather than a breach, because there
is nothing a persuaded model can do that the code lets through:

1. **Every prompt labels user text as data.** Each system prompt says so.
2. **No value can impersonate the prompt.** `gateway/prompts.neutralise`
   removes the section separator, fence tags and control characters from
   every filled in value.
3. **Prices are clamped in code.** A bargaining reply naming a price outside
   the band is clamped, and the persuaded sentence is replaced with the real
   price before the buyer sees it.
4. **Tools run as the signed in user.** A brand or buyer identifier the model
   supplies is dropped.
5. **Outputs are schema checked** before anything reads them.

Tests: `tests/test_prompt_injection.py`, and the injection cases in the eval
suites, which run offline in CI.

## Headers

The API sends `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, a
`Content-Security-Policy` of `default-src 'none'`,
`Cross-Origin-Resource-Policy: same-origin`, and `Cache-Control: no-store`
unless a route sets its own; HSTS in production. The web app sends a Content
Security Policy that allows connections only to itself and the API, plus
`Cross-Origin-Opener-Policy`, `Cross-Origin-Embedder-Policy: require-corp` and
`Cross-Origin-Resource-Policy: same-origin`. Caddy makes every page revalidate
(`no-cache`) while the hashed scripts stay cached for a year. Tests:
`tests/test_security_headers.py`, and the ZAP scan below.

An unhandled error returns a plain sentence, never a traceback, and emails the
operator the path, request id and error type only.

## Secrets and configuration

Production refuses to start with the example secret key, a printed login
code, offline AI or no API key while AI is on, SQLite, the development
database password, a Redis without a password, plain HTTP URLs, the sandbox
bank account while brands are settled through the platform, demo mode, or no
trusted proxy (`config.assert_production_ready`, `tests/test_production_guard.py`).
`.env` is git ignored and the pre-commit hooks refuse private keys. The CI
dependency scan also scans for committed secrets.

## Dependencies

- CI scans the repository with Trivy and **fails** on any high or critical
  advisory that has a fix. It was advisory until week 51, during which it had
  been reporting a critical remote code execution advisory in Next.js
  (GHSA-2464-fhr4-w9xw) that nothing acted on. Next.js is now 15.5.29 and the
  floor in `package.json` is `^15.5.29`.
- `pip-audit` checks the API's Python packages in CI.
- `npm audit` reports no vulnerabilities in the web app, production or
  development.

## Backups

`scripts/backup.sh` writes a compressed, restorable dump; `scripts/restore.sh`
restores one. `scripts/verify-restore.sh` takes a backup, restores it into a
scratch database and compares every table's row count, and CI runs it on
every push against a seeded database. Scheduling and off machine copies are
in `docs/deployment.md`.

## The zero budget pilot pass, 2026-11-28

Every scanner here is free and ran locally against the production images and
the staging stack, nothing signed up for:

| Scan | Result |
| --- | --- |
| OWASP ZAP baseline, passive, the web app through Caddy | 0 failures, 65 passes; 3 accepted findings below |
| OWASP ZAP API scan, active, every operation from the OpenAPI description, 1,553 requests | 0 failures, 0 warnings, 119 passes, no server errors |
| Trivy, both production images | 0 fixable high or critical after the fixes below; 1 accepted false positive |
| `pip-audit`, the 48 packages in the production API image | No known vulnerabilities |
| `npm audit`, the web app and the browser tests | No vulnerabilities |
| gitleaks, all 161 commits | 1 false positive, recorded in `.gitleaksignore` |

Run them again with `bash scripts/zap-scan.sh` against a running staging
stack; CI runs the same ZAP scans on every push.

| Finding | Source | Severity | Fix |
| --- | --- | --- | --- |
| After a Docker restart the metrics directory came back root owned, and every API request, the health check included, returned 500 | Found while scanning | High | An explicit tmpfs mode, and a metrics failure can no longer fail a request (`tests/test_observability.py`) |
| 56 high or critical OS advisories with fixes in the API image (OpenSSL, GnuTLS, Kerberos, PAM, Perl), on an old Debian snapshot | Trivy | High | Python 3.11.15, `apt-get upgrade` at build, and the unused ensurepip wheels removed |
| 7 OS advisories in the web image, and 10 in npm's bundled packages | Trivy | High | `apt-get upgrade` at build; npm removed from the runtime image, which does not use it |
| Pages marked cacheable by shared caches for a year: a CDN, the Cloudflare tunnel included, could serve a page pointing at deleted scripts | ZAP 10015 | Low | Caddy sends `no-cache` for pages |
| `Cross-Origin-Embedder-Policy` and `Cross-Origin-Resource-Policy` missing from pages; the API's CORP was `same-site` | ZAP 90004 | Low | Added; the API is now `same-origin` |
| The switched off WhatsApp webhook answered 503, which reads as a server fault | ZAP 100000 | Low | 404 while WhatsApp is off |
| The scheduler always showed unhealthy: it inherited the API's HTTP health check | Found while measuring | Low | A heartbeat file the scheduler's own check reads |

Accepted, each recorded with its reason in `deploy/zap/*.tsv`:

- **ZAP 10015, pages without `no-store`.** Pages are public shells with no
  personal data; data comes from the API, which is `no-store`. `no-store`
  would also turn off the back and forward cache on phones.
- **ZAP 10049, cacheable scripts.** Deliberate: they carry a content hash.
- **ZAP 10055, inline scripts in the CSP.** Listed under "Still open".
- **ZAP 100001 in the API scan.** Paths outside `/api` are web pages on the
  same origin.
- **Trivy, setuptools 70.3.0 (CVE-2025-47273).** Trivy reads pip's own
  `vendor.txt`, which names the setuptools release pip copied `pkg_resources`
  from. The advisory is in setuptools' package download code, which pip does
  not include, and the image has the newest pip. The installed setuptools is
  84.2.1.
- **gitleaks, `tests/conftest.py`.** The test suite's placeholder
  `SECRET_KEY`, used only by pytest.

## What the week 51 pass found and fixed

| Finding | Severity | Fix |
| --- | --- | --- |
| Critical RCE advisory in the installed Next.js, reported by CI and ignored | Critical | Upgraded; the scan now blocks |
| Access tokens kept working for up to an hour after sign out or suspension | High | `tokens_valid_after` checked on every request |
| A stolen refresh token used first kept the session; the real user was signed out | High | Reuse detection signs everyone out |
| No per address limit on login codes: one script could send unlimited SMS | High | Twenty an hour per address |
| `X-Forwarded-For` trusted as given, which would defeat any per address limit | Medium | Only trusted behind a configured proxy |
| Uploads read fully into memory before the size check | Medium | Chunked reads with a 413 |
| Decompression bombs decoded in full, or a 500 | Medium | Pixel cap from the header |
| Voice notes of any length sent for paid transcription | Medium | Two minute cap, type check |
| No security headers on the API, no CSP on the web app | Low | Added, with tests |
| The production guard had no tests and missed five unsafe settings | Low | Five checks added, all tested |
| Phone photos lost their orientation when metadata was stripped | Low | Orientation applied before re-encoding |

## Still open

- The refresh token is readable by script in the browser. An httpOnly cookie
  would close that, at the cost of CSRF handling.
- Inline scripts are allowed by the web app's policy because Next.js emits
  them. A nonce based policy would remove that.
- Untrusted text in prompts is labelled and neutralised but not yet wrapped in
  explicit fence tags. New prompt versions with fences were considered in week
  53 and left out: the renderer already stops a value impersonating the
  prompt, and new versions would change model behaviour and need every suite
  re-baselined, for little added protection. Worth doing with the next prompt
  revision for the bargaining and buyer assistant prompts.
- No web application firewall or bot protection in front of the login page
  beyond the rate limits. Worth adding with the real SMS gateway in Phase 6.
- Invite links travel over WhatsApp. Anyone who can read the recipient's
  messages before they open it could use it; it works once, expires in 72
  hours and can be revoked, and the person's own sign in then fails, which
  they would report.
- The beta privacy notice and terms were written for the pilot, not reviewed
  by a lawyer. Have them reviewed before inviting real people.
- A penetration test by someone other than the people who built it.

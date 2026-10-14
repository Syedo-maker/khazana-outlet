# Audit: weeks 1 to 22

Date: 2026-10-14
Audited commit: `6b6f9a0` on `feature/phase3-marketplace`
Scope: Phase 1 weeks 1 to 6, Phase 2 weeks 7 to 16, Phase 3 weeks 17 to 22.

## How this was checked

Not by reading the code alone. Every claim below was run:

- Dependencies installed from scratch in a clean `python:3.11-slim` container
  and a clean `node:22-slim` container, from `pyproject.toml` and
  `package-lock.json` only.
- Lint, format, type check, the full test suite, the web lint and type check,
  and the AI eval suites.
- A fresh PostgreSQL database created, migrated and seeded, with an API served
  against it, and the real flows exercised over HTTP: signup, brand
  registration, lot creation, the discount band guard, the manifest rule,
  photo upload, submission, the approval gate, protection levels, the region
  lock, the buyer catalogue and withdraw.
- The whole git history scanned for secrets, em dashes and AI attribution.

The audit database was dropped afterwards and the existing development
database was not modified. It still holds its 30 seeded lots.

## Summary

The platform works. The business rules that matter are real and enforced: the
manifest sum rule, the discount band, the approval gate, the tenant boundary
and the brand protection levels all behaved correctly against live data, with
error messages a brand could act on.

Two things are badly broken in the development environment, and both are
invisible to the test suite because the tests never touch the paths that fail.
One of them stops every file upload in Docker. The other makes two of the six
AI endpoints return a bare 500 in the default development mode.

| | Found | Fixed |
| --- | --- | --- |
| Critical | 1 | 1 |
| High | 4 | 1 |
| Medium | 7 | 1 |
| Low | 5 | 1 |

Plus the missing changelog. See "Fixes applied" below for what was repaired
and "Still open" for what was deliberately left.

## Step 1: work against the plan

| Week | Module | Planned | Status | Problems |
| --- | --- | --- | --- | --- |
| 1 | Repository and tooling | Monorepo `apps/web`, `apps/api`, `apps/ai`, `packages/shared`, `docs`. Git hygiene, `.gitignore`, `.env.example`, lint, format, pre commit hooks, CI | Partly done | `apps/ai` and `packages/shared` never created. Pre commit config exists but no hook is installed, so nothing is refused locally. CI is real and green |
| 2 | Database schema | Every table the later phases need, Alembic migrations, Mermaid ERD | Done and working | 27 tables, ERD generated from the models. The migration strategy itself is flawed, see H3 |
| 3 | Auth and roles | Phone OTP, email, sessions, role based access, row level rules with tests | Done and working | Verified end to end over HTTP. Cross tenant reads answer 404, not 403 |
| 4 | UI shell | Tokens, layout, navigation, forms, empty, loading and error states, mobile first, Urdu and English direction | Done and working | Direction derived once from the locale. Touch targets defined. Three locales at 92 keys each |
| 5 | AI gateway | Model routing, prompt registry, structured output, retries, timeouts, cost logging, spend caps, cache layer, kill switch | Partly done | Everything present and wired except a response cache. Only Anthropic prompt caching and prompt file memoisation exist, so an identical repeat input is paid for again. See M4 |
| 6 | Eval harness and seed data | A runnable eval per planned AI feature, plus a realistic generator | Partly done | Three eval suites for six features. Seed generates no embeddings, so search returns nothing against seed data. See H4 and M5 |
| 7 to 8 | Photo to listing | Photos in, a complete draft listing out | Done but broken | The feature is sound and has four fixtures. It cannot be reached in Docker because photo upload fails first. See C1 |
| 9 | Manifest extraction | Messy spreadsheet in, clean manifest lines out, reconciled and flagged | Done but broken | Returns HTTP 500 in the default development mode. No committed fixture. See H1 |
| 10 to 11 | Pricing engine | Discount band and days to sell from category, age, season, condition, price | Done but broken | Same as week 9. No committed fixture, so a 500 in offline mode. See H1 |
| 12 to 13 | Visual and semantic search | Image and text embeddings in pgvector | Partly done | Infrastructure, model and endpoint all exist and the PostgreSQL only tests pass. `GET /ai/search` returns zero hits against seed data because no embeddings are generated. See M5 |
| 14 to 15 | Multilingual assistant | Urdu, Roman Urdu and English, answering from the catalogue through tools | Done and working | Six fixtures, eval suite passes, tool calling against real catalogue functions |
| 16 | Listing quality and risk scoring | Scores a draft and routes the doubtful to review | Done and working | Verified live: the queue returned score 30, band medium, one finding, ordered riskiest first |
| 17 to 18 | M2 Brand portal | Registration, documents, verification workflow, dashboard, policy | Done but broken | Registration, role upgrade, dashboard and policy verified live. Document upload fails in Docker for the same reason as photos. See C1 |
| 19 to 21 | M3 Catalog and manifests | Lot creation, manifest editor, bulk upload, photo pipeline, grading, states | Done but broken | Everything verified live except upload in Docker. The pipeline itself is correct: 68 KB and 2400x1800 became 4.9 KB at 1024x768, and the duplicate was refused |
| 22 | Approvals and protection | Approval gate with audit, private and unbranded, region lock, withdraw | Done and working, UI incomplete | Every rule verified live, including that the real brand name never reaches the payload for an unbranded lot. No screen exists for the approval queue, the protection level or the region lock. See M6 |

## Step 2: does it work

| Check | Result |
| --- | --- |
| API dependencies install from scratch, clean container | Pass. All runtime imports resolve. ruff 0.16.10, mypy 2.4.0, pytest 9.1.1, matching the pins |
| Web dependencies install from scratch, clean container | Pass. `npm ci` exit 0, 305 packages |
| `--no-cache` image build | One attempt failed on pip exit 2, consistent with a network timeout on this connection. The clean container install above succeeded and CI builds pass, so this is transient rather than a defect. See L5 |
| ruff check | Pass |
| ruff format | Pass, 88 files |
| mypy | Pass, 61 source files |
| pytest | Pass, 349 passed, 8 skipped |
| Web lint and type check | Pass |
| AI eval suites, offline | Pass, all suites |
| Migrations apply to an empty database | Pass |
| Seed a fresh database | Pass, 5 brands, 30 lots, 127 manifest lines, 12 resellers, 8 orders |
| CI on the audited commit | Pass, all six jobs |

### Flows exercised by hand

| Flow | Result |
| --- | --- |
| OTP request, verify, session, `/auth/me` | Pass. A new account starts as a reseller |
| Brand registration and the role upgrade to brand | Pass |
| Brand dashboard and policy | Pass |
| Lot creation | Pass. Draft, at the brand default protection level, code `LOT-4FQQJGV` |
| Discount floor guard | Pass. "That is a 20 percent discount. Your floor is 50 percent, so the lot price needs to be at most 50,000 PKR" |
| Manifest sum must match | Pass. "The manifest adds up to 90 pieces, which is 10 less than the lot total of 100" |
| Balanced manifest accepted | Pass |
| Photo pipeline | Pass once storage was writable. 68430 bytes to 4895, 2400x1800 to 1024x768 |
| Duplicate photograph refused | Pass |
| Non image upload refused | Pass. Rejected on magic bytes, not the declared type |
| Readiness checklist | Pass. Lists every blocker at once |
| Submit for approval | Pass |
| Approval queue with risk score | Pass |
| Approval refused for an unverified brand | Pass |
| Approve and publish | Pass |
| Approval trail | Pass. Submitted then approved, with the protection level at each step |
| Unbranded refused without a label | Pass |
| Unbranded hides the brand name | Pass. The real name is absent from the response body, not merely hidden in the client |
| Stock city cannot be region locked | Pass |
| Region lock hides the lot from that city | Pass. Six visible, five from Karachi |
| Withdraw clears the approval | Pass |
| Bulk manifest import | Fail. HTTP 500, no fixture |
| Risk score endpoint | Fail. HTTP 500, no fixture for this input |
| Semantic search | Returns zero hits. No embeddings in seed data |

## Step 3: findings

### Critical

**C1. Every file upload fails in the Docker development environment.**
`docker-compose.yml` mounts the named volume `api_uploads` at `/app/uploads`.
The directory does not exist in the image when `chown -R khazana:khazana /app`
runs, so Docker creates the mount point owned by root while the container runs
as uid 1000. Proven directly:

```
running as: khazana uid 1000
STORAGE_LOCAL_PATH=/app/uploads
  lots: PERMISSION DENIED
  documents: PERMISSION DENIED
```

The failure surfaces as a bare HTTP 500 with the traceback
`PermissionError: [Errno 13] Permission denied: '/app/uploads/lots'`.

This breaks `POST /lots/{lot_id}/photos` and `POST /brands/{brand_id}/documents`,
which means the photo pipeline, the photo to listing feature and brand
verification are all unusable in Docker. It is the same bug class already
fixed for the web container's `.next` volume, and it was missed here.

The test suite does not catch it because `conftest.py` points storage at a
`tmp_path` on the local filesystem, which is correct for tests and means no
test ever writes to the volume.

### High

**H1. Two of the six AI endpoints always return 500 in the default
development mode.** `AI_OFFLINE=true` is the default everywhere. In offline
mode the client replays a recorded fixture keyed by a hash of the input, and
there are fixtures for only three features:

| Feature | Fixtures |
| --- | --- |
| `assistant_buyer` | 6 |
| `listing_from_photos` | 4 |
| `risk_scoring` | 5 |
| `manifest_extract` | 0 |
| `pricing` | 0 |
| `embedding` | 0 |

So `POST /ai/manifests/extract`, `POST /lots/{id}/manifest/import` and
`POST /ai/lots/{id}/price-suggestion` cannot work without a live API key. The
test suite passes because `test_manifest_extract.py` and `test_pricing.py`
monkeypatch `client.FIXTURE_DIR` to a temporary directory and write their own
fixture. Green tests therefore say nothing about whether these endpoints work.

Risk scoring also fails for any input that is not one of its five recorded
hashes, which is why the live call returned 500 even though its eval passes.

**H2. `AiClientError` is never mapped to an HTTP status.** It subclasses
`RuntimeError`, not `AppError`, so the handler in `main.py` does not see it.
Every offline cache miss, every malformed model reply and every empty reply
becomes an unhandled 500 with no message for the caller. The underlying
message is good and the caller never sees it.

**H3. An existing database can never pick up a schema change.** Migration 0001
builds the schema with `Base.metadata.create_all`, so it is a moving baseline
rather than a snapshot. A new column appears automatically for a database
created from scratch and never for one that already exists, and writing a
normal `op.add_column` migration makes a fresh `upgrade head` fail with
"duplicate column". Confirmed on the live development database, which is
missing `lot_photos.checksum` while the models and a fresh migrate both have
it. Every future column has the same problem.

**H4. Three of six AI features have no eval suite.** `CLAUDE.md` section 4
states "Every AI feature ships with an eval, and the eval is written first".
`manifest_extract`, `pricing` and the embedding path have none. They have
pytest coverage, which is not the same thing: an eval grades output quality
against a test set, a unit test checks the plumbing.

### Medium

**M1. `develop` and `main` have diverged.** Three commits sit on `develop` and
not on `main`, and one sits on `main` and not on `develop`. Pull request #2
merged `feature/phase2-ai-engine` straight into `main`, bypassing the flow in
`CLAUDE.md` section 3b, which says feature branches merge into `develop` and
`develop` merges into `main` on release.

**M2. Phase 3 is not merged anywhere.** `feature/phase3-marketplace` is 14
commits ahead of `develop` with no pull request open. Anyone opening the
repository at the default branch sees Phase 2 and none of weeks 17 to 22.

**M3. The default database URL points at the wrong database on this machine.**
`config.py` defaults to `localhost:5432` while `.env.example` says
`localhost:55432`. Port 5432 here is a separate native PostgreSQL 17 service,
so running the API natively without a `.env` silently targets an empty
database that looks identical.

**M4. The week 5 cache layer is only half built.** Anthropic prompt caching is
set on the system block, and prompt files are memoised with `lru_cache`.
Neither avoids a call. There is no response cache keyed on the input, so the
same listing scored twice is billed twice. For a platform whose cost control
is a stated design goal, this is the piece that would actually reduce spend.

**M5. Seed data generates no embeddings.** The `embeddings` table is empty
after a seed, so `GET /ai/search` returns `{"hits": [], "method": "vector"}`.
Weeks 12 and 13 cannot be demonstrated or sense checked against seed data, and
M4 search in weeks 23 and 24 will be built against an empty index.

**M6. Brand protection has no interface.** The API supports the approval
queue, the protection level and the region lock, and all are tested, but
`catalog.queue` and `catalog.setVisibility` are unused by the web app and the
region lock has no client method at all. A brand cannot change its own
protection level without calling the API directly, which is the single feature
most likely to be needed in a hurry.

**M7. Pre commit hooks are configured but not installed.** `.pre-commit-config.yaml`
exists and `.git/hooks` contains only samples, so week 1's "a repository that
refuses bad commits" refuses nothing locally. CI still enforces the rules.

### Low

**L1. The planned monorepo layout was never created.** `apps/ai` and
`packages/shared` do not exist; the AI layer lives in
`apps/api/src/khazana/ai`. `CLAUDE.md` section 4 still says "the AI gateway in
`apps/ai`" and `.gitignore` still has `/apps/ai/.cache/` and
`/apps/ai/evals/results/`. The code is fine; the references are stale.

**L2. Seed never sets `approved_by_user_id`.** Seeded live lots have an
`approved_at` and no recorded approver, although the `ListingApproval` rows do
carry an actor.

**L3. Seed lot codes do not match the real generator.** Seed writes sequential
`LOT-00001`, while `new_lot_code` is random and deliberately excludes
characters that are confusable when read aloud. Seed codes contain `0`, `1`
and `5`.

**L4. `visibility_filter` accepts an anonymous caller that no endpoint
exposes.** `GET /catalog` requires authentication, so the `role=None` branch is
unreachable. Harmless, but it is untested surface.

**L5. One `--no-cache` image build failed.** pip exited 2 partway through the
dependency download. A clean container install of the same dependencies
succeeded immediately afterwards, and CI builds pass, so this reads as a
network timeout rather than a defect. Worth noting because this connection has
produced the same failure before.

### Checked and clean

- No `.env` file has ever been committed. No API key, private key or
  credential appears anywhere in the history.
- `.gitignore` is correct, including the `uploads/` rule at any depth.
- No em dashes or en dashes in any commit message in the entire history.
- No AI attribution anywhere. The sole author across all 51 commits is
  `Syedo-maker <finalyear860@gmail.com>`. The only matches for "Claude" are the
  filename `CLAUDE.md` and one factual sentence explaining that the embedding
  model is deliberately not Claude. The two commits authored by
  `GitHub <noreply@github.com>` are the merge commits created by pull requests
  #1 and #2 on github.com.
- No `TODO`, `FIXME`, `XXX` or `HACK` anywhere in the source.
- No stubs, no `NotImplementedError`.
- Upload validation checks magic bytes rather than the declared content type,
  and rejects an HTML file claiming to be a PNG.
- Tenant isolation holds. A second brand reading, editing or approving another
  brand's lot receives 404, and the response body contains neither the brand
  name nor the lot code.
- Every hardcoded host and port found is a settings default that an environment
  variable overrides, which is correct. The one that is wrong is M3.

## Step 4: GitHub

| Check | Result |
| --- | --- |
| Uncommitted changes | None. Working tree clean |
| Unpushed commits | None. Local `HEAD` matches `origin/feature/phase3-marketplace` at `6b6f9a0` |
| CI on the latest commit | Pass. Repository rules, API lint and types and tests, migrations, web, evals, scan |
| Open pull requests | None |
| Merged pull requests | #1 `feature/phase2-ai-engine` into `develop`, #2 `feature/phase2-ai-engine` into `main` |
| Forgotten branches | `feature/phase2-ai-engine` still exists locally and on the remote although both its pull requests merged |
| Branch flow followed | No. See M1 and M2 |
| Em dashes in messages or pull requests | None |
| AI attribution in messages or pull requests | None |

## Step 5: documentation

| Document | State |
| --- | --- |
| `README.md` | Exists. The containerised steps it gives were run during this audit and work |
| `docs/architecture.md` | Exists, updated to the containerised commands and the six CI jobs |
| `docs/database-schema.md` | Exists, generated from the models, currently accurate |
| `docs/ai-features.md` | Exists |
| `docs/ai-architecture.md` | Exists. Not on the required list but is the authority for the AI boundary |
| `DEPLOYMENT.md` | Exists at the repository root rather than `docs/deployment.md` |
| `CHANGELOG.md` | Missing |
| `docs/product-requirements.md` | Missing |
| `docs/api-reference.md` | Missing. The OpenAPI document is served at `/openapi.json` and has every operation named explicitly |
| `docs/setup-guide.md` | Missing. `README.md` and `DEPLOYMENT.md` cover the ground |
| `docs/user-guides/` | Missing |
| `docs/decisions/` | Missing |

Worth being fair about this list: the roadmap schedules the full documentation
set, including `docs/api-reference.md`, `docs/setup-guide.md`,
`docs/user-guides/`, `docs/decisions/` and `CHANGELOG.md`, for Phase 5 weeks 45
and 46. They are not overdue, they are not yet started. The two that are
genuinely worth having now are `CHANGELOG.md`, because it is cheap and the
history to fill it exists, and moving `DEPLOYMENT.md` to the path the plan
names so the later work does not have to find it.

## Fixes applied, 2026-10-14

Verified against a running stack, not just a passing test.

| Finding | State | Evidence |
| --- | --- | --- |
| C1 uploads volume root owned | Fixed | Both image stages create `/app/uploads` before dropping privileges. On the real volume path a photograph uploads with 201 and stores at 4895 bytes, and an NTN document uploads with 201 |
| H2 `AiClientError` unmapped | Fixed | Now an `AppError` carrying 502 and `ai_unavailable`. A manifest import with no fixture answers 502 with "No fixture for manifest_extract ... Offline mode cannot invent a reply" instead of a blank 500 |
| M3 wrong default database port | Fixed | `config.py` now defaults to 55432, matching `.env.example` and what compose publishes |
| L1 stale `apps/ai` references | Fixed | `CLAUDE.md` and `.gitignore` name the real paths. The eval results directory was previously not ignored at all |
| Missing `CHANGELOG.md` | Fixed | Added, grouped by roadmap week, including the known deviations from the plan |

Four regression tests were added, and the suite is 353 passing. Two of them
guard C1 by reading the Dockerfile, because the runtime failure is in the
image and tests point storage at a temporary directory, which is precisely why
the bug survived this long.

**One manual step is needed on any machine that ran the stack before this.**
Docker seeds a named volume only once, so the existing volume is still root
owned:

```powershell
.\scripts\dev.ps1 down
docker volume rm khazana_api_uploads
.\scripts\dev.ps1 up
```

### Second pass, decisions taken 2026-10-14

| Finding | State | Evidence |
| --- | --- | --- |
| M7 git hooks not installed | Fixed | pre-commit installed as a dev dependency and the hooks installed on the machine. The ruff hook rev now matches the exact pin in pyproject, which it did not. A commit-msg hook was added because nothing checked messages at all. Verified by attempting real commits: an em dash, an en dash range, a Co-Authored-By trailer and a generated-with footer are each refused, and a message that mentions CLAUDE.md still commits |
| M5 seed generates no embeddings | Fixed | 30 lots seeded, 30 vectors written at 768 dimensions, and a search that returned nothing now returns hits through the vector path. Costs nothing: the provider is local. The similarity scores come back at zero, because a hash is not a model of meaning, so the mechanism is proved and the ranking quality is not |
| H4 three features have no eval | Fixed for two of three | Fifteen cases each for manifest extraction and pricing, 11 of them mandatory. All five suites pass at zero cost. The embedding path still has no suite, see below |
| H1 no fixtures for those two features | Fixed, with a caveat | 45 fixtures committed. The endpoints no longer 500 for a recorded input, and three new tests require every endpoint backed feature to have both a fixture and a suite. An unrecorded input still cannot be served offline, by design: the fixture key hashes the rendered prompt, so the refusal is correct and now explains itself |

Cost of the above: zero. The fixtures turned out to be hand written golden
replies rather than live recordings, which is how the three existing suites
already worked. The estimate for recording them live was about 65 cents, and
it was not needed.

Two further defects were found while doing this work, both in the gates
themselves:

- The pre push gate scans tracked files for attribution lines and excludes the
  few that must name what they forbid. The new message checker was not on that
  list, so adding it broke the gate on its own documentation. Fixed, and the
  reason is now written at the top of the script.
- The first version of the message hook was inline in the YAML and silently
  matched nothing, reporting Passed on a message containing an em dash. The
  byte escapes did not survive the YAML and shlex round trip, and grep -P then
  behaved differently under pre-commit's environment with its error hidden by
  a stderr redirect. The logic moved into a script that tests its own
  detection and refuses to approve anything if that self test fails.

### Still open

Everything below was left alone deliberately. Each one either needs a decision,
spends money, or changes how a feature behaves.

| Finding | Why it was not fixed here |
| --- | --- |
| H3 migration baseline is not frozen | Changing how the schema is created is the opposite of a small, safe fix, and week 42 already owns it |
| M1 `develop` and `main` diverged | Reconciling published branches changes shared history and needs a decision about which lineage wins |
| M2 Phase 3 unmerged, 19 commits, no pull request | Opening it is a judgement about whether weeks 17 to 22 are a release boundary |
| M4 no response cache | A new caching layer is a feature, not a repair |
| M6 brand protection has no interface | Three new screens |
| H4, the embedding path | Still has no eval suite. Judging embedding quality needs a real embedding service, not the local hash, so the suite would currently grade the stub |
| M4 no response cache | Moved to week 53, the AI cost pass, and logged as debt |
| L2, L3, L4 | Cosmetic. Worth doing alongside the next change to those files rather than on their own |

## Recommended order of fixes

1. C1, the uploads volume. One line in the API Dockerfile, mirroring the fix
   already made for the web container. Nothing else can be used in Docker until
   this is done.
2. H2, map `AiClientError` to an `AppError`. Small, and it turns every AI
   failure from a blank 500 into a sentence.
3. H1, record fixtures for `manifest_extract` and `pricing`, and add a test
   that every feature in `AiFeature` with an endpoint has at least one
   committed fixture, so this cannot silently recur.
4. M1 and M2, open the pull request for Phase 3 into `develop`, then reconcile
   `develop` and `main`.
5. H3, decide whether to freeze the migration baseline now or at week 42, and
   until then document the reset path in `DEPLOYMENT.md` where a developer will
   actually look.
6. M3, align the `config.py` default with `.env.example`.
7. H4 and M5, the missing evals and seed embeddings, before M4 search is built
   on top of an empty index in week 23.

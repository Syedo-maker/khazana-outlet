# Contributing

Thank you for helping. This file is the short version of how work gets into
this repository. Getting the platform running locally is in
[docs/setup-guide.md](docs/setup-guide.md).

## The rules that are checked

CI fails a pull request that breaks any of these, and
`bash scripts/prepush-check.sh` checks them before you push:

- **English** in code, comments, commit messages, pull requests and docs.
  Text shown to shoppers in the product may be Urdu or Roman Urdu.
- **No em dashes or en dashes**, anywhere in the repository or in commit
  messages. Use a comma, a colon, a full stop or a hyphen. Write ranges as
  `70-80%`.
- **Conventional Commits**: `feat(scope): ...`, `fix:`, `docs:`, `test:`,
  `perf:`, `build:`, `ci:`. One meaningful change per commit.
- **The commit author is a person**, under their own name and email.

## Branches and pull requests

- Work on `feature/<area>-<short-name>`, branched from `develop`.
- Open the pull request into `develop`. `develop` merges into `main` on
  release, and a version tag on `main` publishes the release.
- Every CI job must pass before merge. They are listed in
  [docs/development.md](docs/development.md).
- The repository is public. Never commit a credential, customer data, real
  brand data or the terms of a signed agreement. `.env` and its filled in
  copies are ignored; keep them that way.

## Before you push

```powershell
.\scripts\dev.ps1 check          # lint, format, types and tests, as CI runs them
.\scripts\dev.ps1 evals          # every AI eval suite, offline
bash scripts/prepush-check.sh    # the repository rules
```

A change to a route regenerates the API reference:
`python scripts/generate-api-reference.py`. A change to the models needs a
migration, and `docs/database-schema.md` regenerated with
`python scripts/generate-erd.py`. Tests fail when either is stale.

## How the code is built

- **Tests with every fix.** A bug fix comes with a test that fails without
  it.
- **Policy is data.** Commission, discount bands, protection rules, lot
  minimums and courier choice live in the database, never in code.
- **AI goes through the gateway.** No module constructs the Anthropic client;
  `run_feature` in `apps/api/src/khazana/ai/gateway` is the only way to call a
  model ([ADR 0002](docs/decisions/0002-one-ai-gateway-offline-by-default.md)).
- **Every AI feature ships with an eval, written first.**
- **AI never decides money, approvals, bans or quoted stock.** It drafts,
  suggests, scores and flags. The one exception, choosing inside a band a
  brand set, is [ADR 0001](docs/decisions/0001-ai-value-bands.md), and its
  four conditions are all required.
- **A decision that is expensive to reverse gets an ADR** in
  [docs/decisions/](docs/decisions/).

## Reporting a security problem

Open a private security advisory on the GitHub repository rather than a
public issue. [docs/security.md](docs/security.md) describes the controls in
place.

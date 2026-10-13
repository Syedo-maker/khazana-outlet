# Khazana Outlet - Working Rules

These rules apply to every session and every task in this project.

## 1. Skills first

Before starting any task, search for a skill that fits the task using the
find-skill skill. First check the skills already available in the session,
then search wider only if nothing installed fits.

- If a good skill exists, name it and use it.
- If nothing fits, say so plainly and continue with the task normally.

## 2. Language

Communicate only in English. This covers replies, code comments, commit
messages, PR titles and descriptions, documentation, changelogs and issue
text. No Roman Urdu or Urdu in any of these.

## 3. Git and GitHub rules

These apply every time anything is written or pushed.

- No em dashes anywhere. Not in commit messages, PR titles, PR
  descriptions, README, docs, code comments or changelogs. Use a comma, a
  colon, a full stop or a normal hyphen (-) instead. The same applies to
  en dashes in ranges: write "70-80%", not an en dash range.
- Never credit an AI assistant as author or contributor. No
  "Co-Authored-By" lines, no "Generated with" footers, no AI mentions in
  commits, PRs, README or docs. The commit author is the repository owner
  only, using his own git name and email.
- Before every push, check all commit messages and all changed files for
  em dashes and AI mentions, and remove anything found. Treat this as a
  real pre-push gate, not an afterthought.

### Pre-push check

Run this from the repository root before pushing, or let CI run it:

```bash
make prepush          # or: bash scripts/prepush-check.sh
```

It checks tracked files and the commits being pushed for em dashes, en
dashes and AI attribution lines, and checks the commit author. It exits
non zero on any violation, and the CI workflow runs it as a required job.

Two traps it already works around, so do not replace it with a one line
grep:

- `git grep -P` does not read the byte escape form as bytes at all,
  so it silently finds nothing and reports a false clean. The script pipes
  `git ls-files` into real grep instead.
- `grep -P` in Windows git bash rejects the code point spelling outright,
  so the byte form is the only portable one.

## 3b. Publishing cadence

Push as the work lands, not in one batch at the end.

- After each meaningful piece of work, make a Conventional Commit and push it.
  A phase, a module, a bug fix and a documentation update are each their own
  commit. Do not accumulate a day of work into one commit.
- Run the gate before every push: `make prepush`. A failed gate means nothing
  is pushed until it is fixed.
- Feature work goes on `feature/<module>-<short-name>`, merges into `develop`
  through a pull request, and `develop` merges into `main` on release.
- The repository is public. Anything committed can be read by anyone, so no
  credentials, no customer data, no brand data from a real brand, and no
  unredacted commercial terms from a signed agreement.

## 3c. Lint, format and types

The whole development environment runs in containers. One entry point:

```powershell
.\scripts\dev.ps1 check        # lint, format, types and tests, what CI runs
.\scripts\dev.ps1 fix          # apply the automatic fixes
.\scripts\dev.ps1 test         # tests only
.\scripts\dev.ps1 pgtest       # the PostgreSQL only tests, disposable database
.\scripts\dev.ps1 up           # the stack: API on 8000, web on 3000
```

`Get-Help .\scripts\dev.ps1 -Full` lists all sixteen commands, and
`DEPLOYMENT.md` documents the environment, the troubleshooting notes and what
is still missing before a real deployment. Run `check` before every push.

Two environment facts that bite if forgotten:

- The container database publishes on host port **55432**, not 5432. A native
  PostgreSQL 17 service on this machine already holds 5432. Host tooling aimed
  at `localhost:5432` talks to that install, not to the container, and the two
  look identical until one turns out to have none of the data.
- `dev.ps1` does not run its docker calls under `ErrorActionPreference = Stop`.
  Windows PowerShell 5.1 turns a native command's redirected stderr into error
  records, and docker compose writes all its progress there, so piping the
  script's output used to fail on the first progress line while every container
  started correctly. Do not add `Stop` back.

For a lint only run without starting anything, `scripts/lint.ps1` still works:

```powershell
.\scripts\lint.ps1              # lint and format check
.\scripts\lint.ps1 -Fix         # apply the automatic fixes
.\scripts\lint.ps1 -Types       # also run mypy
.\scripts\lint.ps1 -Docker      # force the container path
```

It runs the pinned tools natively when they work, which takes about two
seconds and needs no network. It falls back to Linux containers when they do
not, which is what happens if Windows Smart App Control is blocking unsigned
executables again. Smart App Control is currently off, and since it cannot be
re-enabled without reinstalling Windows, the native path is expected to keep
working on this machine. The containerised path is what makes that
irrelevant.

The container path caches downloaded Python packages in a Docker volume named
`khazana-pip-cache`. The first type check pulls about 70 MB and takes several
minutes on a slow connection; later runs reuse the cache and take under a
minute. If a run dies on a network timeout, run it again: whatever downloaded
is cached, so each attempt gets further.

Ruff and mypy are pinned to exact versions in `apps/api/pyproject.toml`, not
to a range. A newer ruff can format the same code differently, so a floating
version means CI and a developer machine can disagree about a file nobody
touched, which is a CI failure with no corresponding change. When upgrading
either tool, change the pin, reformat, and update the image tags in
`scripts/lint.ps1` and the Makefile in the same commit.

Note that `make` is not installed on this machine, so the make targets in the
README and in the older docs do not run here. Use `scripts/dev.ps1`, or
`scripts/lint.ps1` for a lint only run.

## 4. Project context

Khazana Outlet is an AI native marketplace in Pakistan for brand surplus
stock, B2B first, with a B2C storefront only after launch.

Authoritative plan documents, in this order:

- `ROADMAP.md`: the phase plan. Platform is built first across phases 1 to 5,
  brand recruitment and launch is phase 6. This supersedes the phase order in
  the original saved plan document in this folder.
- `docs/ai-architecture.md`: how the AI layer works, model routing, cost
  control, and the hard list of decisions AI is never allowed to make.
- `phase-6-brands-and-launch/`: the brand and market work, which runs last.

Standing build rules that follow from the roadmap:

- Every model call goes through the AI gateway in `apps/ai`. No module
  constructs the Anthropic client directly.
- Every AI feature ships with an eval, and the eval is written first.
- Commission rates, discount bands, brand protection rules, lot minimums and
  courier choice are configuration in the database, never hard coded.
- AI never decides money, approvals, bans or quoted stock levels. It drafts,
  suggests, scores and flags. See `docs/ai-architecture.md` section 2.
- Build decisions match the Pakistani market: COD, JazzCash and Easypaisa,
  WhatsApp, Android first, Urdu and English in the product UI.

Product UI copy for end users may be in Urdu. Rule 2 governs how we
communicate and what we write in the repository, not the language shown to
shoppers.

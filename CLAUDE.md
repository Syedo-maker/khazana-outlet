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

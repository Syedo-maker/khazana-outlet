#!/usr/bin/env bash
# Repository rules gate. See CLAUDE.md section 3.
#
#   1. No em dashes or en dashes in tracked files or commit messages.
#   2. No AI attribution lines.
#   3. The commit author is the repository owner.
#
# Run it by hand with `make prepush`, or let CI run it on every push.
#
# Two implementation notes, both learned by watching an earlier version of this
# script pass while a real em dash sat in a tracked file:
#
#   - `grep -P '\xe2\x80\x94'` matches the byte sequence, but `git grep -P`
#     does not: its PCRE runs in UTF-8 mode where \xe2 means U+00E2. So the
#     file scan pipes `git ls-files` into real grep instead of using git grep.
#   - The byte form is used rather than `\x{2014}` because grep -P in Windows
#     git bash rejects code points above 0xFF outright.

set -uo pipefail

DASHES='\xe2\x80\x93|\xe2\x80\x94'
# Attribution phrases only. The vendor name is deliberately not matched: this
# project uses the Claude API, so "claude" legitimately appears in code, docs
# and commit subjects such as "feat(ai): add gateway". What must never appear
# is a credit line.
ATTRIBUTION='co-authored-by|generated (with|by) claude|written by claude|assisted by (claude|ai)|claude code'

fail=0

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository, so there is nothing to check before a push."
  echo "Run 'git init' first. Exiting without failing."
  exit 0
fi

# ---------------------------------------------------------------- file scan

echo "== Checking tracked files for em and en dashes =="
dash_hits=$(
  git ls-files -z \
    | tr '\0' '\n' \
    | grep -v '^scripts/prepush-check\.sh$' \
    | while IFS= read -r file; do
        [ -f "$file" ] || continue
        grep -nIHP "$DASHES" -- "$file" 2>/dev/null
      done
)

if [ -n "$dash_hits" ]; then
  echo "$dash_hits"
  echo "FAIL: em or en dash found above. Use a comma, a colon, a full stop or a hyphen."
  fail=1
else
  echo "ok: no em or en dashes in tracked files"
fi

echo "== Checking tracked files for AI attribution =="
attr_hits=$(
  git ls-files -z \
    | tr '\0' '\n' \
    | grep -vE '^(scripts/prepush-check\.sh|\.pre-commit-config\.yaml|CLAUDE\.md)$' \
    | while IFS= read -r file; do
        [ -f "$file" ] || continue
        grep -nIHiE "$ATTRIBUTION" -- "$file" 2>/dev/null
      done
)

if [ -n "$attr_hits" ]; then
  echo "$attr_hits"
  echo "FAIL: AI attribution found above. The author is the repository owner only."
  fail=1
else
  echo "ok: no AI attribution in tracked files"
fi

# ------------------------------------------------------------ commit range

# With an upstream, check what is about to be pushed. Without one, check this
# branch against main, unless this branch is main, in which case check every
# commit. An earlier version used main..HEAD unconditionally and silently
# checked nothing while sitting on main.
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  RANGE='@{u}..HEAD'
elif [ "$branch" != "main" ] && git rev-parse --verify main >/dev/null 2>&1; then
  RANGE='main..HEAD'
else
  RANGE='HEAD'
fi

COMMITS=$(git log --format='%H %s%n%b' "$RANGE" 2>/dev/null || true)

echo "== Checking commit messages in $RANGE =="
if [ -z "$COMMITS" ]; then
  echo "ok: no commits to check"
else
  if printf '%s\n' "$COMMITS" | grep -nP "$DASHES"; then
    echo "FAIL: em or en dash in a commit message above."
    echo "Fix the most recent one with: git commit --amend"
    fail=1
  else
    echo "ok: no em or en dashes in commit messages"
  fi

  if printf '%s\n' "$COMMITS" | grep -niE "$ATTRIBUTION"; then
    echo "FAIL: AI attribution in a commit message above."
    fail=1
  else
    echo "ok: no AI attribution in commit messages"
  fi
fi

# ----------------------------------------------------------------- authors

echo "== Checking the commit author =="
AUTHORS=$(git log --format='%an <%ae>' "$RANGE" 2>/dev/null | sort -u || true)
if [ -z "$AUTHORS" ]; then
  echo "ok: no commits to check"
else
  echo "$AUTHORS"
  if printf '%s\n' "$AUTHORS" | grep -qiE 'claude|anthropic|\[bot\]|noreply@anthropic'; then
    echo "FAIL: an author above is not the repository owner."
    fail=1
  else
    echo "ok: author is the repository owner"
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "Pre push check FAILED. Nothing was pushed."
  exit 1
fi

echo
echo "Pre push check passed."

#!/usr/bin/env bash
#
# Check one commit message against the repository rules in CLAUDE.md.
#
# Installed as a commit-msg hook, so it runs before the commit exists rather
# than before a push. Until this script existed nothing checked the message at
# all: every hook in .pre-commit-config.yaml looks at files, and the pre push
# gate only sees messages once they are already committed.
#
# Usage: check-commit-msg.sh <path to the prepared message>
#
# Three traps, all learned the hard way. The first two are recorded in
# CLAUDE.md section 3; the third was found while writing this script.
#
#   1. git grep -P does not read the byte escape form as bytes at all, so it
#      reports a false clean.
#   2. grep -P in Windows git bash rejects the code point spelling \x{2014}
#      outright.
#   3. grep -P is not dependable here even with byte escapes. The first
#      version of this script used it, worked when run by hand, and silently
#      matched nothing when pre-commit ran it, because pre-commit's
#      environment resolves a grep whose -P behaves differently and the error
#      was being swallowed by a 2>/dev/null. It reported Passed on a message
#      containing an em dash.
#
# So: no -P. The dash characters are built with printf and matched with
# grep -F, which needs no regex engine and no locale assumptions. And the
# script tests its own detection before trusting it, because the failure mode
# that matters is not a missed dash, it is a checker that always passes.

set -uo pipefail

msg_file="${1:-}"
if [[ -z "$msg_file" || ! -f "$msg_file" ]]; then
    echo "check-commit-msg: no message file given" >&2
    exit 2
fi

em_dash="$(printf '\xe2\x80\x94')"
en_dash="$(printf '\xe2\x80\x93')"

# ---------- self test ----------
# If the tooling cannot find a dash in a string that definitely has one, this
# script must fail rather than wave the commit through. A silent pass is the
# whole reason this check did not work the first time.
if ! printf 'x%sy' "$em_dash" | LC_ALL=C grep -qF -- "$em_dash" 2>/dev/null; then
    echo "check-commit-msg: this checker cannot detect an em dash on this" >&2
    echo "system, so it refuses to approve anything. Fix the script rather" >&2
    echo "than bypassing it: a check that always passes is worse than none." >&2
    exit 2
fi

# Comment lines are git's own template and never reach the stored message.
body="$(grep -v '^#' -- "$msg_file" || true)"

status=0

# ---------- em and en dashes ----------
if printf '%s' "$body" | LC_ALL=C grep -nF -e "$em_dash" -e "$en_dash" >/dev/null; then
    echo ""
    echo "Em or en dash in the commit message:"
    printf '%s' "$body" | LC_ALL=C grep -nF -e "$em_dash" -e "$en_dash" | sed 's/^/  /'
    echo ""
    echo "Use a comma, a colon, a full stop or a plain hyphen instead."
    echo "For a range write 70-80 percent, not an en dash range."
    status=1
fi

# ---------- AI attribution ----------
# Deliberately narrow. This repository names CLAUDE.md constantly and its own
# docs explain that the embedding model is not Claude, so matching the bare
# word would reject legitimate messages. Only the attribution forms are a
# breach: a trailer crediting a tool, or a "generated with" footer.
ai_pattern='co-authored-by:[[:space:]]*.*(claude|anthropic|copilot|chatgpt|gpt-)'
ai_pattern+='|(generated|written|authored|created|assisted)[[:space:]]+(with|by)[[:space:]]+(claude|chatgpt|copilot|an?[[:space:]]+ai([[:space:]]|$))'

if printf '%s' "$body" | LC_ALL=C grep -nEi -- "$ai_pattern" >/dev/null; then
    echo ""
    echo "AI attribution in the commit message:"
    printf '%s' "$body" | LC_ALL=C grep -nEi -- "$ai_pattern" | sed 's/^/  /'
    echo ""
    echo "The commit author is the repository owner only. Remove the line."
    status=1
fi

# The robot emoji, which is what the "Generated with" footers carry.
robot="$(printf '\xf0\x9f\xa4\x96')"
if printf '%s' "$body" | LC_ALL=C grep -qF -- "$robot"; then
    echo ""
    echo "The commit message carries a generated-with footer. Remove it."
    status=1
fi

if [[ "$status" -ne 0 ]]; then
    echo "Commit refused. See CLAUDE.md section 3."
fi

exit "$status"

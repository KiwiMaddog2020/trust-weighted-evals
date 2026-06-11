#!/usr/bin/env bash
# Regression harness for the privacy gate at hooks/pre-commit.
#
# For each canonical case it builds a throwaway git repo, points that repo's
# core.hooksPath at this repo's hooks/ directory, stages a single file holding
# the case text, attempts a commit, and records the exit code. A BLOCK case
# expects the commit to fail (the hook exits non-zero), a PASS case expects it
# to succeed. The repo is removed after each case, so this harness never touches
# the working tree or the real index. It only ever runs git inside its own
# temp repos.
#
# Run it after the gate changes, or before relying on the backstop. It prints
# one "PASS/FAIL | label" line per case, then a "X passed, Y failed" tally, and
# exits non-zero if any case did not meet its expectation.
#
# Why the BLOCK cases carry a "<SPLIT>" marker (see run_case): the staged line a
# BLOCK case feeds the gate has to contain a complete synthetic secret or PII
# pattern, or the gate would have nothing to catch. But this script is itself a
# tracked file, so committing it has to clear the same gate. The earlier version
# parked a trailing "pragma: allowlist" token on each case line to do that. That
# was wrong twice over: the gate's allowlist skip is line-global (it drops the
# whole physical line before any matcher runs), so every BLOCK case was waved
# straight through and the harness validated nothing on the block side; and the
# file could only be committed with the gate inert. The fix: each BLOCK case
# splits its secret with the literal marker "<SPLIT>" placed mid-pattern, and
# run_case deletes that marker at runtime to assemble the staged line. The marker
# uses "<" and ">", which appear in none of the gate's matcher character classes,
# so the pattern is broken on every source line here (this file commits through
# the live gate), while the assembled line carries the full, marker-free pattern
# (the gate fires on it). The only example token still marked with the allowlist
# pragma is the one on the PASS "allowlist line" case, which is what that marker
# is for.
set -uo pipefail

# Absolute path to the hooks directory that holds the gate under test. Resolved
# from this script's own location so the harness works from any working
# directory and against this repo's hooks/, not whatever the caller has staged.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRE_COMMIT="$HOOK_DIR/pre-commit"

if [ ! -x "$PRE_COMMIT" ]; then
  echo "harness error: gate not found or not executable at $PRE_COMMIT" >&2
  exit 2
fi

passed=0
failed=0

# run_case EXPECT LABEL EXPECT_CAT TEXT
#   EXPECT     is "block" (commit must fail) or "pass" (commit must succeed).
#   LABEL      is the human name printed on the result line.
#   EXPECT_CAT is the category the gate must name on a BLOCK case (the text after
#              "match #N: " in the gate's stderr, e.g. "possible AWS access key").
#              Pass "" to skip the category assertion (always "" for pass cases).
#   TEXT       is the case text. Any literal "<SPLIT>" markers in it are removed
#              before the line is staged. A BLOCK case puts "<SPLIT>" inside its
#              secret so no complete pattern sits on this file's source line (so
#              this file itself clears the gate); the staged line is marker-free
#              and carries the full pattern under test. "<" and ">" are in none of
#              the gate's matcher classes, so the marker reliably breaks any
#              pattern wherever it is placed.
# Builds an isolated repo, stages the assembled line, commits, compares the
# commit's success to EXPECT, and for a BLOCK case also confirms the gate named
# EXPECT_CAT (so a case cannot pass by blocking for the wrong matcher). Prints
# "PASS/FAIL | LABEL", bumps the tally, and on a failure prints a one-line
# reason. The temp repo is always removed, including on an unexpected git failure.
run_case() {
  local expect="$1" label="$2" expect_cat="$3" raw="$4"
  local text="${raw//<SPLIT>/}"

  local repo rc result reason err
  repo="$(mktemp -d "${TMPDIR:-/tmp}/privacy-gate-test.XXXXXX")"
  err="$(mktemp "${TMPDIR:-/tmp}/privacy-gate-err.XXXXXX")"

  # Quiet, fully self-contained repo. core.hooksPath points back at the gate
  # under test. commit.gpgsign is forced off so a signing config on the machine
  # cannot make a case hang or fail for an unrelated reason. The harness identity
  # email is assembled from a marked literal so no complete email pattern sits on
  # any line of this file; the marker is stripped before git sees the address.
  local harness_email="harness<SPLIT>@example.test"
  harness_email="${harness_email//<SPLIT>/}"
  git -C "$repo" init -q
  git -C "$repo" config core.hooksPath "$HOOK_DIR"
  git -C "$repo" config user.email "$harness_email"
  git -C "$repo" config user.name "Privacy Gate Harness"
  git -C "$repo" config commit.gpgsign false

  # printf, not echo, so a leading dash or a backslash in a case is written
  # literally. The case occupies one staged line in a tracked file.
  printf '%s\n' "$text" > "$repo/sample.txt"
  git -C "$repo" add sample.txt

  # The gate runs as the pre-commit hook here. Capture its effect through the
  # commit's exit code: zero means the commit went through (gate allowed it),
  # non-zero means the gate blocked it. The gate's stderr is captured so a BLOCK
  # case can assert the category it named; stdout is discarded.
  if git -C "$repo" commit -q -m "harness case" >/dev/null 2>"$err"; then
    rc=0
  else
    rc=1
  fi

  result="PASS"
  reason=""
  if [ "$expect" = "block" ]; then
    if [ "$rc" -eq 0 ]; then
      result="FAIL"
      reason="expected block, commit succeeded"
    elif [ -n "$expect_cat" ] && ! grep -qF ": ${expect_cat}" "$err"; then
      result="FAIL"
      reason="blocked but gate did not name category '${expect_cat}'"
    fi
  else
    if [ "$rc" -ne 0 ]; then
      result="FAIL"
      reason="expected pass, commit was blocked"
    fi
  fi

  rm -rf "$repo"
  rm -f "$err"

  if [ "$result" = "PASS" ]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
  fi

  printf '%s | %s\n' "$result" "$label"
  [ -n "$reason" ] && printf '       reason: %s\n' "$reason"
  return 0
}

# Case table. Each BLOCK row names the category the gate must report, then the
# case text with a "<SPLIT>" marker placed inside the secret so no source line
# below holds a complete pattern (this file commits through the live gate). The
# staged line is the same text with the marker removed, so it carries the full
# pattern (the gate fires on it). Grouped by expectation for readability.

# --- Must BLOCK: the gate has to stop these, and name the right category. ---
run_case block "private key header"               "possible private key"       "-----BEGIN <SPLIT>RSA PRIVATE KEY-----"
run_case block "AWS access key"                   "possible AWS access key"     "aws = AKIA<SPLIT>IOSFODNN7EXAMPLE here"
run_case block "Slack bot token (xoxb-)"          "possible Slack token"        "slack = xoxb-<SPLIT>123456789012-abcdefABCDEF0123456789"
run_case block "GitHub token (ghp_, 30+ chars)"   "possible API token"          "gh = ghp_<SPLIT>ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
run_case block "GitHub fine-grained (github_pat_)" "possible API token"         "gh = github_pat_<SPLIT>ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
run_case block "Google API key (AIza)"            "possible API token"          "key = AIza<SPLIT>SyEXAMPLEEXAMPLEEXAMPLEEXAMPLEab"
run_case block "OpenAI key (sk-)"                 "possible API token"          "openai = sk-<SPLIT>EXAMPLEEXAMPLEEXAMPLE0"
run_case block "Stripe rk_live_ key"              "possible API token"          "stripe = rk_live_<SPLIT>ABCDEFGHIJKLMNOP"
run_case block "Stripe sk_test_ key"              "possible API token"          "stripe = sk_test_<SPLIT>ABCDEFGHIJKLMNOP"
run_case block "generic keyword credential"       "possible API token"          "password = <SPLIT>hunter2hunter2hunter2"
run_case block "JWT (eyJ...)"                     "possible JWT"                "token = eyJ<SPLIT>abc123.eyJhbGci.sIgNaTuReXyZ"
run_case block "bearer token"                     "possible bearer token"       "auth: Bearer <SPLIT>abcdefABCDEF0123456789xyz"
run_case block "credential in URL"                "possible credential in URL"  "db = https<SPLIT>://user:pass@dbhost/app"
run_case block "email address"                    "possible email address"      "contact a<SPLIT>@b.com for details"
run_case block "formatted NANP phone, dashed"     "possible phone number"       "call 604-<SPLIT>555-0142 today"
run_case block "SIN dashed (3-3-3)"               "possible SIN"                "sin is 046-454<SPLIT>-286 on file"
run_case block "SIN unformatted (9 digits)"       "possible SIN"                "sin is 046454<SPLIT>286 on file"
run_case block "SIN split 2-4-3"                  "possible SIN"                "sin is 04 6454<SPLIT> 286 on file"
run_case block "card dashed (4-4-4-4)"            "possible payment card"       "card 4111-1111<SPLIT>-1111-1111 on file"
run_case block "grouped card then trailing text"  "possible payment card"       "card 4111 1111<SPLIT> 1111 1111 done"

# --- Must PASS: the gate must not over-block these. ---
run_case pass  "Luhn-invalid 9-digit 123456789"   "" "ticket id 123456789 closed"
run_case pass  "Luhn-invalid 9-digit 100000000"   "" "budget line 100000000 approved"
run_case pass  "Luhn-invalid 9-digit 100200300"   "" "build number 100200300 shipped"
run_case pass  "bare 10-digit 6045550142"          "" "record 6045550142 archived"
run_case pass  "DOB 1994-03-21"                    "" "date of birth 1994-03-21 noted"
run_case pass  "clean prose"                       "" "this is an ordinary sentence with no secrets"
run_case pass  "allowlist line with card example"  "" "example card 4111-1111-1111-1111 pragma: allowlist"

# Tally and overall verdict. Print the totals, then exit non-zero if any case
# missed its expectation so a caller (or CI) can gate on the result.
printf '%d passed, %d failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]

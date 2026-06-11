#!/bin/bash
# scaffold_handoff.sh — generate the peer-audit hand-off bundle.
#
# Reads templates from pipeline/templates/,
# substitutes placeholders, writes three files at the target dir:
#
#   <target-dir>/CODEX_PROMPT_<slug>.md       (paste-block for Codex)
#   <target-dir>/HANDOFF_<date>_<slug>.md     (Maestro state doc)
#   <target-dir>/.peer-audit-<slug>.json      (machine state file)
#
# Usage:
#   bash scaffold_handoff.sh \
#     --subject "<subject>" \
#     --slug "<slug>" \
#     --mode <plan|code> \
#     --target-dir "<dir>" \
#     --pass <N> \
#     [--carry-findings <path-to-state.json>] \
#     [--reading-order <path-to-reading-order.txt>]

set -euo pipefail

# ---- arg parsing -----------------------------------------------------------

SUBJECT=""
SLUG=""
MODE=""
TARGET_DIR=""
PASS="1"
CARRY_FINDINGS=""
READING_ORDER_FILE=""
# N-rater generalization: comma-separated engine names + user-set target.
# Defaults preserve the classic 2-rater (codex+claude) / 9.5 contract.
RATERS="codex,claude"
TARGET_CRAFT="9.5"
TARGET_FIT="9.5"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --subject) SUBJECT="$2"; shift 2 ;;
        --slug) SLUG="$2"; shift 2 ;;
        --mode) MODE="$2"; shift 2 ;;
        --target-dir) TARGET_DIR="$2"; shift 2 ;;
        --pass) PASS="$2"; shift 2 ;;
        --carry-findings) CARRY_FINDINGS="$2"; shift 2 ;;
        --reading-order) READING_ORDER_FILE="$2"; shift 2 ;;
        --raters) RATERS="$2"; shift 2 ;;
        --target-craft) TARGET_CRAFT="$2"; shift 2 ;;
        --target-fit) TARGET_FIT="$2"; shift 2 ;;
        *) echo "ERROR: unknown arg: $1" >&2; exit 1 ;;
    esac
done

for var in SUBJECT SLUG MODE TARGET_DIR; do
    if [ -z "${!var}" ]; then
        # Bash 3.x compat: tr instead of ${var,,} for lowercase (macOS default
        # /bin/bash is 3.2). Claude Pass 1 new finding N2.
        var_lower=$(printf '%s' "$var" | tr '[:upper:]' '[:lower:]')
        echo "ERROR: --$var_lower is required" >&2
        exit 1
    fi
done

case "$MODE" in
    plan|code) ;;
    *) echo "ERROR: --mode must be 'plan' or 'code', got: $MODE" >&2; exit 1 ;;
esac

# Plan-mode requires an explicit reading-order file. Without one, the prompt's
# READING_ORDER substitution falls back to whatever .md files sit in the
# target output directory — which is normally empty or contains only
# peer-audit artifacts, sending Codex to audit the scaffold instead of the
# real subject. Fixed by making the flag required for plan mode (Train 5
# patch, CRITICAL #1).
if [ "$MODE" = "plan" ] && [ -z "$READING_ORDER_FILE" ]; then
    echo "ERROR: plan mode requires --reading-order <path> with the subject files + anchor docs to read" >&2
    echo "       Build a reading-order file listing the documents Codex should audit, one per line:" >&2
    echo "         - <path/to/subject-doc-1.md>" >&2
    echo "         - <path/to/subject-doc-2.md>" >&2
    echo "         - .claude/PROJECT_CHARTER.md  (for the fit-axis anchor)" >&2
    exit 1
fi

if ! [[ "$PASS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: --pass must be a positive integer, got: $PASS" >&2
    exit 1
fi

# ---- derive paths ----------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
TEMPLATE_DIR="$SKILL_DIR/templates"

TEMPLATE_PROMPT="$TEMPLATE_DIR/CODEX_PROMPT_${MODE}.md"
TEMPLATE_HANDOFF="$TEMPLATE_DIR/HANDOFF.md"

for f in "$TEMPLATE_PROMPT" "$TEMPLATE_HANDOFF"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: missing template: $f" >&2
        exit 1
    fi
done

mkdir -p "$TARGET_DIR"

DATE="$(date -u +%Y-%m-%d)"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

PROMPT_OUT="$TARGET_DIR/CODEX_PROMPT_${SLUG}.md"
HANDOFF_OUT="$TARGET_DIR/HANDOFF_${DATE}_${SLUG}.md"
STATE_OUT="$TARGET_DIR/.peer-audit-${SLUG}.json"

PASS_MINUS_1=$((PASS - 1))
PASS_PLUS_1=$((PASS + 1))

# ---- reading order ---------------------------------------------------------

if [ -n "$READING_ORDER_FILE" ] && [ -f "$READING_ORDER_FILE" ]; then
    READING_ORDER="$(cat "$READING_ORDER_FILE")"
elif [ "$MODE" = "plan" ]; then
    # Default plan-mode reading order: every .md in the target dir, plus
    # any sibling docs the user has referenced. Skill should override via
    # --reading-order for tighter scopes.
    READING_ORDER=$(
        find "$TARGET_DIR" -maxdepth 2 -type f -name '*.md' 2>/dev/null \
            | sort \
            | sed 's|^|  - |'
    )
    if [ -z "$READING_ORDER" ]; then
        READING_ORDER="  - (no markdown files found at $TARGET_DIR — populate or pass --reading-order)"
    fi
else
    # code-mode: skill's prompt embeds the find/wc commands. Reading order
    # here is auxiliary file pointers.
    READING_ORDER="  - .claude/PROJECT_CHARTER.md
  - README.md
  - docs/ (recent design docs)
  - Largest source files (per the wc -l survey above)"
fi

# ---- prior findings block --------------------------------------------------

if [ "$PASS" -eq 1 ]; then
    PRIOR_FINDINGS_BLOCK="(Pass 1 — no prior findings. Score from scratch.)"
elif [ -n "$CARRY_FINDINGS" ] && [ -f "$CARRY_FINDINGS" ]; then
    PRIOR_FINDINGS_BLOCK=$(python3 - "$CARRY_FINDINGS" <<'PY'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        state = json.load(f)
except Exception as e:
    print(f"(could not parse {path}: {e})")
    sys.exit(0)
findings = state.get("open_findings", []) or []
if not findings:
    print("(No open findings carried from prior passes.)")
    sys.exit(0)
print(f"Open findings from prior passes ({len(findings)}):")
print("")
for fnd in findings:
    sev = fnd.get("severity", "?")
    loc = fnd.get("location", "?")
    summary = fnd.get("summary", "")
    intro = fnd.get("introduced_on_pass", "?")
    by = fnd.get("introduced_by", "?")
    print(f"  - [{sev}] {loc} — {summary}")
    print(f"    (introduced pass {intro} by {by})")
PY
)
else
    PRIOR_FINDINGS_BLOCK="(Pass $PASS but no --carry-findings file passed; review prior POLISH_*.md files at $TARGET_DIR manually.)"
fi

# ---- history table (for HANDOFF.md) ---------------------------------------
#
# N-rater aware: two columns per rater (verdict + craft/fit), plus the trailing
# new-findings + patches columns. The rater set comes from the carried state's
# `raters` list when available, else the --raters arg (default codex,claude).

# Each rater contributes 2 placeholder cells; trailing new-findings + patches = 2.
RATER_COUNT=$(printf '%s' "$RATERS" | awk -F',' '{print NF}')
PENDING_CELLS=""
i=0
while [ "$i" -lt "$((RATER_COUNT * 2 + 2))" ]; do
    PENDING_CELLS="$PENDING_CELLS _pending_ |"
    i=$((i + 1))
done

if [ "$PASS" -eq 1 ]; then
    HISTORY_TABLE="| 1 |$PENDING_CELLS"
elif [ -n "$CARRY_FINDINGS" ] && [ -f "$CARRY_FINDINGS" ]; then
    HISTORY_TABLE=$(RATERS_ENV="$RATERS" python3 - "$CARRY_FINDINGS" "$PASS" <<'PY'
import json, os, sys
path = sys.argv[1]
current_pass = int(sys.argv[2])
fallback = [r for r in os.environ.get("RATERS_ENV", "codex,claude").split(",") if r]
try:
    with open(path) as f:
        state = json.load(f)
except Exception:
    print("| (history not parseable) |")
    sys.exit(0)
history = state.get("history", []) or []

def entry_raters(h):
    rmap = h.get("raters")
    if isinstance(rmap, dict) and rmap:
        return rmap
    synth = {}
    for name in ("codex", "claude"):
        block = h.get(name)
        if isinstance(block, dict):
            synth[name] = block
    return synth

# Rater order: configured list, else union across history, else fallback arg.
names = state.get("raters")
if not (isinstance(names, list) and names):
    names = []
    for h in history:
        for n in entry_raters(h):
            if n not in names:
                names.append(n)
if not names:
    names = fallback or ["codex", "claude"]

rows = []
for h in history:
    p = h.get("pass", "?")
    rmap = entry_raters(h)
    cells = [str(p)]
    for n in names:
        r = rmap.get(n) or {}
        v = r.get("verdict") or "_pending_"
        craft = r.get("craft", "")
        fit = r.get("fit", "")
        score = f"{craft}/{fit}" if craft != "" and craft is not None else "_pending_"
        cells.append(v)
        cells.append(score)
    cells.append(str(h.get("new_findings", 0)))
    cells.append(str(h.get("patches_applied", 0)))
    rows.append("| " + " | ".join(cells) + " |")
# Trailing placeholder row for the in-flight pass.
pending = ["_pending_"] * (len(names) * 2 + 2)
rows.append("| " + str(current_pass) + " | " + " | ".join(pending) + " |")
print("\n".join(rows))
PY
)
else
    HISTORY_TABLE="| $PASS |$PENDING_CELLS"
fi

# ---- carried findings (for HANDOFF.md NEXT_ACTION etc.) -------------------

if [ "$PASS" -eq 1 ]; then
    CARRIED_FINDINGS="_(none — first pass)_"
    NEXT_ACTION="Codex fires Pass 1. Output expected at \`$TARGET_DIR/POLISH_${DATE}_${SLUG}_pass1.md\`."
else
    CARRIED_FINDINGS="See \`$STATE_OUT\` § \`open_findings\` for the full list. Each finding's location, severity, and pass of introduction is recorded."
    NEXT_ACTION="Codex fires Pass $PASS, addressing the open findings above. Claude re-reviews after."
fi

# ---- dirty worktree status ------------------------------------------------

# Use the script's repo if available.
REPO_ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ]; then
    DIRTY=$(git -C "$REPO_ROOT" status --short 2>/dev/null | head -40)
else
    DIRTY=$(git status --short 2>/dev/null | head -40)
fi
if [ -z "$DIRTY" ]; then
    DIRTY="(clean working tree at scaffold time)"
fi

# ---- N-rater header + list strings (for HANDOFF.md) -----------------------
#
# Build the dynamic Pass-history header ("<Rater> verdict | <Rater> craft/fit |"
# per rater) + its alignment row, plus a human-readable rater list, from the
# resolved rater set. Title-cases each name. Mirrors the generator's logic so
# the HANDOFF table header matches the N-column HISTORY_TABLE rows.
HISTORY_RATER_HEADERS=$(RATERS_ENV="$RATERS" python3 - <<'PY'
import os
names = [r.strip().lower() for r in os.environ.get("RATERS_ENV", "codex,claude").split(",") if r.strip()] or ["codex", "claude"]
def t(n): return n[:1].upper() + n[1:]
print("".join(f"{t(n)} verdict | {t(n)} craft/fit | " for n in names), end="")
PY
)
HISTORY_RATER_ALIGN=$(RATERS_ENV="$RATERS" python3 - <<'PY'
import os
names = [r.strip().lower() for r in os.environ.get("RATERS_ENV", "codex,claude").split(",") if r.strip()] or ["codex", "claude"]
print("---|---:|" * len(names), end="")
PY
)
RATERS_LIST=$(RATERS_ENV="$RATERS" python3 - <<'PY'
import os
names = [r.strip().lower() for r in os.environ.get("RATERS_ENV", "codex,claude").split(",") if r.strip()] or ["codex", "claude"]
def t(n): return n[:1].upper() + n[1:]
print(", ".join(t(n) for n in names), end="")
PY
)

# ---- substitute & write prompt + handoff ---------------------------------

substitute() {
    local infile="$1"
    SUBJECT="$SUBJECT" \
    SLUG="$SLUG" \
    MODE="$MODE" \
    TARGET_DIR="$TARGET_DIR" \
    PASS="$PASS" \
    PASS_MINUS_1="$PASS_MINUS_1" \
    PASS_PLUS_1="$PASS_PLUS_1" \
    DATE="$DATE" \
    READING_ORDER="$READING_ORDER" \
    PRIOR_FINDINGS_BLOCK="$PRIOR_FINDINGS_BLOCK" \
    HISTORY_TABLE="$HISTORY_TABLE" \
    CARRIED_FINDINGS="$CARRIED_FINDINGS" \
    NEXT_ACTION="$NEXT_ACTION" \
    DIRTY_WORKTREE="$DIRTY" \
    HISTORY_RATER_HEADERS="$HISTORY_RATER_HEADERS" \
    HISTORY_RATER_ALIGN="$HISTORY_RATER_ALIGN" \
    RATERS_LIST="$RATERS_LIST" \
    TARGET_CRAFT="$TARGET_CRAFT" \
    TARGET_FIT="$TARGET_FIT" \
    python3 -c '
import os, sys
template = sys.stdin.read()
keys = [
    "SUBJECT", "SLUG", "MODE", "TARGET_DIR", "PASS",
    "PASS_MINUS_1", "PASS_PLUS_1", "DATE",
    "READING_ORDER", "PRIOR_FINDINGS_BLOCK",
    "HISTORY_TABLE", "CARRIED_FINDINGS", "NEXT_ACTION",
    "DIRTY_WORKTREE",
    "HISTORY_RATER_HEADERS", "HISTORY_RATER_ALIGN",
    "RATERS_LIST", "TARGET_CRAFT", "TARGET_FIT",
]
for k in keys:
    template = template.replace("{{" + k + "}}", os.environ.get(k, ""))
sys.stdout.write(template)
' < "$infile"
}

substitute "$TEMPLATE_PROMPT"  > "$PROMPT_OUT"
substitute "$TEMPLATE_HANDOFF" > "$HANDOFF_OUT"

# ---- write state.json ------------------------------------------------------
#
# Train 5: state.json is always written via python json.dump — subjects with
# quotes / backslashes / newlines no longer corrupt the file (Codex Pass 1
# MEDIUM finding #5).

SLUG="$SLUG" \
SUBJECT="$SUBJECT" \
MODE="$MODE" \
TARGET_DIR="$TARGET_DIR" \
PASS="$PASS" \
TIMESTAMP="$TIMESTAMP" \
STATE_OUT="$STATE_OUT" \
RATERS_ENV="$RATERS" \
TARGET_CRAFT="$TARGET_CRAFT" \
TARGET_FIT="$TARGET_FIT" \
python3 - <<'PY'
import json, os, sys

slug = os.environ["SLUG"]
subject = os.environ["SUBJECT"]
mode = os.environ["MODE"]
target_dir = os.environ["TARGET_DIR"]
pass_n = int(os.environ["PASS"])
timestamp = os.environ["TIMESTAMP"]
state_out = os.environ["STATE_OUT"]

# N-rater generalization: engine set + user-set convergence target are stored
# values, not literals. Defaults keep the classic codex+claude / 9.5 contract.
raters = [r.strip().lower() for r in os.environ.get("RATERS_ENV", "codex,claude").split(",") if r.strip()]
if not raters:
    raters = ["codex", "claude"]


def _num(env_key, default):
    raw = os.environ.get(env_key, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


target_craft = _num("TARGET_CRAFT", 9.5)
target_fit = _num("TARGET_FIT", 9.5)

if pass_n == 1 or not os.path.exists(state_out):
    state = {
        "slug": slug,
        "subject": subject,
        "mode": mode,
        "target_dir": target_dir,
        "current_pass": pass_n,
        "max_passes": 5,
        "raters": raters,
        "convergence": {
            "target_craft": target_craft,
            "target_fit": target_fit,
            "status": "pending",
        },
        "codex_binary": None,
        "history": [],
        "open_findings": [],
        "scaffolded_at": timestamp,
    }
else:
    with open(state_out) as f:
        state = json.load(f)
    state["current_pass"] = pass_n
    state["last_scaffolded_at"] = timestamp
    # Backfill the rater set + target on resumed audits that predate them, but
    # never clobber an existing user-set value.
    state.setdefault("raters", raters)
    conv = state.setdefault("convergence", {})
    conv.setdefault("target_craft", target_craft)
    conv.setdefault("target_fit", target_fit)
    conv.setdefault("status", "pending")

with open(state_out, "w") as f:
    json.dump(state, f, indent=2)
PY

# Verify the write succeeded (set -e would already have killed us on python
# failure, but double-check the file is non-empty + valid JSON).
if [ ! -s "$STATE_OUT" ]; then
    echo "ERROR: state file $STATE_OUT is empty after write" >&2
    exit 1
fi

# ---- report ---------------------------------------------------------------

cat <<REPORT
Peer-audit hand-off scaffolded.

  Prompt:   $PROMPT_OUT
  Handoff:  $HANDOFF_OUT
  State:    $STATE_OUT

  Subject:  $SUBJECT
  Slug:     $SLUG
  Mode:     $MODE
  Pass:     $PASS

Next step (Phase 2 in SKILL.md): Codex runs the prompt and writes
  $TARGET_DIR/POLISH_${DATE}_${SLUG}_pass${PASS}.md

Claude's peer-review (Phase 3) will land at
  $TARGET_DIR/POLISH_${DATE}_${SLUG}_pass${PASS}_claude-peer-review.md
REPORT

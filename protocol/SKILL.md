---
name: forge
description: Three-rater polish-and-converge loop across Opus + Codex + Gemini on a plan or codebase, iterating the polish craft × fit rubric to a user-set target with a per-engine agent ceiling, domain-aware engine roles (code vs UI/design), and doer != rater across engines. Disagreement is surfaced, never outvoted. Trigger with "forge", "/forge", "three-way review", "trio audit", "Opus Codex Gemini review", "triple review", "converge to <N>". Outputs `<target-dir>/CONVERGED_<date>_<slug>.md` plus a decision-residue batch.
---

You are running the **forge protocol** — peer-audit generalized from two raters to the full trio (Opus + Codex + Gemini), with a **user-set target** (craft × fit ≥ N), a **per-engine agent ceiling**, and a **domain-aware** weight table / fleet ratio / role split. Forge is peer-audit with three rater slots instead of two and the bar promoted from hard-coded 9.5 to user-tunable. It reuses the same loop skeleton, the same drivers, the same generalized `bin/`, the same rubric, and the same fences — it does NOT rebuild them.

Run Phase 0 (setup) then Phases 1-5 (execution) in order. **Each phase has explicit gates — do not skip them.** The deliverable is the polished work PLUS a short, honest batch of the judgment calls only a human should make (the decision residue).

**Public extract note:** `adjudicator/...`, `pipeline/bin/...`, and `protocol/...` are the repo-relative components shipped in this extract. Paths under `orchestration/...`, plus references to `codex-spawn.sh`, `gemini-spawn.sh`, `gemini-review.sh`, `goal.py`, halt/P0 fence scripts, `maestro-decision.sh`, and `AskUserQuestion`, are part of the larger orchestration system, not included in this extract.

**Sibling skills + docs (compose, never duplicate):**

- `orchestration/skills/peer-audit/SKILL.md` — the two-rater parent. Forge reuses its Phase-0→5 loop, its `bin/` (slugify, scaffold, detect/invoke/validate, parse, **generalized** update-state, converged-report), its state schema, and its carry-findings mechanic. The pipeline is already N-rater; Forge fills three rater slots — it does not re-derive the loop or hand-roll a parallel state file.
- `orchestration/skills/polish/SKILL.md` — the locked two-axis craft × fit rubric. The scoreboard every forge iteration converges toward, and the exact prompt Opus uses for its in-session re-score.
- `orchestration/skills/rate-code/SKILL.md` — the score anchor for code-mode runs.
- `orchestration/skills/goal/SKILL.md` — the employee loop whose ORIENT→PLAN→EXECUTE→RATE→GATE→loop|park→RECORD spine Forge reuses, and whose `orchestration/bin/goal.py gate` enforces the **fixed safety floor** (see Phase 4 for the precise division of labor between that floor and the user target N).
- `docs/DUET_PROTOCOL.md` — the canonical mutual-polish ensemble mechanic. Forge is its three-engine, domain-aware extension.
- `adjudicator/trio_policy.json` — the operator-owned domain table (weights + fleet ratio + roles per domain). Read it; never hardcode the numbers into prose decisions.

---

## Phase 0 — Resolve params + domain + fences (the user-tunable knobs)

Forge has a small set of user-tunable params. Resolve them all before firing Phase 1.

| Param                    | What                                                                                              | Default                         |
| ------------------------ | ------------------------------------------------------------------------------------------------- | ------------------------------- |
| **subject**              | the plan or codebase under review                                                                 | active project's whole codebase |
| **target**               | the GO bar: craft × fit ≥ **N** (both aggregate axes, both stored as `target_craft`/`target_fit`) | N = 9.5                         |
| **per-engine ceiling K** | max agents per engine you may fan out to                                                          | 2                               |
| **domain**               | `general` (code) or `ui` (design) — picks the weight table + fleet ratio + roles                  | classified from subject         |
| **mode**                 | `write` (mutual-polish, engines edit) or `advisory` (rate-only, no edits)                         | `write`                         |

**Arg shapes:**

| Invocation                                                        | subject         | target | K   | domain     | mode     |
| ----------------------------------------------------------------- | --------------- | ------ | --- | ---------- | -------- |
| `/forge`                                                          | active codebase | 9.5    | 2   | classified | write    |
| `/forge <subject>`                                                | `<subject>`     | 9.5    | 2   | classified | write    |
| `/forge <subject> to 9.0`                                         | `<subject>`     | 9.0    | 2   | classified | write    |
| `/forge <subject> --target 9.2 --ceiling 1 --domain ui`           | `<subject>`     | 9.2    | 1   | ui         | write    |
| `/forge <subject> --advisory`                                     | `<subject>`     | 9.5    | 2   | classified | advisory |
| Verbal: "trio audit the Arc 2 plan, converge to 9, advisory only" | "Arc 2 plan"    | 9.0    | 2   | classified | advisory |

**Mode inference (subject → plan|code), same rule as peer-audit:** `*.md` / `docs/` / "plan" / "spec" / "RFC" → **plan**; "codebase" / "engine" / "module" / empty → **code**; else ask. Plan mode REQUIRES a reading-order file (Phase 1, Step 1.3) — peer-audit's scaffold errors without it.

**Domain classification (the cleave-safe knob).** Classify the subject, then load the matching row from `adjudicator/trio_policy.json` — never bake the weights into a prose judgment:

- Subject touches CSS / HTML / templates / Canvas / theme / visual layout / first-run UX / "design" → **`ui`**.
- Everything else (logic, data, runner, build, libs, plans) → **`general`** (code).
- An explicit `--domain ui` / `--domain general` overrides the classifier.

```
DOMAIN=$(python3 - "$SUBJECT" "$EXPLICIT_DOMAIN" <<'PY'
import json, re, sys
subject, explicit = (sys.argv[1] if len(sys.argv) > 1 else ""), (sys.argv[2] if len(sys.argv) > 2 else "")
if explicit in ("ui", "general"):
    print(explicit); raise SystemExit
ui = re.search(r"\.(css|scss|html)\b|templates?/|canvas|theme|visual|first-run|layout|design|a11y|accessib", subject, re.I)
print("ui" if ui else "general")
PY
)
POLICY="$REPO_ROOT/adjudicator/trio_policy.json"
# weights + fleet ratio + roles for $DOMAIN come from $POLICY — read, never retype.
```

**Domain table (operator-owned — the canonical copy is `trio_policy.json`; reproduced here for orientation only):**

| Domain             | Weights (Opus / Codex / Gemini) | Fleet ratio (Opus / Codex / Gemini) | Roles                                                                                                                                                           |
| ------------------ | ------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **general / code** | 9 / 8.5 / 8                     | 45% / 40% / 15%                     | Codex = many-agent workhorse **author** (fast mode + priority tier); Gemini = **READ-ONLY checkpoint auditor only**; Opus = **adjudicator/merger + author**.    |
| **ui / design**    | 9 / 7.5 / 8.5                   | 45% / 25% / 30%                     | Gemini = **first-class design author AND reviewer**, leveraged OVER Codex; Codex = **code-correctness** (markup / logic / a11y); Opus = **adjudicator/merger**. |

In UI mode Gemini is promoted to a first-pass design author (not just a reviewer) on **non-sensitive** lanes, and the fleet leans more agents toward it (30% vs 15%); Codex drops to the code-correctness role. In code mode Codex is the author workhorse and Gemini stays read-only. The numbers are config — re-tuning a domain is a one-line edit in `trio_policy.json`, not a SKILL.md rewrite.

**Target bar — promoted from code-literal to a user input, but it still lives OUTSIDE the doer's reach.** The doer cannot lower N mid-run to "pass" something. The user's N is stored as `convergence.target_craft` / `convergence.target_fit` in the state file, and the **authoritative convergence gate that reads it is `update_state.py`'s `decide_convergence`** (Phase 3/4) — it requires EVERY rater verdict==GO AND craft ≥ target AND fit ≥ target AND new_findings == 0. **`orchestration/bin/goal.py gate` does NOT enforce N** — it hardcodes `BAR_MIN = 8.5` with no target param and only enforces the **fixed safety floor** (doer != rater independence + the 9.5 high-stakes / Tier-3 / irreversible / user-facing escalation + leak/scope-clean). The two run together: the user target gates "is this good enough yet?" (`decide_convergence`), the safety floor gates "may this ever land?" (`goal.py gate`). A user N below 9.5 can never dip the high-stakes floor; a user N above 9.5 raises the convergence bar but the safety floor is unchanged.

**Force advisory (rate-only) when `write` is unsafe:** Tier-3 scope (auth / payments / runner / public-flip), thin test coverage, unfamiliar code, architectural findings needing an RFC first, or explicit user request. State the reason in the run header. Tier-3 classification uses the single source of truth — pass the _path list_ correctly:

```
# CORRECT: is_tier3 takes ONE path; for a LIST use tier3_hits (or any(...)).
SENSITIVE=$(python3 - "$REPO_ROOT" <<'PY'
import importlib.util, sys
root = sys.argv[1]
spec = importlib.util.spec_from_file_location("ensemble_tier3", f"{root}/pipeline/bin/ensemble_tier3.py")
t3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(t3)
changed = ["bin/dashgen/runner.py", "cloudflare/worker.js"]   # the actual changed-path LIST
print("1" if t3.tier3_hits(changed) else "0")    # NEVER t3.is_tier3(changed) on a list — that returns False and defeats the branch
PY
)
```

Gemini is additionally barred from _first-pass authoring_ any Tier-3 lane by `pipeline/bin/trio_policy.sh` (`trio_can_first_pass gemini 1` fails: weight 8 < the 8.5 first-pass threshold) — route those lanes to Codex/Opus to avoid a wasted refused spawn; Gemini still rates them read-only.

**Confirm the params in one tight sentence** before Phase 1, e.g.:

> Forge-auditing **Arc 2 plan** (mode=plan, domain=general, **write**) → `docs/ai-council/`. Target **craft × fit ≥ 9.5**; ceiling **2 agents/engine**; converge at GO from all three (or measured plateau → honest park).

If any param is ambiguous, use `AskUserQuestion` when available after mentally running `ask-validator`; in Codex or another runtime without that tool, use the runtime's closest decision UI or ask one concise question and wait.

**Runtime adapter for the rest of this skill:** every later `AskUserQuestion` reference inherits that rule. Do not silently fall back to prose option lists when a native decision tool exists.

**Phase-0 fences (inherited from the P0 cage — wire in, never reimplement):**

1. **Halt-check first + at every phase boundary.** First executable line and each subsequent phase: `"$REPO_ROOT/orchestration/bin/ensemble-halt-check.sh" || exit 99`. Honor `state.json.autopilot_freeze_until`. Treat it as a cooperative start-gate, not a security wall — Forge must also be killable out-of-process (`orchestration/bin/actions.sh kill`).
2. **Worktree-only.** Every engine lane runs in its own `orchestration/bin/codex-worktree.sh`-created worktree; never on the live tree (spawners refuse with exit 4). Gemini's worktree fence is load-bearing (no FS sandbox).
3. **Single egress + budget cap.** Workers are commit-only; integration is duet_hold (Opus owns the merge); push is default-deny (`ORCHESTRATION_PUSH_ALLOWED`). Every spawn carries the `*_MAX_MIN` timeout backstop and the three-layer mutex.
4. **K × engines ≤ max_workers.** The per-engine ceiling K (default 2) times the engine count MUST be ≤ `max_workers` (4 in `trio_policy.json`) or the run insta-parks. With three engines, K=1 fits (3 ≤ 4); K=2 would be 6 > 4, so K is effectively capped at 1 for a full three-engine fan unless the user narrows the engine set. Check before fanning out and PARK honestly if it would breach.

---

## Phase 1 — Scaffold the three-engine hand-off

Goal: produce the shared hand-off artifacts at `<target-dir>/` so each engine can run its pass. Reuse peer-audit's `bin/` wholesale, scaffolding with the **three rater slots + the user target** so the generalized pipeline carries them end-to-end.

**Step 1.1 — Slug + target dir.** Run `bash pipeline/bin/slugify.sh "<subject>"` → kebab slug. Target dir: `--target-dir <path>` if given, else an inferred `docs/<scope>/`, else default `docs/forge/<slug>/`.

**Step 1.2 — Detect the two non-Opus engines.**

- Codex: `bash pipeline/bin/detect_codex.sh` → binary path or empty.
- Gemini: `GEMINI_BIN` (PATH `gemini`, else `/opt/homebrew/bin/gemini`). The generic `--invoke "<template>"` mechanism in `invoke_codex_cli.sh` accepts an arbitrary binary, so Gemini reuses the same invoker with `--binary <gemini-cli>` — no new invoker needed.

Opus (you) is always present as the third rater + the merge/adjudication owner. Opus's rating is produced **in-session** (Step 3.4), recorded as a real rater row, so the three-verdict convergence gate actually sees an Opus verdict.

**Step 1.3 — Reading-order file (REQUIRED for plan mode).** Persist `<target-dir>/READING_ORDER_<slug>.txt` (one `  - path` per line) listing the subject docs plus the fit anchors: `PROJECT_CHARTER.md`, `README.md`, and the polish rubric `orchestration/skills/polish/SKILL.md` (part of the larger orchestration system, not included in this extract; the locked craft × fit scoreboard). Plan-mode scaffold errors without it; the persisted file lets Phase 4 regenerate the next pass with identical scope.

**Step 1.4 — Scaffold with the rater set + the user target (the generalized flags).** Use peer-audit's scaffold, passing the three raters and the user's N so the state file is born with the right shape — do NOT scaffold a 2-rater default and hand-promote it afterward:

```
bash pipeline/bin/scaffold_handoff.sh \
  --subject "<subject>" --slug "<slug>" --mode <plan|code> \
  --target-dir "<target-dir>" --pass 1 \
  --raters "opus,codex,gemini" \
  --target-craft <N> --target-fit <N> \
  --reading-order "<target-dir>/READING_ORDER_<slug>.txt"
```

This writes `CODEX_PROMPT_<slug>.md` (the rater-neutral paste/CLI block each engine runs), `HANDOFF_<date>_<slug>.md` (with the N-rater history headers/alignment substituted), and the machine state file `<target-dir>/.peer-audit-<slug>.json`. Because `--raters` and `--target-*` were passed, the state file's top-level `raters` array is `["opus","codex","gemini"]`, `convergence.target_craft`/`target_fit` hold the user N, and each per-pass `raters` map has three slots — exactly what the generalized `update_state.py` and `generate_converged_report.py` expect. (The scaffold defaults to `raters="codex,claude"` + 9.5/9.5, so the classic two-rater shape is preserved when those flags are omitted; Forge always passes them.)

**Step 1.5 — Right-size the fleet under the K × engines ≤ 4 fence.** K is a **CEILING, not a target.** Start with **1 agent per engine** for pass 1 (3 engines × 1 = 3 ≤ 4, fits). Only escalate toward K in later passes if BOTH hold: (a) early rounds show the target is _reachable_ (scores climbing, not plateaued), AND (b) the extra agents are _paying_ in distinct findings (diversity, not duplicate flags) — AND the K × engines ≤ max_workers fence still holds. If a second agent on an engine returns near-identical findings, drop back. Do not spend the ceiling reflexively.

**Step 1.6 — Report.** In chat: scaffold path, the three engines (Opus always; Codex/Gemini detected or paste-fallback), domain + its weight table / fleet ratio / roles, target N, ceiling K, mode. Hand to Phase 2.

---

## Phase 2 — Trio pass (fan out by domain ratio, doer != rater)

Goal: each engine produces/polishes its lane, then the OTHER engines rate it. **Rule 1 — doer != rater across engines:** an engine never scores its own candidate; the other two rate it. Opus is one of the three raters AND the merge owner.

**Decompose into scope-disjoint lanes** (warp decomposer; check `orchestration/bin/codex-scope-overlap.sh` before parallel dispatch). Route authorship with the trio policy + the domain ratio rather than re-encoding weights:

- `source pipeline/bin/trio_policy.sh`; `trio_route_author <sensitive> codex gemini` echoes the worker engines eligible to author the lane (drops Gemini on Tier-3 sensitive); `trio_route_reviewers <author>` returns the other duet engine + always Gemini for review.
- Apply the **domain fleet ratio** (`trio_policy.json`) to decide HOW MANY agents per engine within the K × engines ≤ 4 budget: code mode leans Codex (the author workhorse, 40%), UI mode leans Gemini (the design author/reviewer, 30%) over Codex (25%).
- In **write** (mutual-polish) mode each author polishes its lane, then the lanes SWAP and each engine peer-reviews + edits another's work in-worktree. In **advisory** (rate-only) mode engines score but never edit source.

### Dispatch (reuse the spawners AS-IS — never raw `codex exec` / `gemini`)

Per lane, one parallel batch, each into its own worktree, each with the timeout backstop and `NO_TERMINAL` for unattended runs:

```
# Codex lane (author in code mode; code-correctness reviewer in UI mode)
CODEX_CD=<worktree> CODEX_MAX_MIN=20 CODEX_SCOPE=<nearest-ancestor> CODEX_NO_TERMINAL=1 \
  orchestration/bin/codex-spawn.sh <target-dir>/CODEX_PROMPT_<slug>.md          # task_id on last line → | tail -1

# Gemini first-pass authoring lane (UI mode, NON-sensitive only; worktree-only)
GEMINI_CD=<worktree> GEMINI_MAX_MIN=25 GEMINI_SCOPE=<globs> GEMINI_NO_TERMINAL=1 \
  orchestration/bin/gemini-spawn.sh <target-dir>/CODEX_PROMPT_<slug>.md

# Gemini read-only review (the code-mode checkpoint auditor; on the real repo root — fence-exempt, read-only)
orchestration/bin/gemini-review.sh <lane.diff-or-file> [scope-globs...]
```

In **code** mode Gemini runs ONLY via `gemini-review.sh` (read-only checkpoint auditor). In **ui** mode Gemini may additionally author non-sensitive design lanes via `gemini-spawn.sh`. Up to **K agents per engine** (Phase 1 ceiling, within the K × engines ≤ 4 fence), each with a distinct `--output-file`. `gemini-review.sh` owns the read-only brief + the daily budget + the visible degrade-to-duet log — do not build a separate review path.

### CLI-vs-paste fallback (reuse peer-audit's plumbing per engine)

For each non-Opus engine, if its CLI is absent or the user chose paste: `bash pipeline/bin/emit_paste_block.sh "<target-dir>/CODEX_PROMPT_<slug>.md"` copies the inner block to the clipboard; the user pastes into that engine, saves output to the expected `POLISH_<date>_<slug>_pass<N>_<engine>.md`, and signals Done via `AskUserQuestion`. Then `bash pipeline/bin/validate_codex_output.sh "<path>"` gates re-entry. With a CLI present, `invoke_codex_cli.sh --binary <engine-bin> --prompt-file <CODEX_PROMPT> --output-file <POLISH_..._<engine>.md> [--invoke "<template>"] --timeout 1800` runs it; map its exit codes (0 ok / 1 CLI-nonzero / 2 timeout / 3 validation-fail) to the same `AskUserQuestion` recovery forks peer-audit uses.

### Read-back

Poll the existing ledgers — `orchestration/bin/codex-status.sh` (table or `<task_id>` detail; owns the running→done/failed resolution) and `orchestration/bin/trio-status.sh` (review budget + degrade log). Let those own truth; do not invent a parallel ledger.

**Verify edits are real (write mode) / absent (advisory).** Before scoring a post-swap state, grep + read each patch in its worktree so a hallucinated diff is never scored as real. In advisory mode, a dirty worktree outside `<target-dir>/` = protocol-broken; ask the user to discard / keep / escalate.

Each engine's review artifact lands at `<target-dir>/POLISH_<date>_<slug>_pass<N>_<engine>.md` (parsed by peer-audit's `parse_polish_output.py`). Hand to Phase 3 once the two non-Opus rater artifacts exist, are non-empty, and validate (Opus's rating is produced in Phase 3, Step 3.4).

---

## Phase 3 — Adjudicate the three (the clever part)

Goal: turn three independent ratings into one decision per claim, surfacing disagreement instead of burying it. **Reuse `adjudicator/trio_adjudicate.py` + `pipeline/bin/ensemble_tier3.py` wholesale — do not re-derive the weight × confidence math.**

**Step 3.1 — Assemble findings + the sensitivity flag (correct path-list API).** Collect every finding from all three POLISH artifacts as `{engine, confidence (0-1), claim|file|line|title}` dicts. Classify the changed-path LIST with `tier3_hits` / `any(is_tier3(p) for p in paths)` — `is_tier3` takes a SINGLE path and silently returns False on a list, defeating the sensitive branch:

```
python3 - <<'PY'
import importlib.util
ROOT = "$REPO_ROOT"
# bin/lib has NO __init__.py — `from lib.trio_adjudicate import adjudicate` is BROKEN.
# Load both modules by absolute path (the only working pattern; cf. goal.py _load_module + tests/test_trio_adjudicate.py).
def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, f"{ROOT}/{rel}")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
adj = load("trio_adjudicate", "adjudicator/trio_adjudicate.py")
t3  = load("ensemble_tier3",  "pipeline/bin/ensemble_tier3.py")

changed_paths = [...]                 # the list of files the lanes touched
sensitive = bool(t3.tier3_hits(changed_paths))   # CORRECT: list → tier3_hits, NOT t3.is_tier3(list)

findings = [ {"engine": "opus", "confidence": 0.8, "file": "x.py", "line": 12, "title": "..."}, ... ]
verdicts = adj.adjudicate(findings, sensitive=sensitive, weights=None)  # weights=None => shared trio_policy.json
PY
```

**Step 3.2 — Adjudicate.** `adjudicate(findings, sensitive=<bool>, weights=None)` defaults weights from `trio_policy.json` (Opus 9 / Codex 8.5 / Gemini 8 — read, never hardcode). It groups findings per claim, computes agreement (≥2 distinct engine families), noisy-or cross-engine confidence, and `boosted_force = top_weight × claim_confidence`, returning one verdict per claim ∈ {ACT, ESCALATE, DISMISS}. (`trio_adjudicate.py` carries the general/code weights; UI-domain weighting affects authorship + fleet ratio, not the adjudication math, which stays on the trust-lineage weights.)

**Step 3.3 — Apply the loop rules on the verdicts:**

- **Rule 2 — disagreement is the deliverable.** Where all three converge (agreement, same direction) → auto-resolve (ACT/DISMISS). Where they diverge on a score or a finding → DO NOT average it away; surface the gap as a decision point in the residue (Phase 5).
- **Rule 3 — minority report.** When 2 raters pass but 1 objects hard, the objection ESCALATES for a focused look; it is **never silently outvoted**. On sensitive diffs the adjudicator (Opus, top weight) decides; a sub-top or Gemini-only flag escalates, never auto-dismisses and never vetoes alone.
- Opus (adjudicator, weight = max) owns ACT/ESCALATE resolution; record who raised each ESCALATE.

**Step 3.4 — Opus's in-session rating (doer != rater, recorded as a real rater row).** Opus forms its OWN craft + fit grade per category from the source — anchored on the fit docs (`PROJECT_CHARTER.md`, `README.md`, latest `docs/VISION_REVISION_*.md`) and the polish rubric (`orchestration/skills/polish/SKILL.md`, part of the larger orchestration system, not included in this extract), NOT on the other engines' scores. Cite ≥1 file:line per craft grade; cite the served objective per fit grade. Run the forbidden-phrase gate (`grep -nE "seems reasonable|looks fine|could be better|appears to be solid|generally well-structured"`) before any score is accepted. This rating is real and produced now, so the three-verdict convergence gate sees a genuine Opus verdict (never a placeholder). Opus only rates lanes it did not author (doer != rater).

**Step 3.5 — Update state with all three raters + the user target (the generalized updater).** Feed the three rater rows into peer-audit's generalized `update_state.py` (N-rater dialect). `decide_convergence` reads `target_craft`/`target_fit` from the state (the user N) and requires EVERY rater verdict==GO AND craft ≥ target AND fit ≥ target AND `new_findings == 0`. In N-rater mode `--new-findings` is REQUIRED (there is no single canonical Claude report to parse):

```
python3 pipeline/bin/update_state.py \
  --state "<target-dir>/.peer-audit-<slug>.json" \
  --pass <N> \
  --new-findings <count> \
  --rater opus   --craft <c> --fit <f> --verdict <GO|GATED-GO|NO-GO> --rater-output "<target-dir>/POLISH_<date>_<slug>_pass<N>_opus.md" \
  --rater codex  --craft <c> --fit <f> --verdict <...>                --rater-output "<target-dir>/POLISH_<date>_<slug>_pass<N>_codex.md" \
  --rater gemini --craft <c> --fit <f> --verdict <...>                --rater-output "<target-dir>/POLISH_<date>_<slug>_pass<N>_gemini.md"
```

(Carry the open-findings list forward across passes with `--findings-from <a-report>` when you have a canonical accounting block; otherwise `--new-findings` is the required scalar.) Stdout is a JSON object carrying the per-engine `raters` map + `convergence.status`. Capture it — Phase 4 reads it. The known-paid bug fixes are intact in the updater (plateau compares `history[-2]` since this pass is pre-appended; the same-pass row is REPLACED not appended; state written via `json.dump`); do NOT re-implement that logic.

**Step 3.6 — Report.** In chat: each engine's craft/fit/verdict, the adjudicated ACT/ESCALATE/DISMISS counts, and the count of live disagreements. Hand to Phase 4.

---

## Phase 4 — Convergence check + safety gate + loop

Two gates run here, and they are NOT the same gate:

1. **The user-target convergence gate** = `update_state.py`'s `decide_convergence` (already ran in Phase 3, Step 3.5). It is the authoritative answer to "is this good enough yet?" — it reads the user N from `convergence.target_craft`/`target_fit` and requires ALL THREE raters GO at ≥ N with zero new findings. Its verdict is written to `convergence.status` ∈ {`converged`, `plateau`, `did_not_converge`, `pending`}.
2. **The fixed safety floor** = `orchestration/bin/goal.py gate`. It answers "may this ever land?" — doer != rater independence, the 9.5 high-stakes / Tier-3 / irreversible / user-facing escalation, and the leak/scope-clean check. **It does NOT know the user's N** (`BAR_MIN` is hardcoded 8.5); never claim it enforces N. Run it on the highest-stakes lane to confirm the result is even land-eligible before treating a `converged` status as shippable.

**Step 4.1 — Read the user-target convergence status.**

```
STATUS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["convergence"]["status"])' "<target-dir>/.peer-audit-<slug>.json")
```

**Step 4.2 — Run the fixed safety floor** per the highest-stakes lane:

```
python3 orchestration/bin/goal.py gate --rating <min-of-three-aggregates> --rater <independent-engine> --doer <author-engine> \
  [--tier3] [--irreversible] [--user-facing]
```

It returns `{verdict: land_eligible|loop|park, reason, escalate}`. doer != rater is enforced in code: a self-score, doer==rater, unknown doer, or non-finite/out-of-range rating can NEVER land. A Tier-3 / user-facing / irreversible at-bar result PARKS + escalates (needs ≥ 9.5 + explicit human GO). This floor is independent of and additional to the user-target gate.

**Step 4.3 — Branch on BOTH gates:**

| `decide_convergence` status    | `goal.py gate` verdict                                    | Action                                                                                                                                           |
| ------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `converged`                    | `land_eligible`                                           | → Phase 5 (converged + shippable).                                                                                                               |
| `converged`                    | `park` / `escalate` (Tier-3 / irreversible / user-facing) | → Phase 5, but the residue flags the human-GO gate; never auto-land.                                                                             |
| `pending`                      | (any)                                                     | budget remains → increment pass, re-scaffold with `--carry-findings <state.json>` + same `--raters` + same `--reading-order`, return to Phase 2. |
| `plateau` / `did_not_converge` | (any)                                                     | → Phase 5 as an **honest park** (rule 4).                                                                                                        |

**Step 4.4 — Plateau detection (rule 4 — honest park).** `decide_convergence` already compares this pass's three rater scores to the prior pass (`history[-2]`, because this pass is appended before the check) and writes `plateau` when pass ≥ 2 AND no new findings AND scores unchanged across all three engines. Polish alone cannot reach the target. PARK with a diagnosis, never fake convergence and never lower N:

> Parked at **86 / target 90**. The last 4 points need a structural choice, not more polish: **X** (rework the publish path for idempotency) **or Y** (accept the current path + document the at-most-once caveat). All three engines agree polish has plateaued here.

**Step 4.5 — Budget + halt ceilings.** Hard pass ceiling = 5 (the updater writes `did_not_converge` after pass 5). User signal phrases (stop / kill / freeze / abort) interrupt to Phase 5. Re-run the halt-check at this boundary. Re-confirm the K × engines ≤ 4 fence before any re-fan.

Before each loop iteration, announce the next pass via `AskUserQuestion` when available (fire pass N+1 / accept current as good-enough / restart with different scope). Per Phase 0, this inherits the runtime adapter.

---

## Phase 5 — Converged work + decision residue (RECORD)

Goal: emit the polished work PLUS the decision-residue batch, and record the run.

**Step 5.1 — Generate the converged report.** Reuse peer-audit's generator unchanged — it derives the rater set from `state.raters` (`["opus","codex","gemini"]` here) and emits N rows in every table, reading the user target from state (no 9.5 literal):

```
python3 pipeline/bin/generate_converged_report.py \
  --state "<target-dir>/.peer-audit-<slug>.json" \
  --output "<target-dir>/CONVERGED_<date>_<slug>.md"
```

The report shows all three engines' final craft/fit/verdict and the status badge (converged / plateau / did-not-converge).

**Step 5.2 — Emit the decision residue (rule 5).** The run's output is the polished work PLUS a short, batched list of the judgment calls **only a human should make** — the live disagreements (rule 2), the escalated minority reports (rule 3), the structural fork from any plateau (rule 4), and any Tier-3 / user-facing / irreversible gate that the safety floor held for human GO. Keep it tight: each item is one line — the call, the two options, and which engines split. Surface it as ONE batched `AskUserQuestion` (bundle up to 4 lanes; do not dribble) when available; otherwise present the numbered residue and ask once.

**Step 5.3 — Record the run (allowlisted payload only).** Once, advisory, never blocking. Use ONLY keys in the recorder's allowlist (`run_id`, `topology`, `shape`, `tier3`, `scope_globs`, `exploration`):

```
python3 orchestration/bin/ensemble-recorder.py record '{"run_id":"forge-<slug>-<ts>","topology":"forge","shape":"<plan|code>","tier3":<bool>,"scope_globs":[...],"exploration":false}'
```

Reuse the existing hash-chained ledger + redactor — do not invent a parallel one. If Forge needs a new telemetry field, ADD it to `_ALLOWED_ENTRY_KEYS` + a sanitizer in `orchestration/bin/ensemble-recorder.py`; never bypass `sanitize_run` or smuggle an off-allowlist key.

**Step 5.4 — Close-out fork.** Present the polished branch + converged report + residue, then a rapid-fire fork (commit the converged artifacts / open the report / run another forge) when `AskUserQuestion` is available. Never push without explicit approval; the merge to main is a separate gated step Forge never performs.

---

## Triggers

**Verbal:** "forge", "trio audit", "three-way review", "triple review", "Opus Codex Gemini review", "converge to <N>", "polish with all three", "trio converge"
**Slash:** `/forge [subject] [to <N>] [--target <N>] [--ceiling <K>] [--domain ui|general] [--advisory]`
**Implicit:** none — user invokes explicitly. (Maestro may _recommend_ it via rapid-fire but does not auto-fire it.)

## Composability with the larger orchestration system

| Skill             | Relationship                                                                                                                                                                                                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `peer-audit`      | Direct parent — the now-N-rater loop. Forge fills three rater slots (Opus + Codex + Gemini), passes the user-set target, and applies the per-engine ceiling + domain ratio. Forge reuses peer-audit's entire generalized `bin/` + state schema + carry-findings loop; it does not fork them or hand-roll a parallel state file. |
| `polish`          | Provides the locked two-axis craft × fit rubric Forge converges toward. Phase 3's Opus in-session re-score IS polish's rating prompt.                                                                                                                                                                                           |
| `rate-code`       | Score anchor for code-mode forge runs.                                                                                                                                                                                                                                                                                          |
| `goal`            | Forge reuses `/goal`'s ORIENT→…→RECORD spine and `orchestration/bin/goal.py gate` for the FIXED safety floor (doer != rater + 9.5 high-stakes + leak). The user target N is enforced separately by `update_state.py`'s `decide_convergence`, NOT by `goal.py gate`.                                                                           |
| `warp-recon`      | A scout pass can map the subject before a code-mode forge so the lanes start scoped, not exploring.                                                                                                                                                                                                                             |
| `autopilot`       | After convergence + explicit approval, implementation of escalated structural forks may fire via autopilot as a separate unit.                                                                                                                                                                                                  |
| `collision-check` | Any follow-up implementation train runs collision-check before each commit. Review-only forge artifacts do not clear commit safety.                                                                                                                                                                                             |

## When NOT to fire

- **Single-rater is enough** — for a one-shot review use `polish`; for a code score use `rate-code`. Forge's cost (three engines + iteration) only pays when convergence + cross-model disagreement is the point.
- **Two raters suffice** — if Gemini is unavailable or the work is Tier-3 (Gemini can't first-pass it), `peer-audit` (Opus + Codex) is the right tool, not a degraded forge.
- **The bar is unreachable by polish** — if the subject needs a structural rewrite, not category-level polish, Forge will plateau and park immediately. Name the structural choice and route to a plan/implementation unit instead.
- **No larger orchestration context** — Forge can still be read as a protocol, but the engine dispatchers and P0 fences under `orchestration/...` are part of the larger orchestration system, not included in this extract.
- **It's an implementation request** — Forge produces converged, polished work + residue; it never pushes and never merges to main. A "ship it" request is autopilot/`/goal`, not Forge.

## Failure-mode signatures (catch your own drift)

- **Rebuilt the loop instead of extending peer-audit** — wrote a fresh scaffold/parse/update/converge pipeline, or hand-promoted a `.forge-<slug>.json` instead of scaffolding `.peer-audit-<slug>.json` with `--raters`/`--target-*`. Recovery: delete the duplicate, re-scaffold via `pipeline/bin/scaffold_handoff.sh --raters "opus,codex,gemini" --target-craft N --target-fit N`, and drive the generalized `update_state.py` — Forge is peer-audit with the rater set filled to three + a user-set bar, not a from-scratch protocol.
- **Claimed `goal.py gate` enforces the user target N** — treated the 8.5 safety floor as the convergence bar, or skipped `decide_convergence`. Recovery: restore the two-gate split — `update_state.py`'s `decide_convergence` reads `convergence.target_craft`/`target_fit` and is the only thing that enforces N; `goal.py gate` is the fixed floor (doer != rater + 9.5 high-stakes + leak). Re-run both.
- **Passed a path LIST to `is_tier3`** — called `is_tier3(changed_paths)`, which silently returns False and defeats the sensitive-diff branch. Recovery: switch to `tier3_hits(paths)` or `any(is_tier3(p) for p in paths)`; re-classify the diff and re-route Gemini off any newly-revealed Tier-3 lane.
- **Used `from lib.trio_adjudicate import adjudicate`** — the broken import (`bin/lib` has no `__init__.py`). Recovery: load both modules via `importlib.util.spec_from_file_location` against the absolute paths (`$REPO_ROOT/adjudicator/trio_adjudicate.py`, `$REPO_ROOT/pipeline/bin/ensemble_tier3.py`), the only working pattern (cf. `goal.py` `_load_module` + `tests/test_trio_adjudicate.py`).
- **An engine scored its own candidate** — doer == rater broke rule 1. Recovery: discard that self-score, route the candidate to the other two engines (`trio_route_reviewers`), and re-run the gate, which fails closed on doer==rater anyway.
- **Averaged away a disagreement** — collapsed a three-way score split into one blended number, violating rules 2-3. Recovery: restore the per-engine rows, surface the gap as a decision-residue item, and escalate any hard minority objection instead of outvoting it.
- **Faked convergence or lowered N to finish** — declared GO below the user target, or edited `convergence.target_*` mid-run. Recovery: restore N, re-run `update_state.py` `decide_convergence`; if polish has plateaued, PARK with the structural diagnosis (rule 4) — the bar lives outside the doer's reach for exactly this reason.
- **Breached the K × engines ≤ 4 fence or spent the ceiling reflexively** — fanned out 3 engines × 2 agents (6 > 4), or escalated to K with no evidence of payoff, violating rule 6. Recovery: drop back to 1 agent/engine (3 ≤ 4), escalate toward K only when scores climb AND extra agents return distinct findings AND the product stays ≤ 4.
- **Ran a worker on the live tree, pushed from a lane, or recorded an off-allowlist key** — bypassed the worktree-only / single-egress / allowlisted-payload fences. Recovery: stop; move the lane into a `orchestration/bin/codex-worktree.sh` worktree (spawners refuse with exit 4 otherwise); route integration through the duet_hold merge (workers are commit-only, push default-deny); and record only `run_id`/`topology`/`shape`/`tier3`/`scope_globs`/`exploration` via `sanitize_run`.
- **Shipped the converged report without the decision residue** — emitted polished work but no batched human-judgment list, violating rule 5. Recovery: assemble the residue from the live disagreements + escalated minority reports + any plateau fork + any human-GO gate, and surface it as one batched question before close-out.

## Cross-references

- `orchestration/skills/peer-audit/SKILL.md` — the now-N-rater parent Forge fills to three; source of the reused generalized `bin/`, state schema, and carry-findings loop.
- `orchestration/skills/polish/SKILL.md` — the locked craft × fit rubric, the convergence scoreboard, and the prompt for Opus's in-session re-score.
- `orchestration/skills/goal/SKILL.md` + `orchestration/bin/goal.py` — the ORIENT→…→RECORD spine and the FIXED safety floor (`gate`); it does NOT enforce the user N.
- `adjudicator/trio_policy.json` — the operator-owned domain table (weights + fleet ratio + roles for general/code vs ui/design); one-line-editable, cleave-safe.
- `pipeline/bin/trio_policy.sh` + `adjudicator/trio_policy.json` — trust weights (Opus 9 / Codex 8.5 / Gemini 8) + author/reviewer routing + the sensitive-lane first-pass bar; read, never hardcode.
- `adjudicator/trio_adjudicate.py` + `pipeline/bin/ensemble_tier3.py` — the weight × confidence adjudication and the Tier-3 sensitivity classifier (`is_tier3` = one path; `tier3_hits` = a list).
- `pipeline/bin/update_state.py` + `generate_converged_report.py` + `scaffold_handoff.sh` — the generalized N-rater pipeline (scaffold with `--raters`/`--target-*`; `decide_convergence` reads the user N from state).
- `orchestration/bin/codex-spawn.sh`, `orchestration/bin/gemini-spawn.sh`, `orchestration/bin/gemini-review.sh` — the fan-out substrate (worktree-only, timeout-capped, ledgered).
- `orchestration/bin/ensemble-halt-check.sh`, `orchestration/bin/ensemble-recorder.py`, `orchestration/bin/ensemble-leak-gate.py` — the P0 halt fence, the hash-chained run recorder (allowlisted payloads only), and the leak gate.
- `docs/DUET_PROTOCOL.md` — the mutual-polish ensemble mechanic Forge extends to three engines.
- `orchestration/memory/rapid_fire_format.md` — the decision-point response shape every phase inherits.

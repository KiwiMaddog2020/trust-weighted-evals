# Forge loop contract

This is the implementation-grade specification of the Forge loop that
`SKILL.md` references. `SKILL.md` is the operator-facing protocol (Phase 0
through the close-out); this file is the precise state machine, the exact
engine invocations, the scoring and combination math, the termination
conditions, and how the six loop-logic items are realized concretely. Where
the two disagree, the running code wins, then this contract, then `SKILL.md`.

Forge is `peer-audit` generalized from two raters to N (here three), with the
quality bar and the per-engine agent count promoted from hard-coded to
user-set. It does NOT reimplement the loop. The peer-audit pipeline already
GENERALIZED to N raters (its four scripts — `update_state.py`,
`generate_converged_report.py`, `scaffold_handoff.sh`, and the
`state_schema.json` / `CONVERGED_template.md` / `HANDOFF.md` templates — now
carry an ordered `raters` list and per-pass `raters` map, and a user-set
`convergence.target_craft` / `target_fit`), so Forge WIRES INTO it rather than
hand-rolling a third rater slot. Forge reuses:

**Public extract note:** `adjudicator/...`, `pipeline/bin/...`, and
`protocol/...` are the repo-relative components shipped in this extract. Paths
under `orchestration/...`, plus references to `codex-spawn.sh`,
`gemini-spawn.sh`, `gemini-review.sh`, `goal.py`, halt/P0 fence scripts,
`maestro-decision.sh`, and `AskUserQuestion`, are part of the larger
orchestration system, not included in this extract.

- the `peer-audit` Phase 0 to 5 skeleton, gate discipline, slugify or
  scaffold or parse or converged-report scripts, and the state-file plus
  carry-findings mechanism (now N-rater native);
- the `polish` two-axis craft by fit rubric as the convergence target;
- the three Trio engine-lane dispatchers (`orchestration/bin/codex-spawn.sh`,
  `orchestration/bin/gemini-spawn.sh`, `orchestration/bin/gemini-review.sh`);
- the Trio trust model (`adjudicator/trio_policy.json`, `pipeline/bin/trio_policy.sh`,
  `adjudicator/trio_adjudicate.py`, `pipeline/bin/ensemble_tier3.py`);
- the `/goal` spine (`orchestration/bin/goal.py`) for the fail-closed land-or-loop-or-park
  SAFETY FLOOR, the budget-as-code, the survey, and the recorder entry;
- the P0 cage (`orchestration/bin/ensemble-halt-check.sh`, the worktree fence, the egress
  chokepoint, the timeout and mutex caps, `orchestration/bin/ensemble-recorder.py`).

The canonical cross-model mechanics both Forge and the duet inherit live in
`orchestration/docs/DUET_PROTOCOL.md`. The Trio trust model lives in
`docs/TRIO_TRUST_MODEL_2026-06-03.md`. Read those before relitigating any
weight, threshold, or routing rule here.

### Two gates, kept distinct (read this before Section 6)

The convergence decision and the safety floor are SEPARATE checks, owned by
SEPARATE code. Do not conflate them.

- **The user target N is the authoritative convergence bar.** It lives in the
  state file (`convergence.target_craft` / `convergence.target_fit`) and is
  enforced ONLY by the peer-audit pipeline's generalized
  `update_state.decide_convergence`, which reads the target FROM state and
  requires EVERY rater verdict == GO AND craft >= target AND fit >= target AND
  `new_findings == 0`. `orchestration/bin/goal.py` does NOT read or enforce N.
- **`orchestration/bin/goal.py gate()` is the fixed SAFETY FLOOR, not the target gate.** It
  hard-codes `BAR_MIN = 8.5` and `HUMAN_GO_BAR = 9.5` and takes no target
  parameter. Its job is the anti-gaming independence check (doer != rater
  family, unknown doer, self-score), the malformed-rating rejection, the
  high-stakes escalation (Tier-3 / irreversible / user-facing at-bar -> needs
  9.5 + explicit human GO), and the leak-gate. It is a per-rating floor that a
  passing convergence must ALSO clear; it never substitutes for N and N never
  substitutes for it. A run converges only when BOTH hold: the pipeline's
  N-target gate is GO for all raters AND every rating cleared `gate()`.

---

## 1. User-tunable parameters

The loop is parameterized by five user-set inputs, resolved in Phase 0 of
`SKILL.md` and threaded through every phase below. They live OUTSIDE the
doer's reach (passed in, or held in the state file's `convergence` block and
in code, never editable by a worker mid-run), so a running agent cannot game
or lower the bar.

| Param         | Type                                              | Default                 | Meaning                                                  |
| ------------- | ------------------------------------------------- | ----------------------- | -------------------------------------------------------- |
| `subject`     | string                                            | active project codebase | what is being polished and rated                         |
| `target`      | craft and fit both at or above N, 0 to 10         | 9.5                     | the convergence GO gate the loop converges toward        |
| `raters`      | ordered engine list                               | `opus,codex,gemini`     | the N rater engines (Forge default is three)             |
| `ceiling` (K) | int per engine, 1 to K                            | 2                       | max agents per engine per round (a CEILING, not a count) |
| `mode`        | `write` (mutual-polish) or `advisory` (rate-only) | `write`                 | whether engines edit each other's work or only score it  |

`target` is stored as `convergence.target_craft` and `convergence.target_fit`
in the state file (the pipeline defaults both to 9.5 for the legacy 2-rater
case; Forge sets them explicitly via the scaffold's `--target-craft` /
`--target-fit` flags). The convergence gate reads these stored user values; it
is NOT a 9.5 literal anywhere in `update_state.py` or
`generate_converged_report.py` after the generalization.

`raters` is the ordered engine set the scaffold writes into `state.raters`
(`scaffold_handoff.sh --raters "opus,codex,gemini"`). Every per-pass update
then supplies one `--rater NAME --craft C --fit F --verdict V` group per engine
(or a single `--raters-json`). The default `codex,claude` reproduces the
byte-for-byte legacy peer-audit two-rater shape.

The high-stakes SAFETY FLOOR is NOT user-lowerable and is owned by `gate()`,
NOT by the target. If the subject touches Tier-3, is user-facing, or is
irreversible, then even when every rater clears the user `target`, `gate()`
returns `park` + `escalate` and the run requires `HUMAN_GO_BAR` (9.5) AND
the operator's explicit GO. A user-set `target` below 9.5 does NOT relax this — the
floor is independent of N. (A `target` below 8.5 also still has to clear
`gate()`'s `BAR_MIN`; `gate()` loops anything under 8.5 regardless of N.)

`ceiling` (K) is per engine, user-set, default 2. The fleet never starts at
the ceiling. It starts at 1 to 2 agents each and escalates only when loop
logic item 6 (right-size the fleet) says diversity is paying and the target is
reachable. **K hard-constraint:** `K * len(raters)` worker engines MUST be
`<= max_workers` (4, from `DEFAULT_BUDGET`); if `K * engines > 4` the run
INSTA-PARKS at PROBE before spending any tokens (the blast-radius worker cap is
the bound). With three raters where only Codex and Gemini are spawnable workers
(Opus is the in-session orchestrator), the effective worker count is
`K * 2 <= 4`, so `K <= 2`.

`mode` defaults to `write`. `advisory` (rate-only, no source edits) is the
safety fallback for the same cases peer-audit names: security-sensitive code
(auth, payments, runner control), thin test coverage, unfamiliar codebase,
architectural findings needing an RFC first, or an explicit user request.

---

## 2. State machine

```
CLASSIFY  ->  PROBE  ->  FAN  ->  RATE  ->  ADJUDICATE  ->  APPLY  ->  CHECK
sensitivity  right-size  trio    cross-    trust-weighted  convergent  target /
             the probe   author  engine    (doer != rater) improvements plateau /
                                  rate                                  budget
                                                                          |
                                          +-------------------------------+
                                          |                               |
                                  CHECK = continue                CHECK = stop
                                          |                               |
                                          v                               v
                                     loop to FAN                  PARK or RECORD
```

Each state below names the exact code it calls, its inputs, its outputs, and
its fail-closed behavior. The loop is a bounded iteration; `round` increments
on each FAN, and the budget (Section 6.4) is the hard ceiling on rounds.

### 2.0 Precondition on every state transition: HALT

The FIRST executable action of the loop, and the first action re-run at every
phase and role boundary, is:

```
"$REPO_ROOT/orchestration/bin/ensemble-halt-check.sh" || exit 99
```

Exit 99 means `state.d/ENSEMBLE_HALT` exists; the loop stops immediately and
routes to RECORD with whatever partial state it holds. This is a cooperative
start-gate, not a security boundary: the same-user owner can clear the flag,
and the real runaway-stop is out-of-process (`orchestration/bin/actions.sh kill`).
Forge must therefore also be killable by `pkill` and must re-poll the halt at
every boundary, not only at startup. Cycle-freeze
(`state.json.autopilot_freeze_until` in the future) short-circuits the same way.

### 2.1 CLASSIFY (sensitivity + domain)

Determine two facts before any token spend: (a) whether the subject's changed
scope is Tier-3 sensitive, and (b) which DOMAIN (general/code vs UI/design) the
subject is, because the domain selects the weight table and the fleet ratio
(Section 5.0).

Tier-3 sensitivity — the single fact that forces routing, the adjudication
branch, the effective floor, and the mode:

- Source of truth: `pipeline/bin/ensemble_tier3.py` reading the shipped Tier-3
  path patterns.
- **API discipline (do not get this wrong):** `is_tier3(path: str) -> bool`
  takes ONE path. For the subject's path LIST, use
  `tier3_hits(paths) -> list[str]` (the matching paths) or
  `any(is_tier3(p) for p in paths)`. Passing a LIST to `is_tier3` is a bug:
  `fnmatch` silently returns False for a list-repr, which would defeat the
  whole sensitive-diff branch. Shell callers use
  `trio_scope_is_sensitive <paths...>` in `pipeline/bin/trio_policy.sh` (exit 0 if
  any path is tier3), which shells `ensemble_tier3.py` and counts `^TIER3 `
  lines.

```python
# CLASSIFY sensitivity — the ONLY correct shapes:
hits = tier3_hits(changed_paths)           # list of the sensitive paths (for residue)
sensitive = bool(hits)                      # or: any(is_tier3(p) for p in changed_paths)
# WRONG: is_tier3(changed_paths)  -> always False on a list; defeats the branch.
```

- `fnmatch` globs deliberately span `/` (over-match is safe: more match means
  more review). Foreign or absolute or `..` paths are anchored back to
  repo-relative tails before matching (`normalize_path` + `_match_candidates`).
- Output: a boolean `sensitive`, plus `hits` (the tier3 path list) for the
  decision residue.

Domain — selects the weight table and fleet ratio (Section 5.0):

- Classify the subject by changed scope: CSS / HTML / templates / visual-asset
  globs => `ui`; everything else => `general`. An explicit `--domain ui`
  overrides the classifier.
- The domain is stored in the run's recorder `shape` string and used to pick
  the `trio_policy` weight set and the fleet ratio. It does NOT change the
  adjudication math, only the weights fed to it.

CLASSIFY also runs the `/goal` ORIENT predicates so the loop knows whether to
ask before acting:

- `python3 orchestration/bin/goal.py survey` loads the present direction-signal docs.
- `should_ask(novel_mandate=, irreversible=, tier3_adjacent=, ambiguous=)` in
  `orchestration/bin/goal.py`. If True, buffer a decision via
  `orchestration/bin/maestro-decision.sh add --lane forge --question "..."` and STOP before
  acting; the move waits for the human. Never freelance a sensitive or
  irreversible or novel-mandate or ambiguous structural choice.

`sensitive` propagates as: (a) the `--tier3` flag to `goal.py gate`; (b) the
`sensitive=` argument to `trio_adjudicate.adjudicate`; (c) the routing input to
`trio_route_author`; (d) the trigger for the 9.5-plus-GO SAFETY FLOOR in
`gate()` (NOT a clamp on the user `target`).

### 2.2 PROBE (right-size the probe + the fleet)

Decide how much work to attempt this round and how to split it, before
spending any engine tokens. This is the PLAN step.

- If a recent `docs/POLISH_*.md` or `docs/CODE_RATING_*.md` exists for the
  subject, read it as the baseline rather than rating from scratch.
- Decompose the subject into scope-disjoint units. Check for overlap with
  `orchestration/bin/codex-scope-overlap.sh` BEFORE any parallel dispatch; overlapping lanes
  are merged or serialized, never run concurrently.
- Per unit, call `plan_topology(difficulty, stakes, isolation, scope_globs)`
  in `orchestration/bin/goal.py` (which delegates to the F4 router `orchestration/bin/ensemble-route.py`).
  It returns `{topology in (same_problem, disjoint_lanes, relay), reason,
tier3, mutual_act}`. `mutual_act` is advisory-only and always false from the
  router.
- Tier-3 scope is FORCED to `relay` (sequenced, review-only) by the router
  policy; this is validated, so a drift to `same_problem` on tier3 fails. On a
  Tier-3 subject the loop runs review-only regardless of the user's `mode`.
- Right-size to the per-run budget (Section 6.4), not a multi-week epic. Lean
  ADVANCE (improve the subject); choose POLISH-only framing when quality debt
  is blocking or embarrassingly below bar.

PROBE also enforces the K ceiling and right-sizes the FLEET (loop logic
item 6):

- **K validation:** verify `K * spawnable_engines <= max_workers` (4). If it
  exceeds, INSTA-PARK with reason "ceiling K=<K> \* engines=<n> > max_workers 4"
  — do not spend tokens. This is the resource-floor mutex made explicit.
- Set the starting agent count per engine to 1 to 2 (not the ceiling),
  recording the ceiling for escalation in later rounds.

### 2.3 FAN (fan the trio per the domain ratio)

Author the candidate work in scope-disjoint lanes, one engine per lane, in a
single parallel batch. This is EXECUTE, worktree-only. Lane assignment per
engine follows the DOMAIN fleet ratio (Section 5.0): general weights Codex
heaviest as the many-agent workhorse with Gemini read-only; UI weights Gemini
as a first-class design author over Codex.

Routing (who authors which lane) is delegated, never hand-encoded:

- `trio_route_author <sensitive 0|1> [candidates...]` in `trio_policy.sh`.
  Candidates default to `codex gemini` (Opus is the in-session orchestrator,
  not a dispatch target). On a sensitive lane, only engines at or above
  `sensitive_min_weight` (8.5) survive, so Gemini (8) is dropped; route
  sensitive lanes to Codex or keep them in-session for Opus to avoid a wasted
  refused spawn.
- The Gemini sensitive-lane refusal (exit 6 in `gemini-spawn.sh`) is the
  safety net behind the routing, so the loop never needs to pre-filter by
  hand, but it SHOULD route correctly to avoid burning a refused spawn.

Engines and their roles (Section 5.0 has the full policy):

- **Opus** = in-session Claude plus `Task` Agent subagents; adjudicator,
  merger, and author. Opus's authored work and its rating are produced
  IN-SESSION this run (not a spawned worker) and recorded as a real rater row
  (Section 4) so the N-verdict convergence gate actually sees an Opus verdict.
- **Codex** (5.5) via `orchestration/bin/codex-spawn.sh`, fast mode default; the many-agent
  workhorse author in general domain, code-correctness reviewer in UI domain.
- **Gemini** (best available model in the larger system) via `orchestration/bin/gemini-spawn.sh` (author,
  NON-SENSITIVE only) and `orchestration/bin/gemini-review.sh` (read-only review); the
  read-only third checkpoint auditor in general domain, a first-class design
  author AND reviewer in UI domain.

Worktree-only dispatch (the blast-radius fence):

- Create one fresh git worktree per lane with `orchestration/bin/codex-worktree.sh create
<task_id> <base_sha>` (forked from the last green SHA).
- Spawn one engine per lane in a single parallel batch:

```
CODEX_CD=<worktree-a> CODEX_MAX_MIN=<cap> CODEX_SCOPE=<nearest-ancestor> \
  CODEX_NO_TERMINAL=1 orchestration/bin/codex-spawn.sh <brief-a.md>      # | tail -1 -> task_id

GEMINI_CD=<worktree-b> GEMINI_MAX_MIN=<cap> GEMINI_SCOPE=<glob> \
  GEMINI_NO_TERMINAL=1 orchestration/bin/gemini-spawn.sh <brief-b.md>    # | tail -1 -> task_id
```

- The bare `task_id` is the LAST stdout line; capture it with `| tail -1`.
- The on-main refusal (exit 4) and the scope-declaration requirement are
  inherited for free. Never set `ORCHESTRATION_CODEX_ON_MAIN=1` or
  `ORCHESTRATION_GEMINI_ON_MAIN=1` unattended.
- The timeout backstop (`CODEX_MAX_MIN` or `GEMINI_MAX_MIN`, default 30,
  clamped [5, 60]) wraps every worker; a missing `timeout` binary refuses the
  spawn (exit 5). Never spawn raw `codex exec` or `gemini` without it.

Per-engine fan-out up to the ceiling K: when item 6 escalates, spawn up to
`ceiling` agents per engine, each into its OWN worktree with a distinct
`--output-file` and distinct `CODEX_CD` or `GEMINI_CD`. Reuse the same spawn
scripts per agent; do not write a new invoker. The K validation from PROBE
already guaranteed `K * engines <= 4`.

Read-back is via the existing ledgers:

- Codex ledger: `$ORCHESTRATION_STATE_DIR/codex_tasks.jsonl`; Gemini ledger:
  `$ORCHESTRATION_STATE_DIR/gemini_tasks.jsonl` (append-only, latest line per
  `task_id` wins).
- Poll with `orchestration/bin/codex-status.sh` (table or `<task_id>` detail; it resolves
  running to done or failed by probing the live PID, and lazily appends a
  completion record). `done` is strict: real work-events plus a non-empty
  `.last`, else `failed`.

FAN ends when every lane's worktree has authored work and its ledger row
resolves to `done`.

### 2.4 RATE (cross-engine, doer != rater)

Each candidate is rated by the OTHER engines, never by the engine that
produced it. This is loop logic item 1 made structural.

- Reviewer routing: `trio_route_reviewers <author-engine>` in
  `trio_policy.sh` returns the OTHER duet engine (cross-model independence)
  plus Gemini (the read-only third reviewer, always). An unknown author gets
  the full panel.
- The duet's cross-review (Claude/Opus rates Codex's lane, Codex rates
  Opus's lane) runs via the same spawn scripts in the reviewer's worktree;
  Opus's own rating pass is produced in-session.
- The third pass is Gemini read-only via `orchestration/bin/gemini-review.sh <target-or-diff>
[scope-glob...]`. It owns the diverse-lens brief, the daily budget, and the
  visible degrade-to-duet log. Do NOT build a separate review path. When the
  Gemini review budget is spent, the pass is SKIPPED and LOGGED
  (`degrade_to_duet` in `gemini_review_events.jsonl`); adjudication then sees
  two families instead of three and proceeds (agreement still needs two
  distinct lineages).

The rubric every rater applies is the `polish` two-axis rubric verbatim
(Section 5). Each rater's `(craft, fit, verdict)` for the subject is recorded
as a rater row in the state file (Section 4) via one
`--rater NAME --craft C --fit F --verdict V` group on the
`update_state.py` call. The per-rating SAFETY FLOOR `orchestration/bin/goal.py gate` is given
the REAL `doer` and `rater` identities; the fail-closed check (Section 6.1)
rejects any self-score, same-family score, unknown doer, or malformed score
regardless of value.

Mutual-polish verification (when `mode = write`): before scoring a
post-polish state, verify each reviewer's patch actually landed (grep plus
read the diff in its worktree). Never score a hallucinated diff. In
`advisory` (rate-only): run a narrow dirty-worktree check; if source changed
outside the target dir, classify the pass as protocol-broken and ask the user.

### 2.5 ADJUDICATE (trust-weighted)

Pool the findings from all raters and decide what to act on, trust-weighted,
with the adjudicator (Opus) owning sensitive claims. This is where loop logic
items 2 (disagreement is the deliverable) and 3 (minority report) are
realized.

- Engine: `adjudicator/trio_adjudicate.py`, `adjudicate(findings, sensitive=,
weights=None, act_threshold=6.0)`. `weights` defaults to the shared config
  via `load_policy()`; for a UI-domain run, pass the UI weight table
  (Section 5.0) explicitly. `sensitive` comes from CLASSIFY (Section 2.1).
- **Import the module by absolute path via importlib — there is NO package.**
  `bin/lib/` has no `__init__.py`, so `from lib.trio_adjudicate import
adjudicate` raises `ModuleNotFoundError`. The ONLY working pattern (the one
  `goal.py._load_module` and `tests/test_trio_adjudicate.py` use) is:

```python
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "trio_adjudicate",
    "$REPO_ROOT/adjudicator/trio_adjudicate.py",
)
trio_adjudicate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trio_adjudicate)
verdicts = trio_adjudicate.adjudicate(findings, sensitive=sensitive)
```

- Each finding is a dict `{engine, confidence (0 to 1), claim | file | line |
title}`. The loop assembles this list; the engine owns the math.
- Findings are grouped by `_claim_key` (the `claim`, else `file:line:title`,
  else `repr`). Each group is adjudicated once.

The math (do not re-derive):

- `finding_force(engine, confidence, weights) = engine_weight(engine) *
clamp01(confidence)`.
- `engine_weight` reads `adjudicator/trio_policy.json`: claude/opus 9, codex 8.5,
  gemini 8 in the GENERAL table (family aliases map opus or sonnet or haiku to
  claude, gpt or openai to codex, google to gemini). The UI-domain table
  (Section 5.0) re-weights Gemini above Codex. Weights are config, not code; a
  re-weight is a one-line edit both the shell and Python sides see, or an
  explicit `weights=` argument for the domain table.
- Cross-engine agreement is two or more DISTINCT families concurring on one
  claim. Confidence combines by noisy-or over per-family BEST confidences
  (`1 - prod(1 - c)`): two lineages at 0.6 give 0.84. Repeated same-family
  findings do NOT compound; only distinct lineages do.
- `boosted_force = top_weight * claim_confidence`.
- `is_adjudicator(engine) = engine_weight(engine) >= max(weights)`, that is
  Opus or Claude at the top weight (9 in general, still top in UI).

Verdict per claim (`adjudicate_claim`):

- SENSITIVE diff branch: if the adjudicator (Opus) raised the claim, `act`;
  else `escalate` (Opus adjudicates). A sub-top or Gemini-only flag is NEVER
  auto-dismissed and NEVER a veto; it escalates and is surfaced. This is the
  minority report (item 3): a single objecting engine on sensitive work is
  always escalated, never silently outvoted.
- NON-SENSITIVE diff branch: `act` when there is cross-engine agreement OR
  `boosted_force >= act_threshold` (6.0); else `dismiss`.
- Output per claim: `{verdict in (act, escalate, dismiss), force, families,
agreement, adjudicator, reason, claim}`.

Disagreement handling (item 2): when the raters diverge on the aggregate craft
or fit score for the subject (not just one claim), the divergence itself is
surfaced as a decision point in the residue (Section 9), not averaged away
silently. The loop auto-resolves only where all raters converge. Concretely: a
claim with `agreement == false` and an `escalate` verdict, or a score spread
across raters exceeding the convergence band, lands in the decision-residue
list rather than being applied unilaterally.

### 2.6 APPLY (convergent improvements)

Apply the improvements the adjudication marked `act`. These are the changes
the trio agrees on (cross-engine agreement) or that clear the force
threshold; they are applied in-worktree by the authoring or reviewing engine
and merged serially by Opus.

- Workers are COMMIT-ONLY. Merge to main is via `orchestration/bin/codex-worktree.sh merge`
  (clean-only, `--no-ff`, conflict aborts and escalates, main untouched),
  gated `duet_hold` so Opus owns the integration seam.
- The push fence is default-deny: `ORCHESTRATION_PUSH_ALLOWED` unset means merges
  stay local. A Forge worker never pushes and never auto-merges a `duet_hold`
  seam.
- `escalate` verdicts are NOT applied this round; they go to the residue and,
  on sensitive work, wait for Opus or the human. `dismiss` verdicts are
  dropped (but recorded).
- After APPLY, the subject is re-scored in the next RATE pass to measure the
  delta; the re-rate is mandatory (the 100-percent-only or no-delta card is a
  failure mode).

### 2.7 CHECK (target or plateau or budget)

Decide continue versus stop. This reuses the peer-audit convergence logic
(already generalized to N raters) and the `/goal` budget gate.

- Update the state file with this round's N rater rows and the new-findings
  count (Section 4) via the generalized `update_state.py`. In N-rater mode
  `--new-findings INT` is REQUIRED (there is no single canonical Claude report
  to parse for the accounting). The generalized `decide_convergence`
  (Section 6.2) reads `target_craft` / `target_fit` from `state.convergence`
  and writes `convergence.status` in `{converged, plateau, did_not_converge,
pending}`.
- Run `step(state, rating=, rater=, doer=, files_touched=, diff_lines=,
commits=, minutes=, workers=, consecutive=, tier3=, irreversible=,
user_facing=, scope_clean=)` in `orchestration/bin/goal.py` to fold in the per-rating
  SAFETY FLOOR plus the blast-radius budget. `step` returns
  `{action in (stage_branch, park, loop), verdict, reason, round, escalate}`.
  Note: `step()`/`gate()` do NOT read the user `target`; they enforce the fixed
  floor. The N-target gate is `decide_convergence`, above.

Branch (the run continues only when BOTH gates agree):

| Condition                                                                                                                      | Next                                                |
| ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| `converged` (decide_convergence: all N GO, all N at or above user target, zero new findings) AND every rating cleared `gate()` | stop, RECORD, stage branch                          |
| `plateau` (round >= 2, zero new findings, scores unchanged across all N raters)                                                | stop, PARK with diagnosis, RECORD                   |
| `did_not_converge` (round budget or `max_passes` exhausted)                                                                    | stop, PARK, RECORD                                  |
| budget overrun on any dimension (`step` / `budget_overruns`)                                                                   | stop, PARK ("blast-radius budget exceeded"), RECORD |
| `gate()` parks (high-stakes at-bar, leak-gate, malformed, non-independent)                                                     | stop, PARK, escalate, RECORD                        |
| `pending` and budget remains                                                                                                   | loop to FAN with `round += 1` and carried findings  |

The bar is never lowered to finish. Sub-bar work loops while budget remains,
then parks honestly (item 4).

### 2.8 PARK or RECORD

- PARK leaves the work on its branch, writes the diagnosis and the decision
  residue, buffers the human decision via `orchestration/bin/maestro-decision.sh`, and then
  RECORDs. `escalate: true` means it needs the human 9.5 plus GO.
- RECORD appends ONE advisory entry per run via `orchestration/bin/ensemble-recorder.py
record` with `topology = "forge"` (Section 4). Every run ends with a recorder
  entry plus one reviewable branch.

---

## 3. Exact engine invocations per the drivers

One parallel batch per round. Capture each `task_id` with `| tail -1`.

Scaffold ONCE up front with the rater set and the user target (this writes
`state.raters` and `convergence.target_craft` / `target_fit`):

```
bash pipeline/bin/scaffold_handoff.sh \
  --subject "<subject>" --slug <slug> --mode code --target-dir <DIR> --pass 1 \
  --raters "opus,codex,gemini" --target-craft <N> --target-fit <N>
```

Codex author lane (one per Codex agent, up to the ceiling K):

```
CODEX_CD=<worktree>       # a orchestration/bin/codex-worktree.sh-created worktree (never repo root)
CODEX_MAX_MIN=<5..60>     # wall-clock cap; default 30
CODEX_SCOPE=<glob>        # sensitivity tag + nearest-ancestor AGENTS.md lift
CODEX_NO_TERMINAL=1       # unattended: suppress the Terminal tail window
orchestration/bin/codex-spawn.sh <brief.md>
```

Gemini author lane (non-sensitive only; refused exit 6 on tier3):

```
GEMINI_CD=<worktree>      # worktree-only; the fence is the SOLE blast-radius limit
GEMINI_MAX_MIN=<5..60>
GEMINI_SCOPE=<glob>       # triggers the sensitive-lane refusal if tier3
GEMINI_ROLE=first_pass    # default; review = read-only, fence-exempt
GEMINI_APPROVAL_MODE=yolo # auto-approve tools headless; plan = read-only
GEMINI_NO_TERMINAL=1
orchestration/bin/gemini-spawn.sh <brief.md>
```

Gemini third-reviewer pass (read-only, on the real repo root):

```
orchestration/bin/gemini-review.sh <target-file-or-diff> [scope-glob...]
# GEMINI_REVIEW_BUDGET (default 20, clamped [1,500]); spent -> degrade_to_duet, exit 0
# GEMINI_REVIEW_DRY_RUN=1 -> build brief + charge budget, no spawn (test hook)
```

Read-back, per-pass state update, SAFETY-FLOOR gate, adjudicate, record:

```
orchestration/bin/codex-status.sh [<task_id>]          # resolve running -> done|failed

# Per-pass N-rater state update (one group per engine; --new-findings REQUIRED):
python3 pipeline/bin/update_state.py \
  --state <DIR>/.peer-audit-<slug>.json --pass <N> --new-findings <INT> \
  --rater opus   --craft <c> --fit <f> --verdict <V> [--rater-output <o.md>] \
  --rater codex  --craft <c> --fit <f> --verdict <V> [--rater-output <c.md>] \
  --rater gemini --craft <c> --fit <f> --verdict <V> [--rater-output <g.md>]
# stdout JSON carries a per-engine `raters` map (+ legacy codex_/claude_ keys
# when those engines ran) and convergence.status.

# Per-rating SAFETY FLOOR (fixed 8.5/9.5; does NOT read the user target N):
python3 orchestration/bin/goal.py gate --rating <r> --rater <name> --doer <engine> \
  [--tier3] [--irreversible] [--user-facing] [--leak]

# Adjudication — importlib by absolute path (bin/lib has no __init__.py):
python3 - <<'PY'
import importlib.util
s = importlib.util.spec_from_file_location(
    "trio_adjudicate",
    "$REPO_ROOT/adjudicator/trio_adjudicate.py")
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
# m.adjudicate(findings, sensitive=...) -> verdicts per claim
PY

# Converged report (derives the rater set from state.raters; N rows, target from state):
python3 pipeline/bin/generate_converged_report.py \
  --state <DIR>/.peer-audit-<slug>.json --output <DIR>/CONVERGED_<slug>.md

python3 orchestration/bin/ensemble-recorder.py record '<forge-payload-json>'   # allowlisted schema only
```

Worktree lifecycle (P0 fence, single-source):

```
orchestration/bin/codex-worktree.sh create <task_id> <base_sha>   # prints absolute worktree path
orchestration/bin/codex-worktree.sh merge  <task_id> [msg]         # clean-only; exit 3 on conflict
orchestration/bin/codex-scope-overlap.sh <globs...>                # pre-dispatch overlap check
```

Exit-code map the loop branches on:

| Code             | Source                               | Meaning                             | Recovery                                        |
| ---------------- | ------------------------------------ | ----------------------------------- | ----------------------------------------------- |
| 99               | `ensemble-halt-check.sh` (any spawn) | halted                              | stop, route to RECORD                           |
| 4                | `codex-spawn.sh` / `gemini-spawn.sh` | worktree == repo root               | re-create a worktree; never override unattended |
| 5                | `codex-spawn.sh` / `gemini-spawn.sh` | no `timeout` binary                 | install coreutils; never spawn unbounded        |
| 6                | `gemini-spawn.sh`                    | Gemini refused sensitive first-pass | route the lane to Codex or Opus                 |
| 2                | spawn scripts                        | engine CLI not found                | fall back to paste, or skip that engine         |
| 3                | `codex-worktree.sh merge`            | merge conflict                      | left clean for manual resolve; escalate         |
| 0 (with degrade) | `gemini-review.sh`                   | budget spent                        | proceed on the duet; the gap is logged          |

In a non-Claude runtime (when Gemini or Codex drive a pass), every
`AskUserQuestion` reference inherits the runtime-adapter rule: use that
runtime's native decision UI, never silently fall back to a prose option list.

---

## 4. State file and recorder

### Per-audit state file (the GENERALIZED peer-audit schema)

Reuse the peer-audit state schema (`templates/state_schema.json`), which is
ALREADY generalized to N raters by the pipeline change. Forge does NOT extend
or fork the schema; it sets the right fields via the scaffold and per-pass
updater. The generalized shape:

- Top level carries an ordered `raters` array (engine list; Forge sets
  `["opus","codex","gemini"]`, default `["codex","claude"]`).
- Each `history[]` entry carries a `raters` MAP keyed by engine family (an open
  object, `additionalProperties`), so the third slot (`gemini`) is a normal map
  key, not a special case. Per-rater object fields:
  `{output_path, verdict (GO|GATED-GO|NO-GO|CONVERGED|PLATEAU|DID-NOT-CONVERGE|null),
craft (number|null), fit (number|null), completed_at (date-time)}`.
- `convergence` REQUIRES `target_craft` and `target_fit` — the STORED USER
  values (default 9.5 for the legacy 2-rater case). `decide_convergence` reads
  them; nothing in the pipeline uses a 9.5 literal after the generalization.
- `convergence.status` in `{pending, converged, plateau, did_not_converge}`,
  same vocabulary as peer-audit.
- `open_findings[].introduced_by` is a free engine-name string (relaxed from
  the `codex|claude` enum), so `gemini` and `opus` are valid.

Backward compatibility is preserved (a 2-rater state validates against the
updated schema; the legacy `codex`/`claude` flat history blocks are still
written alongside the `raters` map; `update_state.py` still emits
`codex_verdict`/`claude_verdict`/`codex_craft_fit`/`claude_craft_fit` for old
readers). The three known-paid bug fixes are intact: plateau compares
`history[-2]` (the current pass is pre-appended); a same-pass row is REPLACED
not appended; state is written via `json.dump` (quote/newline-safe).

The carry-findings mechanism is unchanged: open findings carry forward into
the next round's prompt via the scaffold's `--carry-findings <state.json>`.

The per-engine `agent_count` and `ceiling` (K) for the right-size-the-fleet
decision (item 6) are kept in the run's recorder `shape`/`survival` payload and
the close-out artifact (the schema's allowlist is fixed; do NOT widen the
state schema for fleet telemetry — record it, see below).

### Run recorder (single-source, advisory)

Every Forge run calls `orchestration/bin/ensemble-recorder.py record` ONCE with a
Forge-shaped payload. Do NOT invent a parallel ledger or redactor; reuse the
recorder plus `orchestration/bin/runner/redact.py` so the hash chain stays single-source and
`verify_chain()` covers Forge too.

- Set `topology = "forge"`, `shape` describing the round (include the domain +
  fleet sizing), `tier3` from CLASSIFY, `scope_globs`, `leak_gate`.
- The recorder is best-effort and NEVER raises; a failure is stderr-only and
  must never block the run. It also cannot be relied on as a gate.
- **Keep the payload inside the ALLOWLISTED schema** (`_ALLOWED_ENTRY_KEYS` in
  `orchestration/bin/ensemble-recorder.py`): `run_id, ts, topology, topology_reason, shape,
tier3, exploration, scope_globs, mutual_act (forced False), swap_delta,
swap_delta_source, cross_model_unique, leak_gate, prompt_variants, survival,
findings, prev_hash, entry_hash`. Any field NOT in the allowlist is silently
  DROPPED by `sanitize_run`. If Forge needs a new telemetry field, ADD it to
  `_ALLOWED_ENTRY_KEYS` plus a sanitizer; never bypass `sanitize_run`. Fleet
  sizing (agent counts, K, domain) rides in `shape` / `survival`, both
  allowlisted.
- Each entry carries `prev_hash` plus `entry_hash` (sha256 over canonical
  JSON); `verify_chain()` detects tamper or reorder. The leak-gate records its
  own advisory verdict the same way.

---

## 5. How scores are produced and combined

### 5.0 Domain-aware Trio policy (operator-owned; one-line-editable data)

The weight table AND the fleet ratio are selected by the CLASSIFY domain
(Section 2.1). Store this as cleave-safe one-line-editable data
(`adjudicator/trio_policy.json` for the GENERAL weights; the UI table and the two
ratios as a sibling data block the SKILL reads), never as branchy code.

| Domain         | Selected when                                                         | Weights (Opus / Codex / Gemini) | Fleet ratio (Opus / Codex / Gemini) | Roles                                                                                                                                           |
| -------------- | --------------------------------------------------------------------- | ------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| general / code | CSS/HTML/template/visual NOT dominant (default)                       | 9 / 8.5 / 8                     | 45% / 40% / 15%                     | Codex = many-agent workhorse author (fast mode + priority tier); Gemini = READ-ONLY checkpoint auditor only; Opus = adjudicator/merger + author |
| ui / design    | subject is CSS / HTML / templates / visual, or explicit `--domain ui` | 9 / 7.5 / 8.5                   | 45% / 25% / 30%                     | Gemini = first-class design author AND reviewer (leveraged OVER Codex); Codex = code-correctness (markup/logic/a11y); Opus = adjudicator/merger |

- The GENERAL weights are exactly `adjudicator/trio_policy.json` (claude/opus 9,
  codex 8.5, gemini 8). The UI weights raise Gemini above Codex (Opus 9 /
  Gemini 8.5 / Codex 7.5); pass them as the explicit `weights=` argument to
  `trio_adjudicate.adjudicate` for a UI run. Opus stays the top weight (the
  adjudicator) in both tables.
- The fleet ratio sets how lanes/agents are apportioned in FAN (Section 2.3),
  bounded by K and `max_workers`. In general the workhorse share goes to Codex;
  in UI it shifts to Gemini as a first-class author. Opus's ~45% is in-session
  authoring + adjudication, not a spawn count.
- Domain selection is a one-line classifier (`ui` iff CSS/HTML/template/visual
  dominates the changed scope, else `general`) or the explicit `--domain ui`
  override. The domain changes ONLY the weight table and the ratio; the
  adjudication math, the gates, and the schema are domain-agnostic.

### Produced: the polish two-axis rubric, evidence-cited

Every rater applies the `polish` rubric verbatim (definition in
`orchestration/skills/polish/SKILL.md`). Do not re-implement the locked
audit prompt, the `docs/POLISH_*.md` artifact format, or the four-phase polish
machinery; Forge CONSUMES the rubric as its target metric.

- Two ORTHOGONAL axes, each 1 to 10 per category:
  - CRAFT: universal craftsmanship. "Would a senior discipline expert nod and
    say yes, that is well-built?" Discipline-relative, not project-relative.
  - FIT: fit-to-purpose. "Does this category serve what we are trying to
    build, given the project objectives?" Scored against the project's stated
    objectives.
- Per category: `gap = 10 - min(craft, fit)`. A category is closed only when
  BOTH axes hit the target.
- Evidence is non-negotiable ("cite lines, not vibes"). Every CRAFT grade
  cites at least one file path plus line, test count, benchmark number, commit
  hash, log line, or metric. Every FIT grade cites the project objective it
  serves or fails. Forbidden phrases are grep-gated before any score is
  accepted: `grep -nE "seems reasonable|looks fine|could be better|appears to
be solid|generally well-structured" <report>`. Any hit is fixed or the grade
  is downgraded until citable.
- Project objectives come from the anchor pass, read in order:
  `PROJECT_CHARTER.md`, `README.md`, `docs/GRAND_PLAN.md` or
  `docs/grand-plan/*`, latest `docs/VISION_REVISION_*.md`. Anchoring is
  non-skippable; grading craft without the charter is a failure mode.

### Combined: per-axis weighted aggregate, then trust-weighted across engines

Two layers of combination, plus the per-finding force model. Force is
`weight * confidence` (Section 2.5) — i.e. `force = domain_weight * confidence`.

1. Within one rater's report: the aggregate craft score and aggregate fit
   score are each a WEIGHTED AVERAGE across categories (by category, grouped
   into themes). They are reported as two separate numbers and never collapsed
   into one blended number. Leverage for ordering the top gaps is
   `gap * categories-affected` (impact times cost), not raw gap.

2. Across the N raters: each rater yields its own `(craft_aggregate,
fit_aggregate, verdict)`, recorded as its own rater row. The convergence
   gate (Section 6.2) requires ALL N to clear the user target independently.
   For the act-or-dismiss-or-escalate decision on individual findings, the
   trust-weighted force model (Section 2.5) applies, using the DOMAIN weight
   table: `force = domain_weight(engine) * confidence`, cross-engine agreement
   via noisy-or, Opus adjudicates sensitive claims. Do NOT average the N
   engines' aggregate scores into one Forge score; preserve both axes and all N
   rater rows.

---

## 6. Termination conditions

Three ways the loop stops, all fail-closed, none lowering the bar. The user
target N is enforced by `decide_convergence` (6.2); the FIXED safety floor is
enforced by `gate()` (6.1); they are independent and BOTH must pass to land.

### 6.1 The fail-closed SAFETY FLOOR (inherited verbatim from `orchestration/bin/goal.py`)

`gate(rating, rater=, doer=, tier3=, irreversible=, user_facing=,
scope_clean=)` is the anti-gaming core. It is the FIXED safety floor, NOT the
user-target gate: it hard-codes `BAR_MIN = 8.5` and `HUMAN_GO_BAR = 9.5` and
takes NO target parameter. Re-deriving it risks a weaker check; call it.

Decision ladder, top to bottom (first match wins):

1. rater not independent, unknown doer, or `rater == doer` family -> `park`,
   escalate. A self-score or same-family score NEVER lands regardless of value.
   Identities canonicalize through the CLOSED `_PRINCIPAL_ALIASES` registry;
   `INDEPENDENT_RATERS = {codex, claude, human, cross-model, peer-audit}`.
   Doer and rater must be DIFFERENT families (opus rating claude is the same
   family, not independent).
2. `rating is None` -> `loop` ("no independent rating yet").
3. unparseable rating -> `loop`.
4. non-finite or outside 0 to 10 -> `park`, escalate (malformed).
5. `score < BAR_MIN` (the FIXED 8.5 floor) -> `loop` ("not yet good enough").
   This is the floor only; the user target N is checked SEPARATELY by
   `decide_convergence`. `gate()` does not know N.
6. `score >= BAR_MIN` BUT tier3 or irreversible or user_facing -> `park`,
   escalate (needs `HUMAN_GO_BAR` 9.5 plus the operator's explicit GO).
7. `score >= BAR_MIN` BUT leak-gate flagged (`scope_clean = False`,
   `orchestration/bin/ensemble-leak-gate.py` over touched paths) -> `park`, escalate.
8. `score >= BAR_MIN`, independent, reversible, in-scope, non-Tier-3 ->
   `land_eligible` (BRANCH-ONLY; the merge to main is a separate gated step
   Forge never performs).

The honest statement of what `gate()` does and does NOT do: it does NOT read or
enforce the user target N (it has no target param; it hard-codes 8.5/9.5). It
IS the per-rating independence + malformed + high-stakes + leak floor that
every rating must clear. The user target N is the authoritative CONVERGENCE bar
and is enforced ONLY by `decide_convergence` (6.2), which reads
`convergence.target_craft` / `target_fit` from the state file. A run lands only
when `decide_convergence` is `converged` at the user target AND every rating
cleared `gate()`. The high-stakes floor (rung 6) is NOT user-lowerable: a
high-stakes subject keeps the 9.5-plus-GO requirement even if the user-set
`target` is lower, because that requirement lives in `gate()`, not in N.

### 6.2 Convergence: user target hit (generalized `decide_convergence`)

The pipeline's `update_state.decide_convergence` is ALREADY generalized: it
reads the user `target` from `convergence.target_craft` and `target_fit`
(stored values, default 9.5 for the legacy 2-rater case), iterates over the
`state.raters` engine list (Forge: opus, codex, gemini) rather than two named
keys, and requires:

- EVERY rater verdict == GO; AND
- every rater's craft >= `target_craft` AND fit >= `target_fit`; AND
- `new_findings == 0`.

`converged` only when every one of these holds. In N-rater mode `new_findings`
is supplied explicitly (`--new-findings`, `--raters-json`, or `--findings-from`)
because there is no single canonical Claude report to parse. The validator
requires non-null craft, fit, AND verdict for each rater; a bare "GO" plus a
Scores heading is NOT sufficient.

This is the ONLY place the user target N is enforced. `orchestration/bin/goal.py` plays no
part in the N check.

### 6.3 Plateau over K rounds (honest park)

This is loop logic item 4. Reuse the peer-audit plateau check, generalized to
N raters and compared against the true prior round:

- `plateau` when `current_pass >= 2` AND `new_findings == 0` AND the scores are
  unchanged versus the prior round for ALL N raters. The comparison indexes
  `history[-2]`, not `[-1]`, because the current round is appended to history
  BEFORE the check (the Train 6 fix), and is guarded by `len(history) >= 2`.
- On plateau the loop does NOT relax the target to finish. It PARKS with a
  diagnosis that names the gap and the structural fork, for example: "at 86;
  the last 4 points need a structural choice X or Y." The diagnosis goes into
  the decision residue (Section 9) and a buffered `maestro-decision`.

### 6.4 Budget cap

This is the bounded-run guarantee, inherited from `orchestration/bin/goal.py`
`DEFAULT_BUDGET` (mirrors `goal_item.DEFAULT_BUDGET`; a test asserts lockstep).
`step()` calls `budget_overruns(...)` on every dimension; exceeding ANY one
parks ("blast-radius budget exceeded"), regardless of rating. Even a passing
rating past `max_rounds` parks (the round budget is blown).

| Dimension                             | Cap  |
| ------------------------------------- | ---- |
| `max_rounds` (FAN -> RATE iterations) | 3    |
| `max_files`                           | 40   |
| `max_diff_lines`                      | 1500 |
| `max_commits`                         | 5    |
| `max_minutes`                         | 40   |
| `max_workers`                         | 4    |
| `max_consecutive_goals`               | 3    |

The `max_workers` cap (4) is also the K-ceiling bound: `K * spawnable_engines`
must be `<= 4` or PROBE insta-parks (Section 2.2). `update_state.py` also writes
`did_not_converge` automatically after the `max_passes` ceiling (5). Both
ceilings (the 3-round `step` budget and the 5-pass state ceiling) park rather
than loosen the bar. User signal phrases (stop, kill, freeze, abort) interrupt
the loop and route to PARK or RECORD with the current status.

---

## 7. The six loop-logic items, implemented concretely

The clever part of Forge is layered on the reused pieces. Each item maps to a
specific mechanism, not a vibe.

1. **doer != rater across engines.** Realized in two enforced layers: (a)
   routing, `trio_route_reviewers <author>` excludes the author's own family
   from the reviewer panel, so an engine is never assigned to rate its own
   lane; (b) the SAFETY FLOOR, `orchestration/bin/goal.py gate` fails closed on
   `rater == doer` family, unknown doer, or self-score, so even a mis-routed
   self-score can NEVER land. Identities are the launcher-set families
   (`ORCHESTRATION_PROPOSER_FAMILY` and `ORCHESTRATION_RATER_FAMILY`), never
   agent-supplied metadata. Opus's in-session rating is recorded as a real
   rater row with `doer != rater` honored, so the N-verdict gate sees a true
   Opus verdict.

2. **Disagreement is the deliverable.** When the raters diverge on a claim or
   on an aggregate axis, the divergence is surfaced as a decision point rather
   than averaged away. Mechanism: a claim with `agreement == false` (fewer than
   two distinct families concur) is never auto-`act`-ed on non-sensitive work
   unless its boosted force clears the threshold; on sensitive work it
   `escalate`s. Aggregate-score spread beyond the convergence band is written
   to the decision residue (Section 9). The loop auto-resolves only the
   convergent subset (the `act` verdicts with cross-engine agreement).

3. **Minority report.** When raters mostly pass but one objects hard, the
   objection is escalated for a focused look, never silently outvoted.
   Mechanism: `trio_adjudicate.adjudicate_claim` on a SENSITIVE diff returns
   `escalate` (not `dismiss`) for any sub-top or Gemini-only flag, with the
   reason "single engine, never dropped." A Gemini-only flag is explicitly
   never a veto and never silently dropped. On non-sensitive work a lone
   high-confidence objection still clears the force threshold (Gemini at conf
   0.75 gives force 6.0) and is acted on; a genuinely weak lone flag is
   `dismiss`ed but RECORDed.

4. **Honest park.** Plateau-detect (Section 6.3); when polish alone cannot
   reach the target, PARK with a diagnosis rather than fake or lower the bar.
   Mechanism: the user target lives OUTSIDE the doer's reach
   (`convergence.target_craft` / `target_fit` in the state file, enforced by
   `decide_convergence`), and the safety floor lives in the `orchestration/bin/goal.py`
   `gate()` predicate, so a running agent can edit neither threshold to pass
   something. Sub-target work loops while budget remains, then `step()` parks
   with reason "budget: N round(s) exhausted still below bar." The diagnosis
   names the structural fork.

5. **Decision residue.** The run's output is the polished work PLUS a short
   batched list of the judgment calls only a human should make. Mechanism:
   every `escalate` verdict, every aggregate-score divergence, every
   `should_ask` trip, and every high-stakes `park` is buffered via
   `orchestration/bin/maestro-decision.sh add --lane forge --question "..." [--options
"a|b"] [--urgent]`. The batch is surfaced as ONE `AskUserQuestion` (up to 4
   bundled) at the close, never dribbled out. `--urgent` is reserved for true
   hard-blocks (safety gate, non-negotiable challenged, breaking migration).

6. **Right-size the fleet.** The per-engine `ceiling` (K) is a CEILING, not a
   count, and is user-set (default 2) with the hard constraint
   `K * spawnable_engines <= max_workers` (4) enforced at PROBE. The loop
   starts at 1 to 2 agents each (set in PROBE) and escalates toward the ceiling
   only when early rounds show BOTH that the target is reachable (scores are
   climbing toward `target`, not plateaued) AND that the diversity is paying
   (distinct families are surfacing distinct `act` or `escalate` findings,
   raising `cross_model_unique`). If early rounds plateau or the engines
   converge on the same findings, the loop does NOT escalate; it parks or
   converges at the smaller fleet. The per-engine `agent_count` and `ceiling`
   ride in the recorder `shape`/`survival` payload so the escalation decision
   is auditable.

---

## 8. The P0 cage Forge inherits (do not reimplement)

All four fences plus the recorder are single-source. Forge wires in; it does
not duplicate any of them.

1. HALT: `orchestration/bin/ensemble-halt-check.sh || exit 99` is the first line and re-runs
   at every phase and role boundary. Cooperative start-gate, not a security
   boundary; also killable by `pkill`.
2. WORKTREE: every author and reviewer worker runs in a
   `orchestration/bin/codex-worktree.sh`-created worktree via `orchestration/bin/codex-spawn.sh` or
   `orchestration/bin/gemini-spawn.sh`. The on-main refusal (exit 4) and scope-declaration
   are inherited. No code path runs a worker on the live tree.
3. EGRESS: workers are COMMIT-ONLY; integration is `orchestration/bin/codex-worktree.sh
merge` under `ORCHESTRATION_PUSH_ALLOWED` default-deny; cross-model seams are
   `duet_hold` so Opus or the publisher owns the push. No Forge worker has
   push or auto-merge authority.
4. BUDGET: `CODEX_MAX_MIN` or `GEMINI_MAX_MIN` timeout wrapper plus
   `orchestrator_spawn_lock.sh` three-layer mutex plus the queue and
   concurrency caps (the `K * engines <= 4` resource floor among them). No raw
   engine spawn without the timeout backstop.
5. RECORD: one `orchestration/bin/ensemble-recorder.py record` call per run with
   `topology = "forge"` through the allowlisted schema and the shared
   redactor.

---

## 9. Decision residue format

The residue is the batched human-only judgment list (item 5). It is written to
the PARK or close-out artifact and buffered via `orchestration/bin/maestro-decision.sh`.
Each entry is one line of the form:

```
[severity] <claim or axis> -> <the fork only a human should pick>
  evidence: <file:line / score-spread / tier3 hit>
  raised_by: <engine family or engines that disagree>
```

The residue gathers: every `escalate` verdict from ADJUDICATE; every aggregate
craft or fit divergence beyond the convergence band; every `should_ask` trip
from CLASSIFY; the plateau diagnosis from CHECK; and every high-stakes
`park` reason from the `gate()` floor. It is surfaced as ONE `AskUserQuestion`
(up to 4 bundled options), never one at a time. The polished work ships
alongside it on a reviewable branch.

---

## 10. Cross-references

- `SKILL.md` (same directory) — the operator-facing Forge protocol that
  references this contract. Forge is registered in the skill suite's
  `NEW_SKILLS` list (`tests/test_orchestration_skill_protocol.py`) in the same
  change that ships this skill, so the protocol-drift checks cover it.
- `orchestration/skills/peer-audit/SKILL.md` — the N-rater-generalized
  template Forge wires into; reuse its scripts (`bin/scaffold_handoff.sh`,
  `bin/update_state.py`, `bin/generate_converged_report.py`) and the
  `templates/state_schema.json` state schema.
- `orchestration/skills/polish/SKILL.md` — the two-axis craft by fit rubric
  Forge converges toward (the locked audit prompt + the four-phase machinery).
- `orchestration/skills/rate-code/SKILL.md` — the code-mode score anchor.
- `orchestration/skills/goal/SKILL.md` and `orchestration/bin/goal.py` — the
  ORIENT-PLAN-EXECUTE-RATE-GATE-loop-park-RECORD spine and the fail-closed
  SAFETY FLOOR `gate()` (fixed 8.5/9.5, no target param).
- `adjudicator/trio_adjudicate.py` (importlib-load by absolute path; `bin/lib` has
  no `__init__.py`), `pipeline/bin/trio_policy.sh`, `adjudicator/trio_policy.json`,
  `pipeline/bin/ensemble_tier3.py` (`is_tier3(path)` single-path; `tier3_hits(paths)`
  for a list) — the trust model.
- `orchestration/bin/codex-spawn.sh`, `orchestration/bin/gemini-spawn.sh`, `orchestration/bin/gemini-review.sh` — the
  three engine lanes.
- `orchestration/bin/ensemble-halt-check.sh`, `orchestration/bin/codex-worktree.sh`,
  `orchestration/bin/ensemble-recorder.py`, `orchestration/bin/runner/redact.py` — the P0 cage and the
  recorder.
- `orchestration/docs/DUET_PROTOCOL.md` — the canonical mutual-polish
  mechanics.
- `docs/TRIO_TRUST_MODEL_2026-06-03.md` — the trust-weight and routing spec.
  </content>
  </invoke>

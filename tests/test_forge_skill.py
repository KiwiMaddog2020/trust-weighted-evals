"""Static oracle for the Forge v1 skill (`/forge`).

Forge is peer-audit generalized from two raters (Claude + Codex) to three
(Claude + Codex + Gemini), with the convergence TARGET (craft x fit >= N) and
the per-engine agent COUNT promoted from hard-coded to user-set. It is NOT a
from-scratch protocol: it composes the existing engine-lane drivers, the polish
craft x fit rubric, the Trio trust model, and the Phase-0 cage.

This file asserts the REAL POST-FIX state of the skill — i.e. the seams after
the known drafting bugs were corrected. The corrections it guards:

  1. SKILL.md exists with correct skill-convention frontmatter (kebab `name:`
     matching the dir, a one-line `description:` that names `/forge`).
  2. The USER-SET target is the authoritative bar. goal.py's hard-coded 8.5
     (`BAR_MIN`) is NOT presented as Forge's bar; the user N is what `gate()`
     checks, and the 9.5 + human-GO floor is the only thing that can raise it
     for high-stakes work — never an 8.5 default.
  3. The adjudicator import uses importlib (load-by-path), NOT the broken
     `from lib.trio_adjudicate import ...` — `trio_adjudicate.py` lives in
     `bin/lib/`, so a top-level `lib.` import cannot resolve.
  4. Tier-3 sensitivity is classified PER PATH via the real classifier
     (`pipeline/bin/ensemble_tier3.py` / `is_tier3`), not a hand-rolled scope guess.
  5. The domain-aware policy exists in `adjudicator/trio_policy.json`: a `general`
     and a `ui` craft-vs-fit weight table, each a ratio (the two axes' relative
     emphasis per domain), alongside the engine trust weights.
  6. The per-engine ceiling fan-out is bounded by the budget's `max_workers`:
     K agents x engines can never exceed the blast-radius worker cap (4).
  7. The three REAL engine drivers are referenced (codex-spawn / gemini-spawn /
     gemini-review), never a reinvented spawn/review path.

The source oracle also checked private registry wiring. This extract keeps the
Forge-scoped stale-token, Recovery-clause, and runtime-adapter checks, but does
not require the larger orchestration system's skill registry to exist here.

Pure static checks: no network, no live engine calls, no subprocess spawns. The
only filesystem reads are the protocol text and loop contract.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_DIR = REPO_ROOT / "protocol"
SKILL_MD = PROTOCOL_DIR / "SKILL.md"
LOOP_CONTRACT = PROTOCOL_DIR / "LOOP_CONTRACT.md"
TRIO_POLICY_JSON = REPO_ROOT / "adjudicator" / "trio_policy.json"

# Stale pre-rebrand tokens that must never appear (same canon as the house
# oracle test_orchestration_skill_protocol.py STALE_TOKENS).
STALE_TOKENS = [
    "The Ensemble",
    "plugins/ensemble",
    "ensemble-dashboard",
    "ENSEMBLE_SERVER_URL",
    "/ensemble:",
    "Composability with the Ensemble",
]

# Any one of these phrases satisfies the model-neutral AskUserQuestion adapter
# requirement (same set as the house oracle ADAPTER_PHRASES).
ADAPTER_PHRASES = [
    "when available",
    "Runtime adapter for the rest of this skill",
    "In runtimes without AskUserQuestion",
    "In Codex or another runtime",
    "the runtime's closest decision UI",
    "the runtime doesn't expose AskUserQuestion",
    "fall back to a numbered",
    "fall back to the closest",
    "Codex CLI, plain terminal",
    "Codex CLI or plain terminal",
]


def _body() -> str:
    """Read the Forge SKILL.md once. Fails with a clear message if absent.

    Forge v1 is delivered AS this file, so a missing SKILL.md is a real
    failure, not a skip — every assert below depends on it.
    """
    assert SKILL_MD.is_file(), (
        f"Forge skill not found at {SKILL_MD.relative_to(REPO_ROOT)} — "
        "the `/forge` skill must live in protocol/SKILL.md "
        "for this public extract."
    )
    return SKILL_MD.read_text(encoding="utf-8")


def _frontmatter(body: str) -> str:
    """Return the YAML frontmatter block (between the first two `---` fences)."""
    m = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    assert m, "SKILL.md must open with a `---` YAML frontmatter block"
    return m.group(1)


def _section(body: str, heading: str) -> str:
    """Return the content under a `## <heading>` up to the next `## `.

    Uses rfind so a skill embedding the canonical template heading twice
    (skill-builder pattern) scores only its own LAST section.
    """
    idx = body.rfind(heading)
    if idx < 0:
        return ""
    nl = body.find("\n", idx)
    if nl < 0:
        return ""
    remainder = body[nl + 1 :]
    end = re.search(r"^## ", remainder, re.MULTILINE)
    return remainder[: end.start()] if end else remainder


# ──────────────────────────────────────────────────────────────────────────
# 1. Exists + correct frontmatter (skill convention)
# ──────────────────────────────────────────────────────────────────────────


def test_forge_skill_exists():
    # _body() asserts existence with a descriptive message.
    body = _body()
    assert body.strip(), "SKILL.md is empty"


def test_forge_frontmatter_matches_skill_convention():
    body = _body()
    fm = _frontmatter(body)

    # name: must be the kebab-case dir name (Claude Code auto-discovers by dir).
    assert re.search(r"^name:\s*forge\s*$", fm, re.MULTILINE), (
        "frontmatter `name:` must equal the dir name `forge`"
    )

    # description: present, single line, and names the slash form so /forge fires.
    desc_match = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
    assert desc_match, "frontmatter must carry a `description:` field"
    description = desc_match.group(1)
    assert "/forge" in description, (
        "the `description` must embed the literal `/forge` trigger so the slash "
        "command resolves (there is no separate command-registration file)"
    )
    # description is the trigger surface — keep it to one line.
    assert "\n" not in description


def test_forge_has_canonical_body_sections():
    body = _body()
    # The canonical scaffold (skill-builder Step 3): Triggers, Composability,
    # When NOT to fire, Failure-mode signatures, Cross-references.
    for heading in (
        "## Triggers",
        "## Composability with the larger orchestration system",
        "## When NOT to fire",
        "## Failure-mode signatures",
        "## Cross-references",
    ):
        assert heading in body, f"SKILL.md missing canonical section {heading!r}"


def test_forge_triggers_restate_slash_and_verbal():
    body = _body()
    triggers = _section(body, "## Triggers")
    assert triggers, "Triggers section is empty"
    assert "/forge" in triggers, "Triggers section must list the `/forge` slash form"
    # Forge is fundamentally three-rater; the word must appear as a trigger anchor.
    assert "forge" in triggers.lower()


# ──────────────────────────────────────────────────────────────────────────
# 2. The USER-SET target is the authoritative bar — NOT goal.py's 8.5
# ──────────────────────────────────────────────────────────────────────────


def test_forge_target_is_user_set_not_goal_default():
    body = _body()
    lowered = body.lower()
    # The first generalization seam: the convergence TARGET (craft x fit >= N)
    # is user-set, promoted out of /goal's hard-coded BAR_MIN.
    assert "target" in lowered, "Forge must document the user-set convergence target"
    assert (
        "user-set" in lowered or "user-tunable" in lowered or "user input" in lowered
    ), "Forge must state the target is user-set, not baked in"
    # The bar Forge converges to is the user N. goal.py's autonomous default of
    # 8.5 must NOT be presented as Forge's bar — the user target is authoritative.
    assert not re.search(r"\bbar\s+is\s+8\.5\b", lowered), (
        "Forge must NOT claim the bar is 8.5 — the user-set target is authoritative"
    )
    assert not re.search(r"\btarget\s+(?:is|=|of)\s+8\.5\b", lowered), (
        "the user target is authoritative; 8.5 is goal.py's default, not Forge's bar"
    )


def test_forge_target_lives_outside_the_doer_reach():
    body = _body()
    lowered = body.lower()
    # The anti-gaming property /goal keeps: the doer cannot lower N mid-run.
    assert (
        "cannot lower" in lowered
        or "can't lower" in lowered
        or "never lower" in lowered
        or "not lower" in lowered
        or "outside the doer" in lowered
        or "cannot game" in lowered
    ), "Forge must state the target cannot be lowered mid-run to force a pass"
    # The same fail-closed gate reads the bar; the user N is passed INTO it.
    assert "goal.py" in body, (
        "Forge must reuse bin/goal.py's gate to read the bar, not a second gate"
    )


def test_forge_high_stakes_floor_is_the_only_thing_that_raises_the_bar():
    body = _body()
    # The 9.5 + explicit human GO floor for Tier-3 / user-facing / irreversible
    # is inherited verbatim; it may RAISE a lower user N, never the reverse.
    assert "9.5" in body, "Forge must keep the 9.5 high-stakes / human-GO floor"
    lowered = body.lower()
    assert "human" in lowered and ("go" in lowered or "go" in lowered), (
        "the high-stakes floor requires explicit human GO"
    )


# ──────────────────────────────────────────────────────────────────────────
# 3. The adjudicator import uses importlib — NOT `from lib.trio_adjudicate`
# ──────────────────────────────────────────────────────────────────────────


def test_forge_adjudicate_import_uses_importlib():
    body = _body()
    # trio_adjudicate.py lives in bin/lib/, so a top-level `lib.` package import
    # cannot resolve. The post-fix skill loads it by path via importlib (the
    # same pattern the trio_adjudicate oracle uses: spec_from_file_location).
    assert "importlib" in body, (
        "Forge must load adjudicator/trio_adjudicate.py via importlib "
        "(spec_from_file_location), not a package import"
    )


def test_forge_does_not_use_the_broken_lib_package_import():
    body = _body()
    # The exact drafting bug this guards: `from lib.trio_adjudicate import ...`
    # (and the bare-module variant) would ImportError — the module is bin/lib/,
    # not an importable top-level `lib` package.
    #
    # The post-fix skill MAY name the broken form to WARN against it (a comment
    # or a failure-mode bullet), but never as the actual invocation. So every
    # line that mentions the package import must also flag it as the wrong way
    # (broken / never / not). The working call is the importlib loader, asserted
    # separately below.
    _NEG = (
        "broken",
        "never",
        "not ",
        "wrong",
        "anti-pattern",
        "__init__",  # "has no `__init__.py`, so `from lib...` raises ModuleNotFoundError"
        "has no",
        "modulenotfound",
        "importerror",
    )

    def _every_lib_import_is_flagged(text: str, label: str) -> None:
        for raw in text.splitlines():
            line = raw.lower()
            if "from lib.trio_adjudicate" in line or "import lib.trio_adjudicate" in line:
                assert any(neg in line for neg in _NEG), (
                    f"{label}: line uses the broken `lib.trio_adjudicate` import as a "
                    "real invocation — load via importlib.spec_from_file_location instead:\n"
                    f"  {raw.strip()}"
                )

    _every_lib_import_is_flagged(body, "SKILL.md")
    # The real invocation must be the importlib path-load against the real module.
    assert "spec_from_file_location" in body, (
        "the working adjudicator import is importlib.util.spec_from_file_location, "
        "loading adjudicator/trio_adjudicate.py by absolute path"
    )
    # And the same discipline must hold in the implementation-grade loop contract.
    if LOOP_CONTRACT.is_file():
        _every_lib_import_is_flagged(
            LOOP_CONTRACT.read_text(encoding="utf-8"), "LOOP_CONTRACT.md"
        )


def test_forge_references_the_real_adjudicator_module_by_path():
    body = _body()
    # The skill must point at the actual module path so the importlib load
    # resolves to the real file (not a reinvented adjudicator).
    assert "adjudicator/trio_adjudicate.py" in body, (
        "Forge must reference the real adjudicator/trio_adjudicate.py adjudicator"
    )
    # The two axes + the GO threshold convention it converges to.
    assert "craft" in body.lower() and "fit" in body.lower()
    assert "9.5" in body, "Forge inherits the >= 9.5 GO floor"
    assert "plateau" in body.lower(), "Forge must honor the plateau stop condition"


# ──────────────────────────────────────────────────────────────────────────
# 4. Tier-3 sensitivity is classified PER PATH via the real classifier
# ──────────────────────────────────────────────────────────────────────────


def test_forge_classifies_tier3_per_path_via_real_classifier():
    body = _body()
    # Sensitivity is the single fact that forces routing, the adjudication
    # branch, the target floor, and the mode. It must come from the real
    # classifier per path, not a hand-rolled scope guess.
    assert "ensemble_tier3.py" in body, (
        "Forge must classify sensitivity via the real pipeline/bin/ensemble_tier3.py"
    )
    lowered = body.lower()
    # The per-path API (is_tier3(path) / tier3_hits(paths)) or the per-path
    # shell wrapper (trio_scope_is_sensitive <paths...>) — path-level, not a
    # single whole-scope boolean guessed by hand.
    assert (
        "is_tier3" in body
        or "tier3_hits" in body
        or "trio_scope_is_sensitive" in body
        or "<paths>" in body
        or "<paths...>" in body
        or "changed paths" in lowered
        or "per path" in lowered
        or "per-path" in lowered
    ), "Forge must call tier3 classification PER PATH (is_tier3 / tier3_hits / per-path)"
    # tier3 is the term of art the routing + gate branch on.
    assert "tier3" in lowered or "tier-3" in lowered, (
        "Forge must name the tier3/sensitive routing gate"
    )


def test_forge_routes_through_the_trio_policy_not_a_new_weight_table():
    body = _body()
    # Weights/routing live in the shared lib (single source of truth) — Forge
    # must defer to the existing trio policy, not hardcode 9/8.5/8 or re-encode
    # the sensitive-lane bar.
    assert "trio_policy" in body or "trio_adjudicate" in body, (
        "Forge must route via the existing trio trust model "
        "(trio_policy.sh / trio_policy.json / trio_adjudicate.py), not a fresh table"
    )
    assert "trio_route_author" in body or "trio_route_reviewers" in body, (
        "Forge must use the trio policy's author/reviewer routing, not hand-encode it"
    )


# ──────────────────────────────────────────────────────────────────────────
# 5. The domain-aware policy exists: general + ui weight tables + ratios
# ──────────────────────────────────────────────────────────────────────────


def test_protocol_docs_include_domain_aware_weight_tables():
    body = _body()
    contract = LOOP_CONTRACT.read_text(encoding="utf-8") if LOOP_CONTRACT.is_file() else ""
    combined = f"{body}\n{contract}".lower()
    assert "general / code" in combined, "protocol docs must name the general/code domain table"
    assert "ui / design" in combined, "protocol docs must name the ui/design domain table"
    assert str(TRIO_POLICY_JSON.relative_to(REPO_ROOT)) in body, (
        "SKILL.md must point at the shipped adjudicator/trio_policy.json policy"
    )


def test_protocol_domain_tables_express_distinct_weights_and_fleet_ratios():
    body = _body()
    assert "9 / 8.5 / 8" in body, "general/code weights must be preserved"
    assert "9 / 7.5 / 8.5" in body, "ui/design weights must be preserved"
    assert "45% / 40% / 15%" in body, "general/code fleet ratio must be preserved"
    assert "45% / 25% / 30%" in body, "ui/design fleet ratio must be preserved"


def test_forge_skill_references_the_domain_aware_policy():
    body = _body()
    # The skill must point operators at the shared policy as the source of the
    # weighting (engine trust + domain craft/fit), not restate weights inline.
    assert "adjudicator/trio_policy.json" in body, (
        "Forge must reference adjudicator/trio_policy.json as the weighting source of truth"
    )


# ──────────────────────────────────────────────────────────────────────────
# 6. The per-engine ceiling fan-out is bounded by max_workers (K x engines)
# ──────────────────────────────────────────────────────────────────────────


def test_forge_documents_the_per_engine_agent_ceiling():
    body = _body()
    lowered = body.lower()
    # The second generalization seam: a user-set per-engine agent COUNT used as
    # a CEILING (up to K Codex agents, K Gemini agents).
    assert "per-engine" in lowered or "per engine" in lowered, (
        "Forge must document the per-engine agent parameter"
    )
    assert "ceiling" in lowered, "the per-engine agent param is a CEILING, not a target"


def test_forge_ceiling_fanout_is_bounded_by_max_workers():
    body = _body()
    lowered = body.lower()
    # K agents x engines must never exceed the blast-radius worker cap. The
    # budget's max_workers (4 in DEFAULT_BUDGET) is the hard bound; the skill
    # must tie the ceiling fan-out to it, not let K x engines run unbounded.
    assert "max_workers" in body, (
        "Forge must bound the per-engine ceiling fan-out by the budget's max_workers"
    )
    # The relationship must be a BOUND (total live agents <= max_workers), and
    # the skill must acknowledge the budget caps the fleet (not just name it).
    assert (
        "bound" in lowered
        or "cap" in lowered
        or "exceed" in lowered
        or "<=" in body
        or "≤" in body
        or "budget" in lowered
    ), "the K x engines fan-out must be explicitly bounded by max_workers"


# ──────────────────────────────────────────────────────────────────────────
# 7. The three REAL engine drivers are referenced — not reinvented ones
# ──────────────────────────────────────────────────────────────────────────


def test_forge_references_the_three_real_engine_drivers():
    body = _body()
    # The three live dispatchers — Forge calls these, never a reimplementation.
    for driver in (
        "bin/codex-spawn.sh",
        "bin/gemini-spawn.sh",
        "bin/gemini-review.sh",
    ):
        assert driver in body, (
            f"Forge must dispatch through the real driver {driver}; "
            "reimplementing the spawn path is a duplication failure"
        )


def test_forge_uses_gemini_review_as_the_third_reviewer_path():
    body = _body()
    # gemini-review.sh is the read-only third-rater wrapper — Forge must reuse
    # it rather than building a separate review path (it owns the daily budget
    # + degrade-to-duet log).
    assert "gemini-review.sh" in body
    assert "review" in body.lower()


def test_forge_does_not_reinvent_the_spawn_or_review_plumbing():
    body = _body()
    # Negative guard: the skill must not describe rolling its own raw engine
    # invocation (that would bypass the fences baked into the drivers).
    #
    # The post-fix skill DOES mention `codex exec` — but only inside a "never
    # raw `codex exec`" warning. So flag a `codex exec` mention ONLY when its
    # line is not a negation (never / not / don't / no). The real dispatch must
    # go through the spawners.
    _NEG = ("never", "not ", "n't", "no raw", "avoid", "instead of")
    for raw in body.splitlines():
        line = raw.lower()
        if "codex exec" in line:
            assert any(neg in line for neg in _NEG), (
                "Forge must NOT invoke raw `codex exec` as the dispatch path — "
                "route through bin/codex-spawn.sh so the timeout + worktree fences "
                f"apply. Offending line:\n  {raw.strip()}"
            )
    # And it must actually name the spawners as the dispatch substrate.
    assert "bin/codex-spawn.sh" in body


def test_forge_references_the_polish_rubric_not_a_reinvented_one():
    body = _body()
    # The convergence target is the polish two-axis rubric — referenced by the
    # real skill path, not redefined.
    assert "orchestration/skills/polish/SKILL.md" in body, (
        "Forge must point at the polish skill for the craft x fit rubric "
        "rather than restating its own scoring definition"
    )
    # And the mutual-polish/duet canon must be cited, not re-derived.
    assert "DUET_PROTOCOL.md" in body


def test_forge_composes_peer_audit_rather_than_forking_it():
    body = _body()
    # Forge is peer-audit's three-rater generalization; it should reference the
    # peer-audit skill it extends, not silently re-derive the loop.
    assert "peer-audit" in body
    # And it must name all three rater engines as the defining change (2 -> 3).
    lowered = body.lower()
    for engine in ("claude", "codex", "gemini"):
        assert engine in lowered, f"Forge must name the {engine} rater slot"
    # Opus is the third Claude-family rater + the merge owner.
    assert "opus" in lowered, "Forge must name Opus as the third rater / merge owner"


# ──────────────────────────────────────────────────────────────────────────
# Phase-0 fences + doer != rater (the safety seams that survive the rewrite)
# ──────────────────────────────────────────────────────────────────────────


def test_forge_encodes_the_halt_check_fence():
    body = _body()
    # P0 universal kill-switch — the FIRST action of every loop, re-polled at
    # phase boundaries. Forge wires into the one file, never a new halt.
    assert "ensemble-halt-check.sh" in body, (
        "Forge must run bin/ensemble-halt-check.sh first (exit 99 = halt)"
    )
    assert "99" in body, "the halt-check exit-99 contract must be documented"


def test_forge_encodes_the_worktree_only_fence():
    body = _body()
    lowered = body.lower()
    # Blast-radius limit: workers run ONLY in a git worktree, never on the live
    # repo root (the drivers refuse with exit 4).
    assert "worktree" in lowered, "Forge must declare the worktree-only fence"
    assert "exit 4" in lowered, "Forge must document the worktree-only refusal (exit 4)"
    assert "main" in lowered, "the worktree fence exists to keep main untouched"


def test_forge_encodes_the_budget_cap_fence():
    body = _body()
    # Token-leak backstop: every worker is wall-clock capped via *_MAX_MIN; the
    # drivers refuse to spawn unbounded (exit 5) when no timeout binary exists.
    assert ("CODEX_MAX_MIN" in body) or ("GEMINI_MAX_MIN" in body), (
        "Forge must document the *_MAX_MIN wall-clock cap"
    )
    assert "timeout" in body.lower(), "Forge must document the timeout-based budget cap"


def test_forge_encodes_doer_not_equal_rater():
    body = _body()
    lowered = body.lower()
    # The anti-gaming core: a self-produced / same-family score can never land.
    has_doer_rater = (
        "doer != rater" in lowered
        or "doer ≠ rater" in body
        or ("doer" in lowered and "rater" in lowered)
    )
    assert has_doer_rater, (
        "Forge must enforce doer != rater so no engine grades its own homework"
    )


def test_forge_records_each_run_via_the_shared_recorder():
    body = _body()
    # Every run appends one advisory entry to the shared hash-chained ledger —
    # Forge reuses ensemble-recorder.py, never a parallel ledger.
    assert "ensemble-recorder.py" in body or "ensemble_runs.jsonl" in body, (
        "Forge must record runs via the shared bin/ensemble-recorder.py ledger"
    )


# ──────────────────────────────────────────────────────────────────────────
# House protocol drift checks (mirrors test_orchestration_skill_protocol.py so
# Forge's registration in NEW_SKILLS has a Forge-scoped fast signal)
# ──────────────────────────────────────────────────────────────────────────


def test_forge_has_no_pre_rebrand_stale_tokens():
    body = _body()
    for token in STALE_TOKENS:
        assert token not in body, f"SKILL.md still contains stale token {token!r}"


def test_forge_failure_modes_each_have_a_recovery_clause():
    body = _body()
    section = _section(body, "## Failure-mode signatures")
    assert section, "SKILL.md is missing the `## Failure-mode signatures` section"
    bullets = re.findall(r"^- \*\*", section, re.MULTILINE)
    recoveries = section.count("Recovery:")
    assert len(bullets) >= 3, (
        f"only {len(bullets)} failure-mode bullets — canonical minimum is 3"
    )
    assert len(bullets) == recoveries, (
        f"{len(bullets)} failure-mode bullets but {recoveries} `Recovery:` clauses "
        "— every bullet needs exactly one"
    )


def test_forge_declares_a_runtime_adapter_for_decision_tool():
    body = _body()
    if "AskUserQuestion" not in body:
        # Exempt: a skill that never references the decision tool needs no adapter.
        return
    assert any(phrase in body for phrase in ADAPTER_PHRASES), (
        "Forge references AskUserQuestion but declares no model-neutral runtime "
        "adapter — a non-Claude runtime driving a pass must use its own decision UI"
    )


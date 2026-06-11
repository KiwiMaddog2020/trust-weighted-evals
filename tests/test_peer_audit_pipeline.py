"""End-to-end oracle for the peer-audit pipeline scripts, covering BOTH the
classic two-rater (codex+claude) path and the N-rater generalization (Triad).

Guards the four scripts the N-rater work touched:
  - bin/update_state.py            (convergence state machine + dialects)
  - bin/generate_converged_report.py (final report, N rows)
  - bin/scaffold_handoff.sh        (state-writer + HISTORY_TABLE, N raters)
  - templates/state_schema.json    (raters map + stored user target)

The backward-compat half exercises the exact legacy invocation the peer-audit
SKILL.md documents (--codex/--claude markdown reports parsed via
parse_polish_output.py). The generalization half exercises --rater/--raters-json
with a user-set target. Both must hold for the change to ship.

Pure-stdlib: tempfile + subprocess + json. No network, no live engine calls.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_BIN = REPO_ROOT / "pipeline" / "bin"
TEMPLATES = REPO_ROOT / "pipeline" / "templates"
UPDATE_STATE = SKILL_BIN / "update_state.py"
GEN_REPORT = SKILL_BIN / "generate_converged_report.py"
SCAFFOLD = SKILL_BIN / "scaffold_handoff.sh"
SCHEMA = TEMPLATES / "state_schema.json"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _polish_report(craft, fit, verdict, new_findings, open_findings):
    """Build a canonical POLISH report the parser understands.

    Mirrors the Train-5 contract: a `Verdict:` line, a `... quality: craft X /
    fit Y.` aggregate, a `## Canonical accounting` section with the two scalars,
    and a `## Open findings after this pass` section with the pipe-delimited list.
    """
    of_lines = "\n".join(
        f"- {f['severity']} | {f['location']} | {f['summary']} | "
        f"{f['introduced_on_pass']} | {f['introduced_by']}"
        for f in open_findings
    )
    return f"""# Polish report

`Verdict: {verdict}`

Code quality: craft {craft} / fit {fit}.

Some prose body here.

## Canonical accounting (machine-readable — do not edit by hand)

New findings this pass: {new_findings}
Open findings after this pass: {len(open_findings)}

## Open findings after this pass

{of_lines}
"""


def _write_state(d: Path, slug: str, raters, target_craft=9.5, target_fit=9.5):
    """Write a fresh scaffolded-style state file and return its path."""
    state = {
        "slug": slug,
        "subject": "Test subject",
        "mode": "code",
        "target_dir": str(d),
        "current_pass": 1,
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
    }
    p = d / f".peer-audit-{slug}.json"
    p.write_text(json.dumps(state, indent=2))
    return p


def _run_update(state_path: Path, *args) -> dict:
    """Run update_state.py and return parsed stdout JSON (raises on nonzero)."""
    cmd = [sys.executable, str(UPDATE_STATE), "--state", str(state_path), *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"update_state failed: {r.stderr}\nstdout: {r.stdout}"
    return json.loads(r.stdout)


def _run_update_expect_fail(state_path: Path, *args) -> str:
    cmd = [sys.executable, str(UPDATE_STATE), "--state", str(state_path), *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode != 0, f"expected failure but succeeded: {r.stdout}"
    return r.stderr


# ─────────────────────────────────────────────────────────────────────────────
# 1. BACKWARD COMPAT — the classic two-rater (--codex/--claude) path
# ─────────────────────────────────────────────────────────────────────────────


def test_legacy_two_rater_converges_at_target():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "legacy", ["codex", "claude"])
        codex = d / "codex.md"
        claude = d / "claude.md"
        codex.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        claude.write_text(_polish_report(9.7, 9.6, "GO", 0, []))

        out = _run_update(
            state, "--codex", str(codex), "--claude", str(claude), "--pass", "1"
        )
        assert out["convergence"] == "converged", out
        # Legacy convenience keys preserved for old readers.
        assert out["codex_verdict"] == "GO"
        assert out["claude_verdict"] == "GO"
        assert out["codex_craft_fit"] == [9.6, 9.6]

        st = json.loads(state.read_text())
        entry = st["history"][-1]
        # Both the new raters map AND the legacy flat blocks are written.
        assert entry["raters"]["codex"]["verdict"] == "GO"
        assert entry["raters"]["claude"]["verdict"] == "GO"
        assert entry["codex"]["verdict"] == "GO"
        assert entry["claude"]["verdict"] == "GO"


def test_legacy_pending_when_one_rater_below_target():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "legacy2", ["codex", "claude"])
        codex = d / "c.md"
        claude = d / "cl.md"
        codex.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        claude.write_text(_polish_report(9.1, 9.6, "GO", 0, []))  # craft below 9.5
        out = _run_update(
            state, "--codex", str(codex), "--claude", str(claude), "--pass", "1"
        )
        assert out["convergence"] == "pending", out


def test_legacy_plateau_uses_prior_pass_not_self():
    """The known-paid Train-6 bug: plateau must compare against history[-2]."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "plat", ["codex", "claude"])
        # Pass 1: sub-target, no new findings.
        c1, cl1 = d / "c1.md", d / "cl1.md"
        c1.write_text(_polish_report(9.0, 9.0, "GATED-GO", 0, []))
        cl1.write_text(_polish_report(9.0, 9.0, "GATED-GO", 0, []))
        out1 = _run_update(state, "--codex", str(c1), "--claude", str(cl1), "--pass", "1")
        assert out1["convergence"] == "pending"  # pass 1 can't plateau

        # Pass 2: identical scores, 0 new findings -> plateau.
        c2, cl2 = d / "c2.md", d / "cl2.md"
        c2.write_text(_polish_report(9.0, 9.0, "GATED-GO", 0, []))
        cl2.write_text(_polish_report(9.0, 9.0, "GATED-GO", 0, []))
        out2 = _run_update(state, "--codex", str(c2), "--claude", str(cl2), "--pass", "2")
        assert out2["convergence"] == "plateau", out2


def test_legacy_same_pass_row_replaced_not_appended():
    """Train-7 bug: re-running the same pass replaces its history row."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "rep", ["codex", "claude"])
        c, cl = d / "c.md", d / "cl.md"
        c.write_text(_polish_report(9.0, 9.0, "GATED-GO", 0, []))
        cl.write_text(_polish_report(9.0, 9.0, "GATED-GO", 0, []))
        _run_update(state, "--codex", str(c), "--claude", str(cl), "--pass", "1")
        _run_update(state, "--codex", str(c), "--claude", str(cl), "--pass", "1")
        st = json.loads(state.read_text())
        passes = [h["pass"] for h in st["history"]]
        assert passes == [1], f"same-pass retry should not duplicate rows: {passes}"


def test_legacy_missing_open_findings_scalar_fails_closed():
    """Train-8 fail-closed: legacy Claude report missing the scalar errors."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "fc", ["codex", "claude"])
        c, cl = d / "c.md", d / "cl.md"
        c.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        # Claude report with NO canonical accounting section at all.
        cl.write_text("# Report\n`Verdict: GO`\nCode quality: craft 9.6 / fit 9.6.\n")
        err = _run_update_expect_fail(
            state, "--codex", str(c), "--claude", str(cl), "--pass", "1",
            "--new-findings", "0",
        )
        assert "Open findings after this pass" in err


def test_legacy_state_written_via_json_dump_handles_quotes():
    """State written via json.dump — a subject with quotes stays valid JSON."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "q", ["codex", "claude"])
        st = json.loads(state.read_text())
        st["subject"] = 'A "quoted" subject\nwith newline'
        state.write_text(json.dumps(st, indent=2))
        c, cl = d / "c.md", d / "cl.md"
        c.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        cl.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        _run_update(state, "--codex", str(c), "--claude", str(cl), "--pass", "1")
        # Must still parse.
        reparsed = json.loads(state.read_text())
        assert reparsed["subject"] == 'A "quoted" subject\nwith newline'


# ─────────────────────────────────────────────────────────────────────────────
# 2. N-RATER GENERALIZATION — --rater / --raters-json with user-set target
# ─────────────────────────────────────────────────────────────────────────────


def test_triad_three_raters_converge_at_user_target():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # User-set target 9.0, three raters.
        state = _write_state(d, "triad", ["opus", "codex", "gemini"], 9.0, 9.0)
        out = _run_update(
            state,
            "--rater", "opus", "--craft", "9.2", "--fit", "9.1", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.0", "--fit", "9.0", "--verdict", "GO",
            "--rater", "gemini", "--craft", "9.3", "--fit", "9.0", "--verdict", "GO",
            "--pass", "1", "--new-findings", "0",
        )
        assert out["convergence"] == "converged", out
        assert set(out["raters"].keys()) == {"opus", "codex", "gemini"}
        st = json.loads(state.read_text())
        assert set(st["history"][-1]["raters"].keys()) == {"opus", "codex", "gemini"}


def test_triad_one_rater_below_target_blocks_convergence():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "triad2", ["opus", "codex", "gemini"], 9.5, 9.5)
        out = _run_update(
            state,
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "gemini", "--craft", "9.4", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1", "--new-findings", "0",
        )
        assert out["convergence"] == "pending", out


def test_triad_one_rater_not_go_blocks_convergence():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "triad3", ["opus", "codex", "gemini"], 9.0, 9.0)
        out = _run_update(
            state,
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.6", "--fit", "9.6", "--verdict", "GATED-GO",
            "--rater", "gemini", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1", "--new-findings", "0",
        )
        assert out["convergence"] == "pending", out


def test_triad_configured_rater_absent_from_pass_fails_closed():
    """A 2-of-3 pass must NEVER converge: state declares three raters but the
    pass supplies only two. Even at perfect GO scores, the missing configured
    rater fails the gate closed (regression guard for the silent-drop fail-open
    in rater_names — the convergence GATE evaluates the full configured set)."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "triad_absent", ["opus", "codex", "gemini"], 9.0, 9.0)
        out = _run_update(
            state,
            "--rater", "opus", "--craft", "9.9", "--fit", "9.9", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.9", "--fit", "9.9", "--verdict", "GO",
            # gemini is configured but intentionally ABSENT from this pass.
            "--pass", "1", "--new-findings", "0",
        )
        assert out["convergence"] == "pending", out


def test_triad_new_findings_blocks_convergence():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "triad4", ["opus", "codex", "gemini"], 9.0, 9.0)
        out = _run_update(
            state,
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "gemini", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1", "--new-findings", "2",
        )
        assert out["convergence"] == "pending", out


def test_raters_json_dialect():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "json", ["opus", "codex", "gemini"], 9.0, 9.0)
        blob = json.dumps({
            "raters": {
                "opus": {"craft": 9.2, "fit": 9.1, "verdict": "GO", "output_path": "o.md"},
                "codex": {"craft": 9.0, "fit": 9.0, "verdict": "GO"},
                "gemini": {"craft": 9.3, "fit": 9.0, "verdict": "GO"},
            },
            "new_findings": 0,
            "open_findings": [],
        })
        out = _run_update(state, "--raters-json", blob, "--pass", "1")
        assert out["convergence"] == "converged", out
        st = json.loads(state.read_text())
        assert st["history"][-1]["raters"]["opus"]["output_path"] == "o.md"


def test_generalized_requires_new_findings():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "nf", ["opus", "codex"], 9.0, 9.0)
        err = _run_update_expect_fail(
            state,
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1",
        )
        assert "new-findings" in err or "new_findings" in err


def test_dialects_are_mutually_exclusive():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "mx", ["codex", "claude"])
        c, cl = d / "c.md", d / "cl.md"
        c.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        cl.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        err = _run_update_expect_fail(
            state, "--codex", str(c), "--claude", str(cl),
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1",
        )
        assert "ONE dialect" in err or "not both" in err


def test_target_is_read_from_state_not_literal():
    """A user-set target ABOVE the scores must block; raising it would converge
    a literal-9.5 implementation, proving the target is stored-value driven."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # Scores 9.6 clear 9.5 but NOT a user target of 9.8.
        state = _write_state(d, "tgt", ["opus", "codex"], 9.8, 9.8)
        out = _run_update(
            state,
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1", "--new-findings", "0",
        )
        assert out["convergence"] == "pending", out
        # Lowering the target to 9.5 (still via stored value) converges.
        state2 = _write_state(d, "tgt2", ["opus", "codex"], 9.5, 9.5)
        out2 = _run_update(
            state2,
            "--rater", "opus", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.6", "--fit", "9.6", "--verdict", "GO",
            "--pass", "1", "--new-findings", "0",
        )
        assert out2["convergence"] == "converged", out2


# ─────────────────────────────────────────────────────────────────────────────
# 3. generate_converged_report.py — N rows
# ─────────────────────────────────────────────────────────────────────────────


def test_report_renders_n_rater_rows():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "rep3", ["opus", "codex", "gemini"], 9.0, 9.0)
        _run_update(
            state,
            "--rater", "opus", "--craft", "9.2", "--fit", "9.1", "--verdict", "GO",
            "--rater", "codex", "--craft", "9.0", "--fit", "9.0", "--verdict", "GO",
            "--rater", "gemini", "--craft", "9.3", "--fit", "9.0", "--verdict", "GO",
            "--pass", "1", "--new-findings", "0",
        )
        out_md = d / "CONVERGED.md"
        r = subprocess.run(
            [sys.executable, str(GEN_REPORT), "--state", str(state), "--output", str(out_md)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        text = out_md.read_text()
        # Every rater appears as a verdict-table row.
        for name in ("Opus", "Codex", "Gemini"):
            assert f"| {name} | GO |" in text, f"{name} row missing:\n{text}"
        # The user-set target (9.0) is rendered, not a 9.5 literal.
        assert "≥ 9.0" in text
        assert "| Gemini craft | ≥ 9.0 |" in text


def test_report_legacy_two_rater_still_renders():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "rep2", ["codex", "claude"])
        c, cl = d / "c.md", d / "cl.md"
        c.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        cl.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        _run_update(state, "--codex", str(c), "--claude", str(cl), "--pass", "1")
        out_md = d / "CONVERGED.md"
        r = subprocess.run(
            [sys.executable, str(GEN_REPORT), "--state", str(state), "--output", str(out_md)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        text = out_md.read_text()
        assert "| Codex | GO |" in text
        assert "| Claude | GO |" in text


# ─────────────────────────────────────────────────────────────────────────────
# 4. scaffold_handoff.sh — N raters + user-set target
# ─────────────────────────────────────────────────────────────────────────────


def test_scaffold_writes_default_two_rater_state():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        r = subprocess.run(
            ["bash", str(SCAFFOLD), "--subject", "Sub", "--slug", "sc",
             "--mode", "code", "--target-dir", str(d), "--pass", "1"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        st = json.loads((d / ".peer-audit-sc.json").read_text())
        assert st["raters"] == ["codex", "claude"]
        assert st["convergence"]["target_craft"] == 9.5
        assert st["convergence"]["target_fit"] == 9.5


def test_scaffold_writes_n_rater_state_and_user_target():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        r = subprocess.run(
            ["bash", str(SCAFFOLD), "--subject", "Sub", "--slug", "tri",
             "--mode", "code", "--target-dir", str(d), "--pass", "1",
             "--raters", "opus,codex,gemini",
             "--target-craft", "9.2", "--target-fit", "9.3"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        st = json.loads((d / ".peer-audit-tri.json").read_text())
        assert st["raters"] == ["opus", "codex", "gemini"]
        assert st["convergence"]["target_craft"] == 9.2
        assert st["convergence"]["target_fit"] == 9.3
        # HANDOFF table header should carry the three rater columns + the target.
        handoff = list(d.glob("HANDOFF_*_tri.md"))[0].read_text()
        assert "Opus verdict" in handoff and "Gemini craft/fit" in handoff
        assert "9.2 craft" in handoff and "9.3 fit" in handoff


# ─────────────────────────────────────────────────────────────────────────────
# 5. Schema — a 2-rater state remains valid; user target is required
# ─────────────────────────────────────────────────────────────────────────────


def test_schema_has_raters_and_required_target():
    schema = json.loads(SCHEMA.read_text())
    props = schema["properties"]
    assert "raters" in props, "schema must define a top-level raters field"
    conv = props["convergence"]
    assert conv["required"] == ["target_craft", "target_fit"], (
        "convergence target must be a REQUIRED stored user value"
    )
    # History items carry a per-rater raters map (keyed by engine name).
    hist_item = props["history"]["items"]["properties"]
    assert "raters" in hist_item, "history items must carry a raters map"
    assert "additionalProperties" in hist_item["raters"], (
        "the raters map must be open (additionalProperties), keyed by engine name"
    )
    # Legacy codex/claude blocks still accepted for backward compat.
    assert "codex" in hist_item and "claude" in hist_item


def test_schema_validates_a_two_rater_state():
    """A scaffolded 2-rater state validates against the schema (jsonschema if
    available, else a structural smoke check)."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        state = _write_state(d, "v", ["codex", "claude"])
        c, cl = d / "c.md", d / "cl.md"
        c.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        cl.write_text(_polish_report(9.6, 9.6, "GO", 0, []))
        _run_update(state, "--codex", str(c), "--claude", str(cl), "--pass", "1")
        doc = json.loads(state.read_text())
        schema = json.loads(SCHEMA.read_text())
        try:
            import jsonschema  # type: ignore
            jsonschema.validate(doc, schema)
        except ImportError:
            # Structural smoke check when jsonschema isn't installed.
            for key in schema["required"]:
                assert key in doc, f"required key {key} missing from state"
            assert "target_craft" in doc["convergence"]
            assert isinstance(doc["history"][-1]["raters"], dict)

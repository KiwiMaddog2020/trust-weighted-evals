#!/usr/bin/env python3
"""generate_converged_report.py — synthesize the final CONVERGED_<date>_<slug>.md.

Reads the state file and per-pass POLISH outputs, fills the
CONVERGED_template.md, writes the final report.

Generalized to N raters: every table (last verdicts, patch trail, convergence
math, per-pass artifacts) is built by iterating the state's rater set rather
than the hardcoded codex/claude pair. The convergence target comes from the
stored user value in state.convergence, not a literal.

Usage:
    python3 generate_converged_report.py \\
        --state <path-to-.peer-audit-<slug>.json> \\
        --output <path-to-CONVERGED_<date>_<slug>.md>

Exit:
    0 — report written
    1 — error
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR.parent / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "CONVERGED_template.md"

DEFAULT_RATERS = ["codex", "claude"]

CONVERGED_BADGE = {
    "converged": "✅ CONVERGED",
    "plateau": "🟡 PLATEAU (accepted at sub-target scores; further iteration unproductive)",
    "did_not_converge": "❌ DID-NOT-CONVERGE (hit max-passes ceiling)",
    "pending": "🔵 PENDING (loop did not complete)",
}


VERDICT_BLOCKS = {
    "converged": "Every rater issued **GO**, each at craft ≥ target and fit ≥ target, and the last pass introduced no new findings. The artifact meets the user-set convergence criteria.",
    "plateau": "The raters have stopped finding new issues, but scores plateaued below the target. Per the plateau exception (≥ 2 passes, no new findings, scores unchanged from prior pass), the audit accepts this as the practical ceiling — further iteration would burn tokens without moving the needle.",
    "did_not_converge": "The audit ran out of passes (hit `max_passes` ceiling) before all raters could agree. Open findings remain. Recommended: triage the open findings manually or restart the audit with a tighter scope.",
    "pending": "The audit ended in `pending` state. This is unusual — typically means the loop was interrupted. Inspect the state file for the last-pass details.",
}


def cell(ok: bool) -> str:
    return "✓" if ok else "✗"


def title(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


def entry_raters(entry: dict) -> dict:
    """Return a history entry's raters map, synthesizing one from the legacy
    flat codex/claude blocks if the entry predates the `raters` map.
    """
    raters = entry.get("raters")
    if isinstance(raters, dict) and raters:
        return raters
    synth = {}
    for name in DEFAULT_RATERS:
        block = entry.get(name)
        if isinstance(block, dict):
            synth[name] = block
    return synth


def rater_set(state: dict, history: list) -> list[str]:
    """Ordered rater names: configured list, else union across history, else
    the legacy default ['codex','claude'].
    """
    configured = state.get("raters")
    if isinstance(configured, list) and configured:
        return list(configured)
    seen: list[str] = []
    for h in history:
        for name in entry_raters(h):
            if name not in seen:
                seen.append(name)
    return seen or list(DEFAULT_RATERS)


def render_history_row(h: dict, names: list[str]) -> str:
    p = h.get("pass", "?")
    raters = entry_raters(h)
    cells = [str(p)]
    for name in names:
        r = raters.get(name) or {}
        v = r.get("verdict") or "_pending_"
        craft = r.get("craft", "")
        fit = r.get("fit", "")
        score = f"{craft}/{fit}" if craft != "" and craft is not None else "_pending_"
        cells.append(v)
        cells.append(score)
    cells.append(str(h.get("new_findings", 0)))
    cells.append(str(h.get("patches_applied", 0)))
    return "| " + " | ".join(cells) + " |"


def render_per_pass_files(h: dict, names: list[str]) -> str:
    p = h.get("pass", "?")
    raters = entry_raters(h)
    cells = [str(p)]
    for name in names:
        path = (raters.get(name) or {}).get("output_path") or "_n/a_"
        cells.append(f"`{path}`")
    return "| " + " | ".join(cells) + " |"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv[1:])

    if not args.state.is_file():
        print(f"ERROR: state file {args.state} does not exist", file=sys.stderr)
        return 1
    if not TEMPLATE_PATH.is_file():
        print(f"ERROR: template missing at {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    state = json.loads(args.state.read_text())
    history = state.get("history", []) or []
    if not history:
        print(f"ERROR: state file has no history entries; nothing to converge", file=sys.stderr)
        return 1

    last = history[-1]
    status = (state.get("convergence") or {}).get("status", "pending")
    cfg = state.get("convergence") or {}
    target_craft = cfg.get("target_craft", 9.5)
    target_fit = cfg.get("target_fit", 9.5)

    names = rater_set(state, history)
    last_raters = entry_raters(last)
    new_findings = last.get("new_findings", 0)

    # ── Last-verdict table (N rows) ──────────────────────────────────────────
    verdict_rows = []
    for name in names:
        r = last_raters.get(name) or {}
        v = r.get("verdict") or "_unknown_"
        craft = r.get("craft")
        fit = r.get("fit")
        craft_s = str(craft) if craft is not None else "_n/a_"
        fit_s = str(fit) if fit is not None else "_n/a_"
        verdict_rows.append(f"| {title(name)} | {v} | {craft_s} | {fit_s} |")
    raters_verdict_table = "\n".join(verdict_rows)

    # ── Co-signature ─────────────────────────────────────────────────────────
    score_summary = ", ".join(
        f"{title(n)} {(last_raters.get(n) or {}).get('craft')}/"
        f"{(last_raters.get(n) or {}).get('fit')}"
        for n in names
    )
    if status == "converged":
        cosig = (
            f"All raters ({', '.join(title(n) for n in names)}) independently "
            f"arrived at GO at or above the craft ≥ {target_craft} / fit ≥ "
            f"{target_fit} target. The peer-review system found no remaining issues."
        )
    elif status == "plateau":
        cosig = (
            f"The raters have stopped finding new issues. Scores plateaued at "
            f"{score_summary} — accepted as the practical ceiling."
        )
    elif status == "did_not_converge":
        cosig = "**Disagreement remains** — the raters have not aligned on GO at target within the pass ceiling."
    else:
        cosig = "_Audit incomplete — co-signature pending convergence._"

    # ── Plateau explanation ──────────────────────────────────────────────────
    if status == "plateau":
        plateau_block = (
            f"**Plateau exception fired.** The hard criteria were not all met "
            f"(some scores < {target_craft}/{target_fit}), but the audit completed "
            f"pass ≥ 2 with no new findings and unchanged scores from the prior "
            f"pass. Further iteration would not improve the result."
        )
    else:
        plateau_block = ""

    history_rows = "\n".join(render_history_row(h, names) for h in history)
    file_rows = "\n".join(render_per_pass_files(h, names) for h in history)

    # ── Convergence-criteria table (3 rows per rater + findings) ─────────────
    crit_rows = []
    for name in names:
        r = last_raters.get(name) or {}
        v = r.get("verdict") or "_unknown_"
        craft = r.get("craft")
        fit = r.get("fit")
        crit_rows.append(
            f"| {title(name)} verdict | GO | {v} | {cell(v == 'GO')} |"
        )
        crit_rows.append(
            f"| {title(name)} craft | ≥ {target_craft} | "
            f"{craft if craft is not None else '_n/a_'} | {cell((craft or 0) >= target_craft)} |"
        )
        crit_rows.append(
            f"| {title(name)} fit | ≥ {target_fit} | "
            f"{fit if fit is not None else '_n/a_'} | {cell((fit or 0) >= target_fit)} |"
        )
    crit_rows.append(
        f"| New findings on last pass | 0 | {new_findings} | {cell(new_findings == 0)} |"
    )
    convergence_criteria_table = "\n".join(crit_rows)

    # ── Dynamic table headers (history + artifacts) ──────────────────────────
    history_rater_headers = "".join(
        f"{title(n)} verdict | {title(n)} craft/fit | " for n in names
    )
    history_rater_align = "---|---:|" * len(names)
    artifact_rater_headers = " | ".join(f"{title(n)} output" for n in names)
    artifact_rater_align = "---|" * len(names)

    # ── Next-action recommendation ───────────────────────────────────────────
    if status == "converged":
        next_action = "1. Commit `CONVERGED_<date>_<slug>.md` and the final per-pass POLISH files.\n2. Push when ready (per standing git policy: explicit user approval).\n3. Unblock whatever downstream work this audit was gating."
    elif status == "plateau":
        next_action = "1. Review whether the plateau scores are acceptable for ship.\n2. If yes: commit + unblock downstream.\n3. If no: scope down (smaller subject) or change rater (different model) and re-fire the audit."
    elif status == "did_not_converge":
        next_action = "1. Read the open findings in the state file's `open_findings` array.\n2. Decide: scope down + restart, change rater, or accept partial.\n3. If accept: document the open issues prominently before merging."
    else:
        next_action = "_Audit incomplete. Resume by invoking the skill with the same target dir + slug._"

    output_dir = args.output.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    template = TEMPLATE_PATH.read_text()

    subs = {
        "SUBJECT": state.get("subject", "_unknown_"),
        "MODE": state.get("mode", "_unknown_"),
        "SLUG": state.get("slug", "_unknown_"),
        "TARGET_DIR": state.get("target_dir", "_unknown_"),
        "DATE": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
        "TOTAL_PASSES": str(state.get("current_pass", len(history))),
        "STATUS_BADGE": CONVERGED_BADGE.get(status, status),
        "FINAL_VERDICT_BLOCK": VERDICT_BLOCKS.get(status, "_(no verdict block for status: " + status + ")_"),
        "TARGET_CRAFT": str(target_craft),
        "TARGET_FIT": str(target_fit),
        "RATERS_VERDICT_TABLE": raters_verdict_table,
        "CO_SIGNATURE": cosig,
        "FULL_HISTORY_TABLE": history_rows,
        "HISTORY_RATER_HEADERS": history_rater_headers,
        "HISTORY_RATER_ALIGN": history_rater_align,
        "CONVERGENCE_CRITERIA_TABLE": convergence_criteria_table,
        "FINAL_NEW_FINDINGS": str(new_findings),
        "PLATEAU_EXPLANATION": plateau_block,
        "PER_PASS_FILE_TABLE": file_rows,
        "ARTIFACT_RATER_HEADERS": artifact_rater_headers,
        "ARTIFACT_RATER_ALIGN": artifact_rater_align,
        "NEXT_ACTION_BLOCK": next_action,
    }

    for k, v in subs.items():
        template = template.replace("{{" + k + "}}", v)

    args.output.write_text(template)
    print(f"Wrote {args.output}")
    print(f"Status: {status}")
    print(f"Passes: {state.get('current_pass', len(history))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""update_state.py — bump .peer-audit-<slug>.json with this pass's results.

Generalized from the classic two-rater (codex + claude) peer-audit to an
ARBITRARY set of named raters (the engine set is whatever the caller passes).
Each rater contributes {craft, fit, verdict, output_path?} for the pass; the
convergence gate requires EVERY rater to clear the user-set target.

Two input dialects, pick one (they are mutually exclusive for clarity):

  (A) LEGACY 2-rater (unchanged — the classic peer-audit invocation):

      python3 update_state.py \\
          --state <path-to-.peer-audit-<slug>.json> \\
          --codex <path-to-Codex's POLISH_*.md> \\
          --claude <path-to-Claude's POLISH_*_claude-peer-review.md> \\
          --pass <N> \\
          [--new-findings <int>]            # override the parsed count

      Both args are markdown reports parsed by parse_polish_output.py. The
      new-findings count and the carried-forward open-findings list are read
      from Claude's report (the Train 5 canonical-accounting contract). The
      pass's raters map is written as {'codex': ..., 'claude': ...} AND the
      flat codex/claude blocks are kept for old readers.

  (B) GENERALIZED N-rater (Triad and beyond):

      python3 update_state.py \\
          --state <path> \\
          --rater opus  --craft 9.6 --fit 9.7 --verdict GO [--rater-output P] \\
          --rater codex --craft 9.5 --fit 9.5 --verdict GO \\
          --rater gemini --craft 9.6 --fit 9.6 --verdict GO \\
          --pass <N> \\
          --new-findings <int> \\
          [--findings-from <path-to-a-canonical-report>]  # carry open findings
      OR, in one shot:
          --raters-json '{"raters": {"opus": {"craft": 9.6, "fit": 9.7,
                          "verdict": "GO", "output_path": "..."}, ...},
                          "new_findings": 0, "open_findings": [...]}'

      Scalars are supplied directly (no markdown parsed for scores). Because
      there is no single canonical Claude report to parse, --new-findings is
      REQUIRED in this mode (or new_findings inside --raters-json), and the
      carried-forward open-findings list comes from --findings-from (parsed
      via parse_polish_output.py) or from open_findings in --raters-json.

The convergence TARGET (target_craft / target_fit) is a STORED USER VALUE read
from state.convergence — never a literal in this script.

Exit:
    0 — state updated; prints the convergence decision on stdout
    1 — error
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PARSER = SCRIPT_DIR / "parse_polish_output.py"

# Fallback rater order when state predates the `raters` field (legacy 2-rater).
DEFAULT_RATERS = ["codex", "claude"]


def parse_polish(path: Path) -> dict:
    """Invoke parse_polish_output.py and return the JSON it emits."""
    result = subprocess.run(
        ["python3", str(PARSER), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"parse_polish_output.py failed on {path}: {result.stderr}")
    return json.loads(result.stdout)


def rater_names(state: dict, entry: dict) -> list[str]:
    """The engine set to evaluate, in order.

    Prefer the per-pass entry's raters map (authoritative for THIS pass), then
    the state-level `raters` list (the configured set), then the legacy default
    ['codex','claude'] so old 2-rater state keeps working.
    """
    pass_raters = entry.get("raters")
    if isinstance(pass_raters, dict) and pass_raters:
        configured = state.get("raters")
        if isinstance(configured, list) and configured:
            # Preserve configured order, then append any extras present in the pass.
            ordered = [n for n in configured if n in pass_raters]
            ordered += [n for n in pass_raters if n not in ordered]
            return ordered
        return list(pass_raters.keys())
    configured = state.get("raters")
    if isinstance(configured, list) and configured:
        return list(configured)
    return list(DEFAULT_RATERS)


def coerce_score(value):
    """Coerce a rater score to a finite float in [0, 10]; unusable -> None.

    Trio-rerun fix (2026-06-12, cross-engine agreement): `inf`/`nan`,
    out-of-range numbers, and non-numeric strings must never satisfy a
    convergence target or reach the state JSON. Numeric strings ("9.6")
    coerce cleanly; everything else returns None so callers fail loud
    (intake) or fail closed (convergence).
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f if 0.0 <= f <= 10.0 else None


def _score_arg(value: str) -> float:
    """argparse caster: a craft/fit flag must be a finite score in [0, 10]."""
    f = coerce_score(value)
    if f is None:
        raise ValueError(f"score must be a finite number in [0, 10], got {value!r}")
    return f


def decide_convergence(state: dict, this_pass: dict, new_findings: int) -> tuple[str, str]:
    """Return (status, reasoning) per the locked criteria + plateau exception.

    Generalized to N raters: EVERY rater must verdict==GO AND craft>=target AND
    fit>=target, with the target read from state (the user-set value), AND the
    pass must introduce no new findings.
    """
    cfg = state.get("convergence", {})
    target_craft = cfg.get("target_craft", 9.5)
    target_fit = cfg.get("target_fit", 9.5)
    max_passes = state.get("max_passes", 5)
    current_pass = state["current_pass"]
    history = state.get("history", [])

    raters = this_pass.get("raters", {}) or {}
    names = rater_names(state, this_pass)

    # Fail closed on a configured-but-absent rater: a 2-of-3 pass must NEVER
    # converge. rater_names() intersects with the pass for rendering, but the
    # convergence GATE evaluates the FULL configured set, so a silently-dropped
    # rater fails (its missing row scores 0 < target and verdict != GO).
    # Degrade-to-duet is an EXPLICIT reconfiguration of state['raters'] (a logged
    # decision), not a silent drop, so it still converges over its reduced set.
    configured = state.get("raters")
    if isinstance(configured, list) and configured:
        names = list(configured)

    # Hard criteria — all must hold across every rater.
    criteria: dict[str, bool] = {}
    for name in names:
        r = raters.get(name) or {}
        # Fail closed on malformed scores: coerce_score returns None for
        # inf/nan/out-of-range/non-numeric, and None never clears a target
        # (trio-rerun fix: `--craft inf` used to converge; a string crashed).
        craft = coerce_score(r.get("craft"))
        fit = coerce_score(r.get("fit"))
        criteria[f"{name}_verdict_GO"] = r.get("verdict") == "GO"
        criteria[f"{name}_craft_ok"] = craft is not None and craft >= target_craft
        criteria[f"{name}_fit_ok"] = fit is not None and fit >= target_fit
    criteria["no_new_findings"] = new_findings == 0

    if criteria and all(criteria.values()):
        return (
            "converged",
            f"All hard criteria met: every rater ({', '.join(names)}) issued GO "
            f"at craft ≥ {target_craft} and fit ≥ {target_fit}, and the "
            f"pass introduced no new findings.",
        )

    # Plateau exception: >= 2 passes, no new findings, scores unchanged.
    #
    # Train 6 fix (Claude Pass 2 N4): update_state.py appends `this_pass`
    # to state["history"] BEFORE calling this function, so history[-1] is
    # the just-appended current entry, not the prior pass. Comparing the
    # current pass's scores against itself always returns "unchanged",
    # firing plateau falsely. Fix: index -2 for the true prior pass, and
    # only fire plateau when we genuinely have a prior to compare against
    # (len(history) >= 2).
    if current_pass >= 2 and new_findings == 0 and len(history) >= 2:
        prior = history[-2]
        prior_raters = _entry_raters(prior)
        scores_unchanged = True
        for name in names:
            cur = raters.get(name) or {}
            prev = prior_raters.get(name) or {}
            if (
                prev.get("craft") != cur.get("craft")
                or prev.get("fit") != cur.get("fit")
            ):
                scores_unchanged = False
                break
        if scores_unchanged:
            return (
                "plateau",
                f"Plateau exception: pass {current_pass}, no new findings, scores "
                f"unchanged from prior pass across all raters ({', '.join(names)}). "
                f"Accept even if scores < {target_craft}/{target_fit}.",
            )

    # Hard ceiling.
    if current_pass >= max_passes:
        unmet = [k for k, v in criteria.items() if not v]
        return (
            "did_not_converge",
            f"Hit max_passes={max_passes} ceiling; unmet criteria: {', '.join(unmet)}.",
        )

    return (
        "pending",
        f"Pending: criteria unmet — {', '.join(k for k, v in criteria.items() if not v)}.",
    )


def _entry_raters(entry: dict) -> dict:
    """Return the raters map for a history entry, synthesizing one from the
    legacy flat codex/claude blocks if the entry predates the raters map.
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


# ─────────────────────────────────────────────────────────────────────────────
# Input collection
# ─────────────────────────────────────────────────────────────────────────────


def collect_legacy(args) -> tuple[dict, int, list, int | None, str]:
    """Legacy 2-rater path: parse Codex + Claude markdown reports.

    Returns (raters_map, new_findings, open_findings, open_count, source_tag).
    source_tag is the name whose report carried the canonical findings block.
    """
    codex_parsed = parse_polish(args.codex)
    claude_parsed = parse_polish(args.claude)

    def _legacy_score(parsed: dict, field: str, path) -> float | None:
        """Validate a markdown-parsed score at intake (Tier-2 round-2 fix:
        a 'craft 11' in a legacy report used to persist into the state JSON;
        decide_convergence failed closed but the garbage was stored)."""
        raw = parsed.get(field)
        if raw is None:
            return None
        coerced = coerce_score(raw)
        if coerced is None:
            raise ValueError(
                f"legacy report {path}: {field} must be a finite number in [0, 10], got {raw!r}"
            )
        return coerced

    raters = {
        "codex": {
            "output_path": str(args.codex),
            "verdict": codex_parsed.get("verdict"),
            "craft": _legacy_score(codex_parsed, "craft", args.codex),
            "fit": _legacy_score(codex_parsed, "fit", args.codex),
        },
        "claude": {
            "output_path": str(args.claude),
            "verdict": claude_parsed.get("verdict"),
            "craft": _legacy_score(claude_parsed, "craft", args.claude),
            "fit": _legacy_score(claude_parsed, "fit", args.claude),
        },
    }

    # Train 5 contract: Claude's report MUST include canonical scalars.
    new_findings = args.new_findings
    if new_findings is None:
        new_findings = claude_parsed.get("new_findings")
        if new_findings is None:
            raise ValueError(
                "Claude's report lacks the canonical 'New findings this pass: N' "
                "scalar required by the Train 5 template. Pass --new-findings as "
                "override or fix the report to include the scalar."
            )

    open_findings = claude_parsed.get("open_findings", []) or []
    open_count = claude_parsed.get("open_findings_count")
    return raters, new_findings, open_findings, open_count, "claude"


def collect_generalized(args) -> tuple[dict, int, list, int | None, str]:
    """Generalized N-rater path: scalars from --rater/--raters-json.

    Returns (raters_map, new_findings, open_findings, open_count, source_tag).
    """
    raters: dict = {}
    new_findings = args.new_findings
    open_findings: list = []
    open_count: int | None = None

    if args.raters_json:
        try:
            blob = json.loads(args.raters_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"--raters-json is not valid JSON: {e}")
        rmap = blob.get("raters") if isinstance(blob, dict) else None
        if not isinstance(rmap, dict) or not rmap:
            raise ValueError("--raters-json must contain a non-empty 'raters' object")
        for name, r in rmap.items():
            scores = {}
            for field in ("craft", "fit"):
                raw = r.get(field)
                coerced = coerce_score(raw) if raw is not None else None
                if raw is not None and coerced is None:
                    raise ValueError(
                        f"--raters-json: rater {name!r} {field} must be a finite "
                        f"number in [0, 10], got {raw!r}"
                    )
                scores[field] = coerced
            raters[name.lower()] = {
                "output_path": r.get("output_path"),
                "verdict": (r.get("verdict") or None),
                "craft": scores["craft"],
                "fit": scores["fit"],
            }
        if new_findings is None:
            new_findings = blob.get("new_findings")
        if "open_findings" in blob and isinstance(blob["open_findings"], list):
            open_findings = blob["open_findings"]
            open_count = len(open_findings)

    # Repeatable --rater blocks (override / supplement the JSON map).
    for spec in args.rater or []:
        name = spec["name"].lower()
        raters[name] = {
            "output_path": spec.get("output"),
            "verdict": spec.get("verdict"),
            "craft": spec.get("craft"),
            "fit": spec.get("fit"),
        }

    if not raters:
        raise ValueError(
            "generalized mode requires at least one --rater <name> "
            "(with --craft/--fit/--verdict) or a --raters-json blob"
        )

    # Open findings: explicit --findings-from wins over --raters-json list.
    if args.findings_from is not None:
        parsed = parse_polish(args.findings_from)
        open_findings = parsed.get("open_findings", []) or []
        open_count = parsed.get("open_findings_count")
        if new_findings is None:
            new_findings = parsed.get("new_findings")

    if new_findings is None:
        raise ValueError(
            "generalized mode requires --new-findings <int> (or new_findings in "
            "--raters-json, or a --findings-from report carrying the canonical "
            "'New findings this pass: N' scalar)"
        )

    return raters, new_findings, open_findings, open_count, "generalized"


# ─────────────────────────────────────────────────────────────────────────────


class _RaterAction(argparse.Action):
    """Collect repeatable `--rater NAME` groups, each followed by its own
    --craft/--fit/--verdict/--rater-output. We model this as: --rater opens a
    new group; the scalar flags fill the most recent group.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        groups = getattr(namespace, "rater", None) or []
        groups.append({"name": values})
        namespace.rater = groups


def _make_group_scalar(field, caster):
    class _ScalarAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            groups = getattr(namespace, "rater", None) or []
            if not groups:
                parser.error(f"{option_string} must follow a --rater <name>")
            try:
                groups[-1][field] = caster(values)
            except (TypeError, ValueError):
                parser.error(f"{option_string} got an invalid value: {values!r}")

    return _ScalarAction


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--pass", dest="pass_n", required=True, type=int)
    ap.add_argument("--new-findings", type=int, default=None)

    # Legacy 2-rater dialect.
    ap.add_argument("--codex", type=Path, default=None,
                    help="LEGACY: path to Codex's POLISH_*.md (parsed for scores)")
    ap.add_argument("--claude", type=Path, default=None,
                    help="LEGACY: path to Claude's *_claude-peer-review.md (parsed)")

    # Generalized N-rater dialect.
    ap.add_argument("--rater", action=_RaterAction, dest="rater", default=None,
                    help="Engine name; repeatable. Follow with --craft/--fit/--verdict.")
    ap.add_argument("--craft", action=_make_group_scalar("craft", _score_arg),
                    help="Craft score for the most recent --rater (finite, 0-10).")
    ap.add_argument("--fit", action=_make_group_scalar("fit", _score_arg),
                    help="Fit score for the most recent --rater (finite, 0-10).")
    ap.add_argument("--verdict", action=_make_group_scalar("verdict", str),
                    help="Verdict for the most recent --rater (GO/GATED-GO/...).")
    ap.add_argument("--rater-output", action=_make_group_scalar("output", str),
                    help="Output-report path for the most recent --rater.")
    ap.add_argument("--raters-json", default=None,
                    help="One-shot JSON: {'raters': {name: {craft, fit, verdict, "
                         "output_path}}, 'new_findings': N, 'open_findings': [...]}")
    ap.add_argument("--findings-from", type=Path, default=None,
                    help="Generalized: parse open/new findings from this report.")
    return ap


def main(argv: list[str]) -> int:
    ap = build_parser()
    args = ap.parse_args(argv[1:])

    if not args.state.is_file():
        print(f"ERROR: state file {args.state} does not exist", file=sys.stderr)
        return 1

    legacy = args.codex is not None or args.claude is not None
    generalized = bool(args.rater) or args.raters_json is not None

    if legacy and generalized:
        print(
            "ERROR: choose ONE dialect — either --codex/--claude (legacy) or "
            "--rater/--raters-json (generalized), not both.",
            file=sys.stderr,
        )
        return 1
    if legacy and not (args.codex and args.claude):
        print(
            "ERROR: legacy dialect requires BOTH --codex and --claude.",
            file=sys.stderr,
        )
        return 1
    if not legacy and not generalized:
        print(
            "ERROR: no rater input — pass --codex/--claude (legacy) or "
            "--rater/--raters-json (generalized).",
            file=sys.stderr,
        )
        return 1

    state = json.loads(args.state.read_text())

    try:
        if legacy:
            raters_map, new_findings, open_findings, open_count, _src = collect_legacy(args)
        else:
            raters_map, new_findings, open_findings, open_count, _src = collect_generalized(args)
    except (RuntimeError, ValueError) as e:
        print(f"ERROR collecting rater inputs: {e}", file=sys.stderr)
        return 1

    timestamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    # Stamp completed_at on every rater block.
    for r in raters_map.values():
        r.setdefault("completed_at", timestamp)

    # patches_applied heuristic: prior open findings minus the new ones the
    # pass introduced, floored at 0. In legacy mode the Codex report's total
    # severity-marker count anchored this; generalized mode lacks that signal,
    # so we approximate from prior open-findings count.
    prior_open = len(state.get("open_findings", []) or [])
    patches_applied = max(0, prior_open - new_findings)

    entry = {
        "pass": args.pass_n,
        "fired_at": timestamp,
        "raters": raters_map,
        "new_findings": new_findings,
        "patches_applied": patches_applied,
    }

    # Backward compat: also write the flat codex/claude blocks when those raters
    # participated, so old readers (and the classic peer-audit) keep working.
    for name in DEFAULT_RATERS:
        if name in raters_map:
            entry[name] = dict(raters_map[name])

    # Persist the configured rater set on the state (first writer wins; legacy
    # state without `raters` gets ['codex','claude'] only when codex+claude ran).
    if "raters" not in state:
        if legacy:
            state["raters"] = list(DEFAULT_RATERS)
        else:
            state["raters"] = list(raters_map.keys())

    # Train 7 fix (Codex Pass 3 HIGH #1): replace, don't append, on same-pass
    # retries. Earlier behavior appended unconditionally, producing duplicate
    # history rows on Phase 3 reruns and corrupting the T6a plateau check
    # (history[-2] after a same-pass retry pointed to the previous *attempt*
    # of the same pass, not the actual prior pass).
    existing = state.get("history", []) or []
    state["history"] = [h for h in existing if h.get("pass") != args.pass_n] + [entry]
    state["current_pass"] = args.pass_n

    # Train 5 contract: validate the canonical open-findings scalar matches the
    # list length whenever a canonical count was parsed.
    #
    # Train 8 fix (Codex Pass 4 MEDIUM #1): in LEGACY mode, fail-closed when the
    # scalar is missing entirely (the Claude template marks it required). In
    # generalized mode the open-findings block is optional, so a missing scalar
    # is tolerated — but if a scalar IS present it must match the list length.
    if legacy:
        if open_count is None or open_count != len(open_findings):
            if open_count is None:
                print(
                    "ERROR: Claude's report is missing the canonical 'Open findings "
                    "after this pass: N' scalar required by the Train 5 template. "
                    "Add the canonical accounting block.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"ERROR: Claude's canonical 'Open findings after this pass' = "
                    f"{open_count}, but the machine-readable list parses to "
                    f"{len(open_findings)} entries. Fix the list-block format "
                    f"or update the scalar to match.",
                    file=sys.stderr,
                )
            return 1
    else:
        if open_count is not None and open_count != len(open_findings):
            print(
                f"ERROR: 'Open findings after this pass' = {open_count}, but the "
                f"machine-readable list parses to {len(open_findings)} entries.",
                file=sys.stderr,
            )
            return 1

    state["open_findings"] = open_findings
    entry["open_findings_after_pass"] = len(open_findings)

    decision, reasoning = decide_convergence(state, entry, new_findings)
    state["convergence"] = state.get("convergence", {})
    state["convergence"]["status"] = decision
    state["convergence"]["last_reasoning"] = reasoning

    # allow_nan=False: the state file is standards-compliant JSON; with intake
    # validation upstream this never fires, but if a non-finite ever reaches
    # here we crash rather than write an Infinity token other parsers reject.
    args.state.write_text(json.dumps(state, indent=2, allow_nan=False))

    result = {
        "convergence": decision,
        "reasoning": reasoning,
        "pass": args.pass_n,
        "raters": {
            name: {
                "verdict": (raters_map.get(name) or {}).get("verdict"),
                "craft": (raters_map.get(name) or {}).get("craft"),
                "fit": (raters_map.get(name) or {}).get("fit"),
            }
            for name in rater_names(state, entry)
        },
        "new_findings": new_findings,
    }
    # Backward-compat convenience keys for the classic 2-rater readers.
    if "codex" in raters_map:
        result["codex_verdict"] = raters_map["codex"].get("verdict")
        result["codex_craft_fit"] = [
            raters_map["codex"].get("craft"), raters_map["codex"].get("fit")
        ]
    if "claude" in raters_map:
        result["claude_verdict"] = raters_map["claude"].get("verdict")
        result["claude_craft_fit"] = [
            raters_map["claude"].get("craft"), raters_map["claude"].get("fit")
        ]
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

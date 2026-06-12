#!/usr/bin/env python3
"""trio-weight-apply.py — the ONLY writer of trio trust-weight changes (T1).

EXTRACT NOTE: paths adapted to this repo's layout; the --auto path is
stubbed to refuse (its gate predicates live in the source system).

A THIN wrapper over the existing meta-loop machinery, not a second applier:
HOLD constants come from lib/protocol_limits and the F->G / HOLD predicates
from lib/protocol_gate, evaluated against the gate ledger loaded FROM THE
TRUSTED BASE REF (never the working tree), the same discipline as
protocol-apply.py. Spec: docs/TRIO_ADAPTIVE_WEIGHTS_PLAN.md (rev 2).

Design rules (each one closes a reviewed attack path):

- The applier CONSTRUCTS the new policy file itself from {domain, family, to}
  tuples. It never accepts a whole-file replacement and never trusts a
  proposal-declared key classification, so a proposal cannot mislabel a
  sensitive_min_weight edit as a weight edit. After construction it
  re-derives the changed key-paths by diffing constructed-vs-base and
  asserts they are exactly the declared weight paths (belt and suspenders).
- REFUSALS (hard, in code): any non-weight key change; unknown family or
  domain; more than ONE change per proposal (one change per cycle); a
  per-cycle delta over 0.1; any sign change of (weight - sensitive_min_weight)
  for the affected table (the boundary freeze); any change that makes a
  non-adjudicator family meet or exceed the adjudicator's weight (argmax
  freeze); research-basis deltas over 0.05; a retro-basis proposal without
  >= MIN_VERIFIED_MATCHES verified matches AND a win-rate credible interval
  excluding 0.5.
- MODES: default is a dry run (prints the plan, writes nothing). --confirm
  applies after all refusals pass (the manual path; Kevin's call). --auto
  additionally requires the F->G approval AND the HOLD predicate for organ
  "trio_weights" in the trusted-base gate ledger, so the auto future is
  predicate-gated, not TODO-gated. Nothing today writes with --auto.
- On apply: the changed weight becomes a provenance dict
  {"value": V, "as_of": DATE, "basis": ..., "evidence": ...} (readers take
  .value when present; flat numbers stay valid), policy_version bumps, and
  a line is appended to docs/trio/WEIGHTS_CHANGELOG.md.

Proposal file (JSON):
  {
    "proposal_id": "WEIGHT_PROPOSAL_2026-06-19",
    "basis": "retro" | "research",
    "evidence": "docs/trio/WEIGHT_PROPOSAL_2026-06-19.md",
    "changes": [{"domain": "general"|"ui"|null, "family": "codex", "to": 8.6}],
    "evidence_counts": {"verified_matches": 17, "ci_excludes_half": true}
  }
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "adjudicator" / "trio_policy.json"
CHANGELOG_PATH = REPO_ROOT / "docs" / "WEIGHTS_CHANGELOG.md"
LEDGER_REL = "bin/lib/protocol_gate_ledger.jsonl"

ORGAN = "trio_weights"
MAX_DELTA = 0.1
MAX_DELTA_RESEARCH = 0.05
MIN_VERIFIED_MATCHES = 15
KNOWN_FAMILIES = ("claude", "codex", "gemini")
VALID_BASES = ("retro", "research")


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _weight_value(raw):
    """A weight is a flat number or a provenance dict carrying .value."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _load_base_policy(base_ref: str, policy_path: Path) -> dict:
    """The TRUSTED BASE policy: from git at base_ref, never the working tree.

    Tests may pass base_ref="WORKTREE" to read the file directly.
    """
    if base_ref == "WORKTREE":
        return json.loads(policy_path.read_text(encoding="utf-8"))
    rel = policy_path.resolve().relative_to(REPO_ROOT)
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{base_ref}:{rel}"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"REFUSED: cannot load trusted base policy {base_ref}:{rel}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def _load_base_ledger(base_ref: str) -> list[dict]:
    if base_ref == "WORKTREE":
        path = REPO_ROOT / LEDGER_REL
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    else:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{base_ref}:{LEDGER_REL}"],
            capture_output=True,
            text=True,
        )
        text = out.stdout if out.returncode == 0 else ""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _table_for(policy: dict, domain: str | None) -> tuple[dict, float, str, list]:
    """(weights_map, sensitive_min, adjudicator, key_path_prefix) for a change."""
    adjudicator = policy.get("adjudicator", "claude") or "claude"
    if domain:
        table = (policy.get("domains") or {}).get(domain)
        if not isinstance(table, dict):
            raise SystemExit(f"REFUSED: unknown domain {domain!r} (the applier never creates tables)")
        weights = table.get("weights")
        smin = table.get("sensitive_min_weight", policy.get("sensitive_min_weight", 8.5))
        prefix = ["domains", domain, "weights"]
    else:
        weights = policy.get("weights")
        smin = policy.get("sensitive_min_weight", 8.5)
        prefix = ["weights"]
    if not isinstance(weights, dict):
        raise SystemExit("REFUSED: policy weights table missing or malformed")
    return weights, float(smin), adjudicator, prefix


def _diff_key_paths(a, b, prefix=()) -> set[tuple]:
    """All leaf key-paths whose values differ between two JSON trees."""
    paths: set[tuple] = set()
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            paths |= _diff_key_paths(a.get(k), b.get(k), prefix + (k,))
        return paths
    if a != b:
        paths.add(prefix)
    return paths


def validate_and_construct(policy: dict, proposal: dict, today: str) -> tuple[dict, dict]:
    """Validate the proposal against the trusted base; return (new_policy, plan).

    Raises SystemExit("REFUSED: ...") on any refusal. Pure given its inputs.
    """
    basis = proposal.get("basis")
    if basis not in VALID_BASES:
        raise SystemExit(f"REFUSED: basis must be one of {VALID_BASES}, got {basis!r}")
    evidence = proposal.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise SystemExit("REFUSED: proposal must carry an evidence link")

    changes = proposal.get("changes")
    if not isinstance(changes, list) or not changes:
        raise SystemExit("REFUSED: proposal has no changes")
    if len(changes) != 1:
        raise SystemExit(f"REFUSED: one change per cycle; proposal has {len(changes)}")
    change = changes[0]

    family = change.get("family")
    if family not in KNOWN_FAMILIES:
        raise SystemExit(f"REFUSED: unknown family {family!r}")
    domain = change.get("domain") or None

    weights, smin, adjudicator, prefix = _table_for(policy, domain)
    current = _weight_value(weights.get(family))
    if current is None:
        raise SystemExit(f"REFUSED: family {family!r} has no weight in the {domain or 'flat'} table")

    # A change carries an absolute "to" OR a relative "delta" (the retro's
    # propose_weight_deltas emits deltas; they resolve against the TRUSTED
    # BASE value, never a proposal-claimed current).
    if change.get("to") is not None:
        to = _weight_value(change.get("to"))
    elif change.get("delta") is not None:
        try:
            to = round(current + float(change["delta"]), 4)
        except (TypeError, ValueError):
            to = None
    else:
        to = None
    if to is None or not (0.0 <= to <= 10.0):
        raise SystemExit(
            f"REFUSED: target weight must resolve to a finite number in [0, 10], "
            f"got to={change.get('to')!r} delta={change.get('delta')!r}"
        )

    delta = to - current
    cap = MAX_DELTA_RESEARCH if basis == "research" else MAX_DELTA
    if abs(delta) > cap + 1e-9:
        raise SystemExit(
            f"REFUSED: delta {delta:+.3f} exceeds the {basis} per-cycle bound (±{cap})"
        )

    # Boundary freeze: the sign of (weight - sensitive_min_weight) never
    # changes through this path, regardless of basis or confirm.
    if (current >= smin) != (to >= smin):
        raise SystemExit(
            f"REFUSED: boundary crossing ({family} {current} -> {to} crosses "
            f"sensitive_min_weight {smin}); crossings are a human decision made "
            "by editing the DECLARED authority keys, never a weight delta"
        )

    # Argmax freeze: no non-adjudicator family may meet or exceed the
    # adjudicator's weight in the affected table.
    adj_w = _weight_value(weights.get(adjudicator))
    if family != adjudicator and adj_w is not None and to >= adj_w:
        raise SystemExit(
            f"REFUSED: {family} -> {to} would meet or exceed the adjudicator "
            f"({adjudicator} at {adj_w}); the seat is family-locked and ties are refused"
        )
    if family == adjudicator:
        others = [
            _weight_value(w)
            for fam, w in weights.items()
            if fam != adjudicator and _weight_value(w) is not None
        ]
        if any(to <= other for other in others):
            raise SystemExit(
                f"REFUSED: lowering the adjudicator ({adjudicator}) to {to} would "
                "tie or fall below another engine; the seat must stay strictly top"
            )

    # Evidence-count gate (internal stream). The retro must show enough
    # verification-settled matches and a credible interval excluding 0.5.
    counts = proposal.get("evidence_counts") or {}
    if basis == "retro":
        n = counts.get("verified_matches")
        if not isinstance(n, int) or n < MIN_VERIFIED_MATCHES:
            raise SystemExit(
                f"REFUSED: retro basis needs >= {MIN_VERIFIED_MATCHES} verified matches, got {n!r}"
            )
        if counts.get("ci_excludes_half") is not True:
            raise SystemExit("REFUSED: retro basis needs a win-rate credible interval excluding 0.5")

    # Construct the new policy ourselves (never accept a supplied file).
    new_policy = json.loads(json.dumps(policy))  # deep copy
    target_table = new_policy
    for key in prefix[:-1]:
        target_table = target_table[key]
    target_table[prefix[-1]][family] = {
        "value": to,
        "as_of": today,
        "basis": basis,
        "evidence": evidence,
    }
    new_policy["policy_version"] = int(policy.get("policy_version", 1)) + 1

    # Belt and suspenders: the changed key-paths, re-derived by diffing, must
    # be exactly the declared weight path plus the version bump.
    changed = _diff_key_paths(policy, new_policy)
    allowed = {tuple(prefix) + (family,), ("policy_version",)}
    extra = {p for p in changed if not any(p[: len(a)] == a for a in allowed)}
    if extra:
        raise SystemExit(f"REFUSED: construction touched undeclared keys: {sorted(extra)}")

    plan = {
        "family": family,
        "domain": domain or "flat",
        "from": current,
        "to": to,
        "delta": round(delta, 4),
        "basis": basis,
        "evidence": evidence,
        "policy_version": new_policy["policy_version"],
    }
    return new_policy, plan


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True, type=Path)
    ap.add_argument("--confirm", action="store_true", help="apply (default: dry run)")
    ap.add_argument("--auto", action="store_true",
                    help="unattended mode: ALSO requires F->G + HOLD in the trusted-base ledger")
    ap.add_argument("--base", default="HEAD", help="trusted base ref (tests: WORKTREE)")
    ap.add_argument("--policy-path", type=Path, default=POLICY_PATH)
    ap.add_argument("--changelog-path", type=Path, default=CHANGELOG_PATH)
    ap.add_argument("--now-date", default=None, help="override today's date (tests)")
    args = ap.parse_args(argv)

    proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
    policy = _load_base_policy(args.base, args.policy_path)
    today = args.now_date or _dt.date.today().isoformat()

    new_policy, plan = validate_and_construct(policy, proposal, today)

    if args.auto:
        # The F->G / HOLD predicates and the signed gate ledger live in the
        # source system; this extract ships the manual --confirm path only.
        raise SystemExit(
            "REFUSED: --auto requires the source system's fg_approval ledger "
            "and HOLD predicates (lib/protocol_gate); this extract ships the "
            "manual --confirm path only"
        )

    print(json.dumps({"plan": plan, "mode": "apply" if args.confirm else "dry-run"}, indent=2))
    if not args.confirm:
        return 0

    args.policy_path.write_text(json.dumps(new_policy, indent=2) + "\n", encoding="utf-8")
    args.changelog_path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if args.changelog_path.exists() else (
        "# Trio weights changelog\n\n"
        "Every applied weight change, with provenance. Written ONLY by\n"
        "bin/trio-weight-apply.py. Spec: docs/TRIO_ADAPTIVE_WEIGHTS_PLAN.md.\n\n"
    )
    confirmer = "auto" if args.auto else "kevin (--confirm)"
    with args.changelog_path.open("a", encoding="utf-8") as fh:
        fh.write(header)
        fh.write(
            f"- {today}: {plan['domain']}.{plan['family']} "
            f"{plan['from']} -> {plan['to']} ({plan['delta']:+}) "
            f"basis={plan['basis']} evidence={plan['evidence']} "
            f"policy_version={plan['policy_version']} confirmed_by={confirmer} "
            f"proposal={proposal.get('proposal_id', args.proposal.name)}\n"
        )
    print(f"applied: {args.policy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

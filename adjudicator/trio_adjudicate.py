"""Pure predicates for Trio trust-weighted review adjudication.

The Trio runs three review engines at trust weights (Opus/Claude 9, Codex 8.5,
Gemini 8). After the author + the duet's cross-model pass, Gemini adds a third,
diverse-lineage review. This module decides what to DO with the pooled findings.

It is I/O-free except for `load_policy`, which reads the shared weight config
(bin/lib/trio_policy.json) so a re-weight is a one-line edit shared with
trio_policy.sh. The predicates themselves take weights as an explicit argument,
so they stay pure and fully unit-testable.

The rules (docs/TRIO_TRUST_MODEL_2026-06-03.md):

  - A finding's FORCE = engine_weight * confidence.
  - CROSS-ENGINE AGREEMENT (two distinct lineages concurring on one claim)
    raises confidence sharply: combined via noisy-or over per-family bests.
  - On a SENSITIVE (tier3) diff, NO non-adjudicator finding auto-acts or
    auto-dismisses. Only the adjudicator (Opus) decides. Adjudicator identity
    is FAMILY-LOCKED config (policy "adjudicator", default claude) and
    excludes sub-top same-family models (haiku/sonnet); it is NEVER derived
    from the weights, so a learned weight tie can never grant the seat
    (T0 guard rail, WEIGHTS_PLAN_REVIEW_2026-06-12). A claim the adjudicator
    raised -> ACT; a claim only other engines raised -> ESCALATE (Opus
    adjudicates). A Gemini-only flag is never a veto and is never silently
    dropped: it escalates.
  - On a NON-SENSITIVE diff, weighted findings are acted on directly: ACT when
    there is cross-engine agreement or the boosted force clears the threshold;
    otherwise DISMISS.

Verdicts: "act" (treat as real / fix), "escalate" (Opus adjudicates),
"dismiss" (drop). Adjudication never destroys a finding silently: a sensitive
claim is always at least escalated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Verdicts.
ACT = "act"
ESCALATE = "escalate"
DISMISS = "dismiss"

# Engine name -> trust family. Keys are normalized (lowercased, non-alphanumerics
# stripped) before lookup, so "Opus 4.8", "opus4.8", and "GPT-5.5" all resolve.
_FAMILY_ALIASES: dict[str, str] = {
    # Claude family (Opus/Sonnet/Haiku share a family for independence).
    "claude": "claude",
    "claudecode": "claude",
    "claudereview": "claude",
    "anthropic": "claude",
    "opus": "claude",
    "opus48": "claude",
    "sonnet": "claude",
    "haiku": "claude",
    # GPT / Codex family.
    "codex": "codex",
    "codexcli": "codex",
    "codexreview": "codex",
    "codex55": "codex",
    "gpt": "codex",
    "gpt5": "codex",
    "gpt55": "codex",
    "openai": "codex",
    # Gemini family (a distinct training lineage: the point of the third review).
    "gemini": "gemini",
    "geminicli": "gemini",
    "geminipro": "gemini",
    "google": "gemini",
}

_DEFAULT_WEIGHTS: dict[str, float] = {"claude": 9.0, "codex": 8.5, "gemini": 8.0}
_DEFAULT_SENSITIVE_MIN = 8.5
# T0 guard rail (WEIGHTS_PLAN_REVIEW_2026-06-12): authority is DECLARED config,
# never derived from the tunable weights. The adjudicator seat is family-locked,
# and sub-top same-family models never inherit it (a Haiku reviewer aliases to
# family "claude" at weight 9.0; without the exclusion it would self-adjudicate
# sensitive findings as "the adjudicator raised it").
_DEFAULT_ADJUDICATOR = "claude"
_DEFAULT_SENSITIVE_AUTHORS: tuple[str, ...] = ("claude", "codex")
_SUBTOP_MODELS: tuple[str, ...] = ("haiku", "sonnet")
# Default "act directly" force bar on non-sensitive diffs. 6.0 means a single
# trusted-engine finding acts at conf ~0.67 (claude) / ~0.71 (codex) / 0.75
# (gemini); a low-confidence lone flag falls below it and is dismissed.
_DEFAULT_ACT_THRESHOLD = 6.0

_POLICY_PATH = Path(__file__).resolve().parent / "trio_policy.json"


def _canonical_family(value: Any) -> str:
    """Normalize an engine label to its trust family, or "" if unknown."""
    if not isinstance(value, str):
        return ""
    key = re.sub(r"[^a-z0-9]", "", value.lower())
    return _FAMILY_ALIASES.get(key, "")


def _clamp01(value: Any) -> float:
    """Coerce a confidence to a float in [0, 1]; unusable input -> 0.0."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    if c != c:  # NaN
        return 0.0
    return 0.0 if c < 0.0 else 1.0 if c > 1.0 else c


def _apply_clamps(
    weights: dict[str, float],
    smin: float,
    sensitive_authors: list[str] | tuple[str, ...],
    adjudicator: str,
) -> dict[str, float]:
    """Absolute clamps (T0 guard rail): non-adjudicator weights stay strictly
    below the adjudicator's; declared sensitive authors stay floored at the
    sensitive threshold. A hand- or proposal-edited NUMBER can never move an
    engine across either boundary through this reader; a real crossing
    requires editing the DECLARED authority keys, which live in a tier3 +
    gate-file protected file. The reader clamp is last-resort containment;
    the weight applier is the loud refusal path.

    Mirrored by the shell loader in trio_policy.sh; keep the two in step.
    """
    adj_w = weights.get(adjudicator)
    out = dict(weights)
    for fam, w in weights.items():
        v = w
        if adj_w is not None and fam != adjudicator and v >= adj_w:
            v = round(adj_w - 0.1, 4)
        if fam in sensitive_authors and v < smin:
            v = smin
        out[fam] = v
    return out


def load_policy(path: Any = None) -> dict[str, Any]:
    """Read weights + the sensitive threshold + the DECLARED authority sets
    (adjudicator family, sensitive_authors) from the shared JSON config.

    Falls back to the baked defaults if the file is missing or malformed, and
    always guarantees the three known families have a weight. Applies the T0
    absolute clamps. The ONLY I/O in this module.
    """
    p = Path(path) if path else _POLICY_PATH
    weights = dict(_DEFAULT_WEIGHTS)
    smin = _DEFAULT_SENSITIVE_MIN
    adjudicator = _DEFAULT_ADJUDICATOR
    authors = list(_DEFAULT_SENSITIVE_AUTHORS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("weights", {})
        if isinstance(raw, dict):
            for fam, w in raw.items():
                try:
                    weights[str(fam)] = float(w)
                except (TypeError, ValueError):
                    continue
        smin = float(data.get("sensitive_min_weight", _DEFAULT_SENSITIVE_MIN))
        if isinstance(data.get("adjudicator"), str) and data["adjudicator"]:
            adjudicator = data["adjudicator"]
        raw_a = data.get("sensitive_authors")
        if isinstance(raw_a, list) and raw_a:
            authors = [str(a) for a in raw_a]
    except (OSError, ValueError, TypeError):
        pass
    for fam, w in _DEFAULT_WEIGHTS.items():
        weights.setdefault(fam, w)
    weights = _apply_clamps(weights, smin, authors, adjudicator)
    return {
        "weights": weights,
        "sensitive_min_weight": smin,
        "adjudicator": adjudicator,
        "sensitive_authors": authors,
    }


# --- Domain-aware policy (general/code vs ui/design) -------------------------
# Same shared JSON, per-domain tables under .domains{}. load_policy() above keeps
# returning the FLAT general default so existing callers are unchanged; the
# helpers below read the requested domain's table with a general fallback.

_UI_HINTS = re.compile(
    r"\.(css|scss|sass|less|html?|svg|vue|jsx|tsx)\b"
    r"|template|stylesheet|markup|visual|design|layout|\bui\b"
    r"|theme|styling|a11y|accessib",
    re.IGNORECASE,
)


def classify_domain(subject: Any, *, explicit: Any = None) -> str:
    """Return "ui" or "general". An explicit "ui"/"general" wins; otherwise
    CSS/HTML/templates/visual subjects => "ui", everything else => "general"."""
    if isinstance(explicit, str) and explicit.lower() in ("ui", "general"):
        return explicit.lower()
    text = subject if isinstance(subject, str) else " ".join(map(str, subject or []))
    return "ui" if _UI_HINTS.search(text) else "general"


def load_domain_policy(domain: str = "general", path: Any = None) -> dict[str, Any]:
    """Read one domain's table (weights + sensitive_min_weight + fleet_ratio +
    roles) from the shared JSON, with a general/baked fallback so a missing or
    malformed file still answers.

    Returns {domain, weights, sensitive_min_weight, fleet_ratio, roles}.
    """
    p = Path(path) if path else _POLICY_PATH
    base = load_policy(p)  # flat general default (weights + threshold + authority)
    weights = dict(base["weights"])
    smin = base["sensitive_min_weight"]
    adjudicator = base["adjudicator"]
    authors = list(base["sensitive_authors"])
    fleet_ratio: dict[str, float] = {}
    roles: dict[str, str] = {}
    chosen = domain
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        domains = data.get("domains", {}) or {}
        default_domain = data.get("default_domain", "general")
        table = domains.get(domain) or domains.get(default_domain) or domains.get("general") or {}
        chosen = domain if domains.get(domain) else (default_domain if domains.get(default_domain) else "general")
        raw_w = table.get("weights")
        if isinstance(raw_w, dict):
            for fam, w in raw_w.items():
                try:
                    weights[str(fam)] = float(w)
                except (TypeError, ValueError):
                    continue
        if "sensitive_min_weight" in table:
            try:
                smin = float(table["sensitive_min_weight"])
            except (TypeError, ValueError):
                pass
        raw_a = table.get("sensitive_authors")
        if isinstance(raw_a, list) and raw_a:
            authors = [str(a) for a in raw_a]
        raw_r = table.get("fleet_ratio")
        if isinstance(raw_r, dict):
            for fam, r in raw_r.items():
                try:
                    fleet_ratio[str(fam)] = float(r)
                except (TypeError, ValueError):
                    continue
        raw_roles = table.get("roles")
        if isinstance(raw_roles, dict):
            roles = {str(k): str(v) for k, v in raw_roles.items()}
    except (OSError, ValueError, TypeError):
        pass
    for fam, w in _DEFAULT_WEIGHTS.items():
        weights.setdefault(fam, w)
    weights = _apply_clamps(weights, smin, authors, adjudicator)
    return {
        "domain": chosen,
        "weights": weights,
        "sensitive_min_weight": smin,
        "adjudicator": adjudicator,
        "sensitive_authors": authors,
        "fleet_ratio": fleet_ratio,
        "roles": roles,
    }


def engine_weight(engine: Any, weights: dict[str, float]) -> float:
    """Trust weight for an engine label (0.0 if its family is unknown)."""
    return float(weights.get(_canonical_family(engine), 0.0))


def finding_force(engine: Any, confidence: Any, weights: dict[str, float]) -> float:
    """force = engine_weight * confidence (confidence clamped to [0, 1])."""
    return engine_weight(engine, weights) * _clamp01(confidence)


def is_adjudicator(engine: Any, weights: dict[str, float], *, adjudicator: str | None = None) -> bool:
    """True only for the configured adjudicator family's top model.

    FAMILY-LOCKED (T0 guard rail), never weight-derived. The old predicate
    (engine_weight >= max(weights)) let any engine learn its way into the
    seat via a weight tie, and let a sub-top same-family model (haiku/sonnet
    alias to family "claude" at weight 9.0) self-adjudicate sensitive
    findings. `weights` stays in the signature for call-site compatibility
    but no longer decides identity.
    """
    del weights  # identity is declared config, never weight-derived
    fam = _canonical_family(engine)
    if not fam:
        return False
    if fam != (adjudicator or _DEFAULT_ADJUDICATOR):
        return False
    key = re.sub(r"[^a-z0-9]", "", str(engine).lower())
    return not any(key.startswith(m) for m in _SUBTOP_MODELS)


def _noisy_or(confidences: Any) -> float:
    """Combine independent confidences: 1 - prod(1 - c_i). Two lineages
    concurring at 0.6 each -> 0.84, the 'agreement raises confidence' effect."""
    prod = 1.0
    for c in confidences:
        prod *= 1.0 - _clamp01(c)
    return 1.0 - prod


def _claim_key(finding: Any) -> str:
    """Identity for grouping findings about the same issue."""
    if isinstance(finding, dict):
        if finding.get("claim"):
            return str(finding["claim"])
        parts = [str(finding.get(k, "")) for k in ("file", "line", "title")]
        joined = ":".join(p for p in parts if p)
        if joined:
            return joined
    return repr(finding)


def adjudicate_claim(
    findings: list[dict[str, Any]],
    *,
    sensitive: bool,
    weights: dict[str, float],
    act_threshold: float = _DEFAULT_ACT_THRESHOLD,
    adjudicator: str | None = None,
) -> dict[str, Any]:
    """Adjudicate ONE claim (a group of findings about the same issue).

    `adjudicator` is the family-locked adjudicator family (defaults to the
    policy default, claude). Returns {verdict, force, families, agreement,
    adjudicator, reason}.
    """
    families = sorted({_canonical_family(f.get("engine")) for f in findings if _canonical_family(f.get("engine"))})
    if not families:
        return {
            "verdict": DISMISS,
            "force": 0.0,
            "families": [],
            "agreement": False,
            "adjudicator": False,
            "reason": "no recognized engine raised this claim",
        }

    agreement = len(families) >= 2
    adjudicator_raised = any(is_adjudicator(f.get("engine"), weights, adjudicator=adjudicator) for f in findings)

    # Best confidence per family, then noisy-or so only independent lineages
    # (not repeated same-family findings) compound the confidence.
    by_family_best: dict[str, float] = {}
    for f in findings:
        fam = _canonical_family(f.get("engine"))
        if not fam:
            continue
        by_family_best[fam] = max(by_family_best.get(fam, 0.0), _clamp01(f.get("confidence")))
    claim_confidence = _noisy_or(by_family_best.values())
    top_weight = max(engine_weight(f.get("engine"), weights) for f in findings)
    boosted_force = round(top_weight * claim_confidence, 4)

    if sensitive:
        if adjudicator_raised:
            verdict = ACT
            reason = "sensitive: the adjudicator (Opus) raised it; acted on directly"
        else:
            verdict = ESCALATE
            reason = (
                "sensitive: non-adjudicator finding(s) escalated to Opus "
                + ("(cross-engine agreement raises confidence)" if agreement else "(single engine, never dropped)")
            )
    else:
        if agreement or boosted_force >= act_threshold:
            verdict = ACT
            reason = (
                "non-sensitive: cross-engine agreement"
                if agreement
                else f"non-sensitive: force {boosted_force} >= {act_threshold}"
            )
        else:
            verdict = DISMISS
            reason = f"non-sensitive: force {boosted_force} < {act_threshold}"

    return {
        "verdict": verdict,
        "force": boosted_force,
        "families": families,
        "agreement": agreement,
        "adjudicator": adjudicator_raised,
        "reason": reason,
    }


def adjudicate(
    findings: list[dict[str, Any]],
    *,
    sensitive: bool,
    weights: dict[str, float] | None = None,
    act_threshold: float = _DEFAULT_ACT_THRESHOLD,
    adjudicator: str | None = None,
) -> list[dict[str, Any]]:
    """Group findings by claim and adjudicate each. weights + the adjudicator
    family default to the shared config. Returns one verdict dict per claim,
    each with a "claim" key.
    """
    if weights is None or adjudicator is None:
        pol = load_policy()
        if weights is None:
            weights = pol["weights"]
        if adjudicator is None:
            adjudicator = pol["adjudicator"]
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for f in findings:
        key = _claim_key(f)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    results = []
    for key in order:
        verdict = adjudicate_claim(
            groups[key],
            sensitive=sensitive,
            weights=weights,
            act_threshold=act_threshold,
            adjudicator=adjudicator,
        )
        verdict["claim"] = key
        results.append(verdict)
    return results

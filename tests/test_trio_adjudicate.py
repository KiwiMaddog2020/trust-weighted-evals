"""Oracle for Trio T3: trust-weighted 3-way adjudication.

Pure-predicate tests for adjudicator/trio_adjudicate.py (the weighting, the
non-sensitive force/agreement path, and the sensitive-escalation path), plus a
conformance check that the JSON config and the Python adjudicator report the
SAME weights, so the single source of truth cannot drift.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOD = REPO / "adjudicator" / "trio_adjudicate.py"
CFG = REPO / "adjudicator" / "trio_policy.json"

_spec = importlib.util.spec_from_file_location("trio_adjudicate", MOD)
adj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adj)

W = adj.load_policy()["weights"]


# --- weights + family resolution ---------------------------------------------
def test_engine_weights_by_family() -> None:
    assert adj.engine_weight("opus", W) == 9
    assert adj.engine_weight("Opus 4.8", W) == 9
    assert adj.engine_weight("claude", W) == 9
    assert adj.engine_weight("codex", W) == 8.5
    assert adj.engine_weight("GPT-5.5", W) == 8.5
    assert adj.engine_weight("gemini", W) == 8
    assert adj.engine_weight("Gemini CLI", W) == 8
    assert adj.engine_weight("mystery-model", W) == 0


def test_finding_force_and_confidence_clamp() -> None:
    assert adj.finding_force("gemini", 0.5, W) == 4.0
    assert adj.finding_force("gemini", 1.5, W) == 8.0  # clamp high
    assert adj.finding_force("codex", -1, W) == 0.0  # clamp low
    assert adj.finding_force("codex", None, W) == 0.0  # unusable -> 0
    assert adj.finding_force("codex", "nope", W) == 0.0


def test_is_adjudicator_family_locked() -> None:
    # T0 guard rail: adjudicator identity is DECLARED config, never derived.
    assert adj.is_adjudicator("opus", W) is True
    assert adj.is_adjudicator("claude", W) is True
    assert adj.is_adjudicator("Opus 4.8", W) is True
    assert adj.is_adjudicator("codex", W) is False
    assert adj.is_adjudicator("gemini", W) is False


def test_is_adjudicator_ignores_weight_ties() -> None:
    # The old predicate (weight >= max) let a learned tie or overshoot grant
    # the seat. Family-locked identity cannot be bought with weights.
    inflated = {"claude": 9.0, "codex": 9.0, "gemini": 9.5}
    assert adj.is_adjudicator("codex", inflated) is False
    assert adj.is_adjudicator("gemini", inflated) is False
    assert adj.is_adjudicator("opus", inflated) is True


def test_is_adjudicator_excludes_subtop_family_models() -> None:
    # haiku/sonnet alias to family claude at weight 9.0; they must never
    # inherit the seat (the cross-model review's self-adjudication exploit).
    assert adj.is_adjudicator("haiku", W) is False
    assert adj.is_adjudicator("Haiku 4.5", W) is False
    assert adj.is_adjudicator("sonnet", W) is False


def test_is_adjudicator_config_override() -> None:
    assert adj.is_adjudicator("codex", W, adjudicator="codex") is True
    assert adj.is_adjudicator("opus", W, adjudicator="codex") is False


def test_sensitive_haiku_finding_escalates_not_acts() -> None:
    # A Haiku reviewer aliases to family claude at weight 9.0 and used to
    # auto-ACT sensitive findings as "the adjudicator raised it".
    r = adj.adjudicate_claim([{"engine": "haiku", "confidence": 0.9}], sensitive=True, weights=W)
    assert r["verdict"] == adj.ESCALATE
    assert r["adjudicator"] is False


def test_policy_declares_authority() -> None:
    # T0: authority is declared in the policy file, not derived from weights.
    pol = adj.load_policy()
    assert pol["adjudicator"] == "claude"
    assert pol["sensitive_authors"] == ["claude", "codex"]
    ui = adj.load_domain_policy("ui")
    assert ui["sensitive_authors"] == ["claude"]
    assert ui["adjudicator"] == "claude"


def test_reader_clamps_boundary_crossings(tmp_path) -> None:
    # T0 absolute clamps: an edited NUMBER alone cannot cross either boundary.
    data = json.loads(CFG.read_text())
    data["weights"]["gemini"] = 9.6  # would beat/tie the adjudicator
    data["weights"]["codex"] = 8.2  # would silently revoke a declared author
    alt = tmp_path / "alt.json"
    alt.write_text(json.dumps(data))
    w = adj.load_policy(alt)["weights"]
    assert w["gemini"] == 8.9  # capped strictly below claude (9 - 0.1)
    assert w["codex"] == 8.5  # floored at sensitive_min_weight (declared author)
    assert w["claude"] == 9


def test_noisy_or_compounds_independent_confidence() -> None:
    assert math.isclose(adj._noisy_or([0.6, 0.6]), 0.84, rel_tol=1e-9)
    assert adj._noisy_or([]) == 0.0
    assert adj._noisy_or([1.0]) == 1.0


# --- non-sensitive: weighted findings acted on directly ----------------------
def test_nonsensitive_single_high_confidence_acts() -> None:
    r = adj.adjudicate_claim([{"engine": "gemini", "confidence": 0.9}], sensitive=False, weights=W)
    assert r["verdict"] == adj.ACT  # force 7.2 >= 6.0


def test_nonsensitive_single_low_confidence_dismissed() -> None:
    r = adj.adjudicate_claim([{"engine": "gemini", "confidence": 0.5}], sensitive=False, weights=W)
    assert r["verdict"] == adj.DISMISS  # force 4.0 < 6.0


def test_nonsensitive_cross_engine_agreement_acts() -> None:
    r = adj.adjudicate_claim(
        [{"engine": "codex", "confidence": 0.5}, {"engine": "gemini", "confidence": 0.5}],
        sensitive=False,
        weights=W,
    )
    assert r["verdict"] == adj.ACT
    assert r["agreement"] is True


# --- sensitive: no sub-top auto-acts/dismisses; Opus adjudicates -------------
def test_sensitive_gemini_only_escalates_never_dropped() -> None:
    r = adj.adjudicate_claim([{"engine": "gemini", "confidence": 0.99}], sensitive=True, weights=W)
    assert r["verdict"] == adj.ESCALATE  # never ACT, never DISMISS
    assert r["adjudicator"] is False


def test_sensitive_subtop_agreement_still_escalates() -> None:
    r = adj.adjudicate_claim(
        [{"engine": "codex", "confidence": 0.9}, {"engine": "gemini", "confidence": 0.9}],
        sensitive=True,
        weights=W,
    )
    assert r["verdict"] == adj.ESCALATE  # high confidence, but Opus adjudicates sensitive
    assert r["agreement"] is True


def test_sensitive_opus_acts_as_adjudicator() -> None:
    r = adj.adjudicate_claim([{"engine": "opus", "confidence": 0.2}], sensitive=True, weights=W)
    assert r["verdict"] == adj.ACT  # the adjudicator raised it, even at low confidence
    assert r["adjudicator"] is True


def test_agreement_requires_distinct_families() -> None:
    # Two Gemini findings are NOT agreement (same lineage), so on sensitive they
    # still escalate, and on non-sensitive they do not get the agreement bypass.
    r = adj.adjudicate_claim(
        [{"engine": "gemini", "confidence": 0.5}, {"engine": "gemini-cli", "confidence": 0.5}],
        sensitive=False,
        weights=W,
    )
    assert r["agreement"] is False
    assert r["verdict"] == adj.DISMISS  # still one family, force 4.0 < 6.0


# --- grouping: a Gemini-only sensitive flag survives, never silently dropped --
def test_adjudicate_groups_by_claim_and_preserves_gemini_flag() -> None:
    findings = [
        {"engine": "opus", "confidence": 0.8, "claim": "A"},
        {"engine": "codex", "confidence": 0.8, "claim": "A"},
        {"engine": "gemini", "confidence": 0.95, "claim": "B"},  # Gemini-only, sensitive
    ]
    out = adj.adjudicate(findings, sensitive=True, weights=W)
    by_claim = {r["claim"]: r for r in out}
    assert set(by_claim) == {"A", "B"}
    assert by_claim["A"]["verdict"] == adj.ACT  # Opus among raisers
    assert by_claim["B"]["verdict"] == adj.ESCALATE  # Gemini-only escalated, present in output


def test_weights_are_config_driven(tmp_path) -> None:
    # A re-weight is a one-line data edit: load_policy honors an alternate file.
    data = json.loads(CFG.read_text())
    data["weights"]["gemini"] = 5
    alt = tmp_path / "trio_policy_alt.json"
    alt.write_text(json.dumps(data))
    assert adj.load_policy(alt)["weights"]["gemini"] == 5
    # A malformed config falls back to baked defaults, never crashes.
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert adj.load_policy(bad)["weights"]["gemini"] == 8


# --- conformance: json == python (single source of truth) -------------------
def test_json_python_weights_agree() -> None:
    cfg = json.loads(CFG.read_text())
    jw = cfg["weights"]

    assert adj.engine_weight("opus", W) == float(jw["claude"])
    assert adj.engine_weight("codex", W) == float(jw["codex"])
    assert adj.engine_weight("gemini", W) == float(jw["gemini"])
    assert adj.load_policy()["sensitive_min_weight"] == float(cfg["sensitive_min_weight"])


# Trio-rerun + T2 additions (2026-06-12)


def test_sensitive_adjudicator_malformed_confidence_escalates() -> None:
    # Trio-rerun fix: a missing/None/NaN/zero confidence clamps to 0.0, and the
    # old sensitive branch auto-ACTed it as "the adjudicator raised it",
    # bypassing the force model on malformed input. Now it escalates.
    for bad in ({}, {"confidence": None}, {"confidence": float("nan")}, {"confidence": 0}):
        r = adj.adjudicate_claim([{"engine": "opus", **bad}], sensitive=True, weights=W)
        assert r["verdict"] == adj.ESCALATE, bad
    # A real low confidence still acts: the seat owns sensitive calls.
    r = adj.adjudicate_claim([{"engine": "opus", "confidence": 0.2}], sensitive=True, weights=W)
    assert r["verdict"] == adj.ACT


def test_clamp_order_floor_then_cap_never_ties_adjudicator(tmp_path) -> None:
    # Tier-2 round-2 fix: cap-before-floor let a raised sensitive_min_weight
    # floor a declared author into a TIE with the adjudicator. Floor first,
    # then cap strictly below the post-floor adjudicator.
    data = json.loads(CFG.read_text())
    data["sensitive_min_weight"] = 9.5
    alt = tmp_path / "alt.json"
    alt.write_text(json.dumps(data))
    w = adj.load_policy(alt)["weights"]
    assert w["claude"] == 9.5  # adjudicator floored as a declared author
    assert w["codex"] == 9.4  # capped strictly below the post-floor adjudicator
    assert w["codex"] < w["claude"]


def test_load_domain_policy_normalizes_case() -> None:
    # "UI" must hit the ui table, not silently fall back to general.
    ui = adj.load_domain_policy("UI")
    assert ui["domain"] == "ui"
    assert ui["weights"]["codex"] == 7.5
    assert ui["sensitive_authors"] == ["claude"]


def test_to_match_records_born_unsettled_with_provenance() -> None:
    # T2: match records are born UNSETTLED; the adjudicated verdict is never
    # a match outcome (the decorrelation rule). Provenance is preserved.
    findings = [
        {"engine": "codex", "confidence": 0.95, "claim": "A", "provenance": "pre-swap"},
        {"engine": "opus", "confidence": 0.9, "claim": "A", "provenance": "pre-swap"},
        {"engine": "gemini", "confidence": 0.7, "claim": "B", "provenance": "post-swap"},
    ]
    verdicts = adj.adjudicate(findings, sensitive=False, weights=W)
    records = adj.to_match_records(findings, verdicts, introduced_by="claude")
    by_claim = {r["claim"]: r for r in records}
    a = by_claim["A"]
    assert a["settled_by"] == "none" and a["settled_outcome"] == "pending"
    assert a["verdict"] == "act"
    assert a["families"] == ["claude", "codex"]
    assert a["confidence"] == 0.95
    assert a["provenance"] == "pre-swap"
    assert a["introduced_by"] == "claude"
    b = by_claim["B"]
    assert b["provenance"] == "post-swap"
    assert b["settled_outcome"] == "pending"


def test_to_match_records_mixed_provenance_labels_post_swap() -> None:
    # Tier-2 round-3 fix: any post-swap finding anchors the whole claim;
    # a pre/post mix must never be labeled independent pre-swap agreement.
    findings = [
        {"engine": "codex", "confidence": 0.8, "claim": "M", "provenance": "pre-swap"},
        {"engine": "gemini", "confidence": 0.8, "claim": "M", "provenance": "post-swap"},
    ]
    verdicts = adj.adjudicate(findings, sensitive=False, weights=W)
    records = adj.to_match_records(findings, verdicts)
    assert records[0]["provenance"] == "post-swap"

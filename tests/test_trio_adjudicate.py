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


def test_is_adjudicator_is_top_weight_only() -> None:
    assert adj.is_adjudicator("opus", W) is True
    assert adj.is_adjudicator("claude", W) is True
    assert adj.is_adjudicator("codex", W) is False
    assert adj.is_adjudicator("gemini", W) is False


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

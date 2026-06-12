"""Oracle for T1: the sole trio weight applier + provenance schema.

bin/trio-weight-apply.py is the ONLY writer of trio_policy.json weight
changes. These tests pin the full refusal set (each refusal closes a path
the 2026-06-12 three-lens review identified), the happy path (provenance
dict + version bump + changelog), and the back-compat reader contract
(provenance dicts resolve to .value in both the python reader and the
applier itself). Spec: docs/TRIO_ADAPTIVE_WEIGHTS_PLAN.md rev 2.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APPLY = REPO / "adjudicator" / "trio_weight_apply.py"
ADJ = REPO / "adjudicator" / "trio_adjudicate.py"
CFG = REPO / "adjudicator" / "trio_policy.json"

_spec = importlib.util.spec_from_file_location("trio_adjudicate", ADJ)
adj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adj)


def _proposal(d: Path, **overrides) -> Path:
    base = {
        "proposal_id": "TEST_PROPOSAL",
        "basis": "retro",
        "evidence": "docs/trio/WEIGHT_PROPOSAL_test.md",
        "changes": [{"domain": None, "family": "gemini", "to": 8.1}],
        "evidence_counts": {"verified_matches": 17, "ci_excludes_half": True},
    }
    base.update(overrides)
    p = d / "proposal.json"
    p.write_text(json.dumps(base))
    return p


def _policy_copy(d: Path) -> Path:
    p = d / "trio_policy.json"
    p.write_text(CFG.read_text())
    return p


def _run(proposal: Path, policy: Path, changelog: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, str(APPLY),
            "--proposal", str(proposal),
            "--base", "WORKTREE",
            "--policy-path", str(policy),
            "--changelog-path", str(changelog),
            "--now-date", "2026-06-12",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


# --- dry run + happy path -----------------------------------------------------


def test_dry_run_writes_nothing(tmp_path):
    policy = _policy_copy(tmp_path)
    before = policy.read_text()
    r = _run(_proposal(tmp_path), policy, tmp_path / "log.md")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["mode"] == "dry-run"
    assert policy.read_text() == before
    assert not (tmp_path / "log.md").exists()


def test_confirm_applies_provenance_version_changelog(tmp_path):
    policy = _policy_copy(tmp_path)
    changelog = tmp_path / "log.md"
    r = _run(_proposal(tmp_path), policy, changelog, "--confirm")
    assert r.returncode == 0, r.stderr
    data = json.loads(policy.read_text())
    w = data["weights"]["gemini"]
    assert w == {
        "value": 8.1,
        "as_of": "2026-06-12",
        "basis": "retro",
        "evidence": "docs/trio/WEIGHT_PROPOSAL_test.md",
    }
    assert data["policy_version"] == 2
    log = changelog.read_text()
    assert "flat.gemini 8.0 -> 8.1" in log or "flat.gemini 8 -> 8.1" in log
    assert "confirmed_by=kevin" in log
    # The back-compat reader contract: both readers resolve the dict to .value.
    assert adj.load_policy(policy)["weights"]["gemini"] == 8.1


def _expect_refusal(tmp_path, needle, **overrides):
    policy = _policy_copy(tmp_path)
    before = policy.read_text()
    r = _run(_proposal(tmp_path, **overrides), policy, tmp_path / "log.md", "--confirm")
    assert r.returncode != 0, f"expected refusal, got: {r.stdout}"
    assert "REFUSED" in r.stderr
    assert needle in r.stderr, r.stderr
    assert policy.read_text() == before  # never half-applies
    return r.stderr


def test_refuses_two_changes_per_cycle(tmp_path):
    _expect_refusal(
        tmp_path, "one change per cycle",
        changes=[
            {"domain": None, "family": "gemini", "to": 8.1},
            {"domain": None, "family": "codex", "to": 8.6},
        ],
    )


def test_refuses_delta_over_bound(tmp_path):
    _expect_refusal(
        tmp_path, "per-cycle bound",
        changes=[{"domain": None, "family": "gemini", "to": 8.3}],
    )


def test_refuses_boundary_crossing_downward(tmp_path):
    # codex sits exactly at sensitive_min_weight 8.5: one -0.1 cycle would
    # revoke its sensitive authoring. The boundary freeze refuses it.
    _expect_refusal(
        tmp_path, "boundary crossing",
        changes=[{"domain": None, "family": "codex", "to": 8.4}],
    )


def test_refuses_adjudicator_tie(tmp_path):
    # Even a bounded delta may not tie the adjudicator (crafted base: codex 8.95).
    policy = _policy_copy(tmp_path)
    data = json.loads(policy.read_text())
    data["weights"]["codex"] = 8.95
    policy.write_text(json.dumps(data))
    r = _run(
        _proposal(tmp_path, changes=[{"domain": None, "family": "codex", "to": 9.0}]),
        policy, tmp_path / "log.md", "--confirm",
    )
    assert r.returncode != 0
    assert "adjudicator" in r.stderr


def test_refuses_research_basis_over_its_smaller_cap(tmp_path):
    _expect_refusal(
        tmp_path, "research per-cycle bound",
        basis="research",
        changes=[{"domain": None, "family": "gemini", "to": 8.1}],  # +0.1 > 0.05
    )


def test_refuses_retro_without_evidence_counts(tmp_path):
    _expect_refusal(tmp_path, "verified matches", evidence_counts={})
    _expect_refusal(
        tmp_path, "verified matches",
        evidence_counts={"verified_matches": 5, "ci_excludes_half": True},
    )
    _expect_refusal(
        tmp_path, "credible interval",
        evidence_counts={"verified_matches": 20, "ci_excludes_half": False},
    )


def test_refuses_unknown_family_and_domain(tmp_path):
    _expect_refusal(
        tmp_path, "unknown family",
        changes=[{"domain": None, "family": "grok", "to": 8.0}],
    )
    _expect_refusal(
        tmp_path, "unknown domain",
        changes=[{"domain": "security", "family": "codex", "to": 8.6}],
    )


def test_refuses_auto_without_fg_and_hold(tmp_path):
    # The auto path is predicate-gated from day one: with no fg_approval for
    # organ trio_weights in the ledger, --auto refuses even a valid proposal.
    policy = _policy_copy(tmp_path)
    r = _run(_proposal(tmp_path), policy, tmp_path / "log.md", "--confirm", "--auto")
    assert r.returncode != 0
    assert "fg_approval" in r.stderr or "HOLD" in r.stderr


def test_domain_change_applies_to_that_table_only(tmp_path):
    policy = _policy_copy(tmp_path)
    r = _run(
        _proposal(tmp_path, changes=[{"domain": "ui", "family": "codex", "to": 7.6}]),
        policy, tmp_path / "log.md", "--confirm",
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(policy.read_text())
    assert data["domains"]["ui"]["weights"]["codex"]["value"] == 7.6
    assert data["weights"]["codex"] == 8.5  # flat table untouched
    assert data["domains"]["general"]["weights"]["codex"] == 8.5


def test_weight_sources_schema_and_caps_agree_with_applier():
    # T4: the external-stream source list is tier3 + gate protected; its
    # research cap must match the applier's enforced bound, and every source
    # tier must exist in the reliability table.
    src = json.loads((REPO / "adjudicator" / "weight_sources.json").read_text())
    tiers = src["reliability_tiers"]
    assert tiers["official"] == 1.0 and tiers["social"] == 0.2
    for s in src["sources"]:
        assert s["tier"] in tiers, s
    rules = src["rules"]
    assert rules["reliability_by_fetched_domain_only"] is True
    assert rules["social_never_sole_basis"] is True
    apply_src = APPLY.read_text()
    assert f"MAX_DELTA_RESEARCH = {rules['research_delta_cap']}" in apply_src, (
        "weight_sources.json research_delta_cap must match the applier's enforced bound"
    )



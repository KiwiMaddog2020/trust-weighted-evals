# Trust Weighted Evals

This repo is the public companion extract for the write-up "An evaluation framework you can trust" ([WRITE-UP LINK]). It shows a small evaluation loop where independent raters score work, an adjudicator combines confidence with engine trust, and the protocol treats disagreement, safety floors, and honest failure as part of the output.

## Components

- `adjudicator/`: a roughly 510-line trust-weighted adjudicator that combines findings by engine family, confidence, and sensitivity. Authority is declared, not derived: who may author sensitive work and who adjudicates are explicit config lists, never computed from the tunable weights, and both readers clamp weight edits that would cross a safety boundary. (That guard rail exists because a cross-model review of this very code found the boundary leak; the fix and its tests shipped the same day.)
  Run: `python3 -m pytest tests/test_trio_adjudicate.py`

- `adjudicator/trio_weight_apply.py`: the sole writer of trust-weight changes, with its refusal set (one bounded change per cycle, no safety-boundary crossings, no adjudicator ties, evidence-count gates) and a provenance changelog. Weights are priors with an evidence trail, and the file that lists who may author sensitive work is declared config the learner can never reach. `adjudicator/weight_sources.json` is the firewalled source list for the weekly research pass.
  Run: `python3 -m pytest tests/test_trio_weight_apply.py`

- `pipeline/`: the generalized N-rater state and report pipeline, with 27 tests including the fail-closed regression and the score-validation fixes from the cross-lineage review (scores must be finite floats in range; `inf` used to converge).
  Run: `python3 -m pytest tests/test_peer_audit_pipeline.py`

- `protocol/`: two protocol docs, `protocol/SKILL.md` and `protocol/LOOP_CONTRACT.md`, guarded by a 30-test static oracle.
  Run: `python3 -m pytest tests/test_forge_skill.py`

- `hooks/`: a 27-case privacy-gate harness for public-flip checks.
  Run: `bash hooks/test-pre-commit.sh`

## Principles

- The doer never rates its own work.
- Trust is a number in a data file.
- Disagreement is the product.
- The bar lives outside the doer's reach.
- Permission to fail honestly.

## What This Is Not

This is an extract of one operator's personal system, not enterprise infrastructure. The engine dispatch tooling is not included: spawn scripts, maestro decision buffering, halt fences, and live runtime question tools are referenced by the protocol because they matter to the architecture, but they are not shipped here.

Two tests from the source repo's protocol oracle are intentionally dropped because they assert environment facts that do not ship: one checks the dispatch drivers exist on disk, the other checks the skill's registration in the source repo's plugin registry. Everything else runs verbatim.

Author: Kevin Madson

Write-up: "An evaluation framework you can trust" ([WRITE-UP LINK])

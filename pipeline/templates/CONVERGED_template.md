# Converged Peer-Audit — {{SUBJECT}}

_Generated {{DATE}} by the peer-audit pipeline (`pipeline/`)._

**Subject:** {{SUBJECT}}
**Mode:** {{MODE}}
**Slug:** `{{SLUG}}`
**Target dir:** `{{TARGET_DIR}}`
**Total passes:** {{TOTAL_PASSES}}
**Convergence status:** {{STATUS_BADGE}}

---

## Final verdict

{{FINAL_VERDICT_BLOCK}}

## Each rater's last verdict

| Rater | Verdict | Craft | Fit |
| ----- | ------- | ----: | --: |

{{RATERS_VERDICT_TABLE}}

**Co-signature:** {{CO_SIGNATURE}}

---

## Patch trail across all passes

| Pass | {{HISTORY_RATER_HEADERS}} New findings | Patches applied |
|---:|{{HISTORY_RATER_ALIGN}}---:|---:|
{{FULL_HISTORY_TABLE}}

## Convergence math

User-set target evaluated on the last pass (craft ≥ {{TARGET_CRAFT}}, fit ≥ {{TARGET_FIT}}):

| Criterion | Required | Actual | Met? |
| --------- | -------- | ------ | ---- |

{{CONVERGENCE_CRITERIA_TABLE}}

{{PLATEAU_EXPLANATION}}

---

## Per-pass artifacts

| Pass | {{ARTIFACT_RATER_HEADERS}} |
|---:|{{ARTIFACT_RATER_ALIGN}}|
{{PER_PASS_FILE_TABLE}}

## State file

Full machine-readable history at `{{TARGET_DIR}}/.peer-audit-{{SLUG}}.json`.

---

## Recommended next action

{{NEXT_ACTION_BLOCK}}

---

## Notes

- This report is a _recommendation_, not a binding outcome. Both raters can converge on a flawed answer; treat CONVERGED as "two independent reviews ran out of disagreements" rather than "guaranteed correct."
- Re-running the audit with a different rater or different scope is always available — invoke the skill with a fresh target dir.
- The state file persists; future sessions can resume or fork the audit by reading it.

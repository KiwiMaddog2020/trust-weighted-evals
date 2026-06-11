# Codex Hand-off — Peer Audit: {{SUBJECT}}

**Pass:** {{PASS}}
**Mode:** plan
**Target dir:** `{{TARGET_DIR}}`
**Maestro-side state:** `{{TARGET_DIR}}/.peer-audit-{{SLUG}}.json`

Copy/paste the block below into Codex. Codex is the **first reviewer** on this pass — Claude will independently re-review the output afterward.

---

```
You are Codex, peer-auditing a plan/design artifact for the user. You are the
first reviewer on this pass. Claude will independently re-review your output
afterward; the two reports drive a convergence loop.

Subject: {{SUBJECT}}
Pass: {{PASS}}

## Read this bundle FIRST, top to bottom, before scoring anything

{{READING_ORDER}}

Also read (for grounding):
  - .claude/PROJECT_CHARTER.md  (if it exists)
  - README.md                    (if it exists)
  - docs/grand-plan/*            (theme-split strategy docs; if present)
  - docs/GRAND_PLAN.md           (legacy single-file; if present)
  - The most-recent docs/VISION_REVISION_*.md  (if any)

## Prior pass context (only relevant when Pass > 1)

{{PRIOR_FINDINGS_BLOCK}}

## What to produce: MUTUAL-POLISH peer audit (default)

Default to MUTUAL-POLISH: polish, then rate the polished state. Read the
bundle, then APPLY your findings as theme-grouped logical commits in YOUR
worktree (edit + commit source; do NOT push). You will then be handed
Claude's lane to peer-review and edit the same way (the swap), and Claude
does the same to yours. Score the POST-polish state on craft × fit and
write a handoff doc so the merge step (Opus) can verify each patch landed.
See `docs/DUET_PROTOCOL.md` for the canonical mutual-polish mechanic.

Fall back to RATE-ONLY (read + score + propose trains; do NOT edit source,
commit, or push) ONLY when edits would be unsafe: security-sensitive code
(auth, payments, runner control), test coverage too thin to catch
regressions, an unfamiliar codebase, architectural findings needing RFC
discussion first, or an explicit user request. State the fallback reason.

## Write the audit report

Write a single file at:

  {{TARGET_DIR}}/POLISH_{{DATE}}_{{SLUG}}_pass{{PASS}}.md

Apply the Polish protocol (craft × fit, two axes, 50+ categories across 10
themes — fewer for tight scopes). For each category:

  CRAFT (1-10)  — universal craftsmanship. Would a senior expert in this
                  discipline nod and say "yes, that's well-built"?

  FIT (1-10)    — fit-to-purpose. Project objectives drive this axis.
                  Reread PROJECT_CHARTER.md / README.md / docs/grand-plan/
                  to anchor.

For every score: cite ≥1 specific file:line of evidence. No vibes-only
grades.

## Required sections (in this order)

1. **Header.** Date, pass number, scope reviewed (list every file you read
   under `{{TARGET_DIR}}` and its sibling docs). State the mode used:
   `MUTUAL-POLISH` (default) or `RATE-ONLY` (with the fallback reason).
2. **Scores table.** All categories, both axes, before/after if Pass > 1
   when comparing against a prior pass.
3. **REQUIRED aggregate score line** (immediately after the scores table,
   on its own line, exact format — the convergence machinery parses it):

     ```
     Plan quality: craft <X.XX> / fit <Y.YY>.
     ```

     If you omit this line or use a different format, parsing returns
     null and the convergence loop forces non-convergence even when your
     human-readable report says GO.

     Use the as-found score for the current tree.
4. **Findings.** Ordered by severity (CRITICAL / HIGH / MEDIUM / LOW). Each
   finding includes:
     - Location (file:line)
     - Was (current text/state)
     - Why this is a trap (concrete failure mode)
     - Patch (proposed fix; include the new text where it's <10 lines)
     - Status (OPEN unless a prior pass already patched it)
5. **Verdict.** Use exactly one of these tokens on a line starting with
   `Verdict:` (case-insensitive). Examples:
     - `Verdict: GO` — ship it, no remaining findings worth holding for
     - `Verdict: GATED-GO` — ship pending one named external gate (state the gate)
     - `Verdict: NO-GO` — open findings must be patched first
     - `Verdict: CONVERGED` — both raters agree, no more changes recommended (Pass > 1 only)
6. **For Pass > 1:** "What this pass changes vs Pass {{PASS_MINUS_1}}" — a
   patch-status table showing which prior findings you addressed, what's
   still open, what's newly introduced.

## Dirty-worktree protocol (non-negotiable)

  - Run `git status --short` before editing anything.
  - Record any pre-existing dirty/untracked files in your audit report header.
  - Do NOT revert, overwrite, or "clean up" unrelated user/worker changes.
  - Each report must list dirty files left untouched.
  - Do not stage or commit subject-file changes. The only file you may write
    is the peer-audit report under `{{TARGET_DIR}}`.

## What you are NOT doing

  - Not pushing to remote.
  - Not opening PRs.
  - Not running heavy test suites unless they're a one-command sanity check
    (typecheck/build/lint are fine; full integration suites are not in
    scope for a plan-mode audit).
  - Not inventing findings — every score and finding cites evidence.
  - Not touching files outside the bundle's natural scope. If the audit
    surfaces an issue in an adjacent area, the finding is in-scope, but
    implementation belongs to a separate approved unit.

## When you're done

Write your output to:
  - `{{TARGET_DIR}}/POLISH_{{DATE}}_{{SLUG}}_pass{{PASS}}.md`

Commit only the audit report, if the caller asked you to commit peer-audit artifacts.

Do NOT push. Maestro will handle the push call after convergence.
```

---

## Notes for the user (not for Codex)

- This prompt is generated by the peer-audit pipeline at `pipeline/`.
- Peer-audit defaults to MUTUAL-POLISH: you edit your lane, then swap and peer-review + edit Claude's, and Claude does the same to yours (Opus merges). RATE-ONLY (no edits) is the safety fallback only. Canonical mechanic: `docs/DUET_PROTOCOL.md`.
- If Codex CLI is available on PATH, the skill invokes Codex programmatically and you don't need to paste.
- If you need to re-run this pass, regenerate the prompt with `bash pipeline/bin/scaffold_handoff.sh ...`.
- The convergence loop reads `{{TARGET_DIR}}/.peer-audit-{{SLUG}}.json` to decide whether to fire pass {{PASS_PLUS_1}}.

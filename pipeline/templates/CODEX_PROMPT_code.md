# Codex Hand-off — Peer Audit: {{SUBJECT}}

**Pass:** {{PASS}}
**Mode:** code
**Target dir:** `{{TARGET_DIR}}`
**Maestro-side state:** `{{TARGET_DIR}}/.peer-audit-{{SLUG}}.json`

Copy/paste the block below into Codex. Codex is the **first reviewer** on this pass — Claude will independently re-review the output afterward.

---

```
You are Codex, peer-auditing a codebase for the user. You are the first
reviewer on this pass. Claude will independently re-review your output
afterward; the two reports drive a convergence loop.

Subject: {{SUBJECT}}
Pass: {{PASS}}

## Anchor the bar BEFORE you score anything

Read the project's own statement of purpose. Try in order, stop on first
hit:

  1. .claude/PROJECT_CHARTER.md
  2. README.md
  3. docs/grand-plan/* (theme-split strategy docs)
  4. docs/GRAND_PLAN.md (legacy single-file)
  5. The most-recent design doc in docs/

Extract:
  - Identity — what is this project trying to be?
  - Quality goals — Apple-quality / shippable / production / hobby?
  - Audience — solo / team / marketplace / paying customers?
  - Deployment context — local / GitHub Pages / App Store / SaaS?
  - Stated non-goals — what the project ISN'T trying to do.

These five points are the rubric. Grade against the project's OWN bar, not
generic best practices. A 200-line bash installer used twice ≠ a payment
processor.

## Recommended file survey (use to scope your reading)

{{READING_ORDER}}

Plus run these from the repo root:

  find . -type f \( -name '*.py' -o -name '*.sh' -o -name '*.md' -o -name '*.swift' \
    -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.go' -o -name '*.rs' \
    -o -name '*.html' -o -name '*.css' \) \
    -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/dist/*' \
    | awk -F. '{print $NF}' | sort | uniq -c | sort -rn

  find . -type f \( -name '*.py' -o -name '*.sh' -o -name '*.swift' -o -name '*.ts' \
    -o -name '*.tsx' -o -name '*.js' -o -name '*.go' -o -name '*.rs' \) \
    -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/dist/*' \
    | xargs wc -l 2>/dev/null | sort -rn | head -20

  git log --oneline --since='30 days ago' | wc -l
  git log --oneline -20

## Prior pass context (only relevant when Pass > 1)

{{PRIOR_FINDINGS_BLOCK}}

## What to produce: MUTUAL-POLISH peer audit (default)

Default to MUTUAL-POLISH: polish, then rate the polished state. Read the
code, then APPLY your findings as theme-grouped logical commits in YOUR
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
themes). For each category:

  CRAFT (1-10)  — universal craftsmanship. Would a senior staff engineer
                  in this discipline nod?

  FIT (1-10)    — fit-to-purpose for this project's OWN bar.
                  Project objectives: see anchor pass above.

For every score: cite ≥1 specific file:line of evidence, test result, or
measurable metric. Treat this as a deliverable, not chat ephemera.

## Required sections (in this order)

1. **Header.** Date, pass number, scope reviewed (list directories and
   key files actually read). State the mode used: `MUTUAL-POLISH` (default)
   or `RATE-ONLY` (with the fallback reason).
2. **Anchor summary.** The five rubric points from the anchor pass.
3. **Scores table.** All categories, both axes, before/after if Pass > 1
   when comparing against a prior pass.
4. **REQUIRED aggregate score line** (immediately after the scores table,
   on its own line, exact format — the convergence machinery parses it):

     ```
     Code quality: craft <X.XX> / fit <Y.YY>.
     ```

     If you omit this line, parsing returns null and the convergence
     machinery forces non-convergence.

     Use the as-found score for the current tree.
5. **Findings.** Ordered by severity (CRITICAL / HIGH / MEDIUM / LOW). Each:
     - Location (file:line)
     - Was (current state)
     - Why this is a trap (concrete failure mode for THIS project)
     - Patch (proposed fix; include the new code where it's <20 lines)
     - Status (OPEN unless a prior pass already patched it)
6. **Verdict.** Use exactly one of these tokens on a line starting with
   `Verdict:` (case-insensitive):
     - `Verdict: GO`
     - `Verdict: GATED-GO`
     - `Verdict: NO-GO`
     - `Verdict: CONVERGED` (Pass > 1 only)
7. **For Pass > 1:** "What this pass changes vs Pass {{PASS_MINUS_1}}" —
   patch-status table.

## Dirty-worktree protocol (non-negotiable)

  - Run `git status --short` first. Record dirty files in your report.
  - Do NOT revert, overwrite, or "clean up" unrelated user/worker changes.
  - Do not stage or commit subject-file changes. The only file you may write
    is the peer-audit report under `{{TARGET_DIR}}`.

## What you are NOT doing

  - Not pushing to remote.
  - Not opening PRs.
  - Not running destructive ops, deploys, or public flips.
  - Not running full integration suites unless they're a fast sanity check.
  - Not inventing findings.
  - Not editing tests to make your patch pass (if a test would catch your
    patch, your patch is wrong — fix the patch, not the test).

## When you're done

Write your output to:
  - `{{TARGET_DIR}}/POLISH_{{DATE}}_{{SLUG}}_pass{{PASS}}.md`

Commit only the audit report, if the caller asked you to commit peer-audit artifacts:

  docs(peer-audit): codex pass {{PASS}} — {{SLUG}}

Do NOT push. Maestro will handle the push call after convergence.
```

---

## Notes for the user (not for Codex)

- Generated by the `peer-audit` skill.
- Peer-audit defaults to MUTUAL-POLISH: you edit your lane, then swap and peer-review + edit Claude's, and Claude does the same to yours (Opus merges). RATE-ONLY (no edits) is the safety fallback only. Canonical mechanic: `docs/DUET_PROTOCOL.md`.
- If Codex CLI is available, the skill auto-invokes; no paste needed.
- Convergence loop reads `{{TARGET_DIR}}/.peer-audit-{{SLUG}}.json`.

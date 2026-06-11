#!/usr/bin/env python3
"""parse_polish_output.py — extract scores, verdict, finding accounting, and
the open-findings list from a POLISH_*.md or POLISH_*_claude-peer-review.md
report.

Usage:
    python3 parse_polish_output.py <path>

Stdout: JSON object with keys:
    craft, fit                       — aggregate scores (None if absent)
    verdict                          — GO|GATED-GO|NO-GO|CONVERGED|PLATEAU|DID-NOT-CONVERGE
    findings_count                   — total severity-marker count (legacy/diagnostic)
    new_findings                     — canonical "New findings this pass: N" (None if absent)
    open_findings_count              — canonical "Open findings after this pass: N" (None if absent)
    open_findings                    — list of {severity, location, summary, intro_pass, intro_by}

Exit: 0 on success (even with missing fields), 1 only on missing file.

Score-extraction order (first hit wins):
    1. `<Plan|Code> quality: craft X / fit Y.` aggregate line (required by Train 5 templates)
    2. Markdown table row whose first cell matches "weighted average" or
       "aggregate" with two numeric cells (table fallback)
    3. Last-match prose `craft N / fit M` (legacy heuristic)

Verdict extraction prefers lines starting with `Verdict:` (Train 5 contract).
Falls back to any GO|GATED-GO|NO-GO|CONVERGED token if no labeled line found.
"""

import json
import re
import sys
from pathlib import Path


# Aggregate score line — REQUIRED by Train 5 templates.
AGGREGATE_RE = re.compile(
    r"(?:plan|code)\s+quality\s*[:\-]\s*craft\s+(\d+(?:\.\d+)?)\s*[/·\-—]\s*fit\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Markdown table fallback — first cell matches weighted-average / aggregate,
# followed by exactly two numeric cells. No intermediate cells allowed.
TABLE_AGG_RE = re.compile(
    r"^\|\s*(?:weighted\s+average|aggregate)\s*\|\s*(\d+(?:\.\d+)?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|",
    re.IGNORECASE | re.MULTILINE,
)

# Legacy prose patterns — keep for backward compat with pre-Train-5 reports.
LEGACY_SCORE_PATTERNS = [
    re.compile(r"craft\s+(\d+(?:\.\d+)?)\s*[/·\-—]\s*fit\s+(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"craft\s*[:=]\s*(\d+(?:\.\d+)?)[,\s]+fit\s*[:=]\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
]

# Verdict — prefer Train 5 contract (line starts with "Verdict:")
VERDICT_LABELED_RE = re.compile(
    r"^[^\w]*verdict[^\w]*[:\-]\s*[`*_\s]*(GATED-GO|DID-NOT-CONVERGE|NO-GO|CONVERGED|PLATEAU|GO)\b",
    re.IGNORECASE | re.MULTILINE,
)
VERDICT_FALLBACK_RE = re.compile(
    r"\b(GATED-GO|DID-NOT-CONVERGE|NO-GO|CONVERGED|PLATEAU|GO)\b"
)

# Canonical scalars (Train 5).
NEW_FINDINGS_RE = re.compile(r"new\s+findings\s+this\s+pass[:\s]+(\d+)", re.IGNORECASE)
OPEN_FINDINGS_RE = re.compile(r"open\s+findings\s+after\s+this\s+pass[:\s]+(\d+)", re.IGNORECASE)

# Open-findings block: lines like
#   - SEVERITY | LOCATION | SUMMARY | INTRO_PASS | INTRO_BY
OPEN_FINDING_LINE_RE = re.compile(
    r"^\s*-\s*(CRITICAL|HIGH|MEDIUM|LOW)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(codex|claude)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Legacy severity counter (diagnostic only — Train 5 uses canonical scalar instead).
SEVERITY_RE = re.compile(
    r"^\s*(?:#{1,4}\s+)?(?:\d+\.\s*)?(?:[⚠️🟥🟧🟨🟩]\s*)?(CRITICAL|HIGH|MEDIUM|LOW)\b",
    re.MULTILINE,
)


def extract_scores(text: str) -> tuple[float | None, float | None]:
    """Return (craft, fit). Tries aggregate line → table → legacy prose."""
    m = AGGREGATE_RE.search(text)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    m = TABLE_AGG_RE.search(text)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    # Legacy fallback: LAST matching prose pattern.
    last = None
    for pat in LEGACY_SCORE_PATTERNS:
        for m in pat.finditer(text):
            try:
                last = (float(m.group(1)), float(m.group(2)))
            except ValueError:
                continue
    return last if last else (None, None)


def extract_verdict(text: str) -> str | None:
    """Prefer Verdict-labeled line; fall back to last token anywhere."""
    m = VERDICT_LABELED_RE.search(text)
    if m:
        return m.group(1).upper()
    matches = VERDICT_FALLBACK_RE.findall(text)
    if matches:
        return matches[-1].upper()
    return None


def _extract_section(text: str, header_pattern: str) -> str:
    """Return the substring from a `## <header>` line to the next `## ` or end.

    Train 6 fix (Codex Pass 2 HIGH #2): canonical-scalar and open-findings
    parsing must be scoped to their declared sections. Prose elsewhere
    (especially patch-example code-fences in finding bodies) can contain
    the exact label strings and silently corrupt the parsed counts. This
    helper isolates one section so .search()/.finditer() can't escape.
    """
    section_re = re.compile(
        rf"^##\s+{header_pattern}.*?(?=^##\s|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    m = section_re.search(text)
    return m.group(0) if m else ""


def extract_new_findings_count(text: str) -> int | None:
    """Parse 'New findings this pass: N' from the Canonical-accounting section only."""
    section = _extract_section(text, r"canonical\s+accounting")
    if not section:
        return None
    m = NEW_FINDINGS_RE.search(section)
    return int(m.group(1)) if m else None


def extract_open_findings_count(text: str) -> int | None:
    """Parse 'Open findings after this pass: N' from the Canonical-accounting section only."""
    section = _extract_section(text, r"canonical\s+accounting")
    if not section:
        return None
    m = OPEN_FINDINGS_RE.search(section)
    return int(m.group(1)) if m else None


def extract_open_findings(text: str) -> list[dict]:
    """Parse the open-findings block from the '## Open findings after this pass' section only."""
    section = _extract_section(text, r"open\s+findings\s+after\s+this\s+pass")
    if not section:
        return []
    findings = []
    for m in OPEN_FINDING_LINE_RE.finditer(section):
        findings.append({
            "severity": m.group(1).upper(),
            "location": m.group(2).strip(),
            "summary": m.group(3).strip(),
            "introduced_on_pass": int(m.group(4)),
            "introduced_by": m.group(5).lower(),
        })
    return findings


def count_severity_markers(text: str) -> int:
    return len(SEVERITY_RE.findall(text))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: parse_polish_output.py <path-to-POLISH_*.md>", file=sys.stderr)
        return 1

    path = Path(argv[1])
    if not path.is_file():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    craft, fit = extract_scores(text)
    verdict = extract_verdict(text)
    new_findings = extract_new_findings_count(text)
    open_findings_count = extract_open_findings_count(text)
    open_findings = extract_open_findings(text)
    severity_marker_total = count_severity_markers(text)

    result = {
        "path": str(path),
        "craft": craft,
        "fit": fit,
        "verdict": verdict,
        "findings_count": severity_marker_total,
        "new_findings": new_findings,
        "open_findings_count": open_findings_count,
        "open_findings": open_findings,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

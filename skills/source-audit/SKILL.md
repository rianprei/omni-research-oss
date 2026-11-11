---
name: source-audit
description: Use when asked to fact-check claims, challenge research, find contradictions, inspect citations or validate the reliability of a report.
---

# Source and citation audit

Treat a statement as an atomic claim with exact predicates, dates, units, population and exceptions. Identify original publisher, date of event, date of publication, corrections, and circular citations. Prefer authoritative primary sources and replicate calculations where possible.

For each factual claim, identify the direct supporting URL/DOI and locate the relevant passage in the full document. Use `fetch_source`, `citation_lookup` and `compare_evidence` if available. Never treat substring/numeric overlap returned by `compare_evidence` as proof.

Audit categories: SUPPORTED (directly substantiated), CONTRADICTED (same scope and time), MIXED (legitimate conflicting findings), UNVERIFIABLE (source not obtainable), UNSUPPORTED (no adequate direct evidence), OUTDATED (replaced or superseded). Explicitly separate missing evidence from factual falsity.

Output a compact table: Claim | status | primary evidence | counterevidence | caveats | recommended correction. Quote only brief relevant spans and link directly to sources. Identify suspected fabrication, altered citations, circular sourcing and failure to distinguish event date from reporting date. Never manufacture confidence percentages.

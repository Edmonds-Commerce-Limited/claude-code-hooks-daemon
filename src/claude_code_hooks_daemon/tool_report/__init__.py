"""Tools-vs-tokens usage report (Plan 00293).

Scans a project's Claude Code session transcripts for per-tool invocation
counts, pairs them with measured schema token costs, and produces a
recommendation report (``bin/hooks-daemon tool-report``). The report only ever
RECOMMENDS — nothing is disabled automatically; projects decide.

Privacy contract: only tool NAMES and COUNTS leave the transcript scan.
Transcript content is never copied into any output.
"""

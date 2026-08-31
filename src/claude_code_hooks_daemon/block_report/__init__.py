"""Transcript-scanning block-frequency analyser (Plan 00116 Phase 2b).

Mirrors ``tool_report/``'s streaming-transcript pattern to answer a
different question: which BLOCKING handlers fire often enough in this
project's real history (``bin/hooks-daemon block-report``) to warrant
keeping their full guidance resident in the injected ``<hooksdaemon>``
block (Decision I,
``CLAUDE/Plan/00116-claude-md-token-compression/DESIGN-HYBRID-PROMOTION.md``).

Privacy contract: only handler NAMES and COUNTS leave the transcript scan.
Command text and file contents are never copied into any output.
"""

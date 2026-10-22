"""Skill-opportunity detection pipeline (Plan 00274).

Mines Claude Code session transcripts for repeated workloads and recurring
points of confusion, and files a human-reviewed report of skill-creation
suggestions. Three stages: deterministic extraction, deterministic
condense/redact aggregation, one bounded model call. Never auto-creates a
skill.

This package init deliberately imports nothing. ``utils.session_modes`` imports
the light ``constants`` / ``extraction`` submodules and sits on
``daemon/paths.py``'s import chain (via ``core.data_layer``), which must load
on a pre-3.11 interpreter. Re-exporting
``pipeline`` here would pull ``digest`` -> ``mdformat`` -> ``tomllib`` into that
chain. Import from the submodules directly.
"""

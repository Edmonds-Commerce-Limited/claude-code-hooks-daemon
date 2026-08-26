# Plan 00274 prototype — skill-scan pipeline

Throwaway research code, NOT daemon integration. `skill_scan.py` runs the full
BRAINSTORM.md pipeline: deterministic extraction of genuine human prompts from
`~/.claude/projects/-workspace/*.jsonl` (field filters then content-marker
filters), normalise + greedy Jaccard clustering, secret-list redaction via the
daemon's `utils/secret_redaction`, one bounded headless `claude -p --model haiku`
call, and a dated skill-opportunities report under `untracked/reports/`.
Run with the daemon venv python:
`PYTHONPATH=/workspace/src <venv-python> skill_scan.py [--dry-run] [--window-days N] [--transcript-dir DIR]`.
Tests: `PYTHONPATH=/workspace/src:. <venv-python> -m pytest test_skill_scan.py`.
Findings feed Phases 1-3 of PLAN.md; the real implementation will be rebuilt
with full TDD inside `src/`.

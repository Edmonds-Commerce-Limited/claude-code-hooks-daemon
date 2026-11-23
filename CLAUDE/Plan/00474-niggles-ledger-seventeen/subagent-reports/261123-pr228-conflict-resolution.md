# PR 228 conflict resolution (N709)

Merged origin/main (d59ec23d4 and later) into fix-n709-secret-guard-bootstrap with a merge commit.

- Only conflict: CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md. Kept the branch's N709 root-cause/residual/status text (replacing main's old "Open" status line) and main's new N710-N713 entries.
- config-changes/v3.77.0.yaml merged cleanly: both #225's entries and #228's are present.
- Release note stays 088 (main's highest is 087-human-approval-check.md); no collision.
- secret_file_matching.py: no conflict, nothing else landed there that this merge touched.
- Targeted tests (416 passed): test_secret_file_guard_link_loop.py, tests/integration/test_config_changes_manifest_examples.py, tests/integration/test_pending_release_notes_holding_area.py. Run with PYTHONPATH set to the worktree src, because the worktree has no venv of its own (source_tree_guard refuses main's editable install).
- CI needs one full pass on the merged head.

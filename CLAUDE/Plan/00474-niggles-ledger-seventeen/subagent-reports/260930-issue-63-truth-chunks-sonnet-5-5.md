# Issue #63: truth-changes chunks scan daemon-owned docs; template asserts a superseded fact

Both claims in the triage were re-verified against main before changing anything.

## Changes

1. `src/claude_code_hooks_daemon/install/templates/core/PlanWorkflow.core.md`: journal categories now list `correction` (with the `--ref` requirement the v3.67.0 NOW text states); the failsafe-cron paragraph names `failsafe_cron_session_advisor` (SessionStart). `CLAUDE/core/PlanWorkflow.core.md` (this repo's deployed copy) was byte-identical to the template and is again.
2. `truth_changes.py`: `_RULES_INSTRUCTION` now forbids editing the daemon-owned docs. Paths are built from `core_docs.CORE_DOCS_DIR` + `CORE_SUFFIX` and `upgrade_gate.HOOKS_DAEMON_DOC`, not a second hard-coded copy. The `<hooksdaemon>` tag is prose in the rule: its constant is private to `core/claude_md_injector.py`, and I did not import a private name across packages. `_CHUNKS_HEADING` no longer claims disjoint documents (it cannot hold when every chunk scans the tree); it tells a subagent to re-read a file just before editing.
3. Guard: `tests/unit/install/test_truth_changes_template_guard.py`. `was` is prose (folded YAML, paraphrased, never a substring of a template: the six-category `was` is not literally in the template), so a verbatim `was` match would never fire. Chosen alternative: an optional per-entry `stale_phrases` list (exact phrases the old truth had in shipped text, whitespace-normalised). The test fails while any is in any shipped template. `journal-correction-entry` in v3.67.0.yaml declares one, and a test pins that it does. Also a parity test: every category in `mkplan.bash` `JOURNAL_CATEGORIES` must appear in the core doc. Schema documented in `CLAUDE/UPGRADES/truth-changes/README.md`.
4. Release note `183-...` under UNRELEASED/release-notes. No new truth-changes entry: the category claim is already covered by `journal-correction-entry`, and the rule wording is agent guidance, not a doc statement clients repeat.

## Red output (before implementation)

15 failed, 76 passed. Representative:

- `AttributeError: 'TruthChange' object has no attribute 'stale_phrases'`
- `assert 'CLAUDE/core/*.core.md' in "Truth-Changes chunk [plan-workflow]: v3...`
- `assert 'disjoint' not in "Chunks — di...her chunk's:"`
- `test_every_mkplan_category_is_listed_in_the_core_doc: AssertionError: assert ['correction'] == []` (the real template drift)

## Green

After implementation: `test_truth_changes.py`, `test_truth_changes_template_guard.py`, `test_core_doc_deployment.py`, `test_plan_journalling_doc_parity.py`, `test_unreleased_manifests.py`, `tests/unit/daemon/test_cli_check_truth_changes.py`: 150 passed.

## Caveats

- `stale_phrases` is opt-in per entry, so it only guards entries whose author names a phrase. Only the one known entry was back-filled; older manifests were not audited for template assertions.
- I added the field to the already-released v3.67.0 manifest; the loader ignores it for the agent report.
- The exclusion is static text using the default docs dir (`CLAUDE/`); a project with a different configured docs dir is not covered, since the report renderer has no config in hand.

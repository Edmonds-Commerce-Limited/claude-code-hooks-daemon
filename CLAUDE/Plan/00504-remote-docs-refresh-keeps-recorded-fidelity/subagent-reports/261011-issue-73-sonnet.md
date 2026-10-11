# Issue 73 report (Plan 00504, Tasks 1.1-1.3)

## Verified defect

`_remote_docs_refresh` in `daemon/cli.py` took one fetcher resolved once from `--verbatim` and used it for all targets; `refresh_document` records the passed fidelity, so a mixed corpus was rewritten wrongly. Confirmed in code, not taken from the issue.

## Change

- `daemon/cli.py`: `refresh` no longer receives a pre-resolved fetcher. It reads each target's provenance, uses verbatim when `--verbatim` is given or the recorded fidelity is `verbatim`, otherwise the default fetcher. One resolution (and one fallback warning) per mode, cached. `_resolve_remote_docs_fetcher` gained a `verbatim` override; `add` is unchanged. `--verbatim` help documents the refresh semantics.
- Missing or unreadable fidelity: falls back to what the command line asks for (default fetcher without the flag), which is today's behaviour; `refresh_document` already returns UNREADABLE with no fetch or write. Stated in the test docstring and RemoteDocs.md.
- Tests: `TestRefreshKeepsRecordedFidelity` in `tests/unit/remote_docs/test_cli_remote_docs.py`, using a fake `resolve_fetcher` (no network). RED was 3 failures before the change.
- Docs: `CLAUDE/RemoteDocs.md`; release note `026-remote-docs-refresh-keeps-each-documents-recorded-fidelity.md` (Callout shape).
- PLAN.md Tasks 1.1-1.3 ticked.

## QA

pytest `tests/unit/remote_docs` plus the release-notes holding-area test: 312 passed. black and mypy clean on cli.py. `llm_qa.py changed --base main --allow-unmapped`: 36/40 passed. The two failures are advisory-only findings in files this change does not touch: docs_qa `pointer-resolves` on `CLAUDE/Security/FailOpenBoundaries.md` (moved Plan 00488 link) and plan_qa `journal-freshness` on plan 00495. Because those two detectors failed, project_handlers and changed_tests (119 passed, 0 failed) are marked NOT MEANINGFUL by the runner. cli.py is reported unmapped (too broad), allowed by the flag. pyright passed but was not recorded for this tree (the tree changed during its run).

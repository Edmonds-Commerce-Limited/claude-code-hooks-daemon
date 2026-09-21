# Callout: block-report now attributes denies from every ProjectContext-reading handler

**Plan**: 00430
**Audience**: operators

`hooks-daemon block-report` now initialises `ProjectContext` before scanning
transcripts, the same way `explain-rule`, `explain-handler`,
`status-line --explain`, `session-actions` and `routine-qa` already do.
Previously it never did, so the five handlers whose constructors read
`ProjectContext.project_root()` (`validate_eslint_on_write`,
`markdown_organization`, `npm_command`, `plan_number_helper`,
`remote_docs_provenance`) could not be constructed during handler discovery
and were silently skipped: their rule IDs were missing from the attribution
index, so every deny they had produced was counted as unattributed instead
of attributed to its handler, and a `block-report` run on this repository's
own transcripts logged over two thousand `Failed to inspect handler`
tracebacks in the process. A project with no discoverable `hooks-daemon.yaml`
(or one `ProjectContext` cannot validate — not a git repository, no remote
`origin`) still produces a report exactly as before; only a project with a
working config sees attribution improve.

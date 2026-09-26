# Callout: skip lists now match whole path segments, relative to your project

**Plan**: 00458
**Audience**: client projects

Six guards (`qa_suppression`, `comment_changelog`, `comment_size`,
`british_english`, `security_antipattern` and TDD's common-test-directory
check) tested their vendor/build/venv skip lists with a bare substring
match against the absolute path. A directory that merely ENDED in a skipped
name — `myvenv/`, `rebuild/`, or a worktree you happened to name
`...-venv/` — silently disabled the guard for everything beneath it, with
no decision and no advisory you would ever see. Matching is now
segment-bounded (`venv/` no longer matches inside `myvenv/`) and resolved
against the path **relative to your project root**, so a project that
merely lives under a directory sharing a skip name (e.g. a checkout under
`~/venv/my-project/`) is no longer silently exempted either. If a
directory you renamed to end in one of these names was relying on the old
behaviour to go unchecked, you may see new blocks or advisories there —
that directory was never meant to be skipped; move it under a real
vendor/build directory, or configure `exclude_paths` for it explicitly.

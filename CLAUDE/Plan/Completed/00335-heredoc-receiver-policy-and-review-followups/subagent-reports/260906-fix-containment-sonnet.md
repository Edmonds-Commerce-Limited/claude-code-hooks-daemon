---
title: Fix project_containment I1 (relative destinations) and I2 (trailing-slash copy destination)
---

## Files changed

- `src/claude_code_hooks_daemon/core/utils.py` — `_resolve_write_target`, `_written_paths`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/project_containment.py` — `_named_targets`, new `_resolve_against_cwd`
- Tests: `tests/unit/core/test_bash_write_targets.py`, `tests/unit/handlers/pre_tool_use/test_project_containment.py`

## I1 — relative destinations never resolved

Added `ProjectContainmentHandler._resolve_against_cwd(target, cwd)`: returns
an absolute `target` unchanged, otherwise joins it against
`hook_input[HookInputField.CWD]` (falling back to the raw relative token when
no cwd is present, matching `_is_outside`'s existing "never-outside" treatment
of an unresolvable relative path). `_named_targets` now runs every
`_destination_targets(command)` result through this join before it reaches
`_offending_targets`/`_is_outside`. This mirrors, but does not reuse, the
cwd-join `get_bash_write_targets` already performs in `core/utils.py` —
`_resolve_write_target` there also declines shell-expansion-needing targets
and strips a directory-marking trailing slash, neither of which the
containment test needs (it only asks where a path resolves to).

## I2 — trailing slash makes a copy destination vanish

Root cause: `_resolve_write_target` declined **any** trailing-slash target
outright, before `_written_paths` ever got to call `is_dir()` — so
`cp a.py dest/` and `cp a.py dest` disagreed even when `dest` existed. Fixed
by stripping the trailing slash (after the unexpandable-char/`/dev/` checks,
which key on the token as written) instead of declining, and moving the
"declared to be a directory" test into `_written_paths` as
`candidate.directory_only or candidate.destination.endswith("/")` — checked
against the *raw* destination, so it still correctly declines (rather than
guesses) when the trailing-slash target is **not** actually a directory. This
is the same code path used by `-t`/`--target-directory`, `mkdir`, `tee`, and
plain redirects, so all four call sites (only `get_bash_write_targets`, used
by `project_containment` and `markdown_organization`) benefit uniformly.
Confirmed only `authored=True` (redirect/tee/heredoc) candidates reach content
guards via `get_written_file_paths`'s `authored_only=True` filter, and those
never carry `sources`, so this change cannot affect content-guard behaviour —
kept the fix in the shared function rather than duplicating it in the handler.

## Verification

Probe before → after (`probes/probe_containment.py`):

```
ALLOW curl -o ../../../tmp/x.sh         -> DENY  /repo/sub/../../../tmp/x.sh
ALLOW wget -O ../../../tmp/x.sh         -> DENY  /repo/sub/../../../tmp/x.sh
ALLOW mkdir -p ../../../tmp/newdir      -> DENY  /repo/sub/../../../tmp/newdir
ALLOW tar -cf ../../../tmp/a.tar src    -> DENY  /repo/sub/../../../tmp/a.tar
ALLOW rsync -a src/ ../../../tmp/dest/  -> DENY  /repo/sub/../../../tmp/dest
ALLOW cp README.md /tmp/                -> DENY  /tmp/README.md
```

Unaffected (as expected, out of scope): `cd /tmp && echo hi > out.txt` still
ALLOW (session-cwd tracking); triple-nested `sh -c` still yields `[]`
(depth-bounded).

Tests: added 3 to `test_bash_write_targets.py`, 6 to
`test_project_containment.py`. Full targeted run (both edited modules + their
existing test files + `test_written_file_paths`/`test_markdown_organization`/
`test_blocking_handler_evasion`, which also consume these accessors):
**539 passed**. Full `tests/unit` run: 1 pre-existing failure in
`test_audit_error_hiding.py` over `remote_docs/fetchers.py` — untouched by
this change, caused by a concurrent teammate's in-progress edit to that file
in this shared workspace.

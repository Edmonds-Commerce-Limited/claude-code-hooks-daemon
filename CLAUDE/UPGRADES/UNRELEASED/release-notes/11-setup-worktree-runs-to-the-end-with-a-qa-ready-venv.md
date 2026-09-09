# Callout: `setup_worktree.sh` runs to the end, and its venv can run QA

**Plan**: 00364
**Audience**: everyone

Two defects in `scripts/setup_worktree.sh`, both of which every worktree agent
had been working around by hand.

The script exited 1 silently right after "Venv created". Its editable-install
check ran `pip show` from the new venv inside a `$(...)` assignment under
`set -e`; a uv-managed venv ships no `pip`, so the assignment failed and the
script aborted before the steps that follow it, including the one that writes
`.claude/hooks-daemon.env`. The check now asks the interpreter where the
package imports from.

The venv it built could not run the test suite. `ensure_venv` builds the
runtime venv a client install needs, with no `dev` extra, so `import pytest`
failed in every fresh worktree. The script now syncs `--frozen --all-extras`
from `uv.lock` into that venv, as the main checkout's `venv-include.bash`
already did, and refuses to declare the worktree ready until `import pytest`
succeeds.

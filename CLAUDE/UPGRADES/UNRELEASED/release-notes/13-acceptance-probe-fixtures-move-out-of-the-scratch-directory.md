# Callout: acceptance probe fixtures move out of the scratch directory

**Plan**: 00422
**Audience**: handler authors

Acceptance probes now write their fixtures under `untracked/acceptance/`
instead of `untracked/scratch/`, the directory agents are told to use for
working notes. With both in one directory, an exclusion written for the
notes could silently switch a guard off for its own probes. The playbook
harness now refuses a probe's `setup_commands` or `cleanup_commands` that act
anywhere else, and so reports the probe as skipped. If you have project
handlers whose acceptance tests create fixtures under `untracked/scratch/`,
move them under `untracked/acceptance/` (a Python handler can use
`acceptance_path()` from `claude_code_hooks_daemon.utils.scratch_dir`).

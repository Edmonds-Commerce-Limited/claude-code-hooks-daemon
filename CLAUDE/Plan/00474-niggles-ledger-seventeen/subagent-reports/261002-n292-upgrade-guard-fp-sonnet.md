# N292: upgrade_approval_guard denied a plain interpreter run with PYTHONPATH

## Root cause

`src/claude_code_hooks_daemon/handlers/pre_tool_use/upgrade_approval_guard.py`:

- `_script_run_is_upgrade` (the `if not (path.is_absolute() and path_is_file(...))` branch, ~line 470): a relative script is joined to the HOOK's `cwd`. When the command itself begins `cd /workspace && ...`, the hook cwd is a different directory (here a worktree), so the script looks missing. A missing script is "cannot tell" (`_cannot_tell_script`), which returns True once `steered`.
- `steered` is set by `_STEERING_ASSIGN_RE`: `PYTHON*` matches `PYTHONPATH=`.
- `_segment_runs_upgrade` routes `$V/python script.py` to `_variable_program_is_upgrade` (N285), which ends in `_script_run_is_upgrade`.

Not the cause: by-name, `--skip-reading-confirmation`, script content, unreadable-with-upgrade-args. The probe script carries no marker.

## Reproduction and minimal shape

Judged through `UpgradeApprovalGuardHandler.matches`:

| command                                   | hook cwd                     | verdict before fix |
| ----------------------------------------- | ---------------------------- | ------------------ |
| the N292 command                          | `/workspace` (script exists) | allowed            |
| the N292 command                          | any other dir                | denied             |
| `PYTHONPATH=/w/src $V/python probe.py`    | dir without `probe.py`       | denied             |
| same, absolute path to an existing script | any                          | allowed            |
| `$V/python probe.py` (no steering)        | any                          | allowed            |

Minimal denied shape: steering assignment + `$`-headed interpreter + a relative script not found under the hook cwd. The FP fires whenever the command's own `cd` is what makes the script findable.

## Fix

`_leading_cd_cwd` / `_literal_cd_target` (called first in `_bash_sets_bypass_env_var`): follow an unconditional leading chain of `cd <literal existing dir>` (joined by `&&`, `;`, newline) and resolve relative scripts there, so the script is read and judged by content. It falls back to the hook cwd (status quo, so still denied) whenever it cannot be certain: target computed/`~`/`-`/glob/containing `..`; relative target with no cwd; directory missing (under `;` the shell stays put); subshell `(cd x)`; `cd` with `|`/`||`; any later `cd`/`pushd`/`popd` anywhere.

Judgement call kept as a deny: a steered run of a script that genuinely does not exist, or whose location depends on a computed `cd`, stays denied. A script can be created earlier in the same command, so "missing" is not safe to allow. Also noted, not changed: a path-qualified interpreter with a literal path (`/usr/bin/python3 x.py`) is judged by the interpreter binary's content, not `x.py`, so the script is never inspected. That is pre-existing and outside this niggle.

## Tests (tests/unit/handlers/pre_tool_use/test_upgrade_approval_guard.py)

Allowed (`TestSteeredInterpreterRunAfterALeadingCd`): the N292 command from another hook cwd; minimal shape with script under hook cwd; relative `cd`; a chain of two leading `cd`s.

Denied: leading cd into a dir whose script carries the handoff variable; 11 uncertain-cd shapes (missing dir with `;` and `&&`, `"$D"`, `~`, `-`, subshell, `|| true`, pipe, later cd, later popd, trailing cd). `TestSteeredUpgradesStayDeniedWhateverTheInterpreter`: PYTHONPATH on `bash scripts/upgrade.sh`, `scripts/upgrade_version.sh` (direct and via bash), `$V/python upgrade_gate_standalone.py` (relative, absolute, after a cd), a script whose content carries the handoff variable (absolute, via `$V/python`, via leading cd), unreadable scripts (`bash "$tmp" --project-root .`, `$tmp` positional, missing absolute path), `--skip-reading-confirmation`.

All 242 tests in the file pass, including every pre-existing denied test.

## QA

ruff, black (py311), mypy, pyright clean on the touched source (ruff/black also on the test file). `llm_qa.py changed` result is in the final reply.

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/213-the-upgrade-guard-follows-a-leading-cd-when-judging-a-relative-script.md`.

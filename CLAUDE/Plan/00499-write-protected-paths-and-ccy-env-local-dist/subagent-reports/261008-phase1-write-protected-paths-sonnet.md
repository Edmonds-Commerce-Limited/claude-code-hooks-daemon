# Plan 00499 Phase 1: write_protected_paths (Tasks 1.1 to 1.3)

## What was built

- `handlers/pre_tool_use/write_protected_paths.py`: opt-in PreToolUse handler, option `paths` (repository-relative
  globs, `*` `?` `**`; absolute and `..` refused by `validate_options`). Denies `Write`/`Edit`/`NotebookEdit` and
  Bash routes the shared scan names. Reading is never denied.
- `core/utils.py`: `scan_bash_write_targets(..., include_mutations=True)` and `scan_bash_write_destinations(...)`
  take the new opt-in flag. `BashWriteDestination` gained `mutation: bool = False` (a directory is a real target for
  these verbs). `_repository_root` became public `repository_root` (one internal caller).
- Registration: HandlerID, `Priority.WRITE_PROTECTED_PATHS = 10`, `RuleID.WRITE_PROTECTED_PATH`, `init_config`
  template line, `.claude/hooks-daemon.yaml` (enabled, priority 22, `paths: [.claude/ccy/ccy.env.local]`),
  `.claude/hooks-daemon.yaml.example`, `.claude/HOOKS-DAEMON.md`, `docs/guides/HANDLER_REFERENCE.md`, release note
  003, `config-changes/v3.70.0.yaml`, evasion-triage and guidance-coverage test registries.

## Scan verbs added (all opt-in via `include_mutations`)

`sed -i` (also `-i.bak`, `-ni`, `--in-place[=SUF]`; the script operand is not a file; `-e`/`-f`/`--expression`/`--file`
make every operand a file), `ln` (last operand, or `-t`; copy-verb semantics), `rm` (every operand), `truncate`
(every operand; `-s`/`-r`/`--size`/`--reference` values skipped), and the SOURCE of `mv`.

## Existing callers

Callers of `scan_bash_write_targets`, `get_bash_write_targets`, `get_written_file_paths` and
`scan_bash_write_destinations` (project_containment, markdown_organization, sed_blocker, bash_file_writes, the lint
handlers) do not pass the flag, so their results are unchanged. The default path is pinned by
`TestExistingCallersAreUnchanged`, and `tests/unit/core` passes in full.

## Fail-closed rules

- Unresolved destination: denied only if its raw text carries the protected file name, or is a wildcard that matches
  the literal protected path where it points.
- Unreadable command text: denied only if it contains the protected file name.
- A command with `cd`/`pushd`/`popd`, `$(`, or a backtick is also judged by file name on every resolved path (the
  hook cwd is then not what the operands mean).
- A worktree checkout of the same repository is protected (the call's own repository root is a second root).

## Known gaps (not in the plan)

`unlink`, `shred`, `rsync`, `find -delete`, `perl -i`, `python -c open(...)`, an in-place editor reached through an
interpreter, and a symlink created elsewhere that is then written through. A human or IaC outside Claude Code is out
of scope by design.

## Acceptance tests

One allow probe (an `echo` naming the file) that runs live. The deny probe is declared `harness_cannot_produce`: a
live probe of the real protected file would create or destroy it if the handler were not loaded, which the task
forbids. All deny cases run through the real handler over temporary paths.

## Constraint kept

`.claude/ccy/ccy.env.local` was not created, edited, moved or deleted in any checkout; tests use `tmp_path`.

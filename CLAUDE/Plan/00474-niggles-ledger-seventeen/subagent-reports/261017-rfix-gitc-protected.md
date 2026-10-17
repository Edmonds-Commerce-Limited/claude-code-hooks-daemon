# rfix-gitc-protected: `git -C <dir> rm|mv` operands were not rebased

## Assumptions

None needed. One choice made: `--work-tree` (both `--work-tree=X` and `--work-tree X`) is composed like `-C`,
left to right. With `--work-tree` and no `--git-dir`, git reads pathspecs relative to the work tree, so this
resolves them where git does; the reviewer asked for it.

## Defect

`_write_target_tokens` (core/utils.py) collected the operands of `git rm` / `git mv` (and `sudo git -C d rm`)
verbatim, so `git -C infra rm sub/prot.env` named `sub/prot.env` instead of `infra/sub/prot.env`, and
`write_protected_paths` returned matches=False (fail-open). `_git_output_files` already joined `-C`; the
mutation and move/copy paths did not.

## Red output (before the fix)

27 failed, 621 passed in `test_bash_write_mutations.py` + `test_write_protected_paths.py`. Examples: the
`git -C infra rm sub/prot.env` rows of `TestGitOperandsAreRelativeToItsDirectoryOptions` (got
`/repo/sub/prot.env`, wanted `/repo/infra/sub/prot.env`) and `TestGitDirectoryOptionsMoveTheOperands`
(`matches()` False for `git -C .claude rm ccy/ccy.env.local`).

## Fix

- New `_git_directory(tokens, index)` returns the left-to-right join of every `-C` / `--work-tree` between the
  `git` word and the subcommand (absolute restarts, relative composes). `""` when the verb is not reached
  through git global options alone, so `git -C d status; rm f` leaves `rm f` alone.
- New `_under_directory(directory, path)` joins; a `~` operand is left alone (already absolute once the shell
  expands it).
- `_collect_mutated_operands` (`rm`, `unlink`, `touch`, `truncate`, `sed -i`) and `_collect_trailing_operands`
  (`mv`/`cp`/`install`/`ln` destination, sources, `-t` value) take a `directory` and rebase their operands.
  A redirect's word is NOT rebased (it is the shell's cwd). The `mv` source mutation is rebased because it is
  built from the same sources.
- `tee` and `dd of=` are not git subcommands and pass no directory.

## Tests

- core: `TestGitOperandsAreRelativeToItsDirectoryOptions` in `tests/unit/core/test_bash_write_mutations.py`
  (repeated `-C`, absolute restart, `..`, `-c k=v -C`, `--work-tree` both spellings, `-C` + `--work-tree`,
  `sudo git`, `rm -f/-r --`, multiple operands, `mv`, `mv -k`, redirect not rebased, `status; rm` not rebased,
  `~` operand).
- handler: `TestGitDirectoryOptionsMoveTheOperands` in `tests/unit/handlers/pre_tool_use/test_write_protected_paths.py`
  (deny for each shape above, `mv` source and destination; allow for the same names resolved elsewhere).
- Changed existing row: `("git -C /x rm f.txt", ["/repo/f.txt"])` became `["/x/f.txt"]`. The old expectation
  encoded the bug (the directory option was ignored); the row's intent (a verb after git global options counts)
  is kept.
- Green: tests/unit/core, test_write_protected_paths, test_project_containment, test_markdown_organization:
  4186 passed.

## Other consumers checked

All consumers go through `_write_target_tokens`: `get_bash_write_targets`, `scan_bash_write_targets`,
`scan_bash_write_destinations`, `get_written_file_paths`. Users: `write_protected_paths` (fixed by this),
`project_containment` (a `git -C /outside rm f` was previously judged on `f`; now judged on `/outside/f`, which
is the correct and stricter reading), `markdown_organization`, `installed_plugin_edit_advisor`, `sed_blocker`,
`bash_file_writes`, `message_files`, `git_commit_parsing`, `lint_on_edit`, `validate_eslint_on_write`,
`plan_fact_check_feed`. They all consume the corrected paths; none had its own `git rm/mv` operand parsing.
`_git_output_files` already joined `-C` and needed no change.

## Observation, not changed

`git -C .claude/ccy rm other.txt` (an unprotected file in the protected file's directory) is still denied by
`write_protected_paths`: its separate "any other command naming the directory with -C" rule treats `-C <protected dir>` as a write into that directory. That is pre-existing, conservative, and unrelated to operand rebasing, so I
left it and did not add an allow test for it.

## QA

`./scripts/qa/llm_qa.py changed --allow-unmapped`: 40/40 PASSED, exit 0. `--allow-unmapped` was needed because
`core/utils.py` is reported as too broad to map to tests (the first run without it was 36/40 with that one
unmapped failure plus a format and a lint finding, both fixed). No suppression or exclusion added.

## Release note

None: the defect was never released. Release note 003 (write-protected-paths handler) does not mention `-C`, so
nothing became untrue.

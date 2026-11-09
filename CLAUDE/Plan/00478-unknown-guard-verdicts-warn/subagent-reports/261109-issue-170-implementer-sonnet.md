# Plan 00478 Phase 0 / GitHub #170: git text in a quoted awk program is data

## Cause (reproduced on main)

`destructive_git._scan_target` reads `command_position_argument_segments`, which blanks the quoted program of an
`awk` (`blank_quoted_text_arguments` -> `_blank_literal`). `_blank_literal` keeps any literal containing
`_EXPANSION_MARKERS` (`$`, backtick, `<(`), whatever the quote. `$1` inside a SINGLE-quoted awk program is not a
shell expansion, but it kept the program as command text: the raw pattern for `git worktree remove` matched it,
`_worktree_removals` (via `git_invocations`/`simple_commands`) read no removal, and `_ForceRemovalJudge.judge`
raised `_Unverifiable("no forced branch delete or worktree removal could be read")`. The reporter's literal-only
program has no `$`, which is why it was already blanked and allowed (confirmed: `matches()` False).

## RED (quoted)

`tests/unit/handlers/pre_tool_use/test_destructive_git_awk_data.py` before the fix: `5 failed, 17 passed`.
The failing allows: `print` (reported shape), `-F:`, `printf "...%s\n", $1`, `git branch -D` with print, and with
printf. Already passing (regression guards): the literal-only awk `BEGIN{print ...}`, `echo "git worktree remove x"`,
`echo 'git branch -D x'`, and every executing twin (`| sh`, `| bash`, `|& sh`, `| xargs -I{} sh -c '{}'`,
`eval "$(...)"`, `source <(...)`, `bash -c "$(...)"`, `$(...)`, awk `| "sh"`, awk `system(...)`, `> s.sh && sh s.sh`,
real dirty removal beside the print).

## Fix

Opt-in, default unchanged (`command_position.py` is shared with `git_stash`):
`awk_dollar_is_data: bool = False` on `command_position_argument_segments`, `blank_quoted_text_arguments` and
(`single_quote_is_literal`) `_blank_literal`. Only the awk branch and only SINGLE-quoted literals use it; `destructive_git`
passes `True`. Kept as written still: the awk markers `system` and `|`; under the opt-in also `>` (an awk
`print > "s.sh"` writes a script a later `sh s.sh` runs); a pipeline that hands the output to a non-inert stage
(existing `_pipeline_may_run_output`); and a command that runs a script an earlier segment wrote (existing
`_runs_written_script`, which the opt-in now honours, found by the first GREEN run: `awk ... > s.sh && sh s.sh` had
become allowed). No second parser; the unreadable route is untouched (Phase 2).

## Tests

New: `tests/unit/handlers/pre_tool_use/test_destructive_git_awk_data.py` (allows + executing twins + real removal),
`TestAwkDollarIsDataOptIn` in `tests/unit/utils/test_command_position_text_arguments.py` (default unchanged, opt-in,
double-quoted / git / `ls` / `system` / `|` / `>` kept). After the fix: 70 passed across the two modules.
Before/after probe of 18 shapes: only the 4 awk print/printf allows changed verdict, plus none of the twins.
Note: the `> "file"` and `getline`-free cases cost a false positive for awk programs that compare with `>`
under destructive_git only (conservative by design).

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/022-destructive-git-awk-program-text-is-data.md`.

## Disagreements with the brief

None. The brief's "shared parsing only behind an opt-in" was followed exactly.

# Review-findings fixes, handoff 1

Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch
`agent-acff915e4bf3b86e6-0a26f829`. Everything listed as done is committed and pushed.

## Done

- **6dc71d3ea, D-RULE 1 (HIGH).** `_statements` treats an unquoted newline as a
  separator, and backslash-newline continuations are joined. Every positive case
  in `tests/unit/utils/test_scratch_dir_creation.py` now also runs behind the
  `PRELUDES` (`set -e\n` and others).

- **a54996cce, D-RULE 2 (MED).** `utils/scratch_dir_creation.py` was reworked:

  - Wrappers are peeled with `shell_segmentation.peel_command_wrappers`, in a
    loop with the assignment strip. Redirect words are dropped.
  - Shell `-c` bodies come from `simple_commands.nested_command_strings`. Nesting
    is capped at 3; past the cap the creation counts as unresolved.
  - `cd`/`pushd` carry the cwd to later statements, and `( )` restores it.
  - New makers: `install -d/-D`, recursive `rsync`, `unzip`, `cp`/`mv -t`, and
    `mv`/`ln -s` when a source is an existing directory (otherwise a file move
    stays negative).
  - Unresolved paths (`$VAR`, a backtick, `cd -`) become `None` targets.
    `creates_directory_under` counts them as under every root.
  - A comment no longer swallows its newline (`_KeepNewlineAfterComment`). The
    advisor found that this was the D-RULE 1 class again.
  - The `cd /tmp && mkdir q` expectation was flipped to `/tmp/q`.

- **700af41b4, D-RULE 3 (MED).** `scratch_keep_marker_guard._bash_writes_marker`
  runs the shared scan, then three more checks:

  - a `cp`/`mv`/`install`/`ln` whose source basename is the marker, copied into
    a directory (`-t`, a trailing `/`, more than one source, or an existing dir);
  - a shell `-c` body, scanned recursively as a whole Bash command;
  - an interpreter (`python*`, `perl`, `node`, ...) with an operand containing
    the marker, which fails closed.

  New public helpers in `scratch_dir_creation`: `peeled_statements` and
  `copy_operands`. The negatives still pass: cat, ls, test -e, grep, a git
  commit message, and `cp marker /tmp/file`.

Targeted QA, all green: the tests for scratch_dir_creation, the cap guard, the
refresher, the keep-marker guard and blocking-handler evasion; ruff, black, mypy
and pyright on the touched src files (`bash untracked/qa.sh <files>` in the
worktree).

## Left

1. **Review `scratch_unowned_entry` and the SessionStart `scratch_sweep`** for
   the same issues: newline, wrapper, `-c` body, `cd`, `$VAR`.
   `peeled_statements` is reusable.

2. **F-BYPS F1.** The `--apply` confirm prompt in `daemon/cli.py` (around 7083)
   must name pressure mode and the count of entries that are not due. Pressure
   is currently decided after consent (around 7320). Decide it before the
   prompt, and never widen the run after consent.

3. **F-BYPS F2.** `_scratch_pressure` must use the apply run's own fresh,
   complete classification, not the cached inventory. There are two problems
   today:

   - `scratch_caps.py` around line 106 carries a stored BLOCK forward when the
     inventory is incomplete;
   - `pressure_for` ignores `caps.mode == "advise"`.

   Required tests:

   - a stale cached BLOCK alongside a fresh under-cap reading gives no pressure;
   - an incomplete walk gives no pressure;
   - advise mode gives no pressure;
   - the prompt text names pressure.

   Design F1 and F2 together, but commit them separately.

4. **Docs.**

   - DESIGN.md section 8: the creation scan now peels wrappers, follows `cd`,
     reads `-c` bodies, and treats unresolved as detected. `mv`/`ln` count only
     when a source is a directory.
   - DESIGN.md section 13: record the D-RULE 1-3 and F1/F2 outcomes.
   - PLAN.md: a task row.
   - Journal entry via `CLAUDE/Plan/mkplan.bash --journal`, never by hand.

5. **Not fixed, out of scope:** `python3 -c "os.makedirs('untracked/scratch/x')"`
   is not counted by the cap scan. A brace or glob spelling of the marker name
   was dismissed by the reviewer under the threat model.

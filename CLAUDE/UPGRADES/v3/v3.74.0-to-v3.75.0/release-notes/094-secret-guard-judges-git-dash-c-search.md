# Callout: the secret guard judges a git grep moved by -C, --work-tree or --git-dir

**Plan**: 00618
**Audience**: client projects

`secret_file_guard` skipped every `git grep` that carried a global `-C`, `--git-dir` or `--work-tree`. So `git -C <dir> grep --no-index -e .` read a protected file under `<dir>`, including a gitignored one, with no verdict. The equivalent `cd <dir> && git grep --no-index -e .` was denied. `--no-pager`, a trailing `.` pathspec and `--untracked` were also missed. A value given to `--attr-source` or `--config-env` was read as the subcommand, which hid the search the same way.

A literal `-C <dir>` is now resolved cumulatively from the working directory and judged exactly as the `cd` form is. A literal `--work-tree` is judged in full. A move the guard cannot place fails closed and is judged over every protected file in the project: a `-C`/`--work-tree` value built by a variable, substitution or glob, `--git-dir`, a `-c`/`--config-env` `core.worktree` override, or a `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`/`GIT_COMMON_DIR` assignment. A path-anchored protected path is also reached through `git -C <dir>` (for example `git -C <dir> show HEAD:<file>`), as it already was through `cd`. `quarantine_artefact_read_guard` gets the same placement. `flaggable_content_channel_guard` now places a relative literal `-C` instead of reporting it unplaced.

Every change makes the guards deny more, never less. An ordinary `git -C <dir> grep` over a directory with no protected file stays allowed. A command that is now denied and should not be can name a literal directory instead of a variable, or drop `--git-dir`. Protected patterns and config defaults are unchanged.

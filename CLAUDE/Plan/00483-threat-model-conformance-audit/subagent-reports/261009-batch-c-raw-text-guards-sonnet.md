# Plan 00483 Task 3.2 batch (c): raw-text guards (Sonnet)

Branch: agent-a0faad4a67ec2a1cf-eb2b861e. Ledger N383 marked fixed in 00474 NIGGLES.md.

## N383 (shared `_GIT_GLOBAL_OPTION`, `utils/command_evasion.py`)

`GIT_INVOCATION` options now read a word made of quoted, escaped and plain pieces, so
`git -C 'my dir' reset --hard` (also `"my dir"`, `my\ dir`), `-c 'user.name=A B'` and
`-c user.name='A B'` are denied for reset, clean, checkout, stash. One change covers
destructive_git and git_stash. 66 new deny cases were red on the previous tip.

## curl_pipe_shell

Allowed: a pipe into python/perl/ruby that names its program (`-m`, `-c`, `-e`, `-pe`,
a script file), because the program is local and the download is data. Kept denied: every
shell, `python3`, `python3 -`, `python3 -u`, `perl -`, and any later stage that is a shell.
Reuses `split_unquoted_spans`, `shell_word_spans`, `resolve_shell_word`.

## worktree_file_copy

Each command segment (`command_position_segments`) is judged alone. Allowed: grep/echo that
mention a worktree path, `ls <wt>/src/ && cp README.md src/`, and
`mv <wt>/notes.txt tmp.txt; ls src/x`. The last one: the guard's premise (its Rule and
guidance) is a copy from a worktree INTO main-repo code dirs (`src/`, `tests/`, `config/`).
`tmp.txt` is not one, and `mv <wt>/notes.txt tmp.txt` alone was already allowed on main; the
trailing `ls src/x` only made it look like a destination. So the premise allows it.
Also fixed: `FOO=1 cp <wt>/... src/` was allowed on main and is now denied; `bash -c` bodies
stay denied. The two declared acceptance probes wrapped the command in `echo`; they are now
real relocations of a nonexistent worktree (rsync with `--dry-run`), and the unit test that
pinned "echo-wrapped is denied" now pins "echo-wrapped is allowed".

## root_recursion_guard

Judges the scan root. Allowed: pattern operand (`rg "/home" src/`), `~/x` and `$HOME/x`
subdirectories, an existing file under /proc or /sys, a scan bounded by `-maxdepth 1` /
`--max-depth 1` / `-d 1`. Denied: `/`, `/home`, `/root`, `/proc`, `/sys` (and directories under
the last two), `~`, `$HOME` as a root, including via `-e`/`--regexp`/`rg --files`,
`fd --search-path`, `find -L / `, `find / -maxdepth 2`, and after `&&`, `;`, `||`, `|`, env prefix.
`rg ~` (one operand) is allowed: the tilde is the pattern.

## Gate

17 `a9-*` rows in `tests/fixtures/ordinary_command_corpus.yaml`; the gate is green.

## Review round 1 fixes (review: `261009-batch-c-review-r1-opus.md`)

Each deny case was written red first (24 failed before the change).

- B1: the worktree verb pattern reads any option run before `-c` (`sh -e -c`, `bash -x -c`,
  `bash -n -c`, `bash -o pipefail -c`). Fixed.
- B2: a `-maxdepth` bound excuses a `find` only when it has no `-exec/-execdir/-ok/-okdir` and
  its output is not piped to `xargs`. Fixed.
- B3: a pipe that ends a line is joined to the next line before the curl check. Fixed.
- S1: `/dev/stdin`, `/dev/fd/0`, `/proc/self/fd/0` are stdin for python/perl/ruby, from the
  shared `STDIN_OPERANDS` in `command_evasion.py` (also used by `shell_expansion.py`). Fixed.
- S2: both stale comments in `worktree_file_copy.py` rewritten. Fixed.
- S3: acceptance probes are `bash -n -c '<cp|rsync ...>'` again. Fixed.
- S4: the quote regex piece is one shared `QUOTED_SPAN_REGEX`, used by `GIT_INVOCATION` and
  `_MESSAGE_BODY_PATTERN`. N383 stays Fixed in the ledger; the remaining
  `_git_grep_pattern_spans` duplicate is an open line, and the `-e` guidance omission is fixed.
- NITs: the Rule text and guidance now say "from a worktree into the main repo's code dirs"
  and state that the reverse copy is not blocked.
- Also: the `daemon_stats.py` silent-fallback exclusion line was realigned (23 to 25) after a
  line shift that came in from main; it failed the changed tier through no change of ours.

## Review round 2 fixes (review: `261010-batch-c-review-r2-opus.md`)

Deny cases written red first.

- R2-B1: `worktree_file_copy` no longer uses a regex for shell wrappers. `_effective_command`
  walks the words with `shell_word_spans` and `resolve_shell_word`, skipping assignments,
  `sudo`/`env`/`command`/`nice` and a shell's options up to `-c`, then judges the body.
  `sudo bash -c`, `/bin/bash -c`, `env bash -c`, `bash --login -c`, `bash --norc -c` deny.
- R2-B2: a line-end pipe is joined to the next line with the shared `PIPE_AT_LINE_END` (now in
  `command_evasion`, used by curl_pipe_shell too). `-maxdepth` excuses a `find` only when the
  next pipe stage is a known data consumer (sort, wc, grep, head, ...), which also covers
  `sudo`/`env xargs`, `parallel` and `while read`.
- The N383 duplicate-reader note moved out of the Fixed entry into the open entry N387.
- Known gap: `sudo -u bob ... sh -c` is not read (an option's value is taken as the command).

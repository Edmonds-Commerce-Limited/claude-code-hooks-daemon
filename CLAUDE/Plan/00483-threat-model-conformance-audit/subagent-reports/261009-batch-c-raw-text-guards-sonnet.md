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

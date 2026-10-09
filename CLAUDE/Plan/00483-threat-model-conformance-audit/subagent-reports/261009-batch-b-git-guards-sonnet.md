# Plan 00483 Task 3.2 batch (b): destructive_git and git_stash, 2026-10-09

## Mechanisms fixed

1. A pattern's `.*` ran across `&&`, `;`, `|` into the next command. Both handlers now search each
   command segment (the N241/X-1 `command_position_segments`) on its own.
2. A flag test matched a substring of an operand (`-f` in `build-final/`). `git clean` now needs the
   flag to start a word; `git checkout ... --` needs `--` to start a word.
3. `git restore`: staged-only is allowed wherever `--staged`/`-S` sits and with `--source`; `--worktree`/`-W`
   keeps it denied. The short letters are case-sensitive (`-s` is `--source`; it was missed before).
4. A quoted pattern given to `git` or `awk` was read as a second command. New
   `blank_quoted_text_arguments` blanks a quoted span that holds a blank, except an expansion, a `!` git alias
   and an awk program with `system` or `|`.
5. `git stash --help` / `-h` print usage.
6. Heredoc receivers: `gh pr|issue|release|gist|api` (built-in names an alias cannot shadow), and a
   `while read` loop whose every statement is a structural word or a printing/filtering command. A loop that runs
   its input (`eval`, `$l`, `bash -c`) or an unrelated command earlier on the line keeps the body scanned.

## Left denied, with reasons

- `git clean -n -f` / `-nfd`: git treats the dry run as winning, but the pair is a deliberate force flag
  and was not in the list; kept denied (conservative).
- A `!` git alias definition and `awk` with `system`: text that can run.
- `git status && while read ...; done <<'EOF'` with body text: the loop reader judges the whole prefix, so an
  unrelated earlier command withholds the exemption (a false positive, never a bypass).

## Evidence

Red first: 27 failures in `tests/unit/handlers/pre_tool_use/test_git_guards_command_shapes.py` (all listed shapes, plus
the `-s` and `--staged --worktree` misses). Now 189 pass, each real form also denied after `&&`, `;`, `||`, `(`, `| `.
Gate rows `a8-*` (12) added to `tests/fixtures/ordinary_command_corpus.yaml`; the gate passes (408).

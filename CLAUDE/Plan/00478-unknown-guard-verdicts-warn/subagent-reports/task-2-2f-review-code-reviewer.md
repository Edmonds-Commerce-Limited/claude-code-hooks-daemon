STOPPING BECAUSE: review complete. Verdict is REQUEST CHANGES: 1 Critical, 1 Important (pre-existing, not new), 3 Minor/Suggestion.

# Review: Plan 00478 Task 2.2f (worktree-478-2f-review-minors, HEAD 424f231e9)

I ran `handle()` on three trees: base 6bba54cc7 (a temporary detached worktree, now removed with plain `git worktree remove`), main (which already has 2.2e), and HEAD. The probes are in `/workspace/untracked/worktrees/worktree-478-2f-review-minors/untracked/scratch/probe/`: `wpp_probe.py`, `wpp2.py` and `pb.py`, with outputs in `base.txt`, `main.txt` and `head.txt`.

## Critical

**1. A literal protected path after an operator-expansion awk operand went from deny to allow, and 2.2f does not close it** (`write_protected_paths.py:1057-1083`, `_operator_expansion_violation`). Listed glob is `protected/**`:
- `awk '{print > FILENAME}' "${IN:-a.txt}" protected/x`: deny at base, allow at main, allow at HEAD.
- `awk '{print > FILENAME}' ${IN:-a.txt} "$PWD"/protected/x`: deny, allow, allow.
- `awk '{print > FILENAME}' "${PWD:-.}" ./protected/x`: deny, allow, allow.

2.2e caused this, but 2.2f is the code meant to cover it. Its re-scan only judges words containing `${` (`if "${" in word`), so a plain or `$PWD` operand after the point where parsing stops is never looked at.

**Fix:** judge every remaining word in the statement. A word containing `$`, a backtick or `~` goes through `_unresolved_operand_naming`; a literal word goes through the normal path resolution against the listed globs. Add the three commands above as tests.

**Same function, second defect:** `start = text.find(command.text)` finds the first occurrence of the command text, not this command's position. So `echo awk '{print > FILENAME}' x; awk '{print > FILENAME}' ${PWD:-.}/protected/x` is still allowed at HEAD (it was denied at base). **Fix:** use the command's span from `simple_commands` instead of `find`.

## Important (pre-existing gap, not a 2.2f regression; file as a plan)

**2. Other verbs with an operator-form operand are allowed with no advisory.** Under `protected/**`, these return `matches()` False on both base and HEAD:
- `rm`, `cp src`, `mv src`, `tee`, `echo hi >`, `truncate -s0`, `sed -i` with `${PWD:-.}/protected/x`
- the same verbs with `"${PWD:-.}"/…`, `${HOME#x}/…` and `${x:+a}/…`

The verdicts are identical on both trees, so the implementer's "old gap" claim is correct and nothing new opened. Under a literal `protected/x` entry, every verb denies on both trees.

**Remediation:** move the "words after the truncation point" re-scan into the shared verb path (or teach the scanner to read a `${…}` operator word as one unresolved token), not awk alone.

## Minor / Suggestions

**3. Heredoc bodies are scanned even when nothing runs them** (`pipe_blocker.py:1539-1541`). These deny at HEAD and were allowed at main:
- `cat > notes.md <<'EOF'` / `run pytest | tail` / `EOF` / `docker ps | tail -1`
- `git commit -F - <<'EOF'` / `fix pytest` / `EOF` / `docker ps | tail -1`

A `t.sh` heredoc that only mentions pytest in a comment also denies; you said that is acceptable. It only bites when an unknown-producer pipe shares the command, and the deny message gives a cheap way round it (split the command). **Remediation:** skip heredoc bodies whose receiver writes a `.md` file or is a git/gh message consumer.

**4. Release note 031 describes the heredoc rule too narrowly.** It says "a script written by `cat > t.sh <<'EOF'` and run by the same command", but any heredoc body naming a blacklisted command now denies, including the two in item 3. HANDLER_REFERENCE ("heredoc body") is accurate. **Remediation:** reword 031 to say any heredoc body counts.

**5. Missing tests.** Add pipe tests for `<<-`, unquoted `<<EOF`, multiple heredocs, and `py.test` via env, path and `bash -c`. All of these already behave correctly (item 1 in Verified below). The awk tests need the item 1 shapes and an `echo awk` decoy.

## Verified

1. **Heredoc fix:** quoted, unquoted, `<<-` and multiple heredocs all deny. Here-strings and `bash <<'EOF'` denied before this change and still do.
2. **`py.test` blacklist:** `py.test` denies via `uv run`, `env`, `.venv/bin`, `/usr/bin`, `timeout`, `sudo`, `bash -c`, `unbuffer`, `python -m`, `python3 -m` and `python -mpy.test`.
3. **awk fix:** `${PWD:-.}`, `"${PWD:-.}"`, `${HOME#x}` and `${x:+a}` before `/protected/x` all deny, including after `;`, before `|`, and after another operand. `${PWD:-.}/other/y` is allowed under `protected/**`.

The `test_mkplan_journal.py` reformat is harmless formatter output.

## Verdict

REQUEST CHANGES, for Critical item 1: a deny-to-allow regression against 6bba54cc7 where the protected path is literally visible.
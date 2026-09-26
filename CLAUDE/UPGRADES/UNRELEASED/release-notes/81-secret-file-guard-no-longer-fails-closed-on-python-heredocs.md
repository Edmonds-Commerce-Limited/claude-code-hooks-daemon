# Fix: `secret_file_guard` no longer fails closed on an ordinary `python3 - <<'EOF'` program

**Plan**: 00466 (N101)
**Audience**: client projects

A Bash command that fed a Python program to `python3` through a
quoted-delimiter heredoc could be denied with `R-SECRET-EVALUATION-ERROR`
(`TooManyToEnumerateError`), even though it named no protected file. The
guard enumerated every brace "spelling" in the whole command, the program
body included. A body with many dict literals or f-strings then exceeded the
bounded expander's caps, and the guard failed closed. The same happened for
a long single-quoted `python3 -c '…'` program.

Bash brace-expands only unquoted shell words. The guard now skips brace
enumeration in one place: the program text of a standalone `python3`
command. That is either its single-quoted `-c` word or its one
quoted-delimiter stdin heredoc (`python3 - <<'EOF'` or `python3 <<'EOF'`).
The exemption applies only when no shell can read what the program prints:

- no pipe follows the command, and no process substitution appears in the
  line;
- the command is not inside `( )`, `{ }`, a loop or `if`, a substitution,
  or a wrapper such as `sudo`, `env`, `xargs` or `ssh`;
- the line has no `exec`, `eval` or `coproc`, and does not redefine
  `python3` (a function, alias, `hash`, PATH change, `source` or `.`);
- its output goes to the terminal, `/dev/null`, or a file that no other
  command in the line can run.

What still denies:

- A protected path named literally anywhere, including inside a Python body.
- Any brace spelling in Ruby, Perl, PHP or Node code. Those languages expand
  braces in their own glob functions.
- Any brace spelling in an argument to a Python script or `-c` program.
- A brace-spelled path in a string literal of a Python program that can pass
  its text on: one that starts a process, writes a file, runs code
  dynamically, or imports a module outside a small standard-library
  allowlist.
- A brace-spelled path inside a shell-exec call in any interpreter heredoc.
  Python's process APIs are all covered, including `commands`,
  `os.posix_spawn` and `subprocess` argv lists that name a shell behind a
  wrapper.
- A brace-spelled path in a body a shell runs (`bash <<'EOF'`, or
  `cat <<'EOF' | bash`), in a body written to a file (`cat > run.sh <<'EOF'`),
  or in `bash -c '…'`.
- Any shell word whose expansion goes past the cap. That still fails closed.

If the guard cannot parse a command or its Python program with confidence,
it enumerates the whole command exactly as before.

The same change fixes how the heredoc data-sink exemption shared by several
guards reads a wrapper. `sudo -p cat bash <<'EOF'` runs `bash`, not `cat`,
so its body is now scanned. Options of `sudo`, `env`, `nice`, `timeout`,
`nohup` and `command` are parsed with their values. An option the parser
does not know withholds the exemption.

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

Bash brace-expands only unquoted shell words. The guard now enumerates brace
spellings only in text a shell would expand. It skips a quoted heredoc body
fed to a non-shell interpreter (Python, Ruby, Perl, Node or PHP) when no
shell reads that program's output downstream. It also skips a single-quoted
argument of a non-shell interpreter.

What still denies:

- A protected path named literally anywhere, including inside a Python body.
- A brace-spelled path in a body a shell runs (`bash <<'EOF'`, or
  `cat <<'EOF' | bash`), in a body written to a file (`cat > run.sh <<'EOF'`),
  or in `bash -c '…'`.
- A brace-spelled path inside a shell-exec call in an interpreter heredoc,
  such as Python's os-dot-system. These calls are now extracted from heredoc
  bodies the same way they already were from `-c` one-liners.
- Any shell word whose expansion goes past the cap. That still fails closed.

If the guard cannot parse a command with confidence, it enumerates the whole
command exactly as before.

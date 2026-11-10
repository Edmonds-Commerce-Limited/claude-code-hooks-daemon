# Callout: pipe_blocker reads heredoc bodies and `py.test`; `${x:-a}` operands are read as words

**Plan**: 00478
**Audience**: client projects

`pipe_blocker` allows an unknown producer (`docker ps | tail -1`) with an advisory only when no blacklisted command is named anywhere in the command. That check now also reads **heredoc bodies**: quoted (`<<'EOF'`, `<<-'EOF'`) or not, and whether or not the command then runs the body. So `cat > t.sh <<'EOF'` holding `pytest`, followed by `bash t.sh | tail`, denies. One exception: a quoted-delimiter body that reaches only a markdown file (`cat > notes.md <<'EOF'`) or a git/gh message (`git commit -F -`, `gh pr create --body-file -`) is prose and is not read. `py.test` is now blacklisted like `pytest`, including through `env`, a path (`.venv/bin/py.test`) and `bash -c`.

The shell word reader shared by the safety guards no longer stops at a `${...}` operator form (`${x:-a}`, `${HOME#x}`, `${x:+a}`, `${#x}`). It reads the whole brace-balanced expansion as one word, an unresolved expansion like `$NAME`, so the words after it are still judged. A command substitution (`$(...)`, backticks) or an unclosed brace still stops it. For `write_protected_paths` under a glob such as `protected/**`:

- `awk '{print > FILENAME}' "${IN:-a.txt}" protected/x` now denies.
- `rm`, `cp`, `mv`, `tee`, `>`, `truncate` and `sed -i` judge an operand like `${PWD:-.}/protected/x` the same way they judge `$PWD/protected/x`.
- `${PWD:-w}`, `${PWD-w}`, `${PWD:=w}`, `${PWD=w}`, `${PWD:?w}` and `${PWD?w}` are read as the working directory, exactly as `$PWD` is.

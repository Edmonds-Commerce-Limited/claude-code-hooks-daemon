# Callout: the write-location guards now judge every command bash runs, and fail closed on text they cannot read

**Plan**: 00466
**Audience**: client projects

A Bash command with an unbalanced quote on a later line, or a heredoc whose
delimiter the guards did not recognise, could hide a write outside the
project. `echo x > /opt/o.md` followed by a line `x="u` was allowed, although
bash writes `/opt/o.md` before it reaches the bad line. Heredoc delimiters
are now read by bash's own grammar: any word, quoted or not, including
`<<'my-notes'`, `<<EOF-1`, `<<\EOF`, `<<$'EOF'` and `<<$(echo)`. A body
behind a quoted delimiter is data and never reaches the tokeniser, so prose
with apostrophes in it is not a problem.

The text is read one complete command at a time. When some of it still
cannot be read, `project_containment` denies with
`R-PROJECT-CONTAINMENT-EVALUATION-ERROR`, quoting the text. This also
applies to a heredoc that never reaches its closing line. Close the quote or
heredoc, or split the command. `plan_journal_guard` and
`markdown_organization` deny in the same way when the unread text names what
they protect.

The guards now also read three things the way bash does:

- A `#` inside a word does not start a comment. `echo a#b > /opt/o.md` and
  `curl http://x/#frag > /opt/f` write outside the project and are now
  denied.
- An ANSI-C string such as `$'it\'s'` is a single word. Before this, a
  later separator or `<<` could be misread, which let `pipe_blocker`,
  `destructive_git` and `project_containment` miss a command on the next
  line.
- A quote inside a comment is just a character. In
  `ls # it's` followed by a new line, the next line is judged as its own
  command.

The `git commit -m "$(cat <<'EOF' … EOF)"` exemption now applies only
when that heredoc is the whole message. A second substitution after it, or
a command on its opener line, is judged.

A `<<` counts as a heredoc only where bash reads one. Inside `${…}`,
`$[…]`, `$((…))`, `((…))`, an array or a comment after a backtick it is
text, and the lines after it are judged as commands. A heredoc inside
`<(…)` or `>(…)` closes at `EOF)`, as one inside `$(…)` does. Where the
guards cannot be sure how bash splits a command from a heredoc body, they
stop reading bodies there: the command guards judge the rest as commands,
and the write guards deny it as unreadable. The uncertain shapes are an
unclosed `$(`, a `$((` bash re-reads as subshells, the word `case` inside a
substitution (its patterns end in a `)` that closes nothing), and a new line
inside a substitution while a heredoc opened before it is waiting for its
body. So `x=$(case "$1" in a) …;; esac)` is now denied by
`project_containment` as unreadable; set the value with an `if`, or run the
`case` outside the substitution. A backslash at the end of a line inside a
quoted heredoc no longer joins the closing line to it, because bash does not
join it either. Every other backslash-newline is joined as bash joins it, so
`git reset --ha\` followed by `rd` is still judged as `git reset --hard`.

A quoted heredoc body is blanked as data only when the command reading it
takes nothing that could run it. `tee >(bash)`, `cat > >(bash)`,
`git -c alias.x='!sh' x`, `sort --compress-program=…`, a redirect to a FIFO
or to an fd other than 1 or 2 keep the body judged as commands. A file
target, `git -C` directory or option value the guard cannot resolve
(`cat > "$OUT"`, `git -C "$WT" commit -F -`) does not. `ftp`, `mail`,
`mailx`, `sendmail` and `patch` are no longer treated as data sinks. A body
fed to `bash` or another shell is now read for writes by
`project_containment`, and so is one fed to a variable the command sets to
a shell (`SH=bash; $SH <<'EOF'`), or to `$SHELL` or `$BASH`. A body fed to
any other variable (`$PY - <<'EOF'`) is data, as before.

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

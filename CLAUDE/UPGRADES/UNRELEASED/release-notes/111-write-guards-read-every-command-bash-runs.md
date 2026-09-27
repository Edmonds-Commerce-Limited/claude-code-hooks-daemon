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
unclosed `$(`, a `$((` bash re-reads as subshells, a `case` command inside a
substitution (its patterns end in a `)` that closes nothing), and a new line
inside a substitution while a heredoc opened before it is waiting for its
body. So `x=$(case "$1" in a) …;; esac)` is now denied by
`project_containment` as unreadable; set the value with an `if`, or run the
`case` outside the substitution. Only a `case` bash reads as the keyword
counts: `n=$(grep -c case README.md)` and `echo "$(echo upper case)"` are
read normally. Where `secret_file_guard` cannot read a command it now denies
with `R-SECRET-COMMAND-UNREADABLE` and a rephrase, not with the
evaluation-error rule that asks for a bug report. A backslash before a
carriage return and a newline joins nothing, as in bash. A backslash at the end of a line inside a
quoted heredoc no longer joins the closing line to it, because bash does not
join it either. Every other backslash-newline is joined as bash joins it, so
`git reset --ha\` followed by `rd` is still judged as `git reset --hard`.

A quoted heredoc body is blanked as data only when the command reading it
takes nothing that could run it. `tee >(bash)`, `cat > >(bash)`,
`git -c alias.x='!sh' x`, `sort --compress-program=…`, a redirect to a FIFO
or to an fd other than 1 or 2 keep the body judged as commands. A quoted
file target, `git -C` directory or option value the guard cannot resolve
(`cat > "$OUT"`, `git -C "$WT" commit -F -`) does not. Unquoted, it may
split into options, and it keeps the body judged; so does any unresolved
target in a command that opens an fd on a process (`exec 3> >(bash)`),
because it may be `/dev/fd/3`. `ftp`, `mail`, `mailx`, `sendmail` and
`patch` are no longer treated as data sinks.

A body is data unless a command before it in the same call may change what
a command name means to this shell, because `cat(){ bash; }; cat <<'EOF'`
runs it. That is a function or alias definition; `hash`, `enable`,
`builtin`, `command`, `eval`, `source`/`.`, `exec`, `export`, `declare`,
`typeset`, `local`, `readonly`, `unset`, `shopt`, `trap`, `read`,
`mapfile`, `getopts`, `printf -v`, `let`, `cd`, `pushd`, `popd` or
`coproc`; `set` with anything but `-e`, `-u`, `-x` and `-o pipefail`; an
assignment, or a `for`/`select` loop name, that is `PATH`, `IFS`,
`BASH_ENV`, a `GIT_*` or `LESS*` name or another variable bash or a pager
reads; an assigning
`${X:=…}` or arithmetic; a command name written with a quote, an escape or
an expansion; or any of these inside `{ }`, `( )` or a substitution. Any
other program is a child process and cannot, so `set -euo pipefail`,
`mkdir -p d &&`, `pytest -q;` and an earlier `cat > a.md <<'EOF'` leave a
later prose heredoc as data. Put the heredoc first, or in its own Bash
call, after a command that may rebind.

`secret_file_guard` and `quarantine_artefact_read_guard` no longer treat a
glob as a bug in the guard. A quoted or escaped glob (`rg -g '**/*.md'`,
`jq '.files["a"]'`) is passed on as written and is not expanded. An
unquoted glob that cannot be listed within the budget, or a scan past its
deadline, is denied with "this command could not be verified … name the
files, or narrow the glob or directory". A `Write` of Python source is no
longer brace-expanded as if it were a command: only its string literals and
comments are, so a long option table is allowed.

A body fed to `bash` or another shell is read for writes by
`project_containment`, and so is one fed to a variable the call sets to a
shell (`SH=bash; $SH <<'EOF'`), to `$SHELL` or `$BASH`, or to `exec bash`. A
body fed to a variable is data only when a plain literal assignment earlier
in the call pins it to a program that is no shell (`PY=python3; $PY -`). Any
other variable receiver (`$PY -` with nothing assigning it, `$0`,
`${X:-bash}`, `env $V`, `read PY`) is unknown, so its body is read as
commands and denied where it cannot be read.

`project_containment` also resolves a variable write target from a plain
literal assignment earlier in the same call:
`OUT=/opt/o.md; cat > "$OUT"` is denied, and
`OUT=untracked/scratch/o.md; cat > "$OUT"` is allowed. A target nothing
pins -- a loop variable, `read`, a substitution such as
`"$(dirname …)"`, a variable bash sets such as `$PWD`, or a glob -- is
unknown until the command runs, and is now denied. Write the path out, or
assign it literally first.

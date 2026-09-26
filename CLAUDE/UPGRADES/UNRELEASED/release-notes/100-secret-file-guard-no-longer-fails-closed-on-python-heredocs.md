# Callout: `secret_file_guard` no longer fails closed on an ordinary `python3 - <<'EOF'` program

**Plan**: 00466
**Audience**: client projects

A Bash command that fed a Python program to `python3` through a
quoted-delimiter heredoc could be denied with `R-SECRET-EVALUATION-ERROR`
(`TooManyToEnumerateError`), even though it named no protected file. The
guard enumerated every brace "spelling" in the whole command, the program
body included. A body with many dict literals or f-strings then exceeded the
bounded expander's caps, and the guard failed closed. The same happened for
a long single-quoted `python3 -c '…'` program.

Bash brace-expands only unquoted shell words, and Python never
brace-expands its source. The guard now skips the CODE braces (dict and set
displays, comprehensions, f-string fields) of one kind of text: the program
of a standalone `python3` command in a Bash tool call. That is either its
single-quoted `-c` word or its one quoted-delimiter stdin heredoc
(`python3 - <<'EOF'` or `python3 <<'EOF'`). Every string literal and comment
of that program is still enumerated, each on its own and with the usual
caps. So is the full text of every f-string; for every expression, its
literals joined in source order; and every literal and comment of the
program joined in order with a space. A brace group split across literals
(`'…{a,' + 'x}…'`, `''.join([...])`, `f'{"{"}'`) or across statements is
therefore still seen whole. Every brace word of the program that reaches
outside a literal (`x .p-{"a",z}`) is enumerated on its own as well, and
fails closed past the cap, as before. So is every word bash itself would
split from the program text, inside a literal or not, read with bash's
quoting: a literal such as `'''a' /p/.v-{\x7b,pass} 'b'''` decodes to text
that spells nothing, but bash reads the middle word unquoted. The exemption applies only when no
shell can read what the program prints:

- no pipe follows the command, and no process substitution appears in the
  line;
- the command is not inside `( )`, `{ }`, a loop or `if`, a substitution,
  or a wrapper such as `sudo`, `env`, `xargs` or `ssh`, and the line
  defines no function;
- every other command in the line, including inside `$( )` and backticks,
  is on a short list known not to run text as shell: `cd`, `pushd`,
  `popd`, `pwd`, `echo`, `true`, `false`, `:`, `set` (without `-x`),
  `export` (plain names only), `mkdir`, `ls`, `cat`, `grep`, `sleep` and
  `python3`, named bare or from a system directory, optionally behind
  `sudo`, `env`, `nice`, `nohup`, `timeout` or `command`. Any other
  command (`trap`, `mapfile -C`, `eval`, `git`, a script) withdraws the
  exemption, as do an arithmetic expansion, a `${…}` other than a plain
  name, and an unquoted heredoc whose body holds `$` or a backtick;
- nothing redefines `python3` or what it loads (a function, alias, `hash`,
  `enable`, PATH or `PYTHONPATH`-style change). Command words and these
  words are recognised however they are quoted or escaped (`'exec'`,
  `\exec`, `e\xec`), and a command word built by expansion withdraws the
  exemption;
- the program declares no source encoding other than UTF-8 and carries no
  byte-order mark, so Python reads the same text the guard parsed;
- the program holds no carriage return, and no f- or t-string field holds
  the string's own quote, a backslash, a `#`, a newline or a nested f- or
  t-string. Python 3.12 reads those fields differently from earlier
  versions, and the daemon's Python need not be the one that runs the
  program;
- its output goes to the terminal, `/dev/null`, or a file that no other
  command in the line can run.

What still denies:

- A protected path named literally anywhere, including inside a Python body.
- A brace-spelled path in any Python string literal or comment, whatever
  the program does with it.
- A string literal whose own brace expansion goes past the cap. That fails
  closed, as shell text does.
- Any brace spelling in Ruby, Perl, PHP or Node code. Those languages expand
  braces in their own glob functions.
- Any brace spelling in an argument to a Python script or `-c` program.
- A brace-spelled path inside a shell-exec call in any interpreter heredoc.
  Python's process APIs are all covered, including `commands`,
  `os.posix_spawn` and `subprocess` argv lists that name a shell behind a
  wrapper.
- A brace-spelled path in a body a shell runs (`bash <<'EOF'`, or
  `cat <<'EOF' | bash`), in a body written to a file (`cat > run.sh <<'EOF'`),
  or in `bash -c '…'`.
- Any brace spelling in a shell script, Makefile or CI file authored with
  `Write` or `Edit`: its output reaches whoever runs it later, so it is
  enumerated whole.
- Any shell word whose expansion goes past the cap. That still fails closed.

If the guard cannot parse a command or its Python program with confidence,
it enumerates the whole command exactly as before.

Brace groups are now also read the way bash reads them. A quoted or
backslash-escaped brace or comma is text, not brace syntax, and so is one
inside `${…}`, `$(…)` or backticks. Earlier releases paired braces without
regard to quotes, so a word such as `name-{"}",pass}`, whose first
alternative is a quoted `}`, could spell a protected path (`name-pass`) the
guard never saw. A group
holding quoted whitespace is now seen whole, and so is one inside text a
shell may run (`bash -c '…'`, `eval`, a heredoc body). The earlier reading
is kept alongside, so nothing that denied before is now allowed. The
bash-aware reading follows bash's own brace expansion: a `}` before any
comma is text, a group with no comma that is not a sequence is text, and a
`${…}` inside a group is read as bash's brace scanner reads it. A
substitution the guard cannot place with certainty (a `case` or heredoc
inside `$(…)`) next to a brace group fails closed with
`R-SECRET-EVALUATION-ERROR`.

Three shell forms that hid a brace-spelled or split path are now read as
bash reads them:

- `$"…"` locale quoting: bash drops the `$`, so `cat $".vault-"pass` names
  `.vault-pass`. Earlier releases kept the `$`.
- Braces made by ANSI-C decoding and handed to a shell:
  `bash -c $'cat .vault-\x7bpass,q\x7d'` runs `cat .vault-{pass,q}`. Text
  decoded from `$'…'` is now read as a command whatever it holds.
- After quoting the guard cannot resolve, such as `: ${x:-'a'} ;`, the
  guard stops scanning only when no brace group can still arrive. A
  `$'…'` that decodes to a brace, or an unknown expansion where `eval`,
  `bash -c`, `ssh` or a similar word reads text again, now fails closed
  instead.
- A quote-free word whose group bash reads differently from plain pairing:
  `cat .vault-{},pass}` names `.vault-pass`, because bash reads a `}` before
  the first comma as text. Only a word holding a quoting character used to
  get bash's reading.
- A here-string: `bash <<< $'cat .vault-\x7bpass,q\x7d'` runs the decoded
  text. The guard read the here-string's word as a heredoc delimiter and
  never looked at it.

A glob under a path component longer than the filesystem's name limit no
longer fails the guard closed with `R-SECRET-EVALUATION-ERROR`. No file can
have such a name, so the glob expands to nothing, as for a directory that
does not exist. Any other filesystem error during expansion still denies.

The here-string mistake above is also fixed in the heredoc exemption shared by
several guards. In `cat <<<'EOF'`, the line after is a command bash runs,
but the guards read it as a quoted heredoc body and skipped it. So
`destructive_git`, `pipe_blocker` and the other guards using that exemption
now judge it, and `background_process_tracker` sees an `&` on it.

The same change fixes how the heredoc data-sink exemption shared by several
guards names its receiver. `sudo -p cat bash <<'EOF'` and
`sudo -p 'x cat' bash <<'EOF'` run `bash`, not `cat`, so their bodies are
now scanned, and a receiver built by expansion (`$cat <<'EOF'`) is no longer
trusted as a sink. Options of `sudo`, `env`, `nice`, `timeout`, `nohup` and
`command` are parsed with their values, quotes respected, and an option the
parser does not know withholds the exemption. As a deliberate widening, a
data sink behind one of those wrappers (`env cat <<'EOF'`) is now trusted:
each wrapper runs the named command on the same input and runs nothing
itself. An option that changes the root or working directory
(`sudo -R`/`--chroot`, `sudo -D`/`--chdir`, `env -C`/`--chdir`), runs a
shell (`sudo -i`/`-s`) or keeps the caller's environment across sudo's
reset (`sudo -E`/`--preserve-env`) withholds the exemption, so
`sudo -E tee f <<'EOF'`, which earlier releases trusted, now has its body
scanned.

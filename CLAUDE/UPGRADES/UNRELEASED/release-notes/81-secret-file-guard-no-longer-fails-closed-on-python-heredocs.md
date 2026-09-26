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
outside a literal (`x .p-{"a",z}`) is enumerated on its own as well. When
such a word has too many spellings, the guard checks a wildcard form
instead, with each brace group replaced by `*`. It denies only if that form
could match a protected path, so a large dict display is still allowed. The
exemption applies only when no shell can read what the program prints:

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

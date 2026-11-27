# N744 / N760: the teamchat message sink and its three security reviews

Branch `guard-n744-n760-teamchat-message-sink`, release note 124. This is the durable record. The working reports and harnesses lived in session scratch, which is swept.

## What the branch changes

- **The teamchat message sink** (`utils/message_sink.py`). The guard judges only `teamchat <verb> <words>` when the WHOLE Bash command is exactly one statement matching all of these:

  - the verb is a message verb: `say`, `reply`, `report`, `thread`, `ask-human`, `close` or `retitle`;
  - the message arrives by exactly one of: a quoted-delimiter heredoc (`<<'EOF'` or `<<"EOF"` ending the first line, with only blank lines after the closer); a single-quoted here-string; or one `printf`/`echo` of literal quoted words piped in by a single `|`;
  - the teamchat words are bare `[A-Za-z0-9_@%+=:,./-]+` words, or whole quoted words with no expansion;
  - any option is one of the listed flags;
  - only space, tab and newline count as blank.

  Anything else voids the sink and is judged as before. That covers: a pipe out, a chain, a redirect, a substitution or variable, an unquoted or `<<-` heredoc, a wrapper or assignment, an unknown flag, another verb, a producer that opens a file, a `printf`/`echo` option, and authored Write/Edit content.

- **The whole-quoted-name check.** A quoted multi-word argument whose whole text names a file that is present or indexed always counts. Commands such as `pr 'mid x.secret.key dle'` were allowed on main.

- **N769:** the session-actions baseline tests no longer read the live project scratch.

## Withdrawn

The N749 underscore-identifier narrowing was built and reviewed twice, and both reviews found it leaking:

- a protected name containing a space;
- a `cd` hidden in `source`, `.`, `eval`, a `function f { ... }` body or an alias;
- relaxed authored `.sh` and Makefile scripts.

It was removed, and tests pin main's behaviour. N749 is open for the owner.

The N760 "position of the matched word inside a long token" deny line was removed as unreachable: 0 of 7,542 real denies carried it.

## Review evidence (final tree)

| Harness                                             | Commands now allowed that main denied | Exposed when run |
| --------------------------------------------------- | ------------------------------------- | ---------------- |
| Review 1 differential (10,399 commands)             | 1,447                                 | 0                |
| Review 1 planted-hole control (`cat` as a producer) | —                                     | still EXPOSED    |
| Review 2 corpus c0 (9,165)                          | 1,383 (2,041 allows run)              | 0                |
| Review 2 corpus c1 (1,439)                          | 11 (16 allows run)                    | 0                |
| Review 2 corpus c2 (the leak corpus)                | 0, verdicts identical to main         | 0                |

The third review approved the branch with minor findings only.

## Residual risks for the owner

- A sink that writes its stdin to a file; teamchat does not.
- A `teamchat`, `printf` or `echo` function, alias or look-alike binary brought in from outside the command.
- A spaced protected name that is neither present at a base the guard knows nor indexed, read after a directory move it cannot follow.
- The bare-dotted gate on main trusts existence at the known bases (N770).

NOT READY

# Plan 00466 — adversarial review 7 of `worktree-n466-guard-defects` (INCOMPLETE)

**Reviewer**: Opus 5.5. Target: HEAD `4f977115`, merge-base with main `a20c4139`.
No tracked file was edited and nothing was committed. No real protected file was
opened. Every probe judges command text only, with payloads marked
`synthetic_source`.

## Status

This review was stopped partway through. Only scope item 1 and part of item 3
were done. Items 2(a)-(e) and 4 were **not** run (see "Not done").

The exact probe inputs and per-case results are in
`/workspace/untracked/scratch/probe_gd7_shell.pyprobe` and
`/workspace/untracked/scratch/gd7_shell.txt`. The findings below describe each
problem by class. The payload strings are not repeated here.

## Item 1: review-6 re-run

`probe_gd6_shell2` at HEAD gives 80 cases and 10 mismatches (output:
`/workspace/untracked/scratch/gd7_shell2.txt`). All 10 are the accepted
class-(d) residuals: remote exec, the Perl string-building case, the opaque
base64 pipelines (2), command substitution feeding `-c` (2), variable
indirection (2), alias, and write-then-run. Every other review-6 case now
denies. **Pass.**

## Findings (from `probe_gd7_shell`: 62 cases, 52 fail-opens)

The 52 fail-opens fall into the classes below. None of them is on the accepted
class-(d) list. In each one, the protected path is present as literal command
text.

### MAJOR-1: over-budget input silently allows (fail-open)

`src/claude_code_hooks_daemon/utils/shell_expansion.py:866` (`if count >= max_words: return`)
and `:249` (the `iter_brace_words` cap). Past the word cap (2000 normalised
words, 500 brace words), both generators just stop. The caller
(`secret_file_matching.py:1342`) treats that as "no mention". A mention that
only these streams can see, placed after the cap, is then allowed. The control
case under the cap denies. This breaks the "over-budget must deny" requirement
in scope item 2(c). Fix direction: raise `TooManyToEnumerateError` at the cap,
as the other bounds already do.
Repro: gd7_shell.txt rows "2001 words then G" and "501 brace words".
Direction: fail-open.

### MAJOR-2: nested-command triggers inside `$(...)` / backticks are never parsed

`shell_expansion.py:577-578, 624-627, 649-653`. Command substitution collapses
to `*` and its body is never re-parsed. Any `-c`/`eval`/pipe-to-shell trigger
placed inside `$()` or backticks is therefore unexamined. This is not the
accepted "substitution feeding `-c`" residual: here the substituted body is
itself a literal command. `<(...)` already recurses (its control case denies),
so the fix is to give `$(...)` and backticks the same treatment.
Repro: gd7_shell.txt rows "inside $()" / "inside backticks" (5 rows).
Direction: fail-open.

### MAJOR-3: the review-6 MAJOR-1/minor-1 closures are narrower than claimed

All of these are in `shell_expansion.py`, in `_iter_normalised_shell_words` and
the wrapper/interpreter tables at lines 298-356:

- The pipe-to-shell wrapper stage stops at the wrapper's own options or
  positional words (`sudo -u …`, `env -i`, `timeout N`, `nice -n N`). The
  non-`tee` passthrough stage (`cat`) is also missed, and so is `> >(shell)`.
- A here-string or `<(` is not recognised after an intervening redirect or
  positional word, or after `< <(`. The operator string is compared for exact
  equality (lines 1003 and 1055), so `"<<("` never equals `"<("`. Stdin-path
  aliases other than `-` and `/dev/stdin` are also missed.
- `-c` followed by `--` or another option takes the wrong word as the code.
- `su`/`script`/`flock` long forms (`--command`) are missed, as are
  positional-first spellings (`su user -c`, `script file -c`). `watch -x` is
  missed. `env -S` is not handled.
- Restricted/alternative shells are missing from the interpreter list (rbash,
  yash, posh, pdksh).
  Repro: the matching rows in gd7_shell.txt. Direction: fail-open.

### MAJOR-4: the `file:` URL route is only partly closed

`src/claude_code_hooks_daemon/utils/secret_file_matching.py:1443`. The regex runs
on raw text. It is case-sensitive, although URL schemes are case-insensitive
and curl accepts them in any case. It also stops at a quote character, and
quote-removal never feeds its input, so a URL split by shell quoting is missed.
Fix direction: add `re.IGNORECASE`, and also run the regex over the decoded
words from `iter_normalised_shell_words`.
Repro: gd7_shell.txt `file URL` rows (4 fail-opens; the 127.0.0.1-host, brace,
bracket and encoded-dir rows correctly deny). The `%5C` row is expected to
allow, because curl reads a different filename there. It is a probe-expectation
error, not a finding.
Direction: fail-open.

### MAJOR-5: the interpreter one-liner route (new in a8725147) is exact-match only

`src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py:701-749`.
The route requires the basename to be exactly one of six names, and the code
flag to be the very next word, exactly `-c`/`-e`/`-r`. Versioned or absolute
interpreters (`python3.12`), an interpreter option before the flag, clustered
flags (`-Sc`, `-le`, `-we`), `perl -E`, `node -p`/`--eval` and `pypy3` all skip
the route. The fix should reuse the option-walk approach from shell_expansion.
Repro: gd7_shell.txt one-liner rows. Direction: fail-open.

### MINOR-1: gaps in the Python AST detection

`secret_file_guard.py:381-461`:

- `subprocess.getoutput`/`getstatusoutput` always run a shell, but they are
  gated on `shell=True`, which these functions do not take, so they never
  match.
- f-strings (`ast.JoinedStr`) are not collected as literals, even with no
  placeholders (`_collect_python_string_constants`, line 464).
  Repro: gd7_shell.txt rows "subprocess.getoutput" and "f-string". Direction:
  fail-open.

### MINOR-2: Ruby bare `system 'x'` (no parentheses) is not matched

`secret_file_guard.py:287` requires `(`. The no-paren form is idiomatic Ruby.
Repro: gd7_shell.txt last row. Direction: fail-open.

### NIT-1: stale comment

`shell_expansion.py:393-396` still says a non-literal `source <(…)` "fails
CLOSED (raises)". Since 1aa15f32 it is judged by its own text instead.

### Reported by reading the code only (not probed)

- The ast-to-regex fallback is not equivalent. The AST path runs only when the
  content parses standalone under the daemon's own Python (3.11). The regex
  fallback lacks alias resolution and the spacing-tolerant `shell=True` check.
  On the **Edit** route only `new_string` is scanned, and an indented fragment
  fails `ast.parse`, so in practice Edit usually gets the weaker fallback.
  Newer-syntax files also fall back. This needs a probe to confirm before it is
  rated.
- The Go/Rust/Java first-literal check compares the raw string to bare shell
  names, with no basename strip (the Python path does strip it). It also uses
  the narrower 6-name set. Needs a probe.

## Not done (must be covered before READY)

1. Item 2(a): the false-positive corpus (200+ everyday commands).
2. Item 2(b): timing on a 1 MB command and on a deeply nested command.
3. Item 2(c): fail-closed mutants (parse failure, over-budget, injected
   exception). MAJOR-1 above already shows that over-budget fails open.
4. Item 2(d): the gd5 probe re-run.
5. Item 2(e): the QA-integrity diff of the tests against the merge-base.
6. Item 4: the targeted pytest run of the three test files.
7. Probes for the non-Python content routes (Ruby/PHP/Perl/Node/Go/Rust/Java
   Write/Edit cases).

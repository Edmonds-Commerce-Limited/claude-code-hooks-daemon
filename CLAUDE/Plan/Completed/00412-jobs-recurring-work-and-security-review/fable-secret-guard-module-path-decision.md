# Decision: `secret_file_guard` and the dotted module path

Supporting document for Plan 00412, closing
[DECISION-secret-guard-module-path-false-positive.md](DECISION-secret-guard-module-path-false-positive.md)
and unblocking worklist row **F-PRIV-4**. Decision only — nothing here was
implemented, and nothing needs to be.

## The ruling

**DECISION: none of the four options is adopted as written, because the
decision's premise is wrong in a way that dissolves the choice. The
import-statement half of option A has been shipped since `c8ce2d7a`, hardened
in `b149808f` (2026-09-06) — ten days before the decision was filed. The guard
does NOT deny a Python import of the redaction module. What it denies is the
dotted module path in a NON-import position — a string literal, a docstring, a
`patch()` target — and that residual is accepted (the substance of option D),
because a string literal is exactly how Python names a file. F-PRIV-4 is not
blocked: its fix is an import statement, which is exempt, and its regression
test can simulate the `ImportError` without ever spelling the token.**

Options A-remainder, B and C are rejected on the evidence below. No code
change, no config change, no protection removed.

## Evidence

### What the guard actually does, read from the code

- **Tokenisation treats quotes as delimiters** —
  `utils/secret_file_matching.py:66` lists `"` and `'` in
  `_TOKEN_DELIMITERS`, so the contents of a string literal surface as bare
  tokens (`_tokenise`, `:276-286`). The comment on `:63-65` says why: so
  `open('.vault-pass')` yields a clean path token. That is the design, and it
  is the reason the string-literal case cannot be given up (below).
- **Import statements are already exempt, positionally** —
  `find_protected_mention_detail` (`:744-863`) runs
  `_without_import_module_paths` (`:759`) before tokenising. It blanks the
  module-path span of every line-anchored `from|import <dotted>` statement
  (`_IMPORT_MODULE_RE`, `:292-294`) and of a `python -c "import <dotted>"`
  argument (`_IMPORT_MODULE_INLINE_RE`, `:307-309`). The docstring at
  `:323-360` records the rationale — "a module path is not a filesystem path,
  and importing a module cannot read a file" — and names this exact collision:
  the shipped `*.secret*` substring-matching the package's own module paths.
- **Every surviving token is glob-matched** — `path_matches_globs(form, (pattern,))` at `:771`, gitignore dialect. `*.secret*` matches any token
  containing `.secret`, so `claude_code_hooks_daemon.utils.secret_redaction`
  matches and `utils/secret_redaction.py` does not. The decision's account of
  the mechanism is correct; only its account of WHERE the token sat is not.
- **The script route is scoped by extension** —
  `handlers/pre_tool_use/secret_file_guard.py:126-136` lists `.py`, `.sh`,
  `.js` and six others; `:260` gates on it; `:269` scans `content` or
  `new_string`. Markdown is not scanned, which is why the decision document
  and this one are writable. Four files are on `exclude_paths`
  (`.claude/hooks-daemon.yaml:290-294`); `scripts/qa/check_sensitive_content.py`
  is not, and does not need to be.

### Live probe, against the running daemon

Two `Write` calls to scratch `.py` files, same session, same daemon:

1. A file whose only reference to the module is the exact import shape at
   `check_sensitive_content.py:141-146` — `try:` on its own line, then
   `from claude_code_hooks_daemon.utils.secret_redaction import (` — was
   **ALLOWED**. The file landed and was removed.
2. A file with `monkeypatch.setitem(sys.modules, "claude_code_hooks_daemon.utils.secret_redaction", None)` was **DENIED**:
   `R-SECRET-SCRIPT-AUTHOR`, `Matched protected glob: *.secret*`, and the
   echoed token was the bare dotted path.

The unit tests pin the same boundary: `TestPythonImportStatements`,
`TestPythonDashCImportStatements` and
`TestTheImportExemptionCannotLaunderAMention`
(`tests/unit/utils/test_secret_file_matching.py:609-760`) — 17 tests, all
passing on the current tree. `:648-651` is the test that says the exemption is
"scoped to import statements, not to dotted tokens"; the denied probe above is
that test's case.

### The decision document's factual claims, checked

- **WRONG — "A Python import ... is written in DOTTED form ... so it
  glob-matches `*.secret*` and the write is denied"**, and its consequence
  "Any edit that re-authors one of those import lines is therefore denied".
  False since `b149808f`. The token the deny echoed is right; the context the
  document inferred for it is not. The header says the block was hit "while
  writing the F-PRIV-4 regression test", and a test that knocks the module out
  of `sys.modules` or patches it by dotted string is the natural shape; a
  `try: from … import …` collapsed onto ONE line also escapes the line-start
  anchor. The document elided the token's surroundings, so the exact shape
  cannot be recovered from it — and does not need to be, because every
  candidate is a non-import spelling.
- **WRONG — option D "not viable as written: F-PRIV-4's fix cannot be authored
  at all"**. The fix is an import statement plus an `except` clause, and probe
  1 authored precisely that shape today.
- **RIGHT — the three rejected narrowings each lose real protection.**
  Endorsed, and they are also the grounds on which the unbuilt remainder of
  option A is rejected below.
- **RIGHT — the slash form does not match.** `utils/secret_redaction.py`
  carries no `.secret`.
- **Partly right — "A client project would hit the same wall."** Only for a
  non-import spelling; a client's `import`/`from` statements are exempt.

### Why the remaining options fail

**A, the unbuilt remainder (string literals and other non-import positions).**
`open("mykeys.secret")`, `Path(".vault-pass")` and `shutil.copy("id_rsa", …)`
are all a protected filename inside a string literal in a script — the
write-then-execute route the script surface exists to close. The decision's
own second bullet ("a valid dotted identifier is also a plausible protected
FILENAME") is the exact objection. Narrowing further to "strings passed to
`sys.modules` or `mock.patch`" would teach the guard Python call semantics to
recover a case that has a free alternative (below). Rejected.

**B, `allowed_module_paths`.** A string-identity exemption is the shape
`b149808f` removed: its message calls the pre-fix import exemption "a
laundering primitive … an escape hatch in a guard whose own deny text says
there is NO escape hatch", because a token exempted by STRING vanishes
wherever it appears. A human-edited list is narrower than an agent-typed
`import` line, but it is still string-keyed, it is discovered by failure (the
decision says so), and this repository has no need of it. A client with a
genuine need already has `protected_paths` and `mode: replace`, which the
guidance names. Rejected.

**C, rename `secret_redaction`.** Sixteen files import it (`core/router.py`,
`core/front_controller.py`, `daemon/server.py`, `daemon/cli.py`,
`daemon/payload_capture.py`, `handlers/pre_tool_use/sensitive_content.py`,
two QA scripts, three test files, and more). Four sibling modules carry the
same stem in dotted form — `secret_file_guard`, `secret_file_matching`,
`secret_meta`, `secret_redaction` — and the test class docstring at
`test_secret_file_matching.py:612-614` records that the guard's OWN module was
the first collision. Renaming one fixes nothing for three, and the decision's
own objection stands: the tail wagging the dog. Rejected.

## What unblocks F-PRIV-4

Nothing has to change in the guard, its config or its tests. Three authoring
rules for whoever builds F-PRIV-4:

1. **Keep the imports as statements.** The fix at
   `scripts/qa/check_sensitive_content.py:141-162` changes how the two lazy
   imports degrade; the `from … import …` lines stay at line start, as they
   are now. Exempt, verified by probe 1.

2. **Name the module in prose the way the file already does.** Its docstrings
   use the slash form (`utils/secret_redaction`, `:134`, `:156`, `:239`).
   Backticks and quotes are token delimiters, so that spelling yields the token
   `utils/secret_redaction`, which no shipped glob matches. Never the dotted
   form in a docstring or comment — a comment is content too.

3. **Simulate "daemon package not importable" without the dotted string.**
   `monkeypatch.setitem(sys.modules, "claude_code_hooks_daemon", None)` —
   verified today: a subsequent `from claude_code_hooks_daemon.utils import …`
   raises `ModuleNotFoundError`, an `ImportError` subclass. The token
   `claude_code_hooks_daemon` carries no protected stem. It is also the truer
   simulation: the documented failure mode (`:136-139`) is "system Python
   rather than the venv" — the whole package absent, not one submodule. Where
   a test must target the submodule specifically, refer to it through the
   imported module object (`import claude_code_hooks_daemon.utils.secret_redaction as redaction`, then `redaction.__name__` or
   `mock.patch.object(redaction, "load_secret_terms")`): the statement is
   exempt and the object is what the exemption's rationale says is not a file.

   The existing checker tests run the script as a subprocess (`_run_checker`,
   `tests/unit/qa/test_check_sensitive_content.py:29-50`), so a `sys.modules`
   knock-out has to happen inside the child. That is a test-design detail for
   the author, not a guard question. `test_missing_secret_file_is_inert`
   (`:136-142`) pins the current behaviour the F-PRIV-4 design will revisit.

**Is rule 3 "routing around the guard"?** No, and this ruling says so
explicitly so the F-PRIV-4 author does not have to re-decide it. The journal
entry was right to refuse to "assemble the token from pieces": concatenation
manufactures the protected SPELLING at runtime for a reader to consume, and
the guard's honest-limits text names string-assembled paths as a known evasion.
Rule 3 manufactures nothing and reads nothing — the text contains no protected
token and no file is opened. The line between compliance and evasion is
whether the resulting string is handed to something that opens a file; a
`sys.modules` key and a `patch.object` target are handed to the import system.

## What it costs, and who bears it

- **A dotted spelling of a `.secret`-stemmed module in a non-import position
  of a script file stays denied.** Borne by this repository's authors for four
  modules, and by any client with such a module. The cost per incident is one
  denied write and a rewrite to statement or object form; since Plan 00356 the
  deny names the token, so diagnosis is a read, not a bisection.
- **The guidance already records the acceptance.** `get_claude_md`
  (`secret_file_guard.py:371-376`): "`*.secret*` is intentionally broad …
  That is the accepted cost." This ruling extends that recorded acceptance to
  the dotted-module case by name.
- **Nothing else.** Every DENY surface the exemption gates — the Bash route,
  the script route, `flaggable_content_channel_guard`, payload capture's
  suppress decision — is unchanged.

## The strongest argument against, stated fairly

The decision's real charge is that "the guard currently makes one daemon
module un-editable-by-import, in a repository that dogfoods itself". If that
were true, accepting it would be untenable — a guard that forbids maintaining
the code it protects has failed at its own job. It has not been true since
2026-09-06. What remains is that a test author's first instinct
(`patch("…utils.secret_redaction.load_secret_terms")`) is denied and they must
learn the object form. The rebuttal is that the object form is the idiomatic,
rename-safe spelling anyway; the deny message hands them the exact token; and
the string-literal position is the ONE the guard cannot surrender without
re-opening `open("foo.secret")`.

## Human gate?

**None.** This is a determinate reading of `secret_file_matching.py` confirmed
by executing it — two live writes and 17 pinning tests — not a risk appetite.
No installing project's refusal surface changes: the guard denies today
exactly what it denied yesterday, and the decision that was thought to be
needed turns out to have been taken and shipped before it was asked.

## Two footnotes, neither an option

- **Optional, unbuilt, presentation only:** one sentence in `get_claude_md`
  (`secret_file_guard.py:371-376`) saying that a dotted module path is exempt
  in an `import`/`from` statement but not in a string, docstring or comment,
  and pointing at object-form references. It would have saved the decision
  document from being written. Not needed to close F-PRIV-4.
- **The commit-message denial the journal reports** ("writing the commit
  message about it was itself denied once") is the Bash-mention route working
  as designed — a `git commit -m` carrying the dotted path is a Bash command
  containing a matching token, and the guard has no commit-message exemption
  by doctrine. Commit messages name the module in slash form.

With this recorded, F-PRIV-4 is unblocked and the guard is unchanged.

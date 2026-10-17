STOPPING BECAUSE: the review is complete. I found no release-blocking defect.

# Review: rfix3 delta (98a3abdb0..d0fe01743, src/ and tests/)

The three fixes close N500-N503. I re-ran every rv2 probe. All the earlier deny and allow cases now match what was expected, the earlier typo cases (`prinln!`, `Debg`, `tset`) are denied, and the serde case is still excused.

None of the new findings is release-blocking. Each one below is either an edge case or a gap that was already there in a different form. The targeted tests passed: 878 across message_files, the comment extractor, rust_crate_context and the pre_tool_use handlers, filtered by `-k`.

New probes are in:
- `/workspace/untracked/scratch/rv3-msg/probe.py` and `base.py` (`base.py` compares old and new)
- `/workspace/untracked/scratch/rv3-comments/probe.py` (run with argument `base` or `new`)
- `/workspace/untracked/scratch/rv3-rust/` (`c*.rs`, `d*.rs`, `e*.rs`, run through `../rv2-probe/rust_probe.py`)

## MINOR (file as ledger, not blocking)

**M1. Comment extractor: a Rust lifetime can pair with a quoted word inside the comment, so the comment is not seen.**
- Location: `src/claude_code_hooks_daemon/strategies/comments/extractor.py:262-290`
- Case: `impl<'a> Foo<'a> { /* Prior v1.2: see 'foo' here …` is an Edit fragment with an unterminated comment. It gives a span at 98a3abdb0 and none now. `_find_closing_quote` skips the `'` in `<'a` and `'f`, because each is followed by a letter, and then accepts the closing quote of `'foo'`, which sits after the opener.
- The similar case `fn f(x: &'a str) { /* Prior v1.2: the users' list` fails open both before and after this diff.
- This fail-open is introduced by this diff, but it only applies in fragment mode and needs a lifetime, an unclosed comment opener and a quoted word all on one line. That is why I graded it MINOR.
- Fix: when a `'` is directly followed by an identifier and then a non-`'` character (lifetime shape: `'a>`, `'a,`, `'a `), skip it as an opener instead of searching onward for a closer.

**M2. Comment extractor: an unterminated `"` or backtick no longer opens a string, so a multi-line string can be reported as a comment.**
- Location: same function.
- Cases that give a span now and gave none at 98a3abdb0:
  - ``q := `SELECT /* 2026-08-12: hint`` (a Go raw string spanning lines)
  - `` const t = `line /* Prior v1.2: `` (a JS template literal)
  - `let s = "abc /* Prior v1.2:` (an unterminated double-quoted string)
- This can wrongly trigger comment_changelog or comment_size, but only on an Edit fragment whose string continues past the line. The shipped release had no string tracking at all, so this is not a regression against it.
- Fix: require a closing quote only for `'`. Keep the old behaviour, where an unterminated `"` or backtick opens a literal running to the end of the line.

**M3. Rust lint: the similar-name check also turns real external macros and attributes used without a `use` into findings.** This is the rustc output for each case:

| Name | Crate | rustc's similar-name hint |
| --- | --- | --- |
| `#[rstest]` | rstest | suggests `test` |
| `#[instrument]` | tracing | suggests a built-in attribute |
| `formatdoc!` | indoc | suggests `format` |
| `assert_ok!` | claims / tokio-test | suggests `assert_eq` |

- All four were excused at 98a3abdb0, and all four were denied in the shipped release.
- The realistic case is still fine. With an import (`use tracing::instrument; #[instrument]`), rustc stops at E0432 and the file is excused (`e1.rs` to `e3.rs`). So the denial only happens for `#[macro_use] extern crate` style, or an import that lives in another module.
- Coded errors gained no new denials (`d101` to `d121` are all excused).
- This ambiguity comes with rustc's own hint, since `rstest`→`test` looks exactly like `tset`→`test`. Possible fix: also excuse the file when it has `#[macro_use]` or `extern crate`. Otherwise accept this as the trade-off and record it.

**M4. message_files: a reserved word in argument position can leave a group open, which wrongly denies a commit.**
- Location: `src/claude_code_hooks_daemon/utils/message_files.py:68-70`
- Case: `echo do for; ls /tmp/<term>; echo msg > m.txt; git commit -F m.txt` is now denied. It was allowed at baseline.
- Cause: the `(?<=\bdo)` lookbehind makes `for` count as a compound opener. The unbalanced group then runs to the end and pulls in the `ls` that contains the term.
- Contrived, but it is a new wrong denial.
- Fix: accept `then`/`do`/`else`/`elif` as a command start only when that word is itself at a command start, or only count compound openers once `_COMPOUND_CLOSE` balances them.

**M5. message_files: deeply nested subshells raise RecursionError.**
- Location: `_leaves` / `_unwrap`.
- Case: 1000 nested `( … )` around a `cd /tmp/<term> && … git commit -F m.txt` raises `RecursionError`, and takes 3.6s at depth 1000 and 17.5s at depth 3000. The baseline returned in 0.15s.
- The error is caught by the chain's handler-exception path (`core/chain.py:671`). The input is far outside the threat model.
- Fix: limit the recursion depth in `_leaves`, falling back to keeping the statement whole, or make it iterative.
- Also note that `_statements` is O(spans × tokens): a flat 5000-statement, 79 KB command takes 3.3s.

**M6 (pre-existing, not from this diff). A newline after a pipe is a fail-open.**
- `{ echo <term>; } |\ngit commit -F -` and `echo <term> |\ngit commit -F -` are allowed both at baseline and now.
- Cause: `\n` splits statements even directly after a `|`.
- Fix: do not split on a newline that follows a trailing `|`, `&&` or `||`.

## OK
- **N501 / N502 (message_files):** I checked 38 group and compound cases, all as expected:
  - Write inside the group, term outside the message, allowed: `( cd /tmp/T && … )`, `if [ -d /tmp/T ]; then …; fi`, `for/while` bodies with an unrelated `ls`, a nested `{ } > m.txt` inside `( cd … )`.
  - Write outside the group or via a pipe, denied: `{ } > m.txt`, `}>m.txt`, `1>`, `>>`, `| tee`, `| git commit -F -`, `if/for/while/until/select/case … > m.txt`, case with multi-line patterns, `( if … fi ) > m.txt`, the commit inside an `if`.
  - Fuzzing stray `if`/`fi`/`done`/`esac`/`((`/`${x:-(}` raised no exceptions in either handler.
- **N500 (rust):** typo fixtures come from real rustc output. A typo next to serde is still a finding. E0432 for `std::colections` is still excused, which is the accepted N474 behaviour.
- **N503 (extractor):** `it's`, `don't`, `impl<'a>`, a JS regex containing `"`, char literals `'x'`, `'/'`, `b'/'`, `'\''`, and strings holding an opener all behave correctly.
- **N494-N497:** no regressions. agent_assets was not touched.

## Verdict
APPROVE for the tag. Nothing found is a release-blocking regression. M1 and M3 to M5 are new behaviours in this diff but edge-shaped, and M2 is only a regression against 98a3abdb0, not against the shipped release. File M1 to M6 as ledger entries.
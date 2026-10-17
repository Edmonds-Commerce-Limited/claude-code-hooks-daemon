# rfix2-comment-string: fragment-mode `/*` inside a string literal (delta review D2)

## Assumptions

None needed.

## Root cause

`_consume_delimited` in `src/claude_code_hooks_daemon/strategies/comments/extractor.py` treated every unclosed
opener in `unterminated_is_comment=True` mode as a comment to the end of the fragment, with no look at what
precedes the opener on its line.

## Fix

`_is_inside_string(line, position)` (plus `_has_closing_quote`) walks the line up to the opener, tracking
`"`, backtick and `'` literals with backslash escapes. A `'` opens a literal only when a closing `'` follows on the
line, so a Rust lifetime or lone apostrophe does not swallow the rest of the line. The fragment fallback now
applies only when the opener is outside a literal; otherwise it yields no span and scanning resumes on the next line,
as the whole-file rule does. This is more precise than the reviewer's suggested "only at line start", which would
have missed `call(); /* opens here` (kept working, tested). Multi-line literals are not tracked (documented
line-based precision).

## Tests (red then green)

Red before the fix: 26 failed, 130 passed (extractor + comment_size files). New tests:

- `test_extractor.py`: 7 string shapes (glob, `"*/*"`, single-quoted, Go raw string, char `'"'`, escaped quotes,
  call arg) yield no span in fragment mode; a later real comment is still found; 5 outside-string shapes
  (line start, after code, after lifetimes, after a closed string, after a quote char) still read as a comment.
- `test_comment_size.py`: Edit with `glob("dist/*.js")` / `"*/*"` plus 45 code lines is ALLOWED on
  ts-equivalent, go, rs, java, kt, php, cs, swift, dart (18 cases; the SLASH_DOC family covers ts/js/java/kt/php).

Green after: 335 passed across `tests/unit/strategies/comments`, `test_comment_size.py`, `test_comment_changelog.py`.

## Siblings checked

All C-family strategies share the one extractor path (`SLASH_SYNTAX`, `SLASH_DOC_SYNTAX`, `GO_SYNTAX`,
`PHP_SYNTAX`); the handler test runs every one of them. Python docstring openers require line start, so no
prefix exists. `comment_changelog` uses the same call and benefits from the same fix.

## Callout that becomes untrue (not edited, per brief)

File: `CLAUDE/UPGRADES/UNRELEASED/release-notes/028-comment-checks-ignore-a-block-opener-that-never-closes.md`
(now moved on main's tree). Last sentence: "An `Edit` is judged on its `new_string`, a fragment whose closer may lie
in the untouched file, so there an opener with no closer inside the fragment is read as a comment running to the
end of the fragment." Needs: "...unless the opener sits inside a string literal on its line."

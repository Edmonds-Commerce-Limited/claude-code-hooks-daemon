# rfix3-comment-apostrophe

Finding: second delta review MINOR 4, against the N495 fix in `strategies/comments/extractor.py`.

## Root cause

`_is_inside_string` let a quote open a literal on the strength of ANY later quote on the line (`"` and
backtick: none needed). A Rust lifetime `'a`, a regex `/"/`, or an apostrophe in the comment itself
(`it's`) therefore paired with the comment's own text and hid the `/*` opener (fail-open for
comment_size / comment_changelog on Edit fragments).

## Fix

- A quote opens a literal only if `_find_closing_quote` finds a closer on the line; the opener is
  "inside a string" only when that closer lies AFTER the `/*` position.
- A `'` closes only when the next character is not a word character, so `it's`, `don't` and the quote of a
  lifetime (`'a`) can never end a literal.
- `"` and backtick with no closer on the line no longer open anything (regex `/"/`).

The lead's stated rule alone (closer after the opener) would still hide `&'a str) { /* it's`; the
word-character closer rule is what separates the lifetime/apostrophe pair from `'src/*.rs'`.

## Tests

Five rows added to `test_fragment_mode_still_reads_unterminated_opener_outside_a_string`
(the three reviewer examples, `x = it's; /* can't`, `fn f<'a, 'b>(x: &'a T) { /* it's`).
Red against the old code: 5 failed, 50 passed. Green after: strategies/comments plus
test_comment_size and test_comment_changelog, 340 passed. Existing N495 rows (`glob("dist/*.js")`,
`"*/*"`, etc.) unchanged and green.

## Sibling check

`_is_inside_string` is the only string-awareness in the extractor; `_consume_delimited` is its only caller.

## Callouts

No existing release-note callout describes this behaviour; none edited.

Test runs needed `PYTHONPATH=<worktree>/src` because the worktree has no own venv.

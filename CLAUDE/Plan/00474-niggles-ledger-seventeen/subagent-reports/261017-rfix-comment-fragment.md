# rfix-comment-fragment: Edit fragments with an unclosed block opener (reviewer B, D2)

## Assumption

Chose option (a), a caller-chosen parameter, over option (b), extracting from the post-edit file.

- comment_size already compares `old_string` against `new_string` as fragments; (b) would have needed the on-disk file for both handlers, which is unreadable, stale or ambiguous under `replace_all` and a non-unique `old_string`.
- (a) needs no file I/O and applies identically to both handlers. For comment_size, before and after are read in the same mode (fragments for Edit, whole files for Write), so grow/shrink tiering stays consistent.
- Trade-off: a `/*` inside a string in an Edit fragment now opens a comment to the end of the fragment. The damage is bounded by the fragment, and the #75 whole-file case (a comment-free file denied) is unaffected.

## Fix

- `strategies/comments/extractor.py`: `extract_comment_spans(..., *, unterminated_is_comment=False)`; `_consume_delimited` returns a span running to the last line when the flag is set. Default behaviour (#75) is unchanged.
- `comment_changelog.py` and `comment_size.py`: pass `unterminated_is_comment=True` when `tool_name == Edit`, in matches and handle, for both the new and the old text.
- Callout `CLAUDE/UPGRADES/UNRELEASED/release-notes/028-...md` edited: it claimed an Edit's unclosed opener is not counted, which is no longer true.

## Tests

- Extractor: fragment mode for block, doc and docstring openers, and for terminated comments (unchanged).
- comment_changelog: Edit on x.go, x.ts and x.py denied (the reviewer's inputs); Write with the same unclosed opener still allowed; Edit without narrative allowed.
- comment_size: Edit with an unclosed 10-line opener is denied; an unclosed opener that shrinks is allowed; Write with an unclosed opener is still allowed.
- Changed test: `test_edit_fragment_with_opener_and_no_closer_is_not_counted` in test_comment_size.py asserted the old behaviour (ALLOW) that the reviewer showed to be the regression. It is replaced by `..._is_counted_to_the_end` (DENY).
- Red output was not captured: I applied the source change before writing the tests, so I could not quote a red run. The reviewer's probes show the failing behaviour on HEAD, and the changed comment_size test asserted the opposite outcome. Targeted run: 868 passed (strategies/comments, both handler files, docs_qa).

## Sibling code checked

- `docs_qa/comment_finder.py` scans whole files: keeps default, correct.
- `strategies/comments/__init__.py` only a docstring example.
- No other `extract_comment_spans` callers in src/.

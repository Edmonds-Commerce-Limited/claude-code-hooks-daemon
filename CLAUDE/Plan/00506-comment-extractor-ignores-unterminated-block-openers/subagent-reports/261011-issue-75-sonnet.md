# Plan 00506 report: unterminated block openers (GitHub #75)

## Change

- `strategies/comments/extractor.py`: `_consume_delimited` returns `(None, start_index + 1)` when no closer exists later in the content; `extract_comment_spans` skips a `None` span. Only the rest of the opener's line is lost; scanning resumes on the next line as code. Terminated comments are untouched. Module docstring updated.
- Guidance: `comment_size.get_claude_md()` and `docs/guides/HANDLER_REFERENCE.md` (canonical home for per-handler behaviour) both gain a paragraph stating text-scanning limits, the unterminated-opener rule, the still-possible misread bounded by a later closer, and the Edit-fragment behaviour.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/028-comment-checks-ignore-a-block-opener-that-never-closes.md`.
- PLAN.md Tasks 1.1-1.3 ticked.

## Tests (RED first: 8 failures before the change)

- `tests/unit/strategies/comments/test_extractor.py`: new `TestUnterminatedOpeners` (block, doc, python docstring openers; Rust glob-in-string plus 40 functions; resume-as-code; bounded-by-later-closer unchanged; terminated block unchanged). The old `test_unterminated_block_comment_closes_at_eof` was removed because it pinned the defect.
- `tests/unit/handlers/pre_tool_use/test_comment_size.py`: new `TestUnterminatedOpenerIsNotAComment` (issue reproduction allowed with default limits; 45-line terminated block comment still denied; Edit fragment cases).

## Consumers of extract_comment_spans

`comment_size`, `comment_changelog`, `docs_qa/comment_finder.py` (reports block comments of at least N lines in files; a file-wide scan, so it benefits from the same fix and has no fragment concern).

## Edit-path decision

`comment_size` and `comment_changelog` judge an Edit's `new_string` alone. Before: an opener in new_string with its closer outside was counted to the end of the fragment. After: no span.

Decision: keep the ruling, do not add a fix. Reasoning:

- Lines in the middle of a comment (no opener) are already invisible to a fragment, so the fragment guard has never seen a comment whose delimiters straddle the edit. Opener-only is the narrow subcase of that existing blind spot.
- An Edit that inserts a block comment carries both delimiters in new_string and is still counted and denied (pinned by `test_edit_fragment_with_whole_over_limit_block_comment_is_denied`).
- The only way to see across the fragment boundary is reading the file on disk and splicing, a complex fix with its own ambiguity (old_string location); not invented here. If wanted later it should be its own plan.
- The behaviour kept is pinned by `test_edit_fragment_with_opener_and_no_closer_is_not_counted`, and stated in the user guidance and release note.

Python `"""` docstring openers get the same treatment (unterminated never occurs in valid Python); they are doc spans, exempt from comment_size, still scanned by comment_changelog.

## QA run

Targeted only. black (py311), ruff and mypy clean on the touched files. pytest: tests/unit/strategies, test_comment_size, test_comment_changelog and tests/unit/docs_qa (2425 passed); integration handler-reference, pending-release-notes, doc-truth and path-agnostic-docs tests (404 passed). Full suite not run.

# N470 github_urls implementer report

## Assumptions

- No release note: `scripts/qa/` is repo-internal and no client-visible behaviour changed.
- Reused the existing shared helper `git_visible_paths` (`src/claude_code_hooks_daemon/utils/git_repo.py`) rather than
  adding a new one. It lists tracked plus untracked-not-ignored files, which is "tracked or changed".

## Cause

`check_github_urls._walk` took every file `walk_files` found, minus a hard-coded `_SKIP_DIRS` name list. A gitignored
`.coverage` at the root is in no skip dir, so it was read, failed UTF-8 decoding, and became an `unreadable-file`
violation, which fails the gate. The sibling checks `check_install_mode_marker` (`git_visible_paths`) and
`check_inline_suppressions` (`scan_git_file_states`) already drop git-ignored files.

## Change

- `scripts/qa/check_github_urls.py`: `_walk` keeps only paths in `git_visible_paths(root)`. `None` (not a git
  checkout) keeps all files, so non-git fixture trees behave as before.
- An undecodable file that is NOT ignored is unchanged: it is reported as an `unreadable-file` finding (existing
  behaviour, same as the siblings), never a crash. A test now pins that in a git tree.
- `tests/unit/qa/test_check_github_urls.py`: class `TestGitignoredFilesAreNotJudged`, four tests (ignored binary,
  ignored wrong-owner text, untracked-unignored still judged, undecodable unignored is a finding).

## Red output

Before the fix, `pytest tests/unit/qa/test_check_github_urls.py`: 2 failed, 28 passed. The failures were
`test_a_gitignored_binary_file_is_neither_read_nor_reported` (`.coverage` reported unreadable) and
`test_a_gitignored_file_naming_a_wrong_owner_is_not_a_violation`. After: 30 passed.

## Other checks with the same defect (item 3)

Checked every `scripts/qa/` walker that reads files of any extension:

- `check_install_mode_marker`, `check_inline_suppressions`: already filter ignored files and handle decode errors.
- `check_security_downgrade_flags`: walks without the ignored filter, but selects by suffix allow-list
  (`_SCANNED_SUFFIXES`), handles `UnicodeDecodeError`, and has an excluded-dir list. A gitignored file of an allowed
  suffix (for example a stray `.yml` under an ignored dir) would still be judged. Not fixed: not shown to fail, and
  out of N470's scope. Candidate for a follow-up if it ever bites.
- `check_sensitive_content`, `check_repo_hygiene`, `check_signal_targets`, `check_doc_truth`, `check_daemon_dir_cd_in_docs`:
  use `git ls-files` or `git_visible_paths`.
- `audit_shell`, `check_eacces_safe_predicates`, `check_module_length`, `check_unreachable_handle_branch`,
  `audit_capture_corruption`: read without a decode guard, but walk only `*.py`/`*.sh` patterns, so a binary
  tool artefact cannot reach them. No change.

## Docs

N470 marked fixed in NIGGLES.md and STATUS-INDEX.md; PLAN.md counts: open 12 to 11, checkmark rows 145 to 146
(141 to 142 of the 171 N rows).

## QA

See the reply for the `llm_qa.py changed` verdict.

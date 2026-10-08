# N374: v3.69.0 release-review defect fixes

Branch `agent-aae64cfce276ca0ee-93d3dd26`, one commit per item, each pushed after its commit.
Each item was written test first and then run with its handler's or module's existing tests,
`ruff check`, `black --check`, `mypy` on the changed source files and
`scripts/qa/audit_error_hiding.py`. The full gate was not run.

| Item                                                                    | Commit    | Tests added or changed                                                                                                                                 |
| ----------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1. `rg -r/--replace` and other rg value options                         | 49c9f79b0 | `tests/unit/utils/test_recursive_search.py` (`TestRgValueTakingOptions`)                                                                               |
| 2. Glob advisory while the protected-file index builds                  | 331b91d6e | `test_secret_file_guard_advisory.py`, `test_quarantine_artefact_read_guard.py`                                                                         |
| 3. `git push --mirror` / `--prune`, delete constants                    | d35774c67 | `test_destructive_git_remote_ref_deletion.py`                                                                                                          |
| 4. host_command_guard (`-itv`, compose, `/dev/null`, `pypi.python.org`) | ade110aae | `test_host_command_guard.py`                                                                                                                           |
| 5. Plan fact-check delivery: atomic claim, main thread only             | 6163fd0a8 | `test_plan_fact_check.py`, `test_plan_fact_check_feed.py`                                                                                              |
| 6. daemon_sync_after_merge merge directory                              | bfafdeb20 | `test_daemon_sync_after_merge.py`                                                                                                                      |
| 7. `check-effective-handlers` exit 3, upgrade.sh                        | 5181aee6b | new `tests/unit/daemon/test_cli_check_effective_handlers.py`                                                                                           |
| 8. ccy wrapper migration only for the deployed path                     | abcccb0c1 | `tests/unit/install/test_ccy_supervisor.py`                                                                                                            |
| 9. Open-issue listing paginates or fails closed                         | 26dc4151d | `test_github_issue_validity.py`                                                                                                                        |
| 10. Unreadable doc in unlisted-fake-value sweep                         | db5ff2b23 | `test_unlisted_fake_value.py`                                                                                                                          |
| 11. `index_for` docstring                                               | 119233566 | none (docstring only)                                                                                                                                  |
| 12. bash_safe_mode `validate_options`                                   | fa264c98f | `tests/unit/handlers/test_registry_option_validation.py`                                                                                               |
| 13. Grep `file_path` as target                                          | 725ea5d9f | new `tests/unit/core/test_grep_targets.py`, `test_lsp_enforcement_grep_file_path.py`, plus secret guard, quarantine and reference_repo_freshness tests |
| 14. Long agent names in report filenames                                | ac9314af9 | `tests/unit/utils/test_subagent_report_paths.py`                                                                                                       |

## Notes and judgement calls

- **Item 1.** `scan_options` and `_search_reads` now take the command word. rg alone treats `-r`,
  `-E` and its long value options (`--replace`, `--encoding`, `--max-depth`, ...) as taking a
  value. `grep -r`, `grep -E` and `ag -r` are unchanged. The same fix reaches
  `flaggable_content_channel_guard`, which uses the same parser.
- **Item 2.** The reviewer's fix (advisory on any glob while the index is cold) conflicts with the
  existing test `test_an_unrelated_star_bearing_token_stays_allowed` (`cat report-[0-9]*.txt`
  must not engage the guard), and that test was not loosened. The advisory therefore fires only for
  a name-agnostic glob: an unquoted glob whose file-name part carries fewer than
  `_MIN_GLOB_OVERLAP_CHARS` (2) literal characters (`*`, `.*`, `?`, `[a-z]*`). A glob that
  asserts real name text was already judged by the text checks. This is the new
  `sfm.has_name_agnostic_glob`. The quarantine guard only advises for a content-revealing
  segment. The no-index reason text now also names "wildcard path". **Residual:** with a cold index,
  `cat report-*.txt` still gets no advisory.
- **Item 3.** `--mirror` and `--prune` match the delete pattern but are not in `_PUSH_LONG_FLAGS`,
  so the merged-branch allowance cannot clear them (they come back as "could not be verified").
  I did not touch the rule's `blocked` text in `_RULE_DEFINITIONS`, because that text feeds the
  generated CLAUDE.md table; worth a doc follow-up.
- **Item 4.** The lexer drops a redirect's file descriptor (`2>/dev/null` and `>/dev/null` lex
  alike), so the `/dev/null` redirect is read from the command text. Only stdout sent to
  `/dev/null` (`>`, `1>`, `>>`, `&>`) is allowed. `2>/dev/null` is still denied because the token
  still prints. The reviewer also suggested allowing a redirect to any file; I kept to
  `/dev/null`, as the brief said ("output discarded"). If every `gh auth token` spelling cannot be
  matched in the text (a quoted `"gh"`), the command stays denied.
- **Item 5.** `deliver_pending` claims each record by renaming it to a unique dotfile
  (`claim_pending`), so of two concurrent events exactly one delivers. A vanished record is
  skipped, and a claimed unreadable record is set aside with no `FileNotFoundError`. Delivery
  happens only on an event without `agent_id` (`in_subagent`); a sub-agent event still feeds the
  debouncer. The record is not keyed to a session id, so "the owning session" means "the main
  thread".
- **Item 6.** The directory is now taken from the first `git merge|pull|rebase` invocation,
  using `invocation_directory` (its `cd`/`-C` chain). Where the directory cannot be placed
  statically (`cd $DIR`) the session cwd stands in. `effective_cwds` is no longer used here.
- **Item 7.** Exit codes: 0 unchanged, 1 handlers change, 2 cannot run, 3 config not a valid
  YAML mapping. `_load_yaml` now raises `ConfigYamlError(ValueError)` for malformed YAML and a
  non-mapping. `scripts/upgrade.sh` prints a CONFIG ERROR for rc 3. Note: a non-mapping config
  used to exit 2 and now exits 3.
- **Item 8.** **One existing test fixture was changed, not loosened:**
  `test_existing_install_is_migrated_from_the_bare_script_to_the_launcher` used
  `/w/claude-supervise.py` as the "deployed" path. A custom directory is exactly what the finding
  says must be left alone, so the fixture now names the deployed `ccy` directory (same
  assertions otherwise). Migrated spellings: the self-locating `$(cd "$(dirname ...)" && pwd)/`
  form, `.claude/ccy/`, and the absolute target ccy dir. Any other path is left unchanged and named
  in the deploy message.
- **Item 9.** The listing asks for 1000 (`gh` pages internally) and raises `GhError` when the
  result reaches that number.
- **Item 10.** Now a WARNING log plus an ADVISE finding naming the path.
- **Item 11.** Docstring only; no test.
- **Item 12.** `validate_options` has no try/except; the regex check lives in the
  problem-returning helper `_compile_exempt_patterns`, and the setters reuse the same helpers, so
  messages cannot drift.
- **Item 13.** Shared helpers `grep_targets` / `grep_input_for` in `core/utils.py`. Handlers swept:
  `secret_file_guard`, `quarantine_artefact_read_guard`, `reference_repo_freshness`,
  `lsp_enforcement` (the file type of the target). `flaggable_work_advisor` already read both
  fields. `absolute_path`, `daemon_docs_guard`, `remote_docs_routing` and `write_clobber_guard` do
  not handle Grep. When both fields are present, both are judged.
- **Item 14.** `sanitise_component` bounds a component at 100 characters (91 plus `-` plus 8 hex
  of sha256 of the full value). It is ASCII, so characters equal bytes. Normal names are
  unchanged. The size blocker's fallback path uses the same function.

## Not done

Nothing skipped. `scripts/upgrade.sh` was syntax-checked with `bash -n` only.

# Phase 3 Worklist — Handler Classification (scouted 2026-08-31)

Scouted by a read-only agent classifying on **`Decision.DENY` presence**, not
tags (`HandlerTag.BLOCKING` is unreliable: `npm_command` and
`validate_eslint_on_write` are tagged ADVISORY yet deny conditionally; ~16
files set no tags). 48 of ~95 handlers have a deny path; **zero** handlers
override `get_rules()` yet — the migration is entirely greenfield.

## Migration-relevant gotchas

- Deny idiom is `GatingResult`/`BlockingResult(decision=Decision.DENY)` — NOT
  `.deny()` (only `markdown_organization` and `plan_number_helper` use that
  helper). Enum is ALLOW/DENY/ASK/CONTINUE/DEFER (`core/hook_result.py`).
- **Strategy-backed handlers understate badly**: one deny call site each, but
  the real rules live in `src/claude_code_hooks_daemon/strategies/` —
  security (15 language modules), qa_suppression (13), error_hiding (7),
  tdd (14), lint (13), pipe_blocker (11), comments (17). Fan those out over
  the strategy registry, not the handler file. Rule granularity call: one
  Rule per CONCEPT (e.g. R-QA-SUPPRESSION), not per language — the language
  dimension goes in `Rule.verbose`.
- `permission_request/auto_approve_reads.py` has one defensive DENY for
  non-read tools reaching handle(); real surface is allow-or-defer. Do NOT
  file a Rule for it.

## BLOCKING — pre_tool_use (ships denying)

| handler                         | ~deny reasons     | notes                                                            |
| ------------------------------- | ----------------- | ---------------------------------------------------------------- |
| destructive_git                 | ~9-10             | reference migration (in flight)                                  |
| pipe_blocker                    | ~10+              | 11 strategy modules                                              |
| secret_file_guard               | ~5                | tool-read, bash-mention, authoring, grep-dir, consumer allowlist |
| sensitive_content               | ~4                | public patterns, secret word list, git-metadata routes           |
| sed_blocker                     | ~4-5              | 4 ordered exemptions + Write-tool branch                         |
| plan_time_estimates             | ~5                |                                                                  |
| validate_instruction_content    | ~5                |                                                                  |
| dangerous_permissions           | ~4                |                                                                  |
| markdown_organization           | ~3                | uses `.deny()` helper                                            |
| ask_user_question_blocker       | ~3                |                                                                  |
| absolute_path                   | ~2-3              |                                                                  |
| root_recursion_guard            | ~2                |                                                                  |
| curl_pipe_shell                 | ~2                |                                                                  |
| git_message_backtick            | ~2                |                                                                  |
| artifact_publish_blocker        | ~2                | no escape hatch                                                  |
| error_hiding_blocker            | 1 × 7 langs       | strategies/error_hiding/                                         |
| qa_suppression                  | 1 × 13 langs      | strategies/qa_suppression/                                       |
| security_antipattern            | 5 cats × 15 langs | strategies/security/                                             |
| tdd_enforcement                 | 1 × 14 langs      | strategies/tdd/                                                  |
| lock_file_edit_blocker          | 1 (~10 filenames) |                                                                  |
| write_clobber_guard             | 1                 |                                                                  |
| worktree_file_copy              | 1                 |                                                                  |
| daemon_location_guard           | 1                 |                                                                  |
| gh_issue_comments               | 1                 |                                                                  |
| gh_pr_comments                  | 1                 |                                                                  |
| sudo_pip                        | 1                 |                                                                  |
| pip_break_system                | 1                 |                                                                  |
| plan_number_helper              | 1                 | uses `.deny()` helper                                            |
| lsp_enforcement                 | ~5                | block_once default                                               |
| flaggable_content_channel_guard | ~5                | ships disabled (opt-in)                                          |
| quarantine_artefact_read_guard  | ~2                | ships disabled (opt-in)                                          |
| npm_command                     | ~2                | denies only when `llm:` scripts exist                            |

## BLOCKING — other events

| handler                  | event         | ~deny reasons       | notes                                                                |
| ------------------------ | ------------- | ------------------- | -------------------------------------------------------------------- |
| lint_on_edit             | post_tool_use | 1 × 13 langs        | denial = failure report, not rollback                                |
| validate_eslint_on_write | post_tool_use | ~3                  | errors / timeout / run failure                                       |
| auto_continue_stop       | stop          | ~4+ (10 DENY sites) | STOPPING BECAUSE, tautological question, tool_use_error, goal ledger |

## MIXED-MODE (mode knob; deny path exists — still declare rules)

| handler                    | ships as          | ~deny reasons               |
| -------------------------- | ----------------- | --------------------------- |
| ancestry_preserving_merge  | block             | 3                           |
| git_stash                  | deny              | 3                           |
| github_auto_close_keywords | block             | keyword×ref forms, 4 routes |
| comment_changelog          | block             | 2 blocking (+4 advisory)    |
| comment_size               | block             | 2 limits, tiered            |
| plan_qa_edit               | block (edit_mode) | ~34 check modules           |
| docs_qa_edit               | warn (edit_mode)  | ~7 checks                   |
| plan_qa_commit_gate        | warn              | ~10 invariants              |
| docs_qa_commit_gate        | warn              | 2                           |
| bash_safe_mode             | warn              | 1                           |
| staged_lint_gate           | warn              | 1                           |
| verification_result_gate   | warn              | 1                           |

## ADVISORY-ONLY (Decision C: lighter entry, NO rules/disclosure)

- pre_tool_use: agent_isolation_advisor, british_english, daemon_docs_guard,
  daemon_restart_verifier, flaggable_work_advisor, global_npm_advisor,
  plan_workflow, web_search_year
- post_tool_use: background_process_tracker, command_hints,
  git_hooks_executable_fixer, goal_injection, markdown_table_formatter,
  recovery_cron_advisor
- session_start: all 17 (none deny)
- user_prompt_submit: critical_thinking_advisory, git_context_injector,
  idle_housekeeping_advisor, standing_authorisations
- nitpick: dismissive_language, hedging_language
- pre_compact / worktree_create / worktree_remove / status_line: none deny

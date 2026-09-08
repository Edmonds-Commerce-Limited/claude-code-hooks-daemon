# Plan 00242 — Terminal handler classification (Task 1.1) and the fate of the flag (Task 4.1)

## Ground rule

`Handler.__init__` defaults `terminal=True`, so a handler is terminal if it
passes `terminal=True` OR says nothing. 42 shipped handlers are terminal: 17
explicitly, 25 by omission. Every handler passing `terminal=False` is
excluded (77 of them).

Three classes, as the plan framed them:

- **A — only-ever-denies**: every path `matches()` admits ends in
  DENY/ASK/DEFER; any `ALLOW` in `handle()` is a defensive fallback
  `matches()` makes unreachable.
- **B — reachable ALLOW**: `handle()` returns ALLOW on a path `matches()`
  admits — a "content is clean" outcome, a configurable advisory mode, a
  block-once ladder, an escape hatch. **This was the defect class**: before
  Plan 00242 that ALLOW ended the chain and silently disabled every handler
  behind it.
- **C — ALLOW as the point**: the approval IS the handler's output and
  "approve and stop" is the intended semantic.

Evidence column: the line(s) in `handle()` that return ALLOW (grep-verified
on the delivery commit; `—` = no reachable allow).

## The table

| Event             | Handler                           | Source   | Class | Evidence                                                                                              |
| ----------------- | --------------------------------- | -------- | ----- | ----------------------------------------------------------------------------------------------------- |
| PermissionRequest | `auto_approve_reads`              | default  | C     | line 82: ALLOW for Read/Glob/Grep in bypass mode — the approval is the output                         |
| PostToolUse       | `validate_eslint_on_write`        | default  | B     | 252/267/357: ALLOW when no path, not a TS file, or ESLint passes (normal outcome)                     |
| PreToolUse        | `absolute_path`                   | default  | A     | —                                                                                                     |
| PreToolUse        | `artifact_publish_blocker`        | explicit | B     | 266: ALLOW for a non-publishing Artifact action                                                       |
| PreToolUse        | `ask_user_question_blocker`       | default  | B     | 140/145: ALLOW (with context) when every question is `ASKING BECAUSE:`-prefixed                       |
| PreToolUse        | `curl_pipe_shell`                 | explicit | A     | single defensive allow                                                                                |
| PreToolUse        | `daemon_location_guard`           | explicit | A     | —                                                                                                     |
| PreToolUse        | `dangerous_permissions`           | explicit | A     | single defensive allow                                                                                |
| PreToolUse        | `destructive_git`                 | default  | B     | 309: ALLOW on the `MUST_..._BECAUSE` escape hatch                                                     |
| PreToolUse        | `error_hiding_blocker`            | default  | B     | 193/197/202: ALLOW for excluded path, unsupported language, or clean content                          |
| PreToolUse        | `flaggable_content_channel_guard` | explicit | B     | 243: ALLOW when the command shape is not content-revealing                                            |
| PreToolUse        | `gh_issue_comments`               | default  | A     | single defensive allow; `matches()` admits only the `--comments`-less shape                           |
| PreToolUse        | `gh_pr_comments`                  | default  | A     | as above                                                                                              |
| PreToolUse        | `git_message_backtick`            | default  | A     | single defensive allow                                                                                |
| PreToolUse        | `lock_file_edit_blocker`          | explicit | A     | single defensive allow                                                                                |
| PreToolUse        | `lsp_enforcement`                 | default  | B     | 456: advisory mode; 470: block-once after the first deny — ALLOW is the STEADY STATE                  |
| PreToolUse        | `markdown_organization`           | default  | B     | 717–864, 1220: nine ALLOW paths, most with context — an advisory handler at priority 50               |
| PreToolUse        | `npm_command`                     | default  | B     | 236/273/283: ALLOW when unparsable or when the `llm:` wrapper is already used                         |
| PreToolUse        | `pip_break_system`                | explicit | A     | single defensive allow                                                                                |
| PreToolUse        | `pipe_blocker`                    | default  | A     | defensive allows only; whitelisted producers are filtered in `matches()`                              |
| PreToolUse        | `plan_number_helper`              | explicit | A     | defensive allows; `matches()` admits only the hand-`mkdir` shape                                      |
| PreToolUse        | `plan_time_estimates`             | default  | A     | —                                                                                                     |
| PreToolUse        | `project_containment`             | explicit | B     | 495: ALLOW for an in-repo destination                                                                 |
| PreToolUse        | `qa_suppression`                  | default  | B     | 193–210: ALLOW for excluded path, unsupported language, or clean content                              |
| PreToolUse        | `quarantine_artefact_read_guard`  | explicit | B     | 272: ALLOW for a non-DETAIL artefact                                                                  |
| PreToolUse        | `remote_docs_commit_gate`         | default  | B     | 115/138: ALLOW when nothing staged under the remote-docs tree, or provenance valid                    |
| PreToolUse        | `remote_docs_provenance`          | default  | A     | single defensive allow                                                                                |
| PreToolUse        | `remote_docs_routing`             | default  | B     | 190–221: ALLOW with advisory context (routing hints)                                                  |
| PreToolUse        | `root_recursion_guard`            | default  | A     | single defensive allow                                                                                |
| PreToolUse        | `secret_file_guard`               | explicit | B     | 289: ALLOW when the path is not protected                                                             |
| PreToolUse        | `security_antipattern`            | default  | B     | 238/242/246: ALLOW for excluded path, unsupported language, or clean content                          |
| PreToolUse        | `sed_blocker`                     | default  | A     | — (deny-by-default; exemptions are decided in `matches()`)                                            |
| PreToolUse        | `sensitive_content`               | default  | B     | 685: ALLOW when no pattern or secret term matches                                                     |
| PreToolUse        | `sudo_pip`                        | explicit | A     | single defensive allow                                                                                |
| PreToolUse        | `tdd_enforcement`                 | default  | B     | 416/420/438: ALLOW for exempt paths, existing test, or an edit (not a create)                         |
| PreToolUse        | `validate_instruction_content`    | default  | B     | 221/246: ALLOW (advisory context) for clean instruction files                                         |
| PreToolUse        | `web_search_year`                 | default  | B     | 62: ALLOW with `updated_input` — the rewrite IS the outcome                                           |
| PreToolUse        | `worktree_file_copy`              | default  | A     | —                                                                                                     |
| Stop              | `auto_continue_stop`              | explicit | B     | 697/758: ALLOW on a stop carrying `STOPPING BECAUSE:` — the ALLOWED stop shadowed everything above 10 |
| SubagentStop      | `subagent_report_size_blocker`    | explicit | B     | 123/127: ALLOW when the report is small or written to a file                                          |
| WorktreeCreate    | `worktree_create_handler`         | explicit | C     | ALLOW carrying `worktree_path` — the result is the output                                             |
| WorktreeRemove    | `worktree_remove_handler`         | explicit | C     | ALLOW is the completion signal                                                                        |

Counts: **A = 17, B = 22, C = 3.**

## Reading

- More than half of the terminal handlers (22) had a reachable ALLOW. The
  content scanners (`error_hiding_blocker`, `security_antipattern`,
  `qa_suppression`, `sensitive_content`, `tdd_enforcement`) all sit at
  priorities 10–20 and ALLOW clean content as their NORMAL outcome, so on
  every clean Write/Edit the first of them to match ended the chain and
  every later PreToolUse handler for that write never ran. This is why Plan
  00241's "configurable warn mode" rule was too narrow: it caught 4 of the
  22\.
- `markdown_organization` (nine ALLOW paths, advisory context, priority 50)
  and `auto_continue_stop` (every allowed stop) are the two largest single
  shadows.
- Class C is genuinely per-event: PermissionRequest approval, and the two
  worktree events whose ALLOW carries the result payload. Only
  PermissionRequest needs `allow_is_final`; the worktree chains have one
  handler each, so continuing past their ALLOW changes nothing.

## Task 4.1 — what happens to `terminal`

Under the invariant delivered in `ab3cab93` the flag can no longer change
what the chain decides: an ALLOW continues regardless, a DENY wins
regardless (most-restrictive-wins). Its only remaining effect is whether the
rest of the chain runs after this handler's DENY — a blocked-path
optimisation, measured at up to ~2 ms (`MEASUREMENTS.md`).

**Kept, reduced to that optimisation.** Deleting it would touch 125
handler constructors, the docs generator's BLOCKING/ADVISORY fallback
(`_detect_behavior`), `hooks-daemon handlers` output, the verdict-log
schema (`HandlerVerdict.terminal`) and every project handler in client
repos — for a stability release, with no semantic gain. The classification
above is therefore historical: none of the 22 Class B ALLOWs can shadow
anything now, and `tests/integration/test_allow_never_ends_the_chain.py`
keeps it that way for any handler, shipped or project-level.

# Plan 00242 — Terminal handler classification (Task 1.1) and the fate of the flag (Task 4.1)

## Ground rule

`Handler.__init__` defaults `terminal=True`, so a handler is terminal if it
passes `terminal=True` OR says nothing. No base class in
`core/handler_bases.py` sets the flag. 42 shipped handlers are terminal: 16
explicitly, 26 by omission. Every handler passing `terminal=False` is
excluded. `HookResult.decision` defaults to ALLOW, so a bare
`AdvisoryResult()` is an ALLOW.

Three classes, as the plan framed them:

- **A — only-ever-denies**: every path `matches()` admits ends in
  DENY/ASK/DEFER; any `ALLOW` in `handle()` is a defensive fallback that
  `matches()` makes unreachable (typically a re-check of what `matches()`
  already proved).
- **B — reachable ALLOW**: `handle()` returns ALLOW on a path `matches()`
  admits — a "content is clean" outcome, a configurable advisory mode, a
  block-once ladder, a project-state downgrade. **This was the defect
  class**: before Plan 00242 that ALLOW ended the chain and silently disabled
  every handler behind it.
- **C — ALLOW as the point**: the approval IS the handler's output and
  "approve/service and stop" is the intended semantic.

Line numbers are on the delivery commit (`ab3cab93`); the read was
line-by-line of `matches()` and `handle()` by the `terminal-classifier`
sub-agent, cross-checked against a grep of allow-returning branches.

## The table

| Event             | Handler                           | Source   | Class | Evidence                                                                                                                                  |
| ----------------- | --------------------------------- | -------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| PermissionRequest | `auto_approve_reads`              | default  | C     | matches() L64-68 admits only read-only tools in bypass mode; ALLOW L82 is the point                                                       |
| PostToolUse       | `validate_eslint_on_write`        | default  | B     | ALLOW L357 when ESLint passes (normal); L266 when package.json has no `llm:` scripts (declared downgrade)                                 |
| PreToolUse        | `absolute_path`                   | default  | A     | deny-only (L124)                                                                                                                          |
| PreToolUse        | `artifact_publish_blocker`        | explicit | A     | defensive allow L266 re-calls matches(); unreachable                                                                                      |
| PreToolUse        | `ask_user_question_blocker`       | default  | B     | matches() admits EVERY AskUserQuestion; ALLOW L140 when all questions are prefixed (normal); L144 advisory mode                           |
| PreToolUse        | `curl_pipe_shell`                 | explicit | A     | defensive allow L312, unreachable                                                                                                         |
| PreToolUse        | `daemon_location_guard`           | explicit | A     | deny-only (L129)                                                                                                                          |
| PreToolUse        | `dangerous_permissions`           | explicit | A     | defensive allow L145, unreachable                                                                                                         |
| PreToolUse        | `destructive_git`                 | default  | A     | defensive allow L309; an unrecognised rule still DENYs generically at L319                                                                |
| PreToolUse        | `error_hiding_blocker`            | default  | A     | allows L193/197/202 re-check what matches() L159-174 proved; unreachable                                                                  |
| PreToolUse        | `flaggable_content_channel_guard` | explicit | A     | defensive allow L243, unreachable                                                                                                         |
| PreToolUse        | `gh_issue_comments`               | default  | A     | defensive allow L145, unreachable                                                                                                         |
| PreToolUse        | `gh_pr_comments`                  | default  | A     | defensive allow L162, unreachable                                                                                                         |
| PreToolUse        | `git_message_backtick`            | default  | A     | deny-only (L153)                                                                                                                          |
| PreToolUse        | `lock_file_edit_blocker`          | explicit | A     | defensive allow L170, unreachable                                                                                                         |
| PreToolUse        | `lsp_enforcement`                 | default  | B     | ALLOW L470 on every match after the first block in the default `block_once` mode; L456 in advisory / no-LSP advisory                      |
| PreToolUse        | `markdown_organization`           | default  | B     | planning-mode writes matched at L958 ALLOW after scaffolding: L823, L843/851/859/864, fallbacks L733/743/753                              |
| PreToolUse        | `npm_command`                     | default  | B     | ALLOW+advisory L282 when package.json has no `llm:` scripts (declared downgrade); L236/272 defensive                                      |
| PreToolUse        | `pip_break_system`                | explicit | A     | defensive allow L127, unreachable                                                                                                         |
| PreToolUse        | `pipe_blocker`                    | default  | A     | deny-only (L1102 prose, L1116 blacklist/unknown)                                                                                          |
| PreToolUse        | `plan_number_helper`              | explicit | A     | deny-only (L515, L521, `_deny_hand_rolled_creation` L232)                                                                                 |
| PreToolUse        | `plan_time_estimates`             | default  | A     | deny-only (L193); carries a `NON_TERMINAL` tag at L98 despite being terminal                                                              |
| PreToolUse        | `project_containment`             | explicit | A     | defensive allow L495, unreachable                                                                                                         |
| PreToolUse        | `qa_suppression`                  | default  | A     | allows L193-210 duplicate matches() L157-178; unreachable                                                                                 |
| PreToolUse        | `quarantine_artefact_read_guard`  | explicit | A     | defensive allow L272, unreachable                                                                                                         |
| PreToolUse        | `remote_docs_commit_gate`         | default  | B     | matches() admits EVERY `git commit`; ALLOW L138 when nothing staged lacks provenance — essentially every commit; L115 on index error      |
| PreToolUse        | `remote_docs_provenance`          | default  | A     | deny-only (L128)                                                                                                                          |
| PreToolUse        | `remote_docs_routing`             | default  | B     | ALLOW+advisory L190 (Read of a vendored doc), L207 (unvendored fetch), L220 (stale copy)                                                  |
| PreToolUse        | `root_recursion_guard`            | default  | A     | deny-only (L202)                                                                                                                          |
| PreToolUse        | `secret_file_guard`               | explicit | A     | defensive allow L289, unreachable                                                                                                         |
| PreToolUse        | `security_antipattern`            | default  | A     | allows L238/242/246 re-check matches() L216-230; unreachable                                                                              |
| PreToolUse        | `sed_blocker`                     | default  | A     | deny-only (L388)                                                                                                                          |
| PreToolUse        | `sensitive_content`               | default  | A     | defensive allow L685, unreachable in practice (matches() and handle() each re-read the word list)                                         |
| PreToolUse        | `sudo_pip`                        | explicit | A     | defensive allow L134, unreachable                                                                                                         |
| PreToolUse        | `tdd_enforcement`                 | default  | B     | matches() only proves "a production-source Write"; ALLOW L438 whenever a test file exists — the compliant case; L416/420 defensive        |
| PreToolUse        | `validate_instruction_content`    | default  | B     | matches() admits every CLAUDE.md/README.md write; ALLOW+context L245 for clean content (normal); L220 defensive                           |
| PreToolUse        | `web_search_year`                 | default  | B     | NO deny path: ALLOW+context L61 is the only outcome; tagged `NON_TERMINAL` at L34 while terminal                                          |
| PreToolUse        | `worktree_file_copy`              | default  | A     | deny-only (L151)                                                                                                                          |
| Stop              | `auto_continue_stop`              | explicit | B     | ALLOW L697 on a `STOPPING BECAUSE:` stop (the normal clean stop); L758 when `force_explanation: false`                                    |
| SubagentStop      | `subagent_report_size_blocker`    | explicit | B     | matches() admits every non-re-entry SubagentStop; ALLOW L127 when the report is under 4000 chars (normal)                                 |
| WorktreeCreate    | `worktree_create_handler`         | explicit | C     | matches() unconditionally True; creates the worktree and returns `AdvisoryResult(worktree_path=...)` L112 — the ALLOW carries the payload |
| WorktreeRemove    | `worktree_remove_handler`         | explicit | C     | matches() unconditionally True; removes/prunes then returns `AdvisoryResult()` L69                                                        |

Counts: **A = 27, B = 12, C = 3.**

## Reading

- All 12 Class B ALLOWs are NORMAL outcomes, not escape hatches. Ranked by
  how often the allow fired — i.e. how often every handler behind it was
  silently skipped: `remote_docs_commit_gate` (essentially every
  `git commit`), `auto_continue_stop` (every clean stop),
  `subagent_report_size_blocker` (every small report), `tdd_enforcement`
  (every compliant source write), `validate_instruction_content` (every clean
  CLAUDE.md/README.md write), `web_search_year` (every match — it has no
  deny path), `ask_user_question_blocker` (every prefixed question),
  `validate_eslint_on_write` (every passing lint), `lsp_enforcement` (every
  symbol grep after the first), `markdown_organization` (every planning-mode
  plan write), `remote_docs_routing`, `npm_command`. Plan 00241's
  "configurable warn mode" rule caught the mode-driven subset; the rest are
  why the rule had to become an invariant.
- Class C is genuinely per-event: PermissionRequest approval, and the two
  worktree events whose ALLOW carries the result payload ("service and
  stop" rather than "approve and stop"). Only PermissionRequest needs
  `allow_is_final`; the worktree chains have one handler each, so
  continuing past their ALLOW changes nothing.
- Declaration mismatch, left as found (a stability release): four terminal
  handlers carry a `HandlerTag.NON_TERMINAL` tag — `web_search_year:34`,
  `npm_command:147`, `validate_eslint_on_write:134`,
  `plan_time_estimates:98`. The generated handler table prefers the
  BLOCKING/ADVISORY tags and only falls back to the flag, so nothing
  user-visible depends on it; worth a follow-up sweep.

## Task 4.1 — what happens to `terminal`

Under the invariant delivered in `ab3cab93` the flag can no longer change
what the chain decides: an ALLOW continues regardless, a DENY wins
regardless (most-restrictive-wins). Its only remaining effect is whether the
rest of the chain runs after this handler's DENY — a blocked-path
optimisation, measured at up to ~2 ms (`MEASUREMENTS.md`).

**Kept, reduced to that optimisation.** Deleting it would touch every
handler constructor, the docs generator's BLOCKING/ADVISORY fallback
(`_detect_behavior`), `hooks-daemon handlers` output, the verdict-log schema
(`HandlerVerdict.terminal`) and every project handler in client repos — for
a stability release, with no semantic gain. The classification above is
therefore historical: none of the 12 Class B ALLOWs can shadow anything now,
and `tests/integration/test_allow_never_ends_the_chain.py` keeps it that way
for any handler, shipped or project-level.

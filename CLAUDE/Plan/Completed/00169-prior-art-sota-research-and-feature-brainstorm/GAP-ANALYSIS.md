# Plan 00169 — Gap Analysis

Every external idea from [RESEARCH-FINDINGS.md](RESEARCH-FINDINGS.md) mapped
against our current handler set (from `.claude/HOOKS-DAEMON.md`, v3.42.0).

**Legend**: ✅ **HAVE** — we do this well · 🟡 **PARTIAL** — we have adjacent/weaker
coverage · ❌ **MISSING** — genuine gap.

Ranking of candidate features derived from this table lives in
[FEATURE-BACKLOG.md](FEATURE-BACKLOG.md).

---

## Security & secrets

| External idea                                               | Status     | Our closest handler / note                                                                           |
| ----------------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------- |
| Secret/`.env` read blocker (Read/Bash `cat`)                | ❌ MISSING | Nothing guards secret-file reads                                                                     |
| Output secret scanner + redaction                           | ❌ MISSING | No PostToolUse output scan; `updatedToolOutput` unused                                               |
| Gitleaks-backed secret detection on Write/commit            | ❌ MISSING | `security_antipattern` has hand-rolled hardcoded-credential regex only                               |
| Supply-chain / malicious-package gate on installs           | 🟡 PARTIAL | `lock_file_edit_blocker` protects lockfiles; no reputation/behaviour check                           |
| OS-sandbox execution mode (bubblewrap/Seatbelt)             | ❌ MISSING | All command guards are string-matchers; no kernel enforcement                                        |
| Network-egress allowlist proxy                              | ❌ MISSING | `curl_pipe_shell` blocks `curl\|sh`; no egress control                                               |
| Lethal-trifecta / spotlighting advisory on untrusted reads  | ❌ MISSING | We fetch web/issues/files with no injection-awareness advisory                                       |
| CLAUDE.md / instructions prompt-injection scan              | ❌ MISSING | `validate_instruction_content` checks *ephemerality*, not injection                                  |
| Presidio-style PII redaction on writes                      | ❌ MISSING | —                                                                                                    |
| ConfigChange guard (protect daemon config mid-session)      | ❌ MISSING | No handler on ConfigChange                                                                           |
| Catastrophic-bash guards (`rm -rf ~`, fork bomb, chmod 777) | ✅ HAVE    | `destructive_git`, `dangerous_permissions`, `root_recursion_guard`, `curl_pipe_shell`, `sed_blocker` |
| Protected-path carve-outs                                   | 🟡 PARTIAL | `daemon_location_guard` + `worktree_file_copy` hardcode paths; not config-driven                     |

## Permission / guardrail model

| External idea                                          | Status     | Our closest handler / note                                                                       |
| ------------------------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------ |
| allow/ask/deny bash gating w/ glob precedence (config) | 🟡 PARTIAL | We have fixed denylist handlers + `auto_approve_reads`; no config-driven allow/ask/deny for bash |
| Allowlist-first over denylist                          | ❌ MISSING | Our bash posture is denylist-only (the pattern Cursor got burned on)                             |
| Exact-command vs prefix matching                       | 🟡 PARTIAL | Handlers match substrings; no exact-match allowlist mode                                         |
| Two-axis sandbox × approval posture                    | 🟡 PARTIAL | `auto_approve_reads` is YOLO/bypassPermissions-aware; single-axis                                |
| Second-LLM risk reviewer for escape hatches            | ❌ MISSING | `MUST_*_BECAUSE=` escape hatches trust prose blindly                                             |
| `updatedInput` auto-fix instead of block               | ❌ MISSING | `gh_pr_comments`/`gh_issue_comments`/`absolute_path` block+retry instead of rewriting args       |
| PermissionRequest `permissionRulesToAdd` (learn rules) | ❌ MISSING | `auto_approve_reads` re-decides every call                                                       |
| Per-agent/subagent tool permission scoping             | ❌ MISSING | Project-handlers have no role-scoped permission sets                                             |

## Workflow enforcement

| External idea                                        | Status     | Our closest handler / note                                               |
| ---------------------------------------------------- | ---------- | ------------------------------------------------------------------------ |
| Protect-tests (block deleting/editing red tests)     | ❌ MISSING | `tdd_enforcement` requires a test to exist; doesn't stop deletion        |
| Test-integrity / "gaming" detector                   | ❌ MISSING | No detection of edit-test-then-claim-pass                                |
| Auto-lint/auto-test self-fix loop (feed errors back) | 🟡 PARTIAL | `lint_on_edit` + `bash_error_detector` advise; no enforced feedback loop |
| Stop-gate quality checks (block stop until green)    | 🟡 PARTIAL | `task_completion_checker` advises; doesn't re-run/block                  |
| Branch guard (edits/commits on main)                 | 🟡 PARTIAL | `destructive_git` blocks force-push; nothing blocks editing on main      |
| Auto-checkpoint before risky ops (WIP commit)        | ❌ MISSING | We *block* destructive git; don't snapshot first                         |
| Iteration / request-cap circuit breaker              | ❌ MISSING | No per-session tool-call cap                                             |
| Subagent spawn-budget (PreToolUse:Task)              | ❌ MISSING | `task_tdd_advisor` advises; no spawn budget                              |
| Copyright-header / naming-convention enforcement     | ❌ MISSING | Niche; not covered                                                       |
| TDD enforcement                                      | ✅ HAVE    | `tdd_enforcement`                                                        |
| Plan-workflow enforcement                            | ✅ HAVE    | `plan_qa_*`, `plan_workflow`, `plan_number_helper`, journalling          |
| LSP-over-grep                                        | ✅ HAVE    | `lsp_enforcement`                                                        |

## Context / memory / orchestration

| External idea                                              | Status     | Our closest handler / note                                            |
| ---------------------------------------------------------- | ---------- | --------------------------------------------------------------------- |
| Continuous stale-tool-result clearing (early)              | ❌ MISSING | Supervisor injects `/compact` at red only — late + coarse             |
| Save-to-memory before compaction                           | ❌ MISSING | `transcript_archiver` archives; doesn't force a decisions/bugs flush  |
| Enforce 1–2k distilled-summary contract on subagents       | ❌ MISSING | No policy on subagent return size                                     |
| Tiered memory (core vs recall)                             | 🟡 PARTIAL | CLAUDE.md + plan journals exist; no explicit hot/cold tiering         |
| Loop/stuck detection for recovery cron                     | ❌ MISSING | Recovery cron distinguishes idle vs busy, not stalled vs livelocked   |
| Budget + circuit-breaker for sub-agents/bg processes       | 🟡 PARTIAL | `background_process_tracker` surfaces, never kills; no token/cost cap |
| Deterministic orchestration wrapper (Conductor)            | 🟡 PARTIAL | Release/plan flows are doc-driven, not a deterministic engine         |
| Auto-resume after rate-limit/interruption                  | ✅ HAVE    | `recovery_cron_advisor` — ahead of upstream                           |
| StopFailure-native recovery trigger                        | 🟡 PARTIAL | We poll hourly; the native `StopFailure` event is unused              |
| Shadow-git per-turn checkpoint + context-preserving rewind | ❌ MISSING | Checkpoint commits are *policy*, not an automatic shadow ref          |
| Compaction signalling to a supervisor                      | ✅ HAVE    | `compaction_signal`, PTY supervisor auto-`/compact`                   |

## Observability

| External idea                                   | Status     | Our closest handler / note                                                                         |
| ----------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------- |
| Per-session scorecard at Stop                   | ❌ MISSING | We log pieces (notifications, subagent completions) but don't aggregate                            |
| Guardrail-block analytics (unique to us)        | ❌ MISSING | Block decisions + reasons not aggregated/queried                                                   |
| Local session-analytics dashboard (HTML)        | ❌ MISSING | JSONL written; no renderer                                                                         |
| Emit OTEL GenAI-compatible spans                | ❌ MISSING | No OTLP export                                                                                     |
| Context-pressure / compaction analytics         | 🟡 PARTIAL | `context_sidecar` writes state; not aggregated over time                                           |
| Time-to-green / red→green tracker               | ❌ MISSING | `bash_error_detector` sees test output but doesn't track cycles                                    |
| Edit/revert code-turnover tracker               | ❌ MISSING | —                                                                                                  |
| Trajectory replay export                        | ❌ MISSING | Ordered event stream exists in logs; no exporter                                                   |
| Regression detection on our own behaviour       | ❌ MISSING | No baseline store across daemon upgrades                                                           |
| Per-session cost/token logging                  | 🟡 PARTIAL | `usage_tracking` + `model_context` show live %; no durable per-session record (native OTEL has it) |
| Outbound notifications (Slack/ntfy/desktop/TTS) | ❌ MISSING | `notification_logger` logs only; doesn't emit                                                      |
| Dead-rules / dead-guidance audit                | ❌ MISSING | No `InstructionsLoaded` telemetry                                                                  |
| Event-stream logging                            | 🟡 PARTIAL | Several JSONL loggers exist, uncorrelated                                                          |

## Ecosystem interop

| External idea                                  | Status     | Our closest handler / note                                                        |
| ---------------------------------------------- | ---------- | --------------------------------------------------------------------------------- |
| AGENTS.md read/validate/sync                   | ❌ MISSING | `markdown_organization` governs CLAUDE memory only                                |
| Codified workflows as validated units          | 🟡 PARTIAL | Skills exist; `.claude/workflows/` not validated                                  |
| Declarative policy config (validated document) | 🟡 PARTIAL | Rich YAML config already; not a single validated policy doc with allow/deny lists |

---

## Gap summary (counts)

- **✅ HAVE**: catastrophic-bash guards, TDD, plan-workflow/QA, LSP-over-grep,
  auto-resume, compaction signalling — our core is strong and, on auto-resume,
  ahead of upstream.
- **🟡 PARTIAL** (~15): mostly *advisory where SOTA enforces*, or *hardcoded where
  SOTA is config-driven* (protected paths, allow/deny, lint-loop, budgets,
  cost logging, tiered memory).
- **❌ MISSING** (~30): concentrated in four buckets — **secrets/sandboxing**,
  **observability from our own event stream**, **checkpoint/rewind**, and
  **context hygiene**. These four are where the highest-value, most on-brand
  candidate features live.

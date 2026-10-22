# ANALYSIS: Plan workflow and workflow enforcement under opencode (Plan 00549 Task 2.2)

The harness refused a Write to the canonical `ANALYSIS-plan-workflow.md` path twice, so this is the coordinator's
fallback location. Move it to `../ANALYSIS-plan-workflow.md` when landing it.

Research only. It answers the owner's question "can we force/provision plan workflow stuff?" for opencode.

**Baselines.** opencode clone `untracked/repos/opencode` at `c93aaae37157d785f76a8e9a9243a6560e286468`, product
version **2.1.2** (V2). Paths of the form `pkg/...` are relative to that clone and line numbers are at that commit.
Daemon paths are relative to `/workspace` and abbreviate `src/claude_code_hooks_daemon/` as `src/`. Inputs, all in
the plan folder:

- EXT: `RESEARCH-opencode-extension-surface.md`
- ARCH: `RESEARCH-opencode-architecture.md`
- DUAL: `RESEARCH-dual-tool-repos.md`
- COUP: `RESEARCH-daemon-couplings.md`

**Fidelity vocabulary.**

- **enforced**: the agent cannot get past it.
- **re-drive**: no veto, but the session is re-prompted automatically after the fact. This is the nearest
  opencode gets to a Stop block.
- **advisory**: text only.
- **commit-time**: enforced by a git hook or CI.
- **impossible**: no mechanism found.

**Provisioning vocabulary.**

- `AGENTS.md`: opencode's only auto-loaded instruction file (DUAL §1.1).
- `opencode.json`: `permissions`, `agents`, `commands`, `plugins`, `instructions`.
- `.opencode/{agents,modes,commands}/*.md` (EXT §6.4, §6.5).
- `.claude/skills/`: already read by opencode (EXT §6.6).
- **plugin**: a V2 `@opencode/plugin` bridge to the daemon socket (EXT §3, bridge 1).
- **driver**: an out-of-process HTTP API client. It could be the long-lived daemon (ARCH §1.2).
- **git hook**: through `core.hooksPath`. None is installed today (DUAL §7).

---

## 1. New facts established in this pass

1. **RESOLVED (EXT §2.4 had this UNVERIFIED): a synthetic message restarts the agent loop.** `Session.synthetic`
   admits the text, then calls `execution.wake(sessionID)` unless `resume === false`
   (`packages/core/src/session/session.ts:283-322`). The route description is "Durably admit synthetic session
   input and schedule execution unless resume is false." (`packages/protocol/src/groups/session.ts:403-416`).
   `session.prompt` is the same (`:336-352`). The built-in Plan plugin passes `resume:false` deliberately, so that
   its reminders do not start a turn (`packages/core/src/plugin/plan.ts:67`, `:83-88`).
2. **A pending steer continues a turn without going idle.** The drain completes only when nothing is pending, or
   only a `queue` item at a steer boundary (`packages/core/src/session/runner/llm.ts:158-159`). Otherwise it
   promotes the input and steps again (`:160-178`). The default delivery is `steer` (`session.ts:302`;
   `packages/schema/src/session-inbox.ts:11`; opencode `AGENTS.md:185`). An early re-drive is a true continuation;
   a late one wakes a new execution. Either way the agent keeps working.
3. **No scheduler, no `/goal`.** A search of `packages/{core,schema,cli}/src` for `cron`, `CronCreate` and
   `setInterval` found no hits.
4. **The `session.retry` hook can lengthen or veto a retry, but cannot create one.** It is only reached when
   `ModelRetry.policy` returns a decision (`packages/core/src/session/runner/retry.ts:32-55`, `:38` before `:47`).
5. **Edit permission resources are project-relative paths** (`packages/core/src/file-access.ts:92-122`), and `*`
   also matches `/` (`packages/core/src/util/wildcard.ts:3-14`). So `{edit, "CLAUDE/Plan/*", allow}` covers the
   plan tree. Caveat: the path is relative to the session's directory. A subdirectory session is UNVERIFIED.
6. **A shell permission resource is the command text, redirections included** (`packages/core/src/shell/parse.ts:197`).
   `{shell, "*>*", deny}` can catch redirect writes. It is crude, because it also matches `2>&1`.
7. **Command templates run shell commands without a permission check.** `` !`cmd` `` goes through
   `services.processes.run` directly (`packages/core/src/config/plugin/command.ts:185-237`, `:247`). `$1` and
   `$ARGUMENTS` are substituted first (`:196-204`). That gives deterministic `mkplan.bash` calls, but the arguments
   need quoting to avoid shell injection.

---

## 2. Inventory

### 2.1 Plan creation and numbering

| Behaviour                                                                     | CC mechanism                                                                  | opencode route                                                                                                                | Fidelity                                    | Provisioned      |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ---------------- |
| `mkplan.bash` numbering (git counter, lock)                                   | bash; `src/handlers/utils/plan_numbering.py:1-16`                             | Unchanged, tool-neutral (COUP B11)                                                                                            | n/a                                         | already deployed |
| Deny `mkdir` of a plan folder and scan-based numbering (`plan_number_helper`) | PreToolUse Bash deny (`src/handlers/pre_tool_use/plan_number_helper.py:1-34`) | Plugin `tool.execute.before` on `shell`; or a config rule `{shell, "mkdir *CLAUDE/Plan/0*", deny}`                            | plugin: enforced; config: enforced (coarse) | plugin / config  |
| Number collisions and counter sanity                                          | `plan_qa_commit_gate`                                                         | `bin/hooks-daemon plan-qa --check-staged` in pre-commit                                                                       | commit-time                                 | git hook         |
| `/plan-new` entry point                                                       | none                                                                          | `.opencode/commands/plan-new.md` with `` !`CLAUDE/Plan/mkplan.bash "$1"` ``, `agent: planner` (fact 7)                        | deterministic numbering                     | command file     |
| Dedupe scout                                                                  | `hooks-daemon-plan-dedupe-scout` agent                                        | Rendered `.opencode/agents/` file. Claude-format files are dropped (DUAL §3.2)                                                | advisory                                    | rendered agent   |
| `plansDirectory` redirect                                                     | `markdown_organization` (COUP B10)                                            | Not applicable. The opencode plan agent writes to the global `~/.opencode/plan/` (`plan.ts:30-31`, `:40`). Override it (§2.3) | n/a                                         | agent override   |

### 2.2 Plan QA, status and journal

| Behaviour                                                       | CC mechanism                                               | opencode route                                                                                                                                             | Fidelity                                     | Provisioned           |
| --------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | --------------------- |
| Edit-time PLAN.md lint (`plan_qa_edit`)                         | PreToolUse Write/Edit (`plan_qa_edit.py:1-24`)             | Plugin `tool.execute.before` (input visible and mutable, EXT §2.1); else `plan-qa --lint FILE` in pre-commit                                               | plugin: enforced; else commit-time           | plugin / git hook     |
| Cross-file commit gate                                          | PreToolUse on `git commit` (`plan_qa_commit_gate.py:1-15`) | `plan-qa --check-staged` (an existing CLI) in pre-commit                                                                                                   | **commit-time; covers every tool and human** | git hook              |
| Session-start drift report (`plan_qa_sweep`)                    | SessionStart context                                       | Plugin: `session.created` event then `synthetic(resume:false)`, the Plan plugin's pattern (`plan.ts:75-96`)                                                | advisory                                     | plugin                |
| No time estimates (`plan_time_estimates`)                       | PreToolUse                                                 | Plugin; or pre-commit on staged PLAN.md                                                                                                                    | enforced / commit-time                       | plugin / git hook     |
| Close approval (`plan_close_approval`, opt-in)                  | PreToolUse deny; `approve-plan-close`                      | Plugin; pre-commit can only catch it after the write (partial)                                                                                             | enforced / partial                           | plugin / git hook     |
| Journal via `mkplan.bash --journal` only (`plan_journal_guard`) | PreToolUse deny (`plan_journal_guard.py:1-30`)             | Plugin. Config `{edit, "CLAUDE/Plan/*/JOURNAL/*", deny}` covers the edit tools but not a shell heredoc. Pre-commit can check entry immutability and stamps | enforced / partial / commit-time             | plugin / config / git |
| Plan fact-check feed                                            | PostToolUse, delivered on a later event                    | Plugin `tool.execute.after`. Delivery by `synthetic` as soon as the plan goes quiet, which is better than in CC                                            | advisory, prompt                             | plugin                |
| Asset checker                                                   | SessionStart                                               | Plugin or `AGENTS.md`                                                                                                                                      | advisory                                     | plugin / AGENTS.md    |
| Issue assignment guard                                          | PreToolUse                                                 | Plugin; `commit-msg` hook with `issue-validity`                                                                                                            | enforced / commit-time                       | plugin / git hook     |
| Closing-keyword guard                                           | PreToolUse                                                 | `commit-msg` hook; the plugin for `gh`                                                                                                                     | commit-time / enforced                       | git hook / plugin     |

### 2.3 "Plan before code" (point b)

| Mechanism                                                                                                                                                                                                                              | Fidelity                                                        | Provisioned        |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------ |
| Override the built-in `plan` agent: append `{edit, "CLAUDE/Plan/*", allow}` and `{shell, "CLAUDE/Plan/mkplan.bash *", allow}`. Last match wins (`packages/core/src/permission.ts:74-84`); every other edit stays denied (`plan.ts:39`) | **enforced** (the reminder text still names `~/.opencode/plan`) | `opencode.json`    |
| A custom primary `planner` agent (`.opencode/modes/planner.md`): `edit * deny`, `edit CLAUDE/Plan/* allow`, a tight shell allow-list, the workflow prompt as `system`, and optionally `default_agent: planner`                         | **enforced by config alone**                                    | config / mode file |
| Gap: `shell` writes. The default ruleset is `*:* allow` (`packages/schema/src/agent.ts:46-51`), and plan mode does not deny shell (ARCH §3.4). Close it with a shell allow-list or a `*>*` deny                                        | enforced if tight                                               | config             |
| Make the build agent require an In Progress plan. This is stateful, so it needs a plugin using `permission.evaluate` (deny plus message) or `tool.execute.before`                                                                      | enforced                                                        | plugin             |
| Agent switching is a human/API act (`POST /api/session/:id/agent`). There is no model-side `ExitPlanMode`, so the model cannot skip approval. Unattended runs must start in the right agent (`opencode run --agent`)                   | structural                                                      | —                  |
| `AGENTS.md` instruction only                                                                                                                                                                                                           | advisory                                                        | AGENTS.md          |

**Verdict:** yes. opencode agents enforce plan-first through permission rules from config alone, which is stronger
than Claude Code config. Making the build agent conditional on an existing plan needs a plugin.

### 2.4 Forcing the agent to keep working (point a)

| Behaviour                                                                                                 | CC mechanism                                                         | opencode route                                                                                                                                                                                                                                                                 | Fidelity                                        | Provisioned                |
| --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- | -------------------------- |
| `auto_continue_stop` (STOPPING BECAUSE, QA failure, tool-error recovery, confirmation questions)          | Stop `decision:block`, with the `stop_hook_active` guard (COUP B4)   | Plugin on `session.execution.succeeded`. It reads the last text and sends the verdict through `ctx.session.synthetic` (default resume wakes the session, fact 1). It keeps its own one-re-drive-per-idle guard, and skips `interrupted` and `failed`                           | **re-drive** (same outcome, no veto)            | plugin                     |
| Low-latency variant                                                                                       | —                                                                    | On a `session.step.ended` with no tool calls, steer the message in before the drain settles (fact 2). Racy; a miss degrades to the variant above                                                                                                                               | re-drive                                        | plugin                     |
| Fact-checking stop gates (`cron_stop_enforcer`, `idle_workable_issue_stop_gate`, `usage_pause_stop_gate`) | Stop payload `session_crons`, `background_tasks`                     | Same re-drive pattern. "In flight" means child sessions that are not idle (ARCH §3.3). The work queue and issue cache are unchanged                                                                                                                                            | re-drive                                        | plugin                     |
| SubagentStop gates (size, path, handoff)                                                                  | SubagentStop block                                                   | The foreground `subagent` tool returns at child idle. `tool.execute.after` on `subagent` rewrites the result: persist the report, return path plus summary, flag missing paths. Background children can be re-driven                                                           | size/path enforced by rewrite; handoff re-drive | plugin                     |
| Report persistence                                                                                        | SubagentStop `last_assistant_message`                                | `tool.execute.after` on `subagent`                                                                                                                                                                                                                                             | enforced                                        | plugin                     |
| Sub-agent PreToolUse guards (dispatch declaration, context budget, full QA, tier, worktree)               | PreToolUse                                                           | `tool.execute.before` on `subagent` and on child-session tools. Token totals come from `session_v2` (ARCH §1.5)                                                                                                                                                                | enforced                                        | plugin                     |
| Failsafe recovery cron                                                                                    | CC session cron (COUP B5)                                            | Mostly unnecessary: the long-lived server resumes mid-turn sessions from execution claims (ARCH §1.2), and `session.retry` delays can be stretched (fact 4). Residual `execution.failed` sessions are handled by a plugin `setInterval` or a daemon driver sending `synthetic` | enforced, stronger than CC                      | plugin / driver            |
| `persistent_crons` (`issue-sdlc` hourly)                                                                  | Instruct CronCreate; Stop enforcer; 7-day refresh                    | A real scheduler (daemon or plugin) sends `POST /api/session/:id/prompt` or creates a fresh session; or an OS timer runs `opencode run --agent build "/issue-sdlc"`. The assert/record/refresh/enforce chain is unnecessary                                                    | enforced (scheduler-owned)                      | driver / plugin / OS timer |
| `[awaiting-human]` suppression and the stand-in                                                           | Stop marker plus UserPromptSubmit block                              | The scheduler checks the marker before sending, so it is zero-token (`session.prompt` cannot block anyway, EXT §2.4)                                                                                                                                                           | enforced                                        | driver / plugin            |
| `/goal` plus `goal_injection`                                                                             | Goal-intent file; the ccy PTY supervisor types `/goal` (COUP B6, B7) | Plugin records the goal on the PLAN.md In Progress flip and judges it on idle (daemon rules, or the `generate` domain, UNVERIFIED), then re-drives. **No PTY supervisor**                                                                                                      | re-drive                                        | plugin                     |
| Session-actions directive                                                                                 | Supervisor-typed turn                                                | `synthetic` on `session.created`: a native turn-level channel                                                                                                                                                                                                                  | enforced delivery                               | plugin                     |
| Work-queue re-brief                                                                                       | SessionStart / UserPromptSubmit                                      | `session.compaction` or `session.context`                                                                                                                                                                                                                                      | advisory                                        | plugin                     |
| AskUserQuestion policy                                                                                    | PreToolUse                                                           | The `question` tool (`packages/core/src/tool/plugin/question.ts:10`, `:65`). Unattended: config `{question, *, deny}`. The prefix rule needs the plugin                                                                                                                        | enforced (config) / plugin                      | config / plugin            |
| Runaway cap                                                                                               | none                                                                 | `agents.<id>.steps` (`runner/llm.ts:220-238`). It resets on each promotion, so the re-drive guard must be the plugin's own                                                                                                                                                     | enforced cap                                    | config                     |

**Verdict:** opencode cannot refuse a stop, but it can cheaply undo one. The differences from a Claude Code block:

- the turn boundary is visible;
- the reason arrives as user-role text;
- the loop guard has to be built by hand.

Crons, the failsafe tick and the PTY supervisor become simpler, because the scheduler is a real process rather than
something the model is asked to create.

### 2.5 Guidance delivery

| Behaviour                     | opencode route                                                                                                                       | Fidelity | Provisioned           |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------- | --------------------- |
| `<hooksdaemon>` guidance      | A generated `AGENTS.md` section with opencode tool names (DUAL §6 item 1), or a `session.context` injection on every step            | advisory | AGENTS.md / plugin    |
| `.claude/rules` path pointers | Fold them into `AGENTS.md`, or have the plugin append them on the first touch of a matching path                                     | advisory | AGENTS.md / plugin    |
| `issue-sdlc` skill            | Read from `.claude/skills/`. The body needs an audit for `Task` and `$ARGUMENTS` (DUAL §1.4). Add `.opencode/commands/issue-sdlc.md` | advisory | skill audit + command |
| Standing authorisations       | `session.prompt` append or `session.context`                                                                                         | advisory | plugin                |

---

## 3. What a repository would carry

1. **`opencode.json`**:
   - `default_agent` (optional) and the plan/planner permissions.
   - `{question, *, deny}` for unattended projects.
   - The JOURNAL edit deny.
   - `steps` caps.
   - `plugins` pointing at the bridge.
   - `instructions`.
2. **`.opencode/modes/planner.md`** and **`.opencode/agents/*.md`** rendered from `.claude/agents`.
3. **`.opencode/commands/`**: `plan-new`, `journal`, `issue-sdlc`, `plan-qa`.
4. **`AGENTS.md`**: the generated section.
5. **`.opencode/plugins/hooks-daemon/`**: the bridge.
6. **Git hooks** via `core.hooksPath`.
7. **Optional daemon driver** using `$XDG_STATE_HOME/opencode/service.json` (ARCH §1.2). The file holds a private
   password, which makes this an owner trust decision.

---

## 4. Tool-neutral git hooks: what is cheapest to move (point c)

| #   | Check                                                                                                        | Hook       | Why cheap                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------ | ---------- | -------------------------------------------------------------------------- |
| 1   | Plan QA commit gate (index-at-birth, atomicity, collisions, bijection, statistics, counter, message hygiene) | pre-commit | **Already a CLI**: `bin/hooks-daemon plan-qa --check-staged [--json]`      |
| 2   | PLAN.md edit-stage lint (incl. time estimates) on staged plans                                               | pre-commit | `plan-qa --lint FILE` exists                                               |
| 3   | Journal immutability and stamp sanity                                                                        | pre-commit | The commit stage of `journal-dayfile-is-today` already exists              |
| 4   | Conflict markers, staged lint, sensitive-content added lines                                                 | pre-commit | Pure functions over staged content (DUAL §7); CLI entry points not checked |
| 5   | Closing keyword; issue-tied commit validity                                                                  | commit-msg | Message-only, plus the `issue-validity` CLI                                |
| 6   | Plan close approval                                                                                          | pre-commit | Approval store exists; weaker than the edit-time deny                      |
| 7   | Docs QA                                                                                                      | pre-commit | `docs-qa` CLI exists; staged mode not checked                              |

Limits:

- Commit-time only.
- `--no-verify` bypasses them. For agents, close that with a plugin or a `{shell, "git commit*--no-verify*", deny}`
  rule.
- They cannot keep an agent working.
- CI remains the backstop.

Under Claude Code the commit gates become dual-enforced.

---

## 5. Ranked list

**A. Provisionable now (no plugin):**

1. Pre-commit `plan-qa --check-staged` / `--lint`, plus `commit-msg`.
2. Plan-before-code through agent permissions (plan override or planner, a tight shell allow-list, `default_agent`).
3. Config rules: `question` deny, JOURNAL edit deny, plan `mkdir` deny, `steps` caps.
4. `.opencode/commands/` (`plan-new`, `journal`, `issue-sdlc`, `plan-qa`).
5. A generated `AGENTS.md`, audited skills, rendered agents (advisory).
6. OS-timer headless `opencode run` ticks.

**B. Needs a plugin:**

1. All edit-time plan guards and sub-agent guards, and the `ASKING BECAUSE:` prefix.
2. Stop gates as re-drives, and `/goal` without a PTY supervisor.
3. Sub-agent hand-over enforcement by rewriting the result.
4. A build agent conditional on an active plan.
5. Per-step guidance, session-start directives, compaction re-brief, stretched retry.
6. An in-plugin scheduler.

**C. Needs an external driver:**

1. Daemon-owned `persistent_crons` and failsafe ticks with zero-token `[awaiting-human]` suppression. These survive
   a server restart or version replacement.
2. Holder-session ticks, stand-ins, coordinator re-brief after a restart.
3. A headless permission responder when no plugin is installed (it races the UI).

**D. Not achievable as in Claude Code:**

1. A synchronous stop veto (re-drive instead).
2. Blocking a user prompt with a reason (rewrite only).
3. Path-scoped rules loading.
4. Stateful enforcement from config alone.
5. Blocking a foreground sub-agent's stop before the parent sees the result (rewrite instead).

---

## Gaps

- No live opencode run. These are untested: re-drive timing, the subdirectory edit resource, the `*>*` rule, and
  `default_agent` with a mode file.
- Not traced: the plugin `generate` domain; `opencode run` with `question: deny`; worktree isolation for
  `subagent`.
- Not checked: CLI entry points for conflict-marker, sensitive and staged-lint gates; the `docs-qa` staged mode.
- `CLAUDE/core/PlanWorkflow.core.md` was not read in full. The inventory comes from the handler module docstrings.

# Plan 00161 — Idle Housekeeping Mode: Brainstorm

**Type**: Divergent ideation (Phase 1, Task 1.1)
**Sources**: this session's transcript (`5ba5bdfc-cf08-443d-bf5d-acd43589022e.jsonl`) + repo handlers/docs. No code or config changed.

---

## 0. What the transcript actually shows (the evidence)

- **19 consecutive hourly no-op recovery ticks**, 2026-07-13 12:56 UTC → 2026-07-14 06:56 UTC, every tick at `:56`.
- Each tick produced a **pair** of near-identical stops. The two alternating shapes, verbatim:
  - `STOPPING BECAUSE: failsafe tick found nothing to resume; all work is done and committed.`
  - `STOPPING BECAUSE: nothing to resume — all work complete and committed, working tree clean; the failsafe tick is a no-op.`
- **Why pairs**: the first stop's hook response carried `additionalContext: ["✅ Stop hook system active"]` (the `hello_world_stop` dogfood handler), and Claude Code treats a Stop response with additional context as "give the model another turn" — so the model stopped *again*. 19 ticks × 2 turns = **38 assistant turns**, each dragging a ~1,400-message context, producing zero value.
- The repetition is machine-detectable: the tick prompt always contains the canonical marker `**FAILSAFE RECOVERY CHECK (automated hourly safety net — NOT a heartbeat).**` (a `Final` constant, `_CANONICAL_CRON_PROMPT`, in `src/claude_code_hooks_daemon/handlers/post_tool_use/recovery_cron_advisor.py`), and the no-op reply always matches a `STOPPING BECAUSE:.*nothing to resume` shape with **no tool calls in between**.

Incidental dogfooding finding (worth its own follow-up): `hello_world_stop` injecting context on every Stop **doubles** the cost of every idle tick. Rate-limiting or disabling its context injection would halve idle burn independently of anything else in this plan.

---

## A. Detection mechanism

### A.1 Candidate signals (enumerate, then combine)

| Signal                                                                                                        | Where it lives                                                                                                                   | Strength                                    | Notes                                                                                                  |
| ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| S1. Incoming prompt contains the canonical `FAILSAFE RECOVERY CHECK` marker                                   | UserPromptSubmit `prompt` field                                                                                                  | Exact — the marker is a repo-owned constant | The daemon literally authored the string; matching it is not heuristic                                 |
| S2. Trailing transcript cycles of tick → `STOPPING BECAUSE:.*nothing to resume` with **zero tool_use blocks** | Transcript tail via `TranscriptReader` (same infra `auto_continue_stop.py` uses)                                                 | Very strong when ≥2 consecutive             | The transcript IS the counter — stateless, survives daemon restarts, immune to counter-drift           |
| S3. No real (non-tick) user prompt since the last completed unit of work                                      | Transcript tail                                                                                                                  | Strong guard                                | Any human prompt resets everything                                                                     |
| S4. Clean working tree (`git status --porcelain` empty)                                                       | Subprocess (pattern exists in `handlers/user_prompt_submit/git_context_injector.py`)                                             | Corroborating                               | Dirty tree ≠ housekeeping time; it's either resumable work (recovery's job) or a *report-only* finding |
| S5. No unharvested background processes                                                                       | `background-processes.jsonl` in daemon untracked dir + `harvest-background` CLI                                                  | Corroborating                               | A live watchdog concern outranks housekeeping                                                          |
| S6. Last real stop was NOT "blocked on human input" / no pending `AskUserQuestion`                            | Transcript tail (`reader.last_assistant_used_tool(ToolName.ASK_USER_QUESTION)` — same check `auto_continue_stop.matches()` does) | Hard guard                                  | The cron prompt itself says: blocked only on human input → do nothing                                  |
| S7. Usage headroom (daily/weekly % from the `usage_tracking` status handler's data source)                    | Status-line data cache                                                                                                           | Optional gate                               | Housekeeping should not eat the last of a 5-hour window                                                |

**Recommended composite rule**: trip housekeeping when **S1 ∧ S2(≥ threshold) ∧ S3 ∧ S6**, with S4/S5 shaping *what* is advised (dirty tree / live background procs demote to report-only), and S7 as an optional config gate.

### A.2 Which event type hosts it?

| Option                                                                                                            | Mechanics                                                                                                                             | Pros                                                                                                                                                             | Cons                                                                                                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **B. UserPromptSubmit advisory (RECOMMENDED)**                                                                    | `matches()` on S1; `handle()` reads transcript tail for S2/S3/S6; injects housekeeping context **alongside the arriving tick prompt** | Guidance lands in the exact turn where the agent decides "nothing to resume"; zero interaction with Stop dispatch; advisory-only; one turn, no extra round-trips | Needs transcript access at UserPromptSubmit (available: `transcript_path` is on the hook input, same as Stop)                                                                          |
| A. Stop handler (sibling of `auto_continue_stop`, priority < 10 so it wins the terminal chain)                    | Counts no-op-shaped stops; at threshold DENYs the stop with a housekeeping checklist as the reason                                    | Reuses the proven DENY-to-redirect mechanism (Branch 1/3 of `auto_continue_stop.py`)                                                                             | Fights the Stop contract — the agent just said `STOPPING BECAUSE:` truthfully and gets blocked anyway; erodes trust in the prefix; two handlers competing over the same terminal event |
| C. Amend `_CANONICAL_CRON_PROMPT` only (zero-code)                                                                | Add "if this is a repeated no-op, run the housekeeping checklist" to the cron prompt                                                  | No handler at all; ships in one constant edit                                                                                                                    | Static text cannot count ticks, enforce caps, or check guards; every tick becomes a judgement call; truth-change ripple (CLAUDE.md, docs, acceptance tests assert the verbatim prompt) |
| D. Separate agent-created "housekeeping cron" (e.g. 4-hourly), advised by a `recovery_cron_advisor`-style sibling | The cron prompt IS the checklist                                                                                                      | Dead simple; mirrors existing cron-advisor pattern                                                                                                               | Fires regardless of idleness (only REPL-idle gates it); can't see "N consecutive no-ops"; another cron to manage/leak                                                                  |
| E. Daemon-side idle pseudo-event (Plan 00085 reminder pseudo-event system)                                        | Daemon timer notices no events for T and synthesises a reminder                                                                       | The "right" long-term shape — daemon owns idleness                                                                                                               | Biggest build; pseudo-event delivery into a live REPL is exactly the hard problem Plans 00085/00135 (send-keys injection) circle                                                       |
| F. ccy supervisor send-keys injection (Plan 00135/00160 infra)                                                    | Supervisor sees idle PTY + no-op stops, types the housekeeping prompt                                                                 | Works even when hooks can't fire                                                                                                                                 | Only exists on supervised sessions; out of daemon-handler scope                                                                                                                        |

**Recommendation: Option B**, with Option C's *spirit* folded in (the injected context explains the mode switch so the model isn't surprised). Option A is the fallback if UserPromptSubmit turns out not to receive cron-originated prompts (verify with `./scripts/debug_hooks.sh` before building — the debug-first rule in `CLAUDE/DEBUGGING_HOOKS.md`).

### A.3 Counting & persistence

Three options for the consecutive-no-op counter:

1. **Transcript-as-counter (recommended)** — walk the tail backwards at `handle()` time counting tick→no-op-stop cycles until the first real user prompt or tool_use. No state to corrupt; daemon restarts irrelevant; identical result on re-fire. Cost: one bounded tail read per tick (once/hour — negligible).
2. In-memory dict on the handler singleton keyed by `session_id` (the `recovery_cron_advisor._progress_counts` / `background_process_tracker._session_counts` pattern, bounded + insertion-order evicted). Cheap, but resets on daemon restart and can double-count if the tick re-fires.
3. JSONL sidecar in `ProjectContext.daemon_untracked_dir()` (the `background-processes.jsonl` pattern via `write_state_record`). Needed anyway for the **housekeeping-pass cap** (passes done this session must survive daemon restarts to keep the hard stop honest) — but not for the tick count itself.

**Hybrid**: transcript for the *no-op count*, sidecar (`idle-housekeeping.jsonl`, session-keyed) for the *passes-done cap* and a dedupe set of already-reported findings.

### A.4 Threshold & false-positive guards

- **Threshold: 2 consecutive no-op ticks** (config `noop_threshold`, default 2). One no-op is normal ("work just finished an hour ago; user may be typing"). Two means ≥ ~2 hours of confirmed idleness. Three is over-cautious given the guards below.
- **Never trip when**:
  - the last real stop reads as *waiting on the user* (`STOPPING BECAUSE: need user input`, pending `AskUserQuestion` — S6);
  - any tool_use occurred inside the trailing tick window (work is happening — S2's zero-tool-calls condition);
  - a real user prompt is the most recent non-tick turn and unanswered (S3);
  - the session is mid-plan with an In Progress task actively being edited (approximation: any Write/Edit tool_use in the trailing window — already covered by S2).
- **Instant yield**: guidance text must state that a real user prompt aborts housekeeping immediately, and the counter/pass state resets on any non-tick prompt.

---

## B. The housekeeping task catalogue

Scoring: **Value** (H/M/L to this repo, generalisable in parentheses), **Autonomy-safety** (SAFE = fully unattended; GUARDED = unattended only under codified rules; HUMAN = report/plan-task only), **Mutation** (RO = read-only report, MUT = writes files, COMMIT = warrants its own commit).

### B.1 Plan-tree hygiene (all rules already codified in `src/claude_code_hooks_daemon/plan_qa/`)

| #   | Task                                                                                                                               | Value | Safety  | Mutation   |
| --- | ---------------------------------------------------------------------------------------------------------------------------------- | ----- | ------- | ---------- |
| 1   | Run `plan-qa --sweep`; fix **mechanical** findings (README stats recount, row/folder bijection, broken links)                      | H (H) | GUARDED | MUT+COMMIT |
| 2   | Archive terminal-status plans still in the plan root (`git mv` + README row + stats, the atomic recipe in `CLAUDE/Plan/CLAUDE.md`) | H (H) | GUARDED | MUT+COMMIT |
| 3   | Staleness/dormancy triage of long-idle In Progress plans                                                                           | M (M) | HUMAN   | RO         |
| 4   | Untracked-plan-folder inventory (plan folders lingering uncommitted — explicitly forbidden by `CLAUDE/Plan/CLAUDE.md`)             | M (M) | HUMAN   | RO         |

Why GUARDED not SAFE for #1/#2: the fixes are deterministic *and* validated by the `plan_qa_commit_gate` handler on commit — a wrong fix gets caught by the daemon's own gate. That double-lock is what makes unattended commits defensible here first.

### B.2 Doc / truth drift

| #   | Task                                                                                                             | Value | Safety | Mutation   |
| --- | ---------------------------------------------------------------------------------------------------------------- | ----- | ------ | ---------- |
| 5   | `generate-docs` regeneration of `.claude/HOOKS-DAEMON.md`; commit iff diff                                       | H (M) | SAFE   | MUT+COMMIT |
| 6   | Stale backticked `src/...` path scan across `CLAUDE/` + `docs/` (plan-qa already has this rule for plans)        | M (H) | HUMAN  | RO         |
| 7   | Dead-link check across markdown docs                                                                             | M (H) | HUMAN  | RO         |
| 8   | `format-markdown` sweep of drifted tables                                                                        | L (M) | SAFE   | MUT        |
| 9   | `UNRELEASED/` hygiene check: post-upgrade-tasks / truth-changes / config-changes staged for work done this cycle | M (L) | HUMAN  | RO         |
| 10  | British-English / spelling sweep of content files                                                                | L (L) | HUMAN  | RO         |

**Hard exclusion**: CHANGELOG.md and `RELEASES/*.md` are FORBIDDEN outside `/release` (CLAUDE.md release rule). Housekeeping must never touch them, ever.

### B.3 Test / QA health

| #   | Task                                                                                                | Value | Safety | Mutation                  |
| --- | --------------------------------------------------------------------------------------------------- | ----- | ------ | ------------------------- |
| 11  | Baseline QA smoke: `./scripts/qa/llm_qa.py all` — confirm HEAD is green while nobody is waiting     | H (H) | SAFE   | RO                        |
| 12  | Coverage-gap report from `untracked/qa/coverage.json` (name the lowest-covered modules → plan task) | M (H) | HUMAN  | RO                        |
| 13  | Slow-test report (pytest `--durations` from the QA run's own output)                                | M (M) | HUMAN  | RO                        |
| 14  | Flaky-test detection via repeated suite runs                                                        | L (M) | HUMAN  | RO — expensive, rank last |
| 15  | Orphaned/dead test-fixture scan                                                                     | L (M) | HUMAN  | RO                        |

### B.4 Code hygiene

| #   | Task                                                                                                                                  | Value | Safety | Mutation |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------ | -------- |
| 16  | TODO/FIXME/XXX inventory → triage into a follow-up plan's task list                                                                   | M (H) | HUMAN  | RO       |
| 17  | `get_claude_md()` completeness audit across all handlers (the RELEASING.md Step 11 sub-agent prompt, run early instead of at release) | H (L) | HUMAN  | RO       |
| 18  | Dead-code scan (vulture-style / ruff unused)                                                                                          | M (M) | HUMAN  | RO       |
| 19  | Acceptance-playbook regeneration diff (`generate-playbook` vs last committed expectations)                                            | M (L) | HUMAN  | RO       |

### B.5 Dependency / security drift

| #   | Task                                                                          | Value | Safety | Mutation |
| --- | ----------------------------------------------------------------------------- | ----- | ------ | -------- |
| 20  | `uv lock --check` lockfile drift                                              | M (H) | HUMAN  | RO       |
| 21  | Security rescan (`run_security_check.sh` / pip-audit style)                   | M (H) | HUMAN  | RO       |
| 22  | `version_check`-style upstream-release check (already a SessionStart handler) | L (M) | HUMAN  | RO       |

Dependency **upgrades** are always HUMAN — never unattended.

### B.6 Runtime / artifact reaping (dogfooding gold)

| #   | Task                                                                                                                                   | Value | Safety  | Mutation                    |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------- | --------------------------- |
| 23  | Daemon log scan for ERROR/WARN since last check (`daemon.cli logs`) + `status` health check                                            | H (H) | SAFE    | RO                          |
| 24  | `harvest-background` + reap surfaced runaways per the codified process-group protocol                                                  | H (H) | GUARDED | kills procs, no file writes |
| 25  | `prune-venvs --legacy` (CLI guarantees the current fingerprint is never deleted)                                                       | M (L) | SAFE    | deletes untracked venvs     |
| 26  | Stale untracked-artifact report (`untracked/release-artifacts/`, aged logs, `/tmp/hook_debug_*`) — report; deletion only via allowlist | M (M) | HUMAN   | RO                          |

### B.7 Knowledge capture

| #   | Task                                                                                                    | Value | Safety | Mutation |
| --- | ------------------------------------------------------------------------------------------------------- | ----- | ------ | -------- |
| 27  | Session-lesson extraction into `CLAUDE/development/LESSONS.md` draft (prompt-library reminder analogue) | M (M) | HUMAN  | RO/draft |
| 28  | Unpushed-commit / untracked-file inventory report                                                       | M (H) | HUMAN  | RO       |

### B.8 Ranked top 10 (value × safety, cheapest-first tie-break)

01. **Plan-tree sweep + mechanical fixes** (#1, #2) — highest value, rules + commit-gate double-lock, and it dogfoods `plan_qa` itself.
02. **QA baseline smoke** (#11) — free confidence; also the precondition for any mutating task below.
03. **Daemon log/health scan** (#23) — surfaces the #1 dogfooding failure mode (silent stale-code/phantom errors) while nobody is watching.
04. **Artifact/venv/background reaping** (#24, #25) — codified CLIs exist; converts idle time into a cleaner runtime.
05. **`generate-docs` drift regen** (#5) — deterministic generator, diff-or-nothing.
06. **TODO/FIXME + dead-code inventory → plan-task capture** (#16, #18) — turns scrollback debt into tracked work.
07. **Coverage-gap + slow-test report** (#12, #13) — piggybacks on #2's run output.
08. **Dependency/lockfile/security drift checks** (#20, #21) — cheap, report-only.
09. **`get_claude_md()` completeness audit** (#17) — front-loads a blocking release gate.
10. **Stale doc path / dead link scan** (#6, #7) — generalisable to any client repo.

---

## C. Autonomy & safety guardrails

**The three-tier action boundary** (per finding, not per pass):

- **Tier R — report only** (default for everything): findings are summarised in the assistant's turn and, where durable, appended as tasks to a designated housekeeping plan (or Plan 00161's follow-up). No file mutation.
- **Tier M — do, commit, each with its own `Housekeeping:`-prefixed commit**: only tasks that are (a) deterministic, (b) already validated by an independent daemon gate or generator (`plan_qa_commit_gate`, `generate-docs`, `format-markdown`), and (c) trivially revertable as a single commit. Never batch heterogeneous fixes into one commit; never commit when the tree was already dirty at pass start (a dirty tree demotes the whole pass to Tier R).
- **Tier H — never unattended**: dependency upgrades, deletions outside codified CLIs, status flips on plans, anything touching CHANGELOG/RELEASES/version files, anything the user framed as a decision.

**Anti-loop / anti-burn rules**:

1. **Pass cap**: `max_passes_per_session` (default 1–2). A pass that finds nothing actionable writes an `exhausted` marker to the sidecar; subsequent ticks genuinely no-op-stop again (the current, correct behaviour). No marker expiry within the session.
2. **Finding dedupe**: a finding reported once is not re-reported next pass (sidecar dedupe set) — prevents the "same checklist every hour" spam loop.
3. **Yield instantly**: any real user prompt aborts housekeeping mid-pass; unfinished Tier-M work is left uncommitted and *said out loud*, not silently continued.
4. **Recovery outranks housekeeping**: if the tick finds genuinely resumable work, the recovery contract runs and the housekeeping advisory must not fire at all (S2's zero-tool-calls trailing-window condition enforces this structurally).
5. **Quota respect**: optional `max_usage_percent` gate against the usage-tracking data; above it, ticks stay pure no-ops.
6. **Never fight the Stop handler**: the advisory rides UserPromptSubmit. If the agent still decides to stop, `STOPPING BECAUSE: housekeeping exhausted/deferred` is a valid stop — the handler never DENYs.
7. **Cron contract untouched**: `_CANONICAL_CRON_PROMPT`, the not-a-heartbeat rule, and `recovery_cron_advisor` lifecycle advice all stay as-is in the MVP (Option C amendments are a later, deliberate truth-change).

---

## D. Handler design sketch

- **Name**: `idle_housekeeping_advisor` (`HandlerID.IDLE_HOUSEKEEPING_ADVISOR`)
- **Event**: UserPromptSubmit. **Priority ~56** (advisory band; slots after `post_clear_auto_execute` 54 and `critical_thinking_advisory` 55). `terminal=False`. Tags: `WORKFLOW`, `ADVISORY`, `NON_TERMINAL`.
- **`matches()`**: `prompt` contains the canonical `FAILSAFE RECOVERY CHECK` marker string (imported from a shared constant with `recovery_cron_advisor` — single source of truth, DRY).
- **`handle()`**:
  1. Load `TranscriptReader` from `transcript_path` (reuse `utils/stop_hook_helpers.get_transcript_reader`).
  2. Walk the tail: count consecutive `tick prompt → STOPPING BECAUSE .* nothing-to-resume` cycles with zero interleaved tool_use; stop at the first real user prompt.
  3. Guards: pending AskUserQuestion → allow silently; count < `noop_threshold` → allow silently; sidecar shows `passes >= max_passes` or `exhausted` → allow silently.
  4. Otherwise inject one advisory context block: the mode-switch explanation + the ranked checklist (MVP: "run `$PYTHON -m ... daemon.cli housekeeping --report`" once that exists; interim: inline the top read-only checks) + the guardrails (yield to user, pass cap, `STOPPING BECAUSE: housekeeping complete/exhausted` when done).
  5. Record the pass in `idle-housekeeping.jsonl` under `ProjectContext.daemon_untracked_dir()` (reuse/extract `write_state_record` from `background_process_tracker.py` into a shared util).
- **Config options** (under `handlers.user_prompt_submit.idle_housekeeping_advisor.options`): `noop_threshold` (default 2), `max_passes_per_session` (default 1), `mode: report | fix-safe` (default `report`), `task_allowlist` (list of catalogue task ids), optional `max_usage_percent`.
- **Default enabled**: opt-in (`get_default_enabled() → False`) for the first release; dogfood-enable in this repo's `.claude/hooks-daemon.yaml`. Flip to default-on only after field time (the `recovery_cron_advisor` → Plan 00139 opt-out flip is the precedent path).
- **Companion CLI (strongly suggested)**: `daemon.cli housekeeping --report [--json]` mirroring `plan-qa --sweep` — runs the Tier-R audits and prints a ranked findings list, exit 1 when findings exist. Concentrates the logic in testable Python instead of ever-growing advisory prose, and makes the feature usable manually and in CI.
- **`get_claude_md()`**: must document the mode, the tiers, and the "housekeeping is lower priority than everything" rule (Step 11 audit would flag its absence).
- **Acceptance tests**: via `get_acceptance_tests()` — advisory fires on a synthetic transcript with 2 no-op cycles; stays silent at 1 cycle, on pending AskUserQuestion, and when exhausted.

---

## E. Open questions & risks (need a human call — deliberately unanswered)

1. **Threshold default**: 2 vs 3 consecutive no-ops? (2 recommended; 19 were observed.)
2. **May the MVP ever auto-commit** (Tier M plan-qa fixes + generate-docs), or is v1 strictly report-only? The commit-gate double-lock argues yes-for-plan-qa; conservatism argues report-first.
3. **Quota gate**: should housekeeping consult usage-tracking data, and at what cutoff? (Coupling to the status-line data source is new surface.)
4. **Amend `_CANONICAL_CRON_PROMPT`** to mention housekeeping mode (Option C fold-in)? It ripples: CLAUDE.md, `recovery_cron_advisor` acceptance patterns, a `truth-changes` manifest.
5. **Multithread sessions** (Plan 00158 world): when several threads share a project, should only one housekeep? A project-scoped lock file in the untracked dir?
6. **The doubled-stop bug**: fix `hello_world_stop`'s per-stop context injection (rate-limit or blank it) as part of this plan or a separate one? It's independent and halves idle burn on its own.
7. **Where do Tier-R findings persist** — a dedicated `HOUSEKEEPING.md`-style report is barred by markdown-organisation rules; appending tasks to a plan is the compliant shape, but *which* plan (rolling housekeeping plan vs per-finding follow-ups)?
8. **Client-repo generalisation**: the catalogue is daemon-repo-flavoured; is the allowlist + `housekeeping --report` plugin point (project handlers contributing audit callables) the right extension seam, or premature (YAGNI)?
9. **Verify the event actually fires**: does a cron-originated prompt raise UserPromptSubmit? Must be confirmed with `./scripts/debug_hooks.sh` before TDD starts (debug-first rule). If not, fall back to the Stop-handler design (Option A).

---

## F. Recommended MVP slice

**A UserPromptSubmit advisory handler, report-only, hard-capped**:

1. `idle_housekeeping_advisor` matching the canonical tick marker; transcript-tail counting with threshold 2; guards S3/S6; pass cap 1 via untracked sidecar; opt-in, dogfood-enabled here.
2. Injected guidance = mode-switch explanation + a **fixed, read-only checklist** requiring zero new audit code: run `plan-qa --sweep`; run `./scripts/qa/llm_qa.py all`; scan `daemon.cli logs` for errors; run `harvest-background`; `uv lock --check`; report TODO/FIXME count — then summarise findings, append actionable ones as tasks to the follow-up plan, and stop with `STOPPING BECAUSE: housekeeping pass complete; findings recorded`.
3. No auto-mutation, no auto-commit, no CLI subcommand, no cron-prompt change in v1. Acceptance tests via `get_acceptance_tests()`; debug-first verification of the event flow (E.9) before RED.

Everything else — Tier-M auto-fix mode, `housekeeping --report` CLI, quota gate, prompt amendment, multithread lock — is a labelled later increment, each individually small.

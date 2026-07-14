# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

### Status Line / Agent View

- [00158: Agent Thread Navigation & Status Line](00158-agent-thread-navigation-statusline/PLAN.md) - In Progress (Phase 1 research/dogfood complete; implementation Phases 2–4 not started)

  - Documents the dogfood-verified Claude Code contract for the main `statusLine` and the newer `subagentStatusLine` surfaces; root-causes the "no status line / whose data?" symptoms under Agent View (arrow-key thread navigation)
  - Scopes daemon support for `subagentStatusLine` (per-thread agent-panel rows) plus a `statusLine` `refreshInterval` so the bar stays live while background agents run
  - Confirmed live: main bar payload carries NO agent-thread identity (always renders main session); we wire only `statusLine` today

- [00159: Status Writers Thread-Safe Tmp Naming](00159-status-writers-thread-safe-tmp-naming/PLAN.md) - Not Started (v3.39.0 code-review follow-up: the four `.{stem}.{pid}.tmp` atomic writers key on PID not thread — harmless today, hardening only)

### Code Quality / Handler Configuration

- [00161: Idle Housekeeping Mode](00161-idle-housekeeping-mode/PLAN.md) - In Progress (Phase 1 brainstorm delivered: turn repeated no-op failsafe-recovery ticks into a bounded, report-first housekeeping mode dispatched to specialist sub-agents; awaiting Phase 2 build)

- [00162: Wire hello_world Handler Flag](00162-wire-hello-world-handler-flag/PLAN.md) - In Progress (fix the dead `daemon.enable_hello_world_handlers` flag so it actually gates the TEST handlers; default off removes the `✅ hook active` injection + the idle-tick doubled-stop root-caused in Plan 00161)

### Plan Workflow / QA

- [00144: Plan QA System — Real-Time Plan Validation & Drift Enforcement](00144-plan-qa-system/PLAN.md) - In Progress (Phase 1 core underway; scope includes mkplan `_TEMPLATE_.md` externalisation)

  - Pure `plan_qa` core (PlanTree/PlanDoc/ReadmeIndex parsers + declarative check registry) consumed by three surfaces: edit-time PreToolUse lint, `git commit` cross-file gate (warn→block ratchet), and whole-tree sweep (SessionStart advisory + `plan-qa` CLI, CI-able)
  - Enforces status-header integrity, index-at-birth, terminal-state atomicity (`git mv` + README row + stats in one commit), number-collision defence, and required archive dirs (`Completed/`/`Cancelled/`, configurable)
  - Config under `plan_workflow.qa`; grandfathering for legacy plans; spec provenance: `untracked/hooks-daemon-plan-verify-qa.md` (31-sin audit catalogue)

### Self-Driving / Automation

- [00135: Event-Driven `send-keys` Injection](00135-event-driven-send-keys-injection/PLAN.md) - **In design**

- [00160: Supervisor Foreground Identity & Dead-File Reaping](00160-supervisor-foreground-identity-and-reaping/PLAN.md) - In Progress (00135 follow-up: reap dead sidecars/signals + bind the supervisor to the foreground session so `/compact` only ever targets the focused Agent-View thread; background-thread looping is out of scope)

### Memory / Documentation Policy

- [00132: PostToolUse Progressive-Disclosure Reminder on Project-Doc Markdown Writes](00132-progressive-disclosure-md-write-reminder/PLAN.md) - Not Started (awaiting sign-off)

  - Complements 00131's *block* with a *positive nudge*: a PostToolUse advisory that, after a project-doc `.md` write, re-hints the progressive-disclosure rules and asks "is this in the right place / is it the single source of truth?"
  - Scoped to `CLAUDE.md` + the `CLAUDE/` doc tree, **excluding** `CLAUDE/Plan/` and `CLAUDE/Journal/` (explicit locations); rate-limited by an in-memory cooldown counter mirroring `critical_thinking_advisory` so it never spams
  - Awaiting sign-off on Decision 1 (trigger path-set; `docs/`+`README` in or out) and the default cooldown size

- [00131: Block Untracked Claude Memory + Tracked-Docs Progressive Disclosure](00131-disable-auto-memory-tracked-docs-system/PLAN.md) - Shipped v3.23.0 (Phases 1–4; Phase 4 scaffolding-skill + Phase 6 dogfood deferred to follow-ups)

  - Shipped: `allow_untracked_claude_memory` option (default `true`) on `markdown_organization` — when `false`, **blocks** Write/Edit + bash redirect/tee writes to Claude memory files (reads always allowed) with a specialist tracked-docs / progressive-disclosure message; `optimal_config_checker` reconciled so it no longer nags to re-enable memory under the policy
  - User-directed design: enforce by **blocking at the daemon layer**, not by disabling Claude's own (unreliable) memory engine
  - Deferred follow-ups: a scaffolding skill (inventory docs, `@`-import audit, auto-build rules/skills) and dogfooding the policy in this repo (migrate `MEMORY.md` into tracked docs)

- [00116: CLAUDE.md Token Compression via Stateful Progressive Disclosure](00116-claude-md-token-compression/PLAN.md) - In Progress (Phases 1–2 complete and merged; Phase 3 pending tracker-wiring decision)

  - Compresses the always-resident CLAUDE.md via stateful progressive disclosure so handler guidance loads on demand rather than inflating every session's base context; Phases 1–2 merged, Phase 3 awaits a tracker-wiring decision

### Tooling / Dependencies

- [00130: Plan-Scaffolding Script Distribution (`mkplan.bash`)](00130-plan-scaffolding-script-distribution/PLAN.md) - Shipped v3.23.0

  - Candidate `mkplan.bash` proposed for distribution into client plan folders: scaffolds the next numbered plan folder + skeleton `PLAN.md`, resolving the number from the git-anchored `hooksdaemon.latestPlanNumber` counter (Plan 00112) so humans and agents stop hand-rolling names / scanning `ls` for the next number
  - Three legs: distribute the script, configure hooks so script + daemon agree on counter ownership (no double-increment), guide agents toward it
  - First deliverable is a **full hostile audit** (correctness, portability, security, daemon-integration, distribution) tracked as versioned `AUDIT-vN.md` docs with the script refined + committed each iteration — not a rubber stamp

- [00129: Wire llm-friendly-qa-wrappers in as a Major Dependency](00129-llm-qa-wrappers-integration/PLAN.md) - Not Started

  - GitHub Issue [#33](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/33)
  - Adopt [`edmondscommerce/llm-friendly-qa-wrappers`](https://github.com/edmondscommerce/llm-friendly-qa-wrappers) (terse-terminal + JSON-to-tempfile wrappers around ESLint/PHPStan/Ruff/etc.) as a major dependency; build PreToolUse handlers that redirect raw QA tool calls → wrapper version and guide the agent to parse JSON with `jq` (generalises the `npm_command` interception pattern)
  - Single schema-validated `raw command → wrapper invocation` SSOT via Strategy + Registry (no hardcoded if/elif)
  - Secondary strand: global `--json` mode on [`lts/php-qa-ci`](https://github.com/LongTermSupport/php-qa-ci) (`bin/qa` Bash pipeline) so the whole PHP pipeline emits one machine-readable result, vs. wrapping each PHP tool individually
  - Reference repos cloned to `untracked/repos/`; wrapper repo audit captured in `AUDIT-llm-friendly-qa-wrappers.md`; adoption gated on the audit verdict

### Infrastructure / Bootstrap

- [00110: Python Interpreter Discovery — DRY Consolidation & Latest-Always Policy](00110-python-discovery-dry-consolidation/PLAN.md) - Not Started

  - Field report from host host-a (`untracked/hooks-daemon-upgrade-python-version.md`): skill `install.sh` aborted on default `python3` (3.9.21) and suggested hardcoded `python3.11` despite `python3.13`/`python3.14` being on PATH
  - Consolidates four WET Python-discovery implementations (`scripts/upgrade.sh`, `scripts/install/prerequisites.sh`, skill `install.sh`, `daemon/paths.py`) into one canonical bash helper + one canonical python helper
  - Replaces hardcoded `(3.13, 3.12, 3.11)` candidate lists with glob `python3.[1-9][0-9]` + numeric sort — Python 3.14+ works the day it ships, no daemon release required
  - Error messages must name interpreters **actually observed during the glob**, never hardcoded ones
  - Adds Task 5.1 host-a replay to RELEASING.md Step 12.0 H-1 gate (count 19 → 20)

### Handler UX Adjustments

- [00117: Enable ask_user_question_blocker (dogfood → default-on)](00117-ask-user-question-blocker-default-on/PLAN.md) - Dormant (remaining: flip shipped default + regression test; awaiting scheduling)

  - Dogfooding alert: agent stalled twice asking tautological questions ("Should I push?"); the prefix-positive `ask_user_question_blocker` (Plan 00108 / v3.14.0) was shipped `enabled: false` so it never fired
  - Phase 1 DONE: enabled in this project's config, daemon restarted, live probe confirms unprefixed AskUserQuestion is denied with `ASKING BECAUSE:` guidance
  - Remaining: flip the shipped install/upgrade default to enabled (G2), regression test pinning the default (G4), upgrade-guide/changelog note (G5)

- [00108: Nuanced AskUserQuestion Blocker](00108-question-blocker-nuanced/PLAN.md) - Not Started

  - Replace always-deny `ask_user_question_blocker` with prefix-positive `ASKING BECAUSE:` policy mirroring the Stop handler's `STOPPING BECAUSE:` convention
  - DENY path instructs agent to state assumed-correct answer and proceed (audit log for the watching user)
  - Ships `enabled: false`; flip to default-on in follow-up after dogfooding

### Stop-Quality Stack (dependency chain)

- [00085: Reminder Pseudo-Event System with Adaptive Triggers](00085-reminder-pseudo-event-system/PLAN.md) - Dormant (8-phase build deferred to a future release window)

  - 8 phases — AdaptiveTrigger, config parsing, dispatcher, WorkflowReminderSetup, handler, constants/registration, config, verification
  - Dependency chain resolved: 00077 (Already Shipped) and 00081 (Superseded by 00082) both closed in Plan 00107 Wave 3

### Long-Running / Carry-Forward

- [00100 (v3): Venv SSOT Consolidation](00100-venv-ssot-consolidation/PLAN.md) - Dormant (residue scope awaits a dedicated release)

  - Phases 0–3.9 **shipped** in v3.9.0 / v3.10.0 / v3.11.0 (canonical SSOT resolver, `.daemon-metadata.json` writers, dead-code removal, path slug, eager upgrade cleanup, H-1 gate coverage)
  - **Residue deferred from v3.12.0** (Plan 00107 Wave 4): Phase 3.5.2–3.5.7 (bootstrap-fallback wiring), Phase 4 (flock concurrency), Phase 5 (parameterised upgrade-cycle test), Phase 6 (docs) — internally coherent and well-suited to a dedicated v3.13.0 release

- [00102: Hook Executable-Bit Defense](00102-hook-exec-bit-defense/PLAN.md) - Dormant (only Task 5.3 remains — release-time acceptance gate, executes with the next /release)

  - Phases 1–4 complete (`bash <path>` invocation, auto-migration, self-heal, filemode checker)
  - **Task 5.3 pending**: acceptance gate at v3.12.0 release time (folded into meta plan 00107 Wave 6 `/release` execution)

### On Hold (upstream-blocked)

- [00032: Sub-Agent Orchestration for Context Preservation](00032-subagent-orchestration-context-preservation/PLAN.md) - On Hold

  - Waiting for upstream Claude Code delegate mode fix (cascades to teammates, breaking agent teams)
  - Blocked by: GitHub issues #23447, #25037 (delegate mode cascade bug)

- [00034: Model-Aware Agent Team Advisor](00034-model-aware-agent-team-advisor/PLAN.md) - On Hold

  - Depends on Plan 00032 orchestration infrastructure

- [00035: StatusLine Data Cache + Model-Aware Advisor](00035-statusline-data-cache-model-advisor/PLAN.md) - On Hold

  - Depends on Plan 00032 orchestration infrastructure

## Completed Plans

- [00157: Review Followups — Perf Wave](Completed/00157-review-followups-perf-wave/PLAN.md) - Complete (closes the loop on the v3.38.0 release-review findings so no review value is lost as tech debt. Fixed immediately after v3.38.0 shipped: removed a dead `pgrep` line in `daemon_control.sh` (the hyphenated console-script name never matched the real underscore module-path daemon after v3.38.0 removed the console entry); corrected `init.sh`'s `emit_error_json` Stop reason so a malformed-Stop-payload reports "daemon likely healthy; do not restart" instead of "daemon not running", still failing CLOSED (RED→GREEN `test_malformed_payload_stop_reason_is_accurate`); documented the two directory-bounded caches (`git_branch.py`/`validation.py`) as an accepted YAGNI trade-off; confirmed the 8 advisory-handler `None` guidances as intentional; added a "Review Early, Never Drop Findings" section to `RELEASING.md`. QA 13/13, 9841 tests, coverage 95.6%; daemon restart RUNNING)

- [00156: Performance Tuning Wave 2 — drop `jq`, slim `init.sh`](Completed/00156-performance-tuning-wave-2-drop-jq-slim-init/PLAN.md) - Complete (`Themes: performance`; Wave 2 off Plan 00154, the forwarder-side wins. T2: eliminated `jq` from every hook wrapper — the per-event JSON wrap (and status-line's wrap+unwrap) moved into the `python3` transport each wrapper already spawns, saving ~22-24 ms/event; all three `send_request_stdin` definitions + `forward_stop_event` are jq-free (jq remains only in `emit_hook_error`). T3: portable, bash-3.2-safe slim of the `init.sh` hot path (guarded `mkdir`, one fewer `tr` spawn in the hostname suffix) — ~12.46→11.07 ms/source (~1.4 ms/event); riskier `stat`/`date`/`dirname` swaps deliberately deferred. Payload stays on stdin (control-char safe); only the hardcoded event-name literal moved to argv. Request envelope, Stop exit-2 contract, status-line fallback, and CI/daemon-down error responses all byte-preserved and pinned by a new 33-test jq-free forwarder guard suite (broken-`jq` shim on PATH) + init.sh characterization tests; dogfooding/CI-passthrough/stop-hard-block gates + live probes green. QA 13/13, 9822 tests, coverage 95.6%. Commits `83f5f91`/`b88d424`/`c4fff5b`)

- [00155: Performance Tuning Wave 1 (daemon-side, safe)](Completed/00155-performance-tuning-wave-1-daemon-side/PLAN.md) - Complete (`Themes: performance`; first implementation wave off Plan 00154 — pure-Python daemon-side wins, no transport-contract risk. T1: memoised `is_hooks_daemon_repo` so `daemon_restart_verifier` forks `git remote` once per daemon lifetime not per Bash event (1076→2.1 µs). T4: short per-cwd TTL cache for the status-line git render (10.4 ms→4.0 µs on a hit, cutting ~4 git forks/render under streaming). Also deleted the drifted, off-production-path legacy one-shot `hooks/*.py` package (−6126 lines) per user decision. QA 13/13, coverage 95.6%. New `CLAUDE/Performance/` hub. Commits `43eaddd`/`eb3e2ad`/`62a7115`/`ea08a31`. Wave 2 = T2 drop `jq` + T3 slim `init.sh`)

- [00154: Daemon Performance — Rust vs Python Research](Completed/00154-daemon-performance-rust-vs-python-research/PLAN.md) - Complete (research-only, delegated to a Fable agent; five write-ups + reproducible benchmark harness/results in-folder. Headline: the daemon is already lightweight — ~85 ms/tool-call against multi-second turns, ~51 MB RSS, no user-visible cost. Full Rust rewrite = **never** (≤4% end-to-end ceiling, pays with the project's auditability); PyO3 core = never; a policy-free transport forwarder is the only Rust increment that could ever pay, and **not yet** (half its win is free by dropping `jq`). Hands back no-rewrite tuning wins T1–T4 to drive future dev. Delivered with plan closure)

- [00153: Plan-QA Extensible Root Files](Completed/00153-plan-qa-extensible-root-files/PLAN.md) - Complete (additive `plan_workflow.qa.extra_root_files` allowlist threaded through `QaPolicy` → `PlanTree.scan` so clients can permit a legitimate non-plan file such as a sourced `_planlib.bash` at the plan root without the permanent stray-file advisory; default empty = zero behaviour change; docs + config-changes manifest `v3.37.0.yaml`. Commit `df9262b`)

- [00152: Supervisor Graduated Compaction Bands](Completed/00152-supervisor-graduated-compaction-bands/PLAN.md) - Complete (split the ccy supervisor's compaction into three context bands — lower red `[red,mid)` waits for child output to settle before `/compact` (restores pre-00151 "blocked whilst busy"), elevated `[mid,critical)` injects promptly even mid-turn, critical adds the ESC flush now gated to critical only; added a `compact_urgent` midpoint band to `context_tiers`/sidecar and `OutputActivity`/`work_idle` child-output tracking. Commit `9a0a4b4`)

- [00151: Supervisor tick starvation + CRITICAL tier](Completed/00151-supervisor-tick-starvation-and-critical-tier/PLAN.md) - Complete (fixed ccy supervisor `on_poll` starvation during child output streaming so context can no longer climb past red unchecked; added a CRITICAL tier above red — 200k ≥90%, 1000k ≥60% — surfaced as a sidecar `critical` flag + a `🛑 COMPACT NOW` status-line call-to-action; supervisor bypasses the compact cooldown at critical, injects `[esc]` to flush a queued `/compact`, and defers to a human-submitted `/compact` instead of double-compacting; `ccy_supervisor_integrity` warns when armed+present but `deploy_supervisor: false`. Commits `029772d`/`09ba2d7`/`df679a0`/`ccc7e74`/`6633792`)

- [00150: Client-configurable exclude_paths for content-scanning blockers](Completed/00150-client-configurable-exclude-paths-for-content-blockers/PLAN.md) - Complete (shared stdlib glob-exclusion utility wired into security_antipattern / qa_suppression / error_hiding_blocker + project-wide `daemon.exclude_paths`; error_hiding_blocker gains sibling default skips; shipped v3.35.0, commit `1c00123`)

- [00149: ccy Supervisor — Sidecar Path + Empty-Box Guard](Completed/00149-ccy-supervisor-sidecar-path-and-empty-box/PLAN.md) - Complete

  - Two High-severity supervisor bugs surfaced once v3.34.0 made the ccy supervisor run in clients. **Bug A**: `_default_sidecar_dir()` hardcoded the self-install layout, so in every normal client install the supervisor polled a dir the daemon never wrote and the compact trigger was permanently inert (masked because prior testing was all self-install) — fixed by mirroring the daemon's install-mode detection (self-install iff `{project}/src/claude_code_hooks_daemon` exists). **Bug B** (Fable subagent, worktree-isolated): the supervisor pasted into a non-empty input box and submitted, corrupting the human's in-progress text — fixed with a `HumanInputLine` model fed from forwarded stdin that gates every injection path on an empty box (conservative bias; injected keystrokes bypass the recorder). Shipped patch v3.34.1. Delivered `c0e7209` (Bug A) / `0a9b09b` (Bug B) / release `a40962a`; QA 13/13 (9840 tests), 127 supervise tests, artifacts consistent.

- [00148: ccy Supervisor Arm on Deploy](Completed/00148-ccy-supervisor-arm-on-deploy/PLAN.md) - Complete

  - Made the v3.33.0 ccy supervisor auto-deploy actually work end-to-end. v3.33.0 copied `claude-supervise.py` but never **armed** it (never wrote the `CCY_CLAUDE_WRAPPER` export the launcher sources), and projects with a blanket-`*` `.claude/ccy/.gitignore` silently ignored the deployed files — so in clients the supervisor was an inert no-op that never reached teammates. Now the deploy **deploys + arms** (self-locating `${BASH_SOURCE[0]}` wrapper, idempotent, respects an existing/commented wrapper), appends `!` whitelist exceptions for our files to an existing `.claude/ccy/.gitignore` (without owning the project's ignore policy), and a new `ccy_supervisor_integrity` SessionStart advisory handler warns when an armed supervisor's files are missing/non-executable/git-ignored (brick risk). Shipped MINOR v3.34.0. Delivered `78164b1`/`8bf12f5`/`663fe75`/`785c913`, release `438a72e`; QA 13/13 (9804 tests), daemon RUNNING, artifacts consistent.

- [00147: ccy Supervisor Auto-Deploy](Completed/00147-ccy-supervisor-auto-deploy/PLAN.md) - Complete

  - Config-gated auto-deploy of the Plan 00135 PTY supervisor (`claude-supervise.py`) into a project's `.claude/ccy/` on install/upgrade. ONE tracked copy at `.claude/ccy/` (pure dogfooding, no `src/`/package duplicate); the deploy sources from the daemon-clone's `.claude/ccy/` (present in every git-clone install) and self-install no-ops when source==target. `ccy.deploy_supervisor` tri-state flag (true=deploy / false=opt-out / absent=deploy+recommend), gated on the target's `.claude/ccy/` dir. Wired via `python -c` heredocs into `install_version.sh` + both `upgrade_version.sh` paths (mirrors the `deploy_skills` / `deploy_plan_workflow_if_enabled` convention). Ships in v3.33.0 with a config-changes manifest (`recommended: true`). Delivered `ba3b822`/`0396c60`/`0c1297a`; QA 13/13, daemon RUNNING.

- [00146: Hard-block rhetorical continue questions in explained stops](Completed/00146-stop-hard-block-rhetorical-continue/PLAN.md) - Complete

  - Dogfooding fix from live evidence: `auto_continue_stop` Branch 2 (`STOPPING BECAUSE:` -> ALLOW) short-circuited before confirmation-question detection, so rhetorical "want me to build slice 2 next?" / "Should I proceed?" stops sailed through when prefixed. The confirmation check now runs on the same freshness-resolved current-turn message INSIDE Branch 2 and hard-DENIES with a firm get-on-with-it block; the shared `_CONTINUE_VERBS` group extends coverage to start/build/implement/tackle/etc. while keeping the `?` requirement so genuine either/or choice questions still stop cleanly. Also killed the 6x advisory spam: nitpick dismissive/hedging handlers dedupe to one line per category, and the Stop-event dismissive detector suppresses back-to-back identical (session + phrase-set) advisories. Live-probed both ways against the production `.claude/hooks/stop` wrapper (block exit 2 / clean allow exit 0 / re-entry no-loop). QA 13/13, daemon RUNNING.

- [00143: Loud Project-Handler Load-Failure Alert](Completed/00143-loud-project-handler-load-failure-alert/PLAN.md) - Complete

  - Closed a silent fail-open on the observability axis: when a project handler under `.claude/project-handlers/` fails to load (e.g. an upgrade made `get_claude_md` required and an older handler predates it), the daemon safely skips it but used to only log a line nobody reads — an agent could work a whole session believing protections were live. Now the running daemon **persists** its load failures (`project_handler_health` state file, always-rewritten so it reflects the live daemon), a new on-by-default `project_handler_load_checker` SessionStart handler injects a loud `🚨 PROJECT PROTECTION DEGRADED 🚨` alert (listing each skipped handler + reason + fix-then-restart remediation; silent when clean), `status`/`check` surface the degraded state and `health` returns a non-zero exit, and `upgrade_version.sh` Step 16.5 runs `validate-project-handlers` post-upgrade (loud, non-fatal). Verified live end-to-end. QA 13/13 (9126 tests, 95.2%), daemon RUNNING. Commits `384f353` (capture+persist), `7cac2b1` (alert), `43b8dc1` (CLI signal), `a37834d` (upgrade gate), `bf183f9` (docs/config/manifest).

- [00142: Background-Shell Harvester & Root-Recursion Guard](Completed/00142-background-shell-harvester-and-root-recursion-guard/PLAN.md) - Complete

  - Two-layer defence from a post-incident report (an orphaned `ugrep -rl … /` ran ~115 min at >1000% CPU, surviving a compaction). **Layer A** — `root_recursion_guard` PreToolUse blocking handler: denies recursive scanners (`grep -r`/`-R`, `ugrep`, `rgrep`, `find`, `fd`, `rg`) rooted at `/`, `/proc`, `/sys`, `/home`, `/root`, `~`, `$HOME`, with scoped-search guidance, the `| head`-doesn't-bound-`-l` note, and a `MUST_SCAN_ROOT_BECAUSE=` escape hatch. **Layer B** — `harvest-background` CLI + pure harvester core (ps-based: CPU breach for ALL processes catches reparented orphans, wall-TTL for tracked pgids; emits `kill -- -<pgid>` but **never kills**) plus `background_process_tracker` PostToolUse advisory (default-on, rate-limited) that records backgrounded commands and steers the agent to a watchdog cron + harvest check. Owner steer honoured: daemon detects & escalates, the agent decides every kill. QA 13/13 (9076 tests, 95.0%), daemon RUNNING, both layers dogfooded live. Commits `c71780a` (Layer A), `b545ee6` (harvest CLI), `f053a35` (tracker).

- [00141: `release-notes` CLI subcommand + skill route](Completed/00141-release-notes-subcommand/PLAN.md) - Complete

  - New `release-notes` daemon CLI subcommand + `/hooks-daemon release-notes` skill route (Plan 00141). Pure module `install/release_notes.py` reads the per-version `RELEASES/vX.Y.Z.md` files (shipped with every git-checkout install — no bundling, no network) and prints notes by installed version (default), `--version`, `--latest`, `--from/--to` range (`from` exclusive, `to` inclusive), or `--list`, in markdown or `--format json`; mirrors the `check-truth-changes` sibling pattern (exit 0 found / 1 not-found / 2 bad range). An audit confirmed release-notes discipline is GOOD (91/91 tags had RELEASES files); the lone gap — `v3.12.0` missing from CHANGELOG.md — was restored during the release. Module coverage 98%+, code-review APPROVED. Shipped as **v3.28.0** (release commit `fad2e4e`, tag `v3.28.0`); commits `8a044fa`/`a995ff7`/`6664328`.

- [00140: Deep Code Review & Fix (Workflow-Orchestrated)](Completed/00140-deep-code-review-fix-workflow/PLAN.md) - Complete

  - Dynamic-Workflow deep review of the daemon source: 13 Opus reviewers + adversarial Opus verification → **101 findings, 77 confirmed** (`FINDINGS.md`). Remediated end-to-end via Opus sub-agent fixers (worktree-isolated, TDD) in two batches: batch 1 = 28 critical/high/medium (incl. a CRITICAL `grep …; sed -i` mass-destruction bypass, RCE `curl | sudo -E bash` bypass, an `auto_continue_stop` QA-pass false-positive, a bandit silent-pass) + the recovery_cron cluster; batch 2 = 49 lows + 1 new `destructive_git` cross-separator false-positive. **78 fixes total**, all merged with QA 13/13 (8947 tests), daemon restart RUNNING, headline fixes live-probed. Doubled as the dogfood load for Plan 00139's cron. Commits: review `75a9dc9`, batch 1 `0cdf4a6`, batch 2 `7fe2cb6`/`b063be5`.

- [00139: Failsafe Recovery Cron](Completed/00139-failsafe-recovery-cron/PLAN.md) - Complete

  - New opt-in `recovery_cron_advisor` PostToolUse handler: across a plan's lifecycle (create → progress → complete) it prompts the agent to run a **non-durable hourly failsafe recovery cron** that resumes work stalled by *external* factors (API overload, rate limits, 5-hour usage limits) — explicitly **not** a heartbeat. Daemon is advisory (`CronCreate` is agent-side); per-plan progress cooldown prevents context spam. Live-dogfooded this session: the cron fired on schedule and was correctly no-op'd; a real API rate-limit stall was recovered per the contract. All 6 self-review findings fixed. Commit `e5a4b83` (handler `09bc085`); config-changes staged for v3.27.0.

- [00138: Fix Plan-Number Handler False Positives](Completed/00138-plan-number-helper-false-positives/PLAN.md) - Complete

  - TWO plan-number handlers wrongly fired on a SPECIFIC, already-known plan folder (same disease). `plan_number_helper` (priority 33, Bash): the `find` pattern matched any subpath and the `echo`/`printf` glob char-class matched a bare digit, so `find`/`echo`/`printf` referencing `CLAUDE/Plan/00135-x` were blocked as discovery. Fix: anchor `find` to the plan dir itself (`/?(\s|$)`) and require a real glob metachar (`*`/`[`/`?`) for echo/printf. `validate_plan_number` (priority 41, Write/Edit + mkdir): warned when editing an EXISTING plan's PLAN.md (no existence check) and zero-stripped the folder name in its message (`00135` → `135`). Fix: skip when the target plan folder already exists on disk; echo the original digit string verbatim and use the zero-padded `PLAN_NUMBER_WIDTH` convention in the corrected example. All pre-existing true positives preserved. 11/13 QA (8720 tests, 95.1% cov); smoke_test deferred to post-merge daemon restart (worktree has no daemon).

- [00137: Install/Upgrade SSoT + KISS Audit & Remediation](Completed/00137-install-upgrade-ssot-kiss-audit/PLAN.md) - Complete

  - Remediated all six remaining findings from the Opus SSoT/KISS audit spawned by 00136. **F-PROFILE** (seed-only): handler profiles documented as a one-shot install-time seed; the config-merge preserves the seed on upgrade (no path re-applies a profile). **F-PLANDEF/F-PLANDIR**: flipped `plan_workflow.enabled` model default to False (opt-in, matching the opt-in plan handlers), kept the legacy-opt-in migration, removed the duplicated per-handler `track_plans_in_project` from the example (top-level `plan_workflow.directory` is the runtime SSoT the registry already injects). **F-PYFLOOR**: `check_python3` raises the Python floor from `pyproject.toml` instead of a hardcoded `3.11`. **F-PROFLIST**: profile handler names validated against config keys. **F-VENVSUM**: install summary prints the real `$VENV_PATH`
  - Delivery commits `defe9fb`, `faa53e2`, `026dde9`, `18c4a65`, `d5c95cd`, `a7ef263`. The plan-workflow opt-in flip is a behaviour change — staged `config-changes`/`truth-changes` manifests under `UNRELEASED/` for the next release. 13/13 QA

- [00136: mkplan deployment driven by config SSoT](Completed/00136-mkplan-deploy-config-ssot/PLAN.md) - Complete

  - Fixed a v3.24.0 field bug (client `client-a-infra`): `mkplan.bash` (Plan 00130) was only deployed by `install_version.sh` behind the opt-in `PLAN_WORKFLOW=yes` and never deployed on upgrade, while `plan_number_helper` guidance told agents to run it. Deployment now derives from the config SSoT (`config.plan_workflow.enabled`) via one `deploy_plan_workflow_if_enabled` entrypoint called by install + both upgrade paths; the `PLAN_WORKFLOW` env var was removed entirely (KISS); two end-to-end acceptance gates prove the script deploys on real install + upgrade
  - Shipped in **v3.25.0** (release commit `a6f0717`, tag `v3.25.0`). Spawned the Opus SSoT/KISS audit → remaining findings tracked in Plan 00137

- [00134: Format CLAUDE.md After Handler-Guidance Injection](Completed/00134-format-claude-md-after-injection/PLAN.md) - Complete

  - Extracted the mdformat+gfm transform into `utils/markdown_format.format_markdown_text` (SSoT) and pointed the `markdown_table_formatter` handler, the `format-markdown` CLI, and `ClaudeMdInjector` at it (removed two duplicate copies)
  - The injector now formats CLAUDE.md after writing its `<hooksdaemon>` block (fail-safe; content-loss guard runs on the pre-format replace result), so a later edit no longer churns the injected block. Shipped in **v3.24.0** (commit `08e25d3`; dogfooded — first restart applied a one-time canonical reformat)

- [00133: Suggest Enabling New Features on Upgrade](Completed/00133-suggest-enabling-new-features-on-upgrade/PLAN.md) - Complete

  - Revived/strengthened/wired the abandoned config-changes upgrade advisory so upgrades actively recommend enabling dormant opt-in features (`recommended`/`dormant`/`recommended_value`; `changed`-value comparison; `🆕 Recommended` section; `check-config-migrations` wired into `upgrade.md` + `scripts/upgrade.sh`; v3.x backfill + `UNRELEASED/config-changes/` staging)
  - Added `Handler.get_default_enabled()` opt-in/opt-out SSoT (concrete, drift-guarded against the template); flipped `allow_untracked_claude_memory` default `true→false` (opt-out, with `critical` post-upgrade task + truth-changes + config-changes manifest); dogfooded the policy in this repo (lessons migrated to `CLAUDE/development/LESSONS.md`)
  - Shipped in **v3.24.0** (release commit `8248c40`, tag `v3.24.0` = `18caf51`)

- [00128: Lean SessionStart — silent-when-healthy + verbose `check` command](Completed/00128-lean-session-start/PLAN.md) - Complete

  - SessionStart printed ~80 lines every session (40-line dogfooding reminder, container banner, "all good" status lines). Made the advisories silent-when-healthy so they only speak when action is needed — matching the already-correct `version_check` / `gitignore_safety_checker` model
  - `git_filemode_checker` + `hook_registration_checker` now emit only on problems; `optimal_config_checker` suppresses its 6-setting audit at session start (keeps silent settings-sync); `yolo_container_detection` gains `show_on_session_start` (default off); the `dogfooding_reminder` plugin trimmed ~40 lines → one line. Kept `hello_world` handlers (dogfooding liveness — explicit user decision)
  - New `cli check` subcommand + `/hooks-daemon check` skill sub-command surface the full verbose env/config audit (output tokens, bash working dir, container runtime, git fileMode, hook registration) on demand, reusing the handlers' own check logic (single source of truth)
  - A fresh in-container SessionStart dropped from ~80 lines to 2. QA 13/13 (8628 tests, 95.1%); daemon RUNNING; live-verified both directions. Commits `4344d46` (Phase 1), `5490f24` (Phase 2), `a8fe650` (format)

- [00127: Parallel-Session Daemon Isolation & Reuse (+ LXC detection)](Completed/00127-parallel-session-daemon-isolation/PLAN.md) - Complete

  - Fixed the parallel-session bug (user report): multiple Claude Code processes sharing one `(hostname, project root)` — e.g. several agents in a single LXC container — fought over the daemon socket because a second start unconditionally unlinked the live socket and clobbered the PID file (one session's hooks worked, the other's silently did not); reproduced live in-container (two daemon servers, one PID file)
  - REUSE fix (Decision 1) across all layers: `init.sh` stops removing a live socket; `cli.cmd_start` runs a three-state liveness gate (LIVE/NOT_LIVE/INDETERMINATE) FIRST and reuses a live-or-busy incumbent before `enforce_single_daemon`; `server.start()` probes under an exclusive `flock` and raises `DaemonAlreadyRunningError` instead of stealing a live socket. Phase 5 orphan janitor dropped as redundant (YAGNI/DRY)
  - LXC/LXD detection (Phase 4): cgroup-v2-safe via `/run/systemd/container` + `container=lxc` env + cgroup-v1 token + `/dev/lxd/sock` (no subprocess); 🧊 status icon; desktop invariant (Plan 00126) preserved
  - Two ultracode workflows (spec → TDD → QA → adversarial review); review caught 5 real bugs, all fixed. QA 13/13 (8617 tests, 95.1%); daemon restart + live parallel-start test verified. Commits `0176767` (lifecycle), `75c755c` (LXC)

- [00126: Container-detection conflation fix + status-line env indicator + memoisation](Completed/00126-statusline-env-indicator-and-memoisation/PLAN.md) - Complete

  - Root cause: container detection scored the tautological `CLAUDECODE=1` / `CLAUDE_CODE_ENTRYPOINT=cli` signals as container evidence — but this daemon ONLY runs under Claude Code, so those are always true and classified every desktop session as a container
  - Rewrote `container_detection` around three honest, separated predicates: `running_under_claude_code()`, `is_yolo_sandbox()`, and `detect_container_runtime()` / `in_container()` (honest OS markers only: `container` env, `/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup`). `is_container_environment()` kept as a precise alias so `enforcement.py` / `init_config.py` call sites stay correct
  - New `EnvironmentIndicatorHandler` (status priority 11) shows 💻 desktop / 🐳 docker / 📦 podman, reading the runtime cached ONCE on `ProjectContext` at daemon startup — no per-render probing
  - Memoisation: container fact via `ProjectContext` startup cache; new shared `settings_reader` (mtime-cached) ends the `model_context` + `thinking_mode` double-parse of `~/.claude/settings.json`. git_branch / account_display / daemon_stats deliberately left per-render (mutable state, not invariants — see PLAN D5)
  - QA 13/13 (8561 tests, 95.1%); daemon restarts RUNNING; live status line renders `📦 podman`

- [00125: Auto-detect containers → uv copy mode](Completed/00125-uv-container-copy-mode/PLAN.md) - Complete

  - Follow-up to v3.19.1: container installs/upgrades printed the `uv hardlink failed (likely overlay-fs) — retrying with UV_LINK_MODE=copy` warning on every run
  - Root cause: `create_venv_at_path`'s proactive copy-mode detection probed only the TARGET fs type (`overlay`/`nfs`); in a container the target is bind-mounted from the host (a normal fs) while uv's cache is on the container overlay fs — cross-device, so hardlink fails but the type probe could not see it
  - Fix: added `_uv_in_container` helper (signals: `container` env var, `/run/.containerenv`, `/.dockerenv`; marker paths overridable for tests) and wired it into the `first_link_mode` decision — containers now pick copy mode up front. Explicit `UV_LINK_MODE` and normal-disk hardlink-first behaviour unchanged
  - 4 new tests; QA 13/13 (8543 tests, 95.1%); live-verified detection in the Podman dev container

- [00124: ensure_venv missing project-path slug](Completed/00124-ensure-venv-missing-slug/PLAN.md) - Complete

  - Hotfix: `ensure_venv` (`scripts/install/venv.sh`) computed the venv fingerprint without passing its `daemon_dir`, so the venv was keyed by the bare slug-less `venv-py{MM}-{hash}` instead of the slugged `venv-{slug}-py{MM}-{hash}`
  - A desktop host and a containerised session sharing a bind-mounted project + the same Python (same `sys.version`/`base_prefix`/arch) collided on one venv and fought over it — the project-path slug (Plan 00100 Task 3.0.5) is the discriminator and it was being dropped
  - Fix: pass `$daemon_dir` to `python_venv_fingerprint`; broadened the venv-discovery glob in `scripts/upgrade.sh` and four acceptance tests from `venv-py*` to `venv-*py3*` (matches both slugged and legacy bare); added a canonical-resolver-exempt marker for the dependency-light metadata glob
  - 1 new isolation test in `test_ensure_venv.py`; QA 13/13 (8539 tests, 95.1%); daemon RUNNING

- [00123: macOS Portability Follow-ups](Completed/00123-macos-portability-followups/PLAN.md) - Complete

  - Discovered during v3.19.0 release prep by a dedicated macOS-gotcha hunt agent — four further BSD/bash-3.2 incompatibilities Plan 00122 did not cover
  - **BUG 1 (critical)** — `init.sh` ran `_abs_project_path=$(realpath "$PROJECT_PATH")` under `set -euo pipefail` on every hook; `realpath` is absent on macOS < 12.3 so the substitution aborted every hook. The variable was dead → deleted
  - **BUG 2 (high)** — `resolve_venv.sh` hot-path cache used GNU `stat -c %Y` (sourced by init.sh per hook); returned empty on macOS so the cache never hit → 50-100ms Python fingerprint spawn every hook. New `_rv_dir_mtime` helper falls back to BSD `stat -f %m`
  - **BUG 3 (medium)** — `daemon_control.sh` used GNU BRE `\|` alternation in `pgrep -f` AND `grep -qi`; BSD treats it literally so neither matched on macOS. Extracted `_daemon_process_exists` (two pgreps) + switched the grep to ERE `-E` (the second site was a bonus catch the hunt missed)
  - **BUG 4 (medium)** — `hooks_deploy.sh` self-install short-circuit used `readlink -f` (no `-f` on BSD) → never fired on macOS; replaced with bash `-ef` (same-inode) operator
  - Repo-wide sweep confirmed no other executable `\|`, `readlink -f`, unguarded `stat -c`, `date -d`, `base64 -w`, `grep -P`, or `sed -i` in shell scripts. 11 new regression tests; QA 13/13 (8538 tests, 95.1%); daemon RUNNING. Delivery commits `a5bd807`, `182be0f`, `039fe69`

- [00122: macOS Portability Fixes](Completed/00122-macos-portability/PLAN.md) - Complete

  - Downstream macOS field report (`untracked/mac-issues/`): the daemon was non-functional on macOS; six bugs reproduced and fixed (not yet released)
  - **BUG 1 (critical)** — when `$HOSTNAME` is unset (default on macOS/zsh, minimal containers), BOTH the Python daemon (`paths.py`) and the bash forwarder (`init.sh`) derived the runtime-file suffix from a `time.time()` hash that changed on every call, so `start`/`status`/`stop` each looked for a different socket. New DRY memoised `resolve_hostname()` (series: `$HOSTNAME` → `socket.gethostname()` → `localhost`) is the Python SSOT (routed through `_get_hostname_suffix` + `cmd_bug_report`); `init.sh` mirrors it via the `hostname` command so bash and Python agree. Antipattern sweep confirmed these two were the only time-as-identity abuses
  - **BUG 2** — `venv.sh` `stat -f -c %T` fs probe is GNU-only; now gated on `uname -s = Linux` (overlayfs is Linux-only), no stray BSD error
  - **BUG 3** — skill `install.sh` "already installed" guard now health-checks (venv python imports) and auto-escalates a broken dir to `--force` repair instead of bailing
  - **BUG 4** — `health-check.sh` EXIT trap makes silent non-zero exits honest; `debug_info.py` detects the client project root (not the daemon clone) and degrades gracefully (dumps runtime files/venv/processes) when init.sh detection fails
  - **BUG 5/6** — docs reconciled (CLAUDE.md Hostname-Based Isolation); user-facing scripts confirmed bash-3.2 clean (lone `mapfile` in dev-only `run_shell_check.sh` de-bash-4'd), with a regression-guard test scanning all repo shell scripts
  - bash↔Python suffix parity test pins the end-to-end fix; QA 13/13 (8527 tests, 95.1%); daemon RUNNING. Delivery commits `8d72594`, `e71df0c`, `28745d2`, `ec27240`, `a48dcb0`

- [00121: Additive extra_allowed_markdown_paths](Completed/00121-additive-markdown-paths/PLAN.md) - Complete

  - New `extra_allowed_markdown_paths` option for `markdown_organization`: additive allowed-location patterns layered on top of the built-in defaults (and over the legacy `allowed_markdown_paths` override), so projects declare only their extras instead of redeclaring the whole default set
  - Generalised `is_adhoc_instruction_file` to allow all markdown inside `.claude/skills/` (not just `SKILL.md`); `.claude/rules/` already covered (commit 38d7d5d)
  - Dogfooded by migrating this repo's own config from a 17-pattern override to a 2-entry additive list; docs (HANDLER_REFERENCE, per-handler doc, get_claude_md, init_config installer comment) updated to prefer additive
  - Staged a post-upgrade-task + truth-change (anticipated v3.19.0) so upgrading projects migrate override → additive
  - 13 new unit tests; full QA 13/13 (8508 tests, 95.1%); live daemon probe verified allow/deny behaviour

- [00120: Git Hooks Executable Fixer Handler](Completed/00120-git-hooks-executable-fixer/PLAN.md) - Complete

  - New `GitHooksExecutableFixerHandler` (PostToolUse, priority 27, non-terminal): detects git's `hint: The '...' hook was ignored because it's not set as executable` in Bash output and auto-remediates it
  - Resolves the active hooks dir via `git rev-parse --git-path hooks` (worktree/`core.hooksPath` safe) and `os.chmod`s every non-`.sample`, non-executable hook with least-privilege exec bits (execute only where read is already granted); `.sample` and already-executable hooks untouched
  - 23 unit tests, 100% handler-file coverage; full QA 13/13; live socket test verified 644 → 755 on a real pre-push hook through the running daemon

- [00119: Scope Single-Daemon Enforcement to Actual Daemon Server Processes](Completed/00119-enforcement-scope-to-daemon-server/PLAN.md) - Complete

  - Root-cause follow-up to the v3.18.2 "exit 143" upgrade false-failure: `find_all_daemon_processes` matched **any** `claude_code_hooks_daemon` cmdline, so single-daemon enforcement could SIGTERM transient CLI helpers (`status`/`stop`/`logs`/…) and hook forwarders
  - Now matches only daemon **server** cmdlines (cli module + `start`/`restart` launch subcommand) via `_is_daemon_server_process`; broad name/substring match + `DAEMON_PROCESS_NAME` removed
  - Allowlist proven complete (os.fork/os.setsid/HooksDaemon/asyncio.run live only in cmd_start, reachable only via start/restart) → zero false negatives; guarded by a unit test. Project-root scoping preserved
  - QA 13/13 (8470 tests, 95.0%); daemon restart RUNNING with no enforcement errors

- [00118: Truth-Changes — Project Doc Reconciliation on Upgrade](Completed/00118-docs-upgrade-guidance-mechanism/PLAN.md) - Complete

  - Per-version `was → now` truth-changes list (`now: ~` = remove all reference); the project LLM reconciles its own docs against it at upgrade time
  - Delivered through the existing upgrade flow (`upgrade.md` step reads `check-truth-changes` over the `(from, to]` range from `UPGRADE_METADATA`) — no marker, no staleness detection, no SessionStart push (deliberately simplified)
  - `install/truth_changes.py` range loader + `check-truth-changes` CLI; proof entry = v3.16.0 plan-number folder-scan → git-counter; fixed `plan_number_helper.get_claude_md()` (was `None`); RELEASING.md Step 6/7 governance
  - Delivered in commits `7aed50e`, `14f77c9`, `a4e49c0`, `090d47f`; exploration history archived under `Completed/00118-docs-upgrade-guidance-mechanism/archive/design1/`

- [00115: Parallel-Batch Cancellation Footgun Mitigation](Completed/00115-parallel-batch-cancellation-footgun/PLAN.md) - Complete

  - Delivered in commits `e7b02c2` (G1+G3) and `11d5eeb` (CLAUDE.md warning); not yet released
  - Root cause (dogfooding gold): when a daemon PreToolUse hook denies one tool call in a turn, Claude Code cancels every sibling tool call — batched Edit/Write/commit are silently lost; the lagged cancellations read like harness flakiness
  - **G1+G3**: every PreToolUse DENY now appends a warning that batched siblings were cancelled and must be re-issued separately (`core/hook_result.py` `_DENY_CONTINUATION_SUFFIX`), replacing the old "do not stop working" text that framed a block as consequence-free; live-proven
  - **G4**: brief permanent footgun warning added to hand-authored `CLAUDE.md`; the generated-`<hooksdaemon>`-clause variant deferred to Plan 00116's single meta-rule to avoid re-bloat
  - **G2 SKIPPED** by maintainer decision: the static suffix is accurate without a transcript-derived sibling count, which would add hot-path I/O

- [00114: Fully Robust Upgrade System](Completed/00114-robust-upgrade-system/PLAN.md) - Complete

  - Field report `untracked/hooks-daemon-upgrade-broken.md`: a client several versions behind saw BOTH documented upgrade paths fail; only `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` worked. Merged to main (not yet released)
  - **F1** — Layer 1 `scripts/upgrade.sh` now accepts-and-ignores `--already-bootstrapped` (heals pre-v3.15 skill shims; breaks the bootstrap deadlock)
  - **F2** — Layer 1 self-contained: fetches `python_discovery.sh` when no installed/`/tmp` copy exists (fixes documented curl-to-`/tmp` flow)
  - **F3** — `scripts/install/venv.sh` detects overlay-fs/NFS up front and chooses copy mode proactively (no failed hardlink attempt, no warning) while keeping hardlink speed on real disks
  - **F4** — recovery hints (`HOOKS_DAEMON_SKIP_BOOTSTRAP=1` + manual fallback) surfaced in the abort messages; `CLAUDE/LLM-UPDATE.md` stuck-client troubleshooting subsection added
  - Regression tests for F1-F4; H-1 acceptance gate count bumped 23→24 in RELEASING.md; QA 13/13

- [00113: First-Class GitRepo Utility](Completed/00113-git-repo-utility/PLAN.md) - Complete

  - Delivered in commits `59b06f1`, `9acf120` (not yet released — release deferred by user)
  - Extracts the git-config access introduced in Plan 00112 into a reusable SOLID `GitRepo` value object (`utils/git_repo.py`): `resolve_for(path)`, `read_config(key)`, `write_config(key, value)` over one bounded subprocess wrapper — single home for git repository access (SRP/OCP/DIP)
  - Migrated both present-day config consumers onto it: `plan_numbering` (deleted its private `_git_output`; the three delegators now call `GitRepo`) and `git_filemode_checker._get_filemode_setting` (own subprocess block → `GitRepo.read_config`)
  - Pure refactor — no behavioural change; 14 new `GitRepo` tests (100% module coverage), 283 consumer tests green, QA 13/13, daemon RUNNING
  - Scope deliberately narrow: other git subprocess sites (`project_context`, `git_context_injector`, `git_branch`) keep their existing helpers — they can adopt `GitRepo` later if it earns more methods (YAGNI)

- [00112: Git-Anchored Plan Numbering](Completed/00112-git-anchored-plan-numbering/PLAN.md) - Complete

  - Delivered in commits `2da5013`, `69fbb21`, `8853f1e`, `87f21db` (not yet released — release deferred by user)
  - Persists the latest plan number per-repository in `git config --local hooksdaemon.latestPlanNumber`, trusted on read (`counter + 1`), bootstrapped from a filesystem scan only when absent — stable across branch switches (fixes the branch-traversal problem)
  - Resolves the nearest enclosing git repo of the target path (`git -C <dir> rev-parse --show-toplevel`), so a plan created inside a nested/vendor repo uses THAT repo's counter and `CLAUDE/Plan/` (fixes vendor-subdir interception)
  - High-water-mark write on real plan creation (`max(counter, N)`) — self-heals drift without ever lowering the next number; non-git targets fall back to the project-root scan
  - Consolidated the duplicate scan in `validate_plan_number` onto the shared `highest_plan_number` primitive
  - New canonical helpers in `handlers/utils/plan_numbering.py`; dogfood-verified live (daemon seeded counter=112 to `.git/config`, answered next=00113)

- [00111: Stop Hook — Context-Limit Guidance Clause](Completed/00111-stop-hook-context-limit-guidance/PLAN.md) - Complete

  - Shipped as commit `7d1b9b8`
  - User dogfooding interrupt mid-Plan-00110: agent voluntarily stopping near the context-window limit to "checkpoint" before auto-compact, when auto-compact handles it automatically
  - Branch 4 `_EXPLAIN_OR_CONTINUE_REASON` extended with an explicit paragraph telling the agent that context-window pressure is never a valid stop reason — auto-compact triggers automatically and preserves state
  - Two new regression tests in `TestExplainOrContinueReasonContent` pin the new clause and assert the existing `STOPPING BECAUSE:` / `AUTO-CONTINUE` clauses remain present
  - `test_handle_reason_is_concise` cap bumped from 500 → 1000 chars (load-bearing guidance, not prose)
  - Scope intentionally narrow — context-checkpoint detection branch and v2.1.114 delivery-gap follow-ups deferred (already covered by Plan 00101)

- [00109: Skill thin-shim + atomic upgrade commit](Completed/00109-skill-thin-shim-and-atomic-upgrade-commit/PLAN.md) - Complete

  - Shipped as v3.15.0 in commit `2ab78df`
  - **Phase 1** — Layer 1 `scripts/upgrade.sh` emits 10-field `UPGRADE_METADATA` block (sentinels `<<<UPGRADE_METADATA` / `UPGRADE_METADATA>>>`) on every successful upgrade; agent parses block and writes one atomic `hooks daemon upgrade: vX → vY` commit covering only daemon-owned paths
  - **Phase 2** — Skill-pushed `scripts/upgrade.sh` collapsed from ~280 lines of frozen logic to a ~23-line thin shim that walks for `.claude/hooks-daemon.yaml`, fetches the canonical script from `${HOOKS_DAEMON_UPGRADE_BASE_URL}/${HOOKS_DAEMON_UPGRADE_REF}/scripts/upgrade.sh` (defaults to `raw/main`), execs with `--project-root`; closes the frozen-at-release-time bug class (v3.9.x `write-venv-metadata`, v3.10.0 `print_info` SEV-1)
  - **Phase 3** — Skill `upgrade.md` rewritten as 5-step agent workflow (run upgrade, parse metadata, verify RUNNING, stage daemon-owned paths only, commit with metadata in body)
  - **Phase 4** — Four new acceptance gates: `test_upgrade_metadata_emission.py`, `test_skill_upgrade_shim.py`, `test_upgrade_md_metadata_contract.py` (4 sub-tests), `test_skill_upgrade_end_to_end.py` (full pipeline against installed daemon); six legacy skill-side integration tests removed (covered behaviours that no longer exist on the shim or moved upstream)
  - **Phase 5** — MINOR release v3.15.0 published with all 5 release artifacts (`upgrade.sh`, `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh`, `bootstrap-checksums.txt`); manifest verified consistent
  - Long-term review of pull-from-`main` source vs `releases/latest/download` tracked in [gh issue #31](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/31)

- [00101: Recap-Stoppage Investigation](Completed/00101-recap-stoppage-investigation/PLAN.md) - Complete

  - Re-opened post-v3.13.0 after silent stop recurred with `preventedContinuation: false, level: suggestion` — same signature Phases 5/6/7 thought they had closed
  - **Phase 9** (commit `f08a2ff`) — bash wrappers `.claude/hooks/stop` and `.claude/hooks/subagent-stop` now translate daemon JSON `decision: block` into exit code 2 + reason on stderr (the contract Claude Code v2.1.114 honours for hard re-entry); daemon JSON output unchanged for back-compat; acceptance test `tests/acceptance/test_stop_hook_hard_block.py` wired into RELEASING.md Step 12.0 H-1
  - **Phase 10** (commit `4c2688f`) — `SocketLimit.REQUEST_BUFFER_BYTES = 16 MiB` passed as `limit=` kwarg to `asyncio.start_unix_server` in `server.py`; eliminates `LimitOverrunError("Separator is found, but chunk is longer than limit")` for Edit payloads up to 16 MiB
  - Closes the suggestion-level delivery gap and the PostToolUse separator-error class — both regression vectors that landed silent stops on top of Phases 5/6/7's `tool_use_error` Branch 2.5

- [00107: Batch Delivery Meta Plan — v3.12.0 Release Bundle](Completed/00107-batch-delivery-meta/PLAN.md) - Complete

  - Six-wave audit-and-close of the v3.x backlog shipped as v3.12.0 in commit `6c5c869`
  - **Closed in bundle**: 00063, 00077, 00081 (Superseded by 00082), 00086, 00089, 00096, 00099, 00101, 00106
  - **Residue Scope**: 00100 (Phases 0–3.9 shipped; 3.5/4/5/6 deferred to v3.13.0)
  - **Deferred**: 00085 (reminder pseudo-event system — 8-phase fresh-TDD scope, future release)

- [00063: FAIL FAST — Plugin Handler Bug & Error Hiding Audit](Completed/00063-fail-fast-plugin-handler-audit/PLAN.md) - Complete (Already Shipped)

  - Phase 1 (plugin handler suffix bug + crash-on-misconfigured-handler) delivered in original sprint
  - Phases 2–5 audited and found already-shipped during Plan 00107 Wave 2: `scripts/qa/audit_error_hiding.py` + `error_hiding_exclusions.json`; `error_hiding` registered as one of the 12 QA gates; live audit reports zero violations across the codebase; `CLAUDE.md:320` codifies FAIL FAST as a non-negotiable Engineering Principle
  - Closed out without further code action

- [00096: Live Daemon Smoke Tests in QA Stack](Completed/00096-live-daemon-smoke-tests/PLAN.md) - Complete (Already Shipped)

  - Delivered in commit `bce66248` — pre-dated Plan 00107 Wave 2 audit
  - `scripts/qa/run_smoke_test.sh` (3 probes: Stop no-explanation, Stop loop-guard, PreToolUse destructive git) + `llm_qa.py` integration + `tests/unit/qa/test_smoke_test.py` all in place
  - Plan 00107 Wave 2 audit confirmed every Phase 1/2/3 task satisfied; closed out without further code action

- [00099: Python-Fingerprint Venv Isolation](Completed/00099-python-fingerprint-venv-isolation/PLAN.md) - Complete (Already Shipped)

  - Every Phase 1–8 deliverable in tree across v3.7.0 / v3.10.0 / v3.11.0: fingerprint-keyed venv paths (`paths.py::project_path_slug` + `python_venv_fingerprint`); `ensure_venv()` auto-bootstrap with integration coverage; legacy `untracked/venv/` cleanup via `eager_cleanup_stale_venvs()`; `list-venvs` / `prune-venvs` CLI with `--legacy`, `--all-except-current`, `--stale`, `--dry-run`, `--force`; H-1 acceptance gate exercising the production install path end-to-end
  - Phase 9 (Release) effectively executed across three releases; "In Progress" status was stale documentation. Closed during Plan 00107 Wave 4 audit.

- [00077: TranscriptReader Enhancement & AskUserQuestion Bug Fix](Completed/00077-transcript-reader-askuser-bugfix/PLAN.md) - Complete (Already Shipped)

  - Phase 1 (`ContentBlock` parsing + `tool_use` content blocks in `core/transcript_reader.py`) delivered in original sprint
  - Phases 2–5 audited and found already-shipped during Plan 00107 Wave 3: `utils/stop_hook_helpers.py` exists; all three Stop handlers (`auto_continue_stop`, `dismissive_language_detector`, `hedging_language_detector`) import from the shared helpers — the duplicated `_get_last_assistant_message` / `_is_stop_hook_active` code from the plan's DRY-violation context is gone
  - Closed out without further code action

- [00086: Plan Redirect System Improvement](Completed/00086-plan-redirect-system-improvement/PLAN.md) - Complete

  - **Handler fix**: `markdown_organization._handle_plan_write` now returns `Decision.ALLOW` (was `DENY`) so Claude Code's flat plan write succeeds and ExitPlanMode displays full plan content to the user for approval
  - **Empirical verification**: `plansDirectory: "./CLAUDE/Plan"` setting in `.claude/settings.json` causes Claude Code to write plans directly to project — proved by `idempotent-chasing-wadler.md` (Apr 10) sitting at the configured directory root
  - **Doc/impl sync**: `handle_planning_mode_write` docstring already said "Returns ALLOW" — Plan 00086 brings impl in line with the documented intent (pre-existing mismatch)
  - **Phase 2 sync check**: `_check_claude_code_sync()` already implemented at line 354 — no action needed
  - **Tests rewritten**: `TestPlanWriteDenyBehaviour` class replaced with `TestPlanWriteAllowBehaviour` (4 tests verifying ALLOW + context messaging for rename/cleanup after approval); integration test updated; 153/153 markdown_organization + integration tests pass
  - Delivered in Plan 00107 Wave 1

- [00106: Bypass-Permissions-Aware Auto-Approve](Completed/00106-bypass-permissions-aware-auto-approve/PLAN.md) - Complete

  - **Security fix**: `auto_approve_reads` now gates on `permission_mode == "bypassPermissions"` via new shared `utils/permission_mode.py::is_bypass_mode()` — defers to Claude Code's normal approval flow in default/plan/acceptEdits/dontAsk modes
  - **Sibling bug fixed under same umbrella (dogfooding)**: `HelloWorldPermissionRequestHandler` was silently auto-approving every PermissionRequest by emitting `Decision.ALLOW` from a non-terminal observability handler — switched to `Decision.CONTINUE` (which does not bind `hookSpecificOutput.decision`)
  - 5 new unit tests guard the hello_world wire-output contract; integration tests updated; HooksSystem.md cross-references the bypass-mode gate
  - Delivered in Plan 00107 Wave 1; no upgrade guide owed (security bug fix, not a breaking change)

- [00089: Fix auto_approve_reads Schema Mismatch + AskUserQuestion YOLO Bypass](Completed/00089-fix-auto-approve-reads-and-askuserquestion-bypass/PLAN.md) - Complete

  - **Bug 2 fix**: `auto_approve_reads` now matches on `tool_name` (the real PermissionRequest event field), not the non-existent `permission_type`. Handler is no longer dead code.
  - **Bug 1 fix**: new `ask_user_question_blocker` PreToolUse handler (disabled by default) blocks `AskUserQuestion` for fully unattended workflows where YOLO mode auto-dismisses with empty answers.
  - Delivered in commit `eb74e4a`; closed out during Plan 00107 Wave 1.

- [00071: Plan Number Validation Hook Bug Fixes](Completed/00071-triage-plan-race-report/PLAN.md) - Complete

  - Triaged two false positives in plan validation hook (TOCTOU race + archive trigger) and shipped fixes
  - Delivered in commit `957f97b1`; moved to Completed/ in commit `4d6dc78d` (Plan 00107 housekeeping pass)

- [00105: v3.11.0 — Stability Hardening (close gaps that let v3.10.0 ship a SEV-1)](Completed/00105-v3.11.0-stability-hardening/PLAN.md) - Complete

  - Released as v3.11.0 — closes the structural gaps that let v3.10.0 ship a SEV-1 print-on-stdout regression
  - **Phase 1**: H-1 acceptance gate now runs `install.sh` and `upgrade_version.sh` end-to-end against fresh fixture projects (would have caught v3.10.0)
  - **Phase 2**: 13th QA gate — `audit_capture_corruption.py` static check + integration matrix for `VAR=$(fn ...)` capture sites
  - **Phase 3**: All 16 `scripts/install/*.sh` helpers certified clean — 0 violations on every QA run
  - **Phase 4**: Parameterised self-bootstrap stanza now serves all four diagnostic scripts (`upgrade.sh`, `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh`) with sha256 verification + per-(basename, sha) cache marker
  - **Phase 5**: `venv.sh::create_venv_at_path` hardlink→copy fallback now uses `print_warning` (silent fallback antipattern removed); pinned by `test_venv_sh_hardlink_fallback_loud.py`
  - **Phase 6**: Plan 00103 housekeeping (moved to `Completed/`, README index updated)
  - Bonus latent-bug fix: `install_version.sh:243` now reads `pyproject.toml` instead of `git rev-parse --short HEAD` (sister-bug to v3.10.0 SEV-1 — silent metadata-write skip)

- [00103: v3.9.1 — venv resolution fail-fast (narrow hotfix)](Completed/00103-v3.9.1-venv-resolution-failfast/PLAN.md) - Complete

  - Released as v3.9.1 — narrow hotfix for v3.9.0 regression where `paths.py:22 import tomllib` crashed under `python3 → 3.9` (RHEL/CentOS hosts); silent `2>/dev/null` + legacy fallback hid the crash
  - Five resolver sites fixed in place (no DRY consolidation — deferred to Plan 00104): `_resolve-venv.sh`, `venv-include.bash`, `venv_resolver.sh`, `init.sh::_resolve_python_cmd`, `venv.sh:261`
  - Bootstrap probe replaces `${HOOKS_DAEMON_PYTHON:-python3}` with explicit `python3.13/3.12/3.11` + open-ended `compgen` discovery (no Python-version ceiling)
  - **v1 superseded**: ambitious version bundled patch + DRY consolidation, returned three FATAL Opus reviews; split per reviewer recommendation
  - Closed out by Plan 00105 Phase 6 housekeeping

- [00104: v3.10.0 — venv resolver DRY + upgrade-flow resilience + production bug fixes](Completed/00104-v3.10.0-venv-resolver-dry-consolidation/PLAN.md) - Complete

  - Released as v3.10.0 — see GitHub releases for the published artifacts
  - Canonical resolver library `scripts/lib/resolve_venv.sh` — five resolver sites collapsed to thin shims
  - 12th QA gate: canonical-callers static-check prevents future drift
  - H-1 acceptance gate (`tests/acceptance/test_diagnostic_scripts.py`) wired into `RELEASING.md` Step 12.0 as BLOCKING
  - Issue #4 root-cause fix: `cli.py:1415` `.resolve()` drop (the bug that produced every `ModuleNotFoundError` in the field report)
  - Skill `upgrade.sh` self-bootstrap with sha256 verification (Issue #1)
  - Multi-host NFS fail-fast + `requires-python` cross-check (Phase 7)
  - Hot-path cache for `_resolve_python_cmd` (Phase 8)
  - QA: 12/12 PASSED, 8125 tests, 95.0% coverage

- [00098: Human-Friendly Markdown Tables](Completed/00098-human-friendly-markdown/PLAN.md) - Complete

  - PostToolUse handler `markdown_table_formatter` auto-formats .md files after Write/Edit via mdformat + mdformat-gfm
  - CLI subcommand `format-markdown` for ad-hoc batch formatting (file/directory/--check modes)
  - Batch-formatted 257 existing project markdown files
  - Gitignore safety for `.CLAUDE.md.pre-inject` added to installer and session-start checker

- [00097: Project Handler Upgrade Resilience](Completed/00097-project-handler-upgrade-resilience/PLAN.md) - Complete

  - Hotfix: daemon no longer crashes when project handlers miss abstract methods after upgrade
  - Actionable version-specific error messages, CLI exit code 1, upgrade guide v2.29→v2.30
  - Handler ABC checklist added to release process Step 6.5

- [00095: /optimise Skill for Config Analysis](Completed/00095-config-optimise-skill/PLAN.md) - Complete

  - New `/optimise` skill analyzing hooks-daemon config across 5 domains: Safety, Stop Quality, Plan Workflow, Code Quality, Daemon Settings
  - Generates prioritised recommendations with enable/disable commands for each finding
  - Bash-driven invoke.sh iterating handler domains and scoring against active config

- [00094: Stop Explainer & Auto-Continue](Completed/00094-claude-code-introspection-debug-agent/PLAN.md) - Complete

  - `auto_continue_stop` redesigned: `matches()` always fires (except `stop_hook_active=True`), routing in `handle()`
  - 4 branches: STOPPING BECAUSE → ALLOW; confirmation question → DENY+auto-continue; QA failure → DENY+fix; default → DENY+explain-or-continue
  - Stop event JSONL logger (`_log_stop_event()`); camelCase `stopHookActive` field support
  - Full TDD with regression tests; 8/8 QA; daemon verified live

- [00093: Fresh-Clone Install Guidance](Completed/00093-fresh-clone-install-guidance/PLAN.md) - Complete

  - Distinguish "daemon not installed" from "daemon not running" in init.sh
  - Fresh clones now see "read CLAUDE/LLM-INSTALL.md" instead of wrong "run restart" advice
  - New `_is_daemon_installed()` helper + `_HOOKS_DAEMON_NOT_INSTALLED` flag, 2 new tests

- [00092: CI Environment Graceful Degradation](Completed/00092-ci-environment-graceful-degradation/PLAN.md) - Complete

  - Config-based `ci_enabled` setting for daemon-unavailable behaviour
  - Default: fail open with one-time noise + state file; `ci_enabled: true`: fail closed with STOP message
  - Fixes broken Claude Code triage in GitHub Actions for projects with hooks daemon installed

- [00090: Command Redirection for Blocking Handlers](Completed/00090-snappy-greeting-cloud/PLAN.md) - Complete

  - Core command_redirection utility module with execute_and_save(), format_redirection_context(), cleanup_old_files()
  - Retrofitted gh_issue_comments, npm_command, pipe_blocker handlers with per-handler toggle
  - Fixed markdown_organization plan folder bug (ALLOW→DENY to prevent duplicate flat files)
  - Config, docs, and acceptance test infrastructure updated

- [00088: Hooks Daemon Install Bugs](Completed/00088-hooks-daemon-install-bugs/PLAN.md) - Complete

  - Fixed 6 install bugs: git remote prereq check, daemon error surfacing, version SSOT, effort level default, plan workflow bootstrap, handler profiles
  - New installer Steps 14-15: PLAN_WORKFLOW=yes and HANDLER_PROFILE=recommended|strict env vars

- [00084: Fix Inplace-Edit Blocker xargs Bypass](Completed/00084-fix-inplace-edit-blocker-xargs-bypass/PLAN.md) - Complete

  - Fixed `grep | xargs sed -i` bypassing the blocker via overly broad grep safety check
  - Clarified handler intent: block destructive file modification, allow read-only pipelines

- [00083: Fix validate_plan_number Hardcoded Plan Directory](Completed/00083-fix-validate-plan-number-hardcoded-dir/PLAN.md) - Complete

  - Fixed handler hardcoding `CLAUDE/Plan` instead of using configurable `track_plans_in_project`
  - Added `shares_options_with="markdown_organization"` for config inheritance

- [00082: Pseudo-Events & Nitpick Handler](Completed/00082-pseudo-events-nitpick-handler/PLAN.md) - Complete

  - Pseudo-event infrastructure: synthetic events triggered by real events with frequency control
  - Nitpick pseudo-event with dismissive/hedging language handlers reusing Stop handler patterns
  - PseudoEventDispatcher with setup functions, handler chains, and result merging
  - Integrated into DaemonController lifecycle (initialise + process_event)

- [00080: Generated HOOKS-DAEMON.md + Version Cache Flush](Completed/00080-generate-hooks-daemon-docs/PLAN.md) - Complete

  - `generate-docs` CLI command producing `.claude/HOOKS-DAEMON.md` from live config + handler metadata
  - Version cache flush fix in upgrade script + stale cache defense in daemon_stats
  - Installer integration (Step 13) and CLAUDE.md update to reference generated docs

- [00079: DismissiveLanguageDetectorHandler](Completed/00079-dismissive-language-detector-handler/PLAN.md) - Complete

  - Stop event advisory handler detecting dismissive language (pre-existing issue, out of scope, not our problem, defer/ignore)
  - Follows hedging_language_detector pattern, 57 unit tests, priority 58 (advisory range)

- [00078: Integrate SecurityAntipatternHandler](Completed/00078-integrate-security-antipattern-handler/PLAN.md) - Complete

  - Blocks Write/Edit of files containing hardcoded secrets (AWS, Stripe, GitHub tokens) and injection patterns (PHP eval/exec, JS innerHTML/eval)
  - Strategy Pattern: SecurityStrategy Protocol with per-language strategies (Secrets, PHP, JavaScript) and registry
  - 60 handler tests + ~40 strategy tests, OWASP A02/A03 coverage

- [00076: TDD Collocated Test Support](Completed/00076-tdd-collocated-test-support/PLAN.md) - Complete

  - Added `test_locations` config option with 3 styles: separate, collocated, __tests__/ subdir
  - Fixes false blocking of Go, React/Vitest/Jest, Dart collocated test conventions
  - Handler-only change (zero strategy modifications), 27 new tests

- [00075: LSP Enforcement Handler](Completed/00075-lsp-enforcement-handler/PLAN.md) - Complete

  - PreToolUse handler detecting Grep/Bash(grep/rg) symbol lookups, steers toward LSP tools
  - Configurable modes: block_once (default), advisory, strict; no_lsp_mode: block/advisory/disable
  - 59 unit tests, 96.28% coverage, 3 acceptance tests, all QA passing

- [00072: Bug Report Generator](Completed/00072-bug-report-generator/PLAN.md) - Complete

  - Added `bug-report` CLI subcommand generating structured markdown reports with full diagnostics
  - Skill integration via `/hooks-daemon bug-report` routing
  - 18 TDD unit tests, all QA checks passing

- [00070: Fix NoneType Priority Comparison Crash](Completed/00070-none-priority-crash/PLAN.md) - Complete

  - Fixed daemon crash when handler has `priority: null` in config (TypeError during chain sort)
  - Multi-layer defence: chain sort fallback, registry skip, project loader validation, Priority.DEFAULT constant
  - 4 regression tests, TDD implementation

- [00069: Restart Mode Preservation Advisory](Completed/00069-restart-mode-advisory/PLAN.md) - Complete

  - Prints advisory when daemon restarts with non-default mode active (e.g. unattended)
  - Shows lost mode and exact restore command; no output for default mode
  - 11 new tests, TDD implementation

- [00068: Daemon Modes System](Completed/00068-daemon-modes-system/PLAN.md) - Complete

  - Runtime-mutable daemon modes with "unattended" mode that blocks all Stop events unconditionally
  - ModeManager + ModeInterceptor pre-dispatch pattern, Controller/Server/CLI integration, /mode skill
  - 6 phases: constants, interceptor, controller, IPC, CLI, skill + config

- [00067: Fix Upgrade Early-Exit Skips Skill/Slash-Command Deployment](Completed/00067-fix-upgrade-early-exit-skips-deployments/PLAN.md) - Complete

  - Replaced minimal early-exit (daemon restart only) with full idempotent deployment sequence
  - Now re-deploys hook scripts, settings.json, .gitignore, slash commands, and skills when already at target version
  - Fixes projects on v2.16.0 that couldn't get skills deployed (added in Plan 00061) via re-running upgrade

- [00058: Fix PHP QA Suppression Pattern Gaps](Completed/00058-php-qa-suppression-pattern-gaps/PLAN.md) - Complete

  - Added 8 missing PHP suppression patterns (@phpstan-ignore, phpcs:disable/enable/ignoreFile, @codingStandards\*)
  - All patterns now blocked via strategy pattern; acceptance tests verified

- [00045: Proper Language Strategy](Completed/00045-proper-language-strategy/PLAN.md) - Complete

  - Unified three inconsistent language-aware systems into ONE canonical strategy pattern
  - Single `qa_suppression.py` handler with 11 language strategies (Python, Go, PHP, JS, Rust, Java, C#, Kotlin, Ruby, Swift, Dart)
  - Removed old individual QA suppression handlers; TDD handler updated to use `_project_languages`
  - Backward-compat config mapping in registry; old handlers fully deprecated and removed

- [00038: Library Handler Over-fitting](Completed/00038-library-handler-over-fitting/PLAN.md) - Cancelled

  - Superseded by Plan 00045 which resolved the core issue via unified language strategy pattern

- [00065: Version-Aware Config Migration Advisory System](Completed/00065-version-aware-config-migration/PLAN.md) - Complete

  - Machine-readable YAML manifests per version tracking all config changes (19 manifests v2.2.0→v2.15.2)
  - New `check-config-migrations` CLI command: compares user config against version range, reports new options
  - Integration tests against real manifests (31 tests) + unit TDD suite
  - LLM-UPDATE.md updated with Method 4 for version-specific advisory step

- [00066: Fix Plan File Race Condition](Completed/00066-plan-file-race-condition/PLAN.md) - Complete

  - Fixed TOCTOU race: `handle_planning_mode_write()` returned `ALLOW` after writing the redirect stub, causing Claude's Write tool to detect file modification and loop infinitely
  - Fix: return `DENY` (content already saved; block the Write tool from overwriting the stub)
  - Acceptance tested: single write attempt, DENY + "PLAN SAVED SUCCESSFULLY", content saved correctly

- [00064: PipeBlocker Strategy Pattern Redesign](Completed/00064-pipe-blocker-strategy-redesign/PLAN.md) - Complete

  - Replaced over-eager whitelist-only logic with three-tier whitelist/blacklist/unknown system
  - Added pipe_blocker strategy domain: 8 language strategies (Universal, Python, JS, Shell, Go, Rust, Java, Ruby)
  - Differentiated messages: blacklisted → "expensive command"; unknown → "unrecognized, add to extra_whitelist"
  - Full TDD coverage, QA suite green, daemon verified running

- [00062: Breaking Changes Lifecycle](Completed/00062-breaking-changes-lifecycle/PLAN.md) - Complete

  - Fixed systemic breaking changes documentation gap causing unknown handler errors during upgrades
  - Created historical upgrade guides for v2.10 through v2.13
  - Automated breaking changes detection in release process with upgrade guide template generation
  - Implemented smart upgrade validation with pre-flight checks and guide reading enforcement
  - Updated release notes format with BREAKING CHANGES sections
  - Total: 5842+ lines, 25 files created, 27 tests added, 7 phases completed

- [00061: Hooks Daemon User-Facing Skill](Completed/00061-hooks-daemon-user-skill/PLAN.md) - Complete

  - Deployed `/hooks-daemon` skill to user projects with 4 subcommands (upgrade, health, dev-handlers, logs)
  - Fixed v2.13.0 breaking change: enhanced error messages for plugin handler abstract method violations
  - Single skill with bash routing to wrapper scripts deployed during install/upgrade
  - Enhanced error formatter detects abstract method violations and provides version-aware guidance

- [00060: Release Blocker Handler](Completed/00060-release-blocker-handler/PLAN.md) - Complete

  - PROJECT HANDLER that blocks session ending during releases until acceptance tests complete
  - Detects release context by checking git status for modified version files
  - Priority 12 with terminal behaviour and infinite loop prevention
  - Addresses AI acceptance test avoidance behaviour from v2.13.0 release

- [00059: Fix MarkdownOrganizationHandler Completed/ Folder](Completed/00059-fix-markdown-handler-completed-folder/PLAN.md) - Complete

  - Fixed handler to allow edits to CLAUDE/Plan/Completed/, Cancelled/, Archive/ folders
  - Added \_PLAN_SUBDIRECTORIES constant for known subdirectories
  - Comprehensive test coverage with backward compatibility verified
  - Updated documentation in 5 affected plans (00048-00052)

- [00057: Single Daemon Process Enforcement](Completed/00057-single-daemon-process-enforcement/PLAN.md) - Complete

  - System-wide daemon process enforcement with automatic container detection
  - 40 new tests added, 95.1% coverage maintained, 0 regressions

- [00056: Fix DaemonLocationGuardHandler Whitelisting](Completed/00056-fix-daemon-location-guard-whitelisting/PLAN.md) - Complete

  - Removed incorrect official upgrade command whitelisting pattern
  - Updated guidance with correct upgrade process using curl and bash upgrade script
  - Test count reduced from 15 to 14 tests, acceptance tests from 2 to 1
  - All QA checks pass, daemon loads successfully

- [00055: Fix TDD Handler Path Detection — Support Multiple Test Directory Conventions](Completed/00055-tdd-handler-multi-path-detection/PLAN.md) - Complete

  - TDD enforcement handler now tries multiple candidate test paths (Python `tests/unit/`, PHP PSR-4 mirror, Java `src/test/`, Go co-located, Ruby `spec/`) before blocking, eliminating false positives when a valid test exists in a non-default but conventional location

- [00054: Lint-on-Edit Handler with Strategy Pattern](Completed/00054-lint-on-edit-strategy-pattern/PLAN.md) - Complete

  - Language-aware lint validation handler using Strategy Pattern (9 languages)
  - Shell/bash support added (default: bash -n, extended: shellcheck)
  - Per-language default and extended lint commands with config overrides
  - Full TDD, 145 tests (119 strategy + 26 handler), QA passing, daemon verified

- [00041: Project-Level Handlers First-Class DX](Completed/00041-project-handlers-first-class-dx/PLAN.md) - Complete

  - First-class project-level handler system: auto-discovery, CLI scaffolding/validation/testing, examples, docs
  - All 5 phases complete: core infrastructure, CLI DX, documentation, dogfooding, release prep

- [00048: Repository Cruft Cleanup](Completed/00048-repo-cruft-cleanup/PLAN.md) - Complete

  - Spurious files deleted, empty plans removed, auto-named folders renamed

- [00026: generate-playbook CLI (completes Plan 00025)](Completed/00026-generate-playbook-cli/PLAN.md) - Complete

  - Implemented the missing `generate-playbook` CLI command that closed out Plan 00025's programmatic acceptance-testing system

- [00022: System Package Safety Handlers](Completed/00022-system-package-safety-handlers/PLAN.md) - Complete

  - Five safety handlers blocking dangerous system-package patterns (pip `--break-system-packages`, `sudo pip`, `curl | bash`, `chmod 777`, global npm advisory); GitHub Issue #11

- [00053: LLM QA Wrapper Script](Completed/00053-llm-qa-wrappers/PLAN.md) - Complete

  - Unified `scripts/qa/llm_qa.py` producing ~16 lines vs 200+ from run_all.sh
  - Fixed run_type_check.sh ANSI color codes breaking JSON error parsing
  - Fixed Handler missing \_project_languages in __slots__/type annotation

- [00052: LLM Command Wrapper Guide & Handler Integration](Completed/00052-llm-command-wrapper-guide/PLAN.md) - Complete

  - Language-agnostic guide shipped with daemon, utility for path resolution, handler advisory references guide

- [00051: Critical Thinking Advisory Handler](Completed/00051-critical-thinking-advisory/PLAN.md) - Complete

  - UserPromptSubmit handler with multi-gate filter (length + random + cooldown)

- [00050: Display Config Key in Handler Block/Deny Output](Completed/00050-handler-config-key-in-errors/PLAN.md) - Complete

  - Append fully-qualified config path to every DENY/ASK message (PHPStan-inspired UX)
  - Implemented at FrontController/EventRouter level (zero handler modifications)

- [00049: NPM Handler - LLM Command Detection & Advisory Mode](Completed/00049-npm-handler-llm-detection/PLAN.md) - Complete

  - Convert NPM handlers from hard blocking to smart advisory based on llm: command detection
  - Created shared utils/npm.py detection utility, updated both handlers

- [00047: User Feedback Resolution (v2.10.0)](Completed/00047-user-feedback-resolution/PLAN.md) - Complete

  - Fixed ghost stats_cache_reader handler in default config (caused DEGRADED MODE)
  - Deduplicated all handler priorities in yaml.example (18+ duplicates resolved)
  - Auto-create .claude/.gitignore, non-fatal installer exit, UV_LINK_MODE=copy
  - Socket path discovery file for init.sh/Python fallback path agreement
  - Documentation consistency fixes in LLM-INSTALL.md and LLM-UPDATE.md

- [00037: Daemon Data Layer](Completed/00037-daemon-data-layer/PLAN.md) - Complete

  - Persistent state and transcript access for daemon data layer

- [00046: Upgrade System Overhaul](Completed/00046-upgrade-system-overhaul/PLAN.md) - Complete (2026-02-11)

  - Fixed Layer 1 checkout ordering, dropped legacy fallback, Python 3.11+ version detection
  - AF_UNIX socket path length validation with XDG_RUNTIME_DIR fallback chain
  - Config validation UX with user-friendly Pydantic error formatting
  - Updated LLM-UPDATE.md documentation

- [00043: Robust Upgrade Detection & Repair](Completed/00043-robust-upgrade-detection/PLAN.md) - 🟢 Complete (2026-02-10)

  - Added fallback detection signal (`.claude/hooks-daemon/.git`) for broken installs missing config
  - Updated both `project_detection.sh` and `upgrade.sh` with multi-signal detection
  - `NEEDS_CONFIG_REPAIR` flag set when config missing, Layer 2 auto-repairs during upgrade
  - **Completed**: 2026-02-10

- [00034: Library/Plugin Separation and QA Sub-Agent Integration](Completed/00034-library-plugin-separation-qa/PLAN.md) - Complete (2026-02-10)

  - Moved dogfooding_reminder from library to plugin system
  - Created CLAUDE/QA.md documenting complete QA pipeline
  - Updated run_all.sh with sub-agent QA reminder
  - Plugin accidentally deleted by 3642c29, restored from git history
  - **Completed**: 2026-02-10

- [00041: DRY Install/Upgrade Architecture Refactoring](Completed/00041-dry-install-upgrade-architecture/PLAN.md) - 🟢 Complete (2026-02-10)

  - Eliminated ~800 lines of duplication between install.sh, install.py, and upgrade.sh
  - Two-layer architecture: Layer 1 (curl-fetched stable) + Layer 2 (version-specific modular)
  - Config preservation engine: Python diff/merge/validate with 82 tests
  - 14 composable bash modules in scripts/install/
  - install.sh: 307→116 lines, upgrade.sh: 612→134 lines
  - **Completed**: 2026-02-10

- [00042: Fix Auto-Continue Stop Handler Bug](Completed/00042-auto-continue-stop-bug/PLAN.md) - 🟢 Complete (2026-02-10)

  - Fixed camelCase `stopHookActive` field not detected (infinite loop risk)
  - Added diagnostic logging throughout `matches()` for future debugging
  - 7 new integration tests covering full DaemonController flow
  - **Completed**: 2026-02-10

- [00039: Handler Config Key Consistency](Completed/00039-handler-config-key-consistency/PLAN.md) - 🟢 Complete (2026-02-10)

  - Fixed design flaw where HandlerID constants were ignored by registry
  - Made HandlerID constants actual SSOT for config keys (eliminated auto-generation)
  - Fixed 5 mismatches: python/php/go QA suppressions, suggest_statusline, session_cleanup
  - Added validation with audit script (0 mismatches found post-fix)
  - Bonus: Eliminated ALL duplicate priority warnings in daemon logs
  - **Completed**: 2026-02-10

- [00033: Status Line Enhancements (PowerShell Port)](Completed/00033-statusline-enhancements/PLAN.md) - 🟡 Complete with reduced scope (2026-02-09)

  - Scope reduced: OAuth tokens blocked from third-party API use since Jan 2026
  - API-based features (progress bars, usage tracking, reset times) all cancelled
  - Delivered: ThinkingModeHandler with thinking On/Off + effortLevel display
  - **Completed**: 2026-02-09

- [00040: Playbook Generator Plugin Support](Completed/00040-playbook-generator-plugin-support/PLAN.md) - 🟢 Complete (2026-02-09)

  - Added plugin handler support to acceptance test playbook generator
  - Modified cli.py to load plugins via PluginLoader and pass to PlaybookGenerator
  - Updated PlaybookGenerator to iterate both library and plugin handlers, sorted by priority
  - Fixed plugin loader to handle Handler suffix (tries ClassName and ClassNameHandler)
  - Fixed plugin config format for dogfooding plugin
  - Verified: 68 handlers in playbook (67 library + 1 dogfooding plugin)
  - **Completed**: 2026-02-09

- [00039: Progressive Verbosity & Data Layer Handler Enhancements](Completed/00039-progressive-verbosity-data-layer/PLAN.md) - 🟢 Complete (2026-02-09)

  - Implemented count_blocks_by_handler() in HandlerHistory
  - Added progressive verbosity to PipeBlocker, SedBlocker, DestructiveGit (3 tiers each)
  - Added block count display in DaemonStats status line
  - Saves tokens by being terse on first block, verbose only when needed
  - All 5 phases complete with full 3-layer QA verification
  - **Completed**: 2026-02-09

- [00021: Language-Specific Handlers](Completed/00021-language-specific-handlers/PLAN.md) - 🟢 Complete (2026-02-06)

  - Refactored Python, Go, PHP QA suppression handlers to use LanguageConfig
  - Eliminated ~18 lines of hardcoded pattern duplication
  - Created single source of truth for language-specific patterns
  - All handlers now uniform structure (128 lines each)
  - 4-Gate verification: All gates passed (Gate 4 veto overridden)
  - **Completed**: 2026-02-06 (GitHub Issue #12)

- [003: Planning Mode Integration](Completed/003-planning-mode-project-integration/PLAN.md) - 🟢 Complete (2026-02-06)

  - Implemented planning mode write interception in markdown_organization handler
  - Auto-calculates plan numbers, creates folders, writes PLAN.md to project structure
  - Config integration with track_plans_in_project and plan_workflow_docs options
  - 28 comprehensive tests covering planning mode detection and integration
  - **Completed**: 2026-02-06 (all 8 phases implemented)

- [00031: Lock File Edit Blocker Handler](Completed/00031-lock-file-edit-blocker/PLAN.md) - 🟢 Complete (2026-02-06)

  - Implemented PreToolUse handler to block direct editing of package manager lock files
  - 225-line handler, 564-line test suite with 45 tests
  - Protects 14 lock file types across 8 ecosystems (npm, pip, composer, cargo, etc.)
  - Priority 10 safety handler with educational error messages
  - **Completed**: 2026-02-06 (GitHub Issue #19)

- [00030: Agent Team Workflow Documentation](Completed/00030-agent-team-documentation/PLAN.md) - 🟢 Complete (2026-02-06)

  - Created comprehensive CLAUDE/AgentTeam.md (752 lines)
  - Documented worktree isolation, daemon management, and merge protocol
  - Captured lessons from Wave 1 parallel execution POC
  - Cross-referenced Worktree.md throughout for complete workflow
  - **Completed**: 2026-02-06

- [00029: Fix Markdown Handler to Allow Memory Writes](Completed/00029-fix-markdown-handler-memory/PLAN.md) - 🟢 Complete (2026-02-06)

  - Fixed markdown_organization handler blocking Claude Code auto memory
  - Scoped enforcement to project-relative paths only
  - Allows writes to `/root/.claude/projects/` (outside project root)
  - Added comprehensive tests for path scoping logic
  - **Completed**: 2026-02-06

- [00028: Daemon CLI Explicit Paths for Worktree Isolation](Completed/00028-daemon-cli-explicit-paths/PLAN.md) - 🟢 Complete (2026-02-06)

  - Added --pid-file and --socket CLI flags to all daemon commands
  - Fixes worktree daemon cross-kill issue with explicit path overrides
  - Maintains backward compatibility (flags are optional)
  - Enables safe multi-daemon worktree workflows
  - **Completed**: 2026-02-06

- [00025: Programmatic Acceptance Testing System](Completed/00025-programmatic-acceptance-tests/PLAN.md) - 🟢 Complete (2026-02-06)

  - Created AcceptanceTest dataclass with validation
  - Made Handler.get_acceptance_tests() REQUIRED (@abstractmethod)
  - Implemented playbook generator with plugin discovery
  - Migrated ALL 63 handlers to programmatic tests
  - CLI command outputs to STDOUT (ephemeral playbooks)
  - Full plugin support with automatic discovery
  - Replaced manual PLAYBOOK.md with GENERATING.md
  - **Completed**: 2026-02-06 (GitHub Issue #18)

- [00027: Plan Completion Move Advisor](Completed/00027-plan-completion-move-advisor/PLAN.md) - 🟢 Complete (2026-02-06)

  - Added PreToolUse handler to detect plan completion markers
  - Advisory reminder for git mv to Completed/ folder
  - Reminds about README.md updates and plan statistics
  - **Completed**: 2026-02-06

- [00023: LLM Upgrade Experience Improvements](Completed/00023-llm-upgrade-experience/PLAN.md) - 🟢 Complete (2026-02-06)

  - Created location detection and self-locating upgrade script
  - Improved LLM-UPDATE.md with clear copy-paste instructions
  - Softened error messages during upgrade to avoid investigation loops
  - **Completed**: 2026-02-06 (GitHub Issue #16)

- [00020: Configuration Validation at Daemon Startup](Completed/00020-config-validation-startup/PLAN.md) - 🟢 Complete (2026-02-06)

  - Implemented config validation at daemon startup with graceful fail-open
  - Added degraded mode for invalid configurations
  - Standardized error handling across all code paths
  - **Completed**: 2026-02-06 (GitHub Issue #13)

- [00019: Orchestrator-Only Mode](Completed/00019-orchestrator-only-mode/PLAN.md) - 🟢 Complete (2026-02-06)

  - Created optional handler to enforce orchestration-only pattern
  - Blocks work tools, allows only Task delegation
  - Configurable read-only Bash prefix allowlist
  - **Completed**: 2026-02-06 (GitHub Issue #14)

- [00016: Comprehensive Handler Integration Tests](Completed/00016-comprehensive-handler-integration-tests/PLAN.md) - 🟢 Complete (2026-02-06)

  - Achieved 100% handler coverage in integration tests
  - Used parametrized tests for multiple scenarios per handler
  - Catches initialization failures and silent handler failures
  - Added 2,270 lines across 10 test files
  - **Completed**: 2026-02-06

- [00014: Eliminate CWD, Implement Calculated Constants](Completed/00014-eliminate-cwd-calculated-constants/PLAN.md) - 🟢 Complete (2026-02-06)

  - Created ProjectContext singleton with all project constants calculated once at daemon startup
  - Eliminated all `Path.cwd()` calls from handler and core code (only CLI discovery remains, acceptable)
  - `get_workspace_root()` falls back to ProjectContext instead of CWD
  - FAIL FAST on uninitialized context (RuntimeError)
  - Comprehensive tests for singleton lifecycle, git URL parsing, mode detection
  - **Completed**: 2026-02-06

- [00008: Fail-Fast Error Hiding Audit](Completed/00008-fail-fast-error-hiding-audit/PLAN.md) - 🟢 Complete (2026-02-05)

  - Fixed all 22 error hiding violations across 13 files
  - Created unified daemon.strict_mode for all fail-fast behavior
  - Replaced bare except blocks with specific exception types
  - Added comprehensive logging and fail-fast paths
  - **Completed**: 2026-02-05

- [00007: Handler Naming Convention Fix](Completed/00007-handler-naming-convention-fix/PLAN.md) - 🟢 Complete (2026-02-04)

  - Fixed handler naming convention conflict (config keys without \_handler suffix)
  - Superseded and completed by Plan 00012 (comprehensive constants system)
  - All handlers now use HandlerID constants with correct naming
  - **Completed**: 2026-02-04 (via Plan 00012)

- [00017: Acceptance Testing Playbook](Completed/00017-acceptance-testing-playbook/PLAN.md) - 🟢 Complete (2026-01-30)

  - Created CLAUDE/AcceptanceTests/ directory structure
  - Evolved to programmatic acceptance testing approach (Plan 00025)
  - Initial manual playbook concept archived, replaced by dynamic generation
  - **Completed**: 2026-01-30

- [00013: Pipe Blocker Handler](Completed/00013-pipe-blocker-handler/PLAN.md) - 🟢 Complete (2026-01-29)

  - Implemented handler to block dangerous pipe operations (expensive commands piped to tail/head)
  - 70 comprehensive tests with 100% pass rate
  - Whitelist support for safe commands (grep, awk, jq, sed, etc.)
  - Clear error messages with temp file suggestions
  - **Completed**: 2026-01-29

- [00009: Status Line Handlers Enhancement](Completed/00009-abundant-puzzling-cray/PLAN.md) - 🟢 Complete (2026-02-05)

  - Fixed schema validation for null context_window fields
  - Implemented account_display and usage_tracking handlers
  - Added stats_cache_reader utility for ~/.claude/stats-cache.json
  - 73 tests passing with excellent coverage
  - **Completed**: 2026-02-05

- [00006: Daemon-Based Status Line System](Completed/00006-eager-popping-nebula/PLAN.md) - 🟢 Complete (2026-02-04)

  - Implemented STATUS_LINE event type and bash hook entry point
  - Created 6 status line handlers (git_repo_name, account_display, model_context, usage_tracking, git_branch, daemon_stats)
  - Added SessionStart suggestion handler
  - Full integration with special response formatting
  - **Completed**: 2026-02-04

- [00004: Final Workspace Test](Completed/00004-final-workspace-test/PLAN.md) - 🟢 Complete (2026-02-05)

  - Verified daemon.strict_mode implementation and testing
  - Confirmed single unified fail-fast configuration
  - Feature deployed and enabled in dogfooding configuration
  - **Completed**: 2026-02-05

- [00012: Eliminate ALL Magic Strings and Magic Numbers](Completed/00012-eliminate-magic-strings/PLAN.md) - 🟢 Complete (2026-02-04)

  - Created comprehensive constants system (12 modules: HandlerID, EventID, Priority, Timeout, Paths, Tags, ToolName, ConfigKey, Protocol, Validation, Formatting)
  - Built custom QA checker with AST-based magic value detection (8 rules)
  - Fixed 320 violations across entire codebase (179 tags, 51 handler names, 41 tool names, 39 priorities, 7 timeouts, 3 config keys)
  - Migrated all 54 handlers to use constants (zero magic strings/numbers remaining)
  - Centralized naming conversion utilities (eliminated \_to_snake_case duplication)
  - Integrated QA checker into CI/CD pipeline (runs first, fail fast)
  - **Completed**: 2026-02-04

- [00024: Plugin System Fix](Completed/00024-plugin-system-fix/PLAN.md) - 🟢 Complete (2026-02-04)

  - Fixed configuration format mismatch (PluginsConfig model is source of truth)
  - Integrated plugin loading into DaemonController lifecycle (THE CORE FIX)
  - Made duplicate priorities deterministic (sort by priority, then name)
  - Added helpful error messages for validation failures
  - Added acceptance test validation for plugin handlers
  - Updated all documentation with event_type requirement
  - **Completed**: 2026-02-04 (GitHub Issue #17)

- [00018: Fix Container/Host Environment Switching](Completed/00018-container-host-environment-switching/PLAN.md) - 🟢 Complete (2026-01-30)

  - Decoupled hook hot path from venv Python (bash path computation, system python3 socket client)
  - Added jq-based error emission with event-specific formatting
  - Added venv health validation with fail-fast and `repair` CLI command
  - Zero new runtime dependencies
  - **Completed**: 2026-01-30 (GitHub Issue #15)

- [00011: Handler Dependency System](Completed/00011-handler-dependency-system/PLAN.md) - 🟢 Complete (2026-01-29)

  - Implemented handler options inheritance via shares_options_with attribute
  - Added config validation to enforce parent-child dependencies (FAIL FAST)
  - Eliminated config duplication between markdown_organization and plan_number_helper
  - Removed YAML anchors, replaced hasattr() hack with generic options inheritance
  - Two-pass registry algorithm for proper options merging
  - **Completed**: 2026-01-29

- [00010: CLI and Server Coverage Improvement to 98%](Completed/00010-cli-server-coverage-improvement/PLAN.md) - 🟢 Complete (2026-01-29)

  - Improved cli.py coverage from 74.31% to 99.63%
  - Improved server.py coverage from 88.83% to 96.95%
  - Overall project coverage improved from 93.72% to 97.04%
  - Added 62 new tests covering fork logic, exception paths, async operations
  - **Completed**: 2026-01-29 (Opus agent execution)

- [002: Fix Silent Handler Failures](Completed/002-fix-silent-handler-failures/PLAN.md) - 🟢 Complete

  - Fix broken handlers (BashErrorDetector, AutoApproveReads, Notification)
  - Add input schema validation (toggleable)
  - Add sanity checks for required fields

- [001: Test Fixture Validation Against Real Claude Code Events](Completed/001-test-fixture-validation/PLAN.md) - 🟢 Complete (2026-01-27)

  - Validated all test fixtures against real daemon logs
  - Identified critical handler failures
  - Implemented HOOKS_DAEMON_LOG_LEVEL env var
  - Generated verification reports
  - **Completed**: 2026-01-27 in ~1 hour (parallel execution)

## Blocked / On Hold Plans

- **00032, 00034, 00035** - On hold pending upstream Claude Code delegate mode fix (GitHub #23447, #25037)

## Cancelled Plans

- [00091: Hook Executable Permissions](Cancelled/00091-hook-executable-permissions/PLAN.md) - Cancelled

  - Superseded by [00102](00102-hook-exec-bit-defense/PLAN.md). The new plan invokes hooks via `bash <abs-path>`, which makes the executable bit irrelevant entirely — root cause goes away. `git_filemode_checker` (originally Plan 00091 Phase 2) was folded into Plan 00102 Phase 4.

- [00081: Pseudo-Events & Nitpick Handler](Cancelled/00081-pseudo-events-nitpick-handler/PLAN.md) - Cancelled

  - Superseded by [00082](Completed/00082-pseudo-events-nitpick-handler/PLAN.md), the revised execution plan (Complete). Both plans share the same title and problem statement; this research-stage plan is preserved for history. Closed during Plan 00107 Wave 3.

- [00087: Post-Clear Auto-Execute](Cancelled/00087-post-clear-auto-execute/PLAN.md) - Cancelled

  - Hooks cannot solve `/clear <text>` auto-execution — client-side `local-command-caveat` and no auto-submit
  - Prototype handler remains enabled (marginal value), but core goal impossible via hooks

- [00044: Acceptance Testing Skill](Cancelled/00044-acceptance-testing-skill/PLAN.md) - Cancelled

  - Sub-agent acceptance testing retired in v2.10.0; main-thread testing is the standard

---

## Plan Statistics

- **Total Plans Created**: 162 (count = `hooksdaemon.latestPlanNumber` git counter; 00145 was allocated by the counter but its folder is not present on this branch)
- **Completed**: 134 (includes 1 reduced-scope plan and 4 found already-shipped when audited; count = `Completed/` folders)
- **Active**: 21 (count = root `NNNNN-*` plan folders; includes the 3 upstream-blocked on-hold plans below and several dormant plans awaiting a scheduling/release window)
- **On Hold**: 3 (blocked by upstream Claude Code delegate mode fix)
- **Cancelled/Abandoned**: 4 on disk (count = `Cancelled/` folders: 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102); plus draft folders deleted and no longer on disk (00036 empty draft, 00038 superseded by 00045, 00073 orphan empty folder removed during Plan 00107 housekeeping)
- **Last reconciled by**: Plan 00144 Task 2.2 sweep remediation

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow and templates
- [HANDLER_DEVELOPMENT.md](../HANDLER_DEVELOPMENT.md) - Handler development guide
- [DEBUGGING_HOOKS.md](../DEBUGGING_HOOKS.md) - How to capture real events

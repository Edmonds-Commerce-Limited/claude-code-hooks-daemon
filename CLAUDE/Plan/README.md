# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00321: injected goal has no retraction path](00321-injected-goal-has-no-retraction-path/PLAN.md) - Not Started (the supervisor can set the session `/goal` slot but nothing can clear it, so a stale condition outlives its ledger entry and challenges every stop; Plan 00320 stopped such goals being created, this one retracts the ones already in the slot)

- [00319: supervisor release review followups](00319-supervisor-release-review-followups/PLAN.md) - Not Started (the ten non-blocking findings surviving the v3.60.0 code-review gate, grouped into silent failures, unbounded per-session growth, and writer/reader contract drift; the three BLOCKING siblings shipped in 55dd5b2e)

- [00314: failsafe cron suppression marker never arms](00314-failsafe-cron-suppression-marker-never-arms/PLAN.md) - Not Started (Plan 00298's cron-tick suppression never engaged live: the human-input marker was not written despite a matching STOPPING BECAUSE phrase, and the pattern set misses natural phrasings; TDD reproduction + field observability + conservative pattern widening)

- [00311: v3.59.0 release review followups](00311-v3590-release-review-followups/PLAN.md) - Not Started (non-blocking findings ledger from the v3.59.0 code review: dispatch_declaration's hardcoded plan path, the secret_file_matching glob-heuristic maintenance surface, and the git rm --cached looseness verification)

- [00295: v3.57.0 release review followups](00295-v3570-release-review-followups/PLAN.md) - Not Started (non-blocking findings ledger from the v3.57.0 code review gate, tiered HIGH/MEDIUM/LOW)

- [00293: tool inventory disable and token savings](00293-tool-inventory-disable-and-token-savings/PLAN.md) - Not Started (disable-at-source for never-wanted tools instead of fighting them with hooks, transcript-scanning analyser for never-used tools, tools-vs-tokens report with the decision left to projects; dogfood here)

- [00291: upgrade path hardening and guarded branch install](00291-upgrade-path-hardening-and-guarded-branch-install/PLAN.md) - Not Started (php-qa-ci canary findings: fresh-clone `upgrade_version.sh` hard-fail, UNRELEASED-manifest visibility, silent old-config retention, `v`-prefix handling — plus the owner-ruled guarded, non-obvious, loudly-warned first-party-only branch-install mechanism)

- [00280: workflow agent model cap in standing authorisation](00280-workflow-agent-model-cap-authorisation/PLAN.md) - Not Started (extend the built-in `workflow-orchestration` standing authorisation with a configurable model cap for workflow/sub-agents — default: Sonnet encouraged, Opus as required, Fable banned)

- [00264: cap the size of a GitHub issue/PR comment](00264-github-comment-size-cap/PLAN.md) - Not Started (field report: agent sessions flooded two issues with 44,467- and 22,398-character comments until neither ticket's state was findable by the humans reading it; a PreToolUse cap on `gh` comment bodies steering the content into `JOURNAL/`, plus seven open questions the report's proposed design asserts rather than settles)

- [00252: guards for premises no write-time hook sees](00252-guards-for-premises-no-write-time-hook-sees/PLAN.md) - Not Started (two defects, one argument from Core Standard 15's corollary: the ambient-git-premise class Plan 00245 fixed seven times by hand without a guard, and the fact that no guard inspects STAGED CONTENT for secret-list terms, so a file arriving by `mv` reached a pushed commit)

- [00250: CI must actually run the acceptance gates it calls blocking](00250-ci-runs-the-blocking-acceptance-gates/PLAN.md) - Not Started (Plan 00245's `-rs` flag named 11 acceptance tests that have skipped on every CI run for want of a daemon socket, three of the files being ones `RELEASING.md` Step 12.0 declares BLOCKING)

- [00243: make the acceptance playbook deterministically executable](00243-deterministic-acceptance-playbook-harness/PLAN.md) - In Progress (Task 1.1's audit sized the work and found 4 defects; Phase 0 fixed the 3 real ones and refuted the 4th, 7/23 tasks)

### Security / Presentation Audit

### Core / Hook Coverage

- [00242: Terminal handlers are a flawed primitive](00242-terminal-handlers-are-a-flawed-primitive/PLAN.md) - Not Started (the chain ALREADY merges correctly — most-restrictive-wins plus accumulated context — and `terminal` overrides that merge, which is why a handler could silently disable its successors; make terminality a property of the DECISION, and return one merged response listing every violation at once)

- [00170: Universal Hook Coverage + Hook-Support Enforcement](00170-universal-hook-coverage-and-enforcement/PLAN.md) - Dormant (fundamental: intercepting hook events is the daemon's raison d'être, yet only **10 of the 30** documented Claude Code hook events are wired — 20 are silently unwired, so a client project cannot even …)

- [00172: Close the HandlersConfig ↔ wired-events coverage gap](00172-handlerconfig-wired-events-coverage-gap/PLAN.md) - Not Started (follow-up from the `status_line` config-drop fix audit: `HandlersConfig` declares only 11 of 31 wired events, so `_build_handler_config_mapping` would silently drop config for any of the 20 …)

- [00189: WorktreeCreate daemon-down raw-path completion](00189-worktree-create-daemon-down-raw-path-completion/PLAN.md) - Not Started (tracked follow-up captured by the v3.49.0 release Code Review Gate per RELEASING.md "never drop a finding".)

- [00204: security_antipattern — the three data-flow categories](00204-security-antipattern-dataflow-categories/PLAN.md) - Not Started (v3.52.0 corrected guidance that claimed SQL injection, weak cryptography and path traversal were blocked when no strategy implements any of them; this decides whether construct-level regexes can carry signal for them without the false-positive rate that gets a handler disabled.)

- [00205: destructive git synonym respellings](00205-destructive-git-synonym-respellings/PLAN.md) - Not Started (tracked follow-up captured by the v3.52.0 release gate per RELEASING.md "never drop a finding": v3.52.0 closed ten *invocation* respellings but not *synonym* ones — `git update-ref -d refs/heads/X` is an unguarded `git branch -D`, and `git push origin +main:main` an unguarded `git push --force`.)

### Status Line / Agent View

- [00175: statusline refreshInterval first-class default + startup validation](00175-statusline-refresh-interval-first-class/PLAN.md) - Dormant, part-shipped (root-caused the Ctrl+Z notice lag to `statusLine.refreshInterval: 10` — Claude Code re-runs the status command only on events (Ctrl+Z is not one) plus this optional timer whose minimum is 1s, so an …)

- [00158: Agent Thread Navigation & Status Line](00158-agent-thread-navigation-statusline/PLAN.md) - Dormant (Phase 1 research/dogfood complete; Phases 2–4 waited on Plan 00174's `subagentStatusLine` rendering design, which is now Superseded — the dependency needs re-deciding, not merely re-pointing, since 00175 concluded the artefact store should not be built)

  - Documents the dogfood-verified Claude Code contract for the main `statusLine` and the newer `subagentStatusLine` surfaces; root-causes the "no status line / whose data?" symptoms under Agent View (arrow-key thread navigation)
  - Scopes daemon support for `subagentStatusLine` (per-thread agent-panel rows) plus a `statusLine` `refreshInterval` so the bar stays live while background agents run
  - Confirmed live: main bar payload carries NO agent-thread identity (always renders main session); we wire only `statusLine` today

- [00159: Status Writers Thread-Safe Tmp Naming](00159-status-writers-thread-safe-tmp-naming/PLAN.md) - Not Started (v3.39.0 code-review follow-up: the four `.{stem}.{pid}.tmp` atomic writers key on PID not thread — harmless today, hardening only)

- [00168: Supervisor Compaction Injection Not Firing](00168-supervisor-compaction-injection-not-firing/PLAN.md) - Dormant, Task 5.3 externally blocked (high-value: user reports the ccy supervisor stopped auto-`/compact`-ing at COMPACT NOW; live diagnostic verified the supervisor armed+running, not stale, session-isolation working single-session …)

### Code Quality / Handler Configuration

- [00161: Idle Housekeeping Mode](00161-idle-housekeeping-mode/PLAN.md) - In Progress (Phase 1 brainstorm delivered: turn repeated no-op failsafe-recovery ticks into a bounded, report-first housekeeping mode dispatched to specialist sub-agents; awaiting Phase 2 build)

### Plan Workflow / QA

- Root cause: agents conflate `PLAN.md` with `JOURNAL/` and append narrative progress into the plan. Measured churn proves it — `del/add` ratio 0.00–0.18 across large plans (00104: 885 lines added, **zero** deleted), so plans grow monotonically (57 KB locally, 100 KB+ reported in client projects)

- Enforces the two contracts: **JOURNAL = append-only**; **PLAN.md = lean, surgical, always-correct**, mutated via commit-if-dirty → edit → commit so history lives in git, not in the file body

- Tiered size enforcement (advise → strong warn → hard block) at escalating thresholds via the existing `plan_qa` surfaces, plus consistent doc/SSoT touch-points — no new handler, no context flooding

- [00163: Plan Journalling — first-class per-plan JOURNAL/ support](00163-plan-journalling/PLAN.md) - Dormant (Phases 1–2 shipped in v3.40.0; Task 3.2 is the sole open item)

  - Every plan folder gains a `JOURNAL/` of per-day append-only files `NNNNN-Journal-YY-MM-DD.md` — the linear activity log (findings, decisions, dead-ends, hand-offs) complementary to PLAN.md, with a fixed entry grammar (`## HH:MM · category · REF`)
  - First-class via the existing plan_qa surfaces (no new handler): six advise-first checks (`journal-dayfile-naming`, `journal-append-only`, `journal-folder-present`, `journal-freshness`, plus deferred …
  - Dogfood in this repo first (Plan 00163 journals itself), then client rollout with a copyable `CLAUDE/PlanJournalling.md` reference doc; `## Notes & Updates` subsumed into JOURNAL with a curated `## Delivery & Milestones` stub kept in PLAN.md

- [00144: Plan QA System — Real-Time Plan Validation & Drift Enforcement](00144-plan-qa-system/PLAN.md) - Dormant (all six phases shipped in v3.32.0; blocked only on a human go/no-go to ratchet `commit_gate_mode` from `warn` to `block`)

  - Pure `plan_qa` core (PlanTree/PlanDoc/ReadmeIndex parsers + declarative check registry) consumed by three surfaces: edit-time PreToolUse lint, `git commit` cross-file gate (warn→block ratchet), and …
  - Enforces status-header integrity, index-at-birth, terminal-state atomicity (`git mv` + README row + stats in one commit), number-collision defence, and required archive dirs (`Completed/`/`Cancelled/`, configurable)
  - Config under `plan_workflow.qa`; grandfathering for legacy plans; spec provenance: `untracked/hooks-daemon-plan-verify-qa.md` (31-sin audit catalogue)

### Self-Driving / Automation

- [00166: Supervisor Multi-Terminal Session Isolation](00166-supervisor-multi-terminal-session-isolation/PLAN.md) - Dormant, implementation shipped and awaiting live two-terminal closure verification (root cause confirmed by code review + live `/proc` topology: the PTY supervisor reads the ONE shared per-repo `context-sidecar/` dir and matches compaction signals / sidecars by freshness / …)

- [00135: Event-Driven `send-keys` Injection](00135-event-driven-send-keys-injection/PLAN.md) - **In design**

- [00160: Supervisor Foreground Identity & Dead-File Reaping](00160-supervisor-foreground-identity-and-reaping/PLAN.md) - Dormant (00135 follow-up: reap dead sidecars/signals + bind the supervisor to the foreground session; remaining verification needs a live 2-thread Agent-View session that cannot be forced from inside a supervised one)

### Memory / Documentation Policy

- [00131: Block Untracked Claude Memory + Tracked-Docs Progressive Disclosure](00131-disable-auto-memory-tracked-docs-system/PLAN.md) - Shipped v3.23.0 (Phases 1–4; Phase 4 scaffolding-skill + Phase 6 dogfood deferred to follow-ups)

  - Shipped: `allow_untracked_claude_memory` option (default `true`) on `markdown_organization` — when `false`, **blocks** Write/Edit + bash redirect/tee writes to Claude memory files (reads always …
  - User-directed design: enforce by **blocking at the daemon layer**, not by disabling Claude's own (unreliable) memory engine
  - Deferred follow-ups: a scaffolding skill (inventory docs, `@`-import audit, auto-build rules/skills) and dogfooding the policy in this repo (migrate `MEMORY.md` into tracked docs)

### Tooling / Dependencies

- [00129: Wire llm-friendly-qa-wrappers in as a Major Dependency](00129-llm-qa-wrappers-integration/PLAN.md) - Not Started

  - GitHub Issue [#33](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/33)
  - Adopt [`edmondscommerce/llm-friendly-qa-wrappers`](https://github.com/edmondscommerce/llm-friendly-qa-wrappers) (terse-terminal + JSON-to-tempfile wrappers around ESLint/PHPStan/Ruff/etc.) as a major …
  - Single schema-validated `raw command → wrapper invocation` SSOT via Strategy + Registry (no hardcoded if/elif)
  - Secondary strand: global `--json` mode on [`lts/php-qa-ci`](https://github.com/LongTermSupport/php-qa-ci) (`bin/qa` Bash pipeline) so the whole PHP pipeline emits one machine-readable result, vs. wrapping each PHP tool individually
  - Reference repos cloned to `untracked/repos/`; wrapper repo audit captured in `AUDIT-llm-friendly-qa-wrappers.md`; adoption gated on the audit verdict

### Infrastructure / Bootstrap

- [00176: settings.json merge — preserve client customizations on upgrade](00176-settings-json-merge-preserve-on-upgrade/PLAN.md) - Not Started (surfaced from Plan 00175: the installer/upgrader deploy the daemon's own `.claude/settings.json` by **verbatim copy** — fresh install backs up then overwrites (`install_version.sh:357-363`), and …)

- [00110: Python Interpreter Discovery — DRY Consolidation & Latest-Always Policy](00110-python-discovery-dry-consolidation/PLAN.md) - Not Started

  - Field report from host `host-a` (`untracked/hooks-daemon-upgrade-python-version.md`): skill `install.sh` aborted on default `python3` (3.9.21) and suggested hardcoded `python3.11` despite `python3.13`/`python3.14` being on PATH
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
  - **Residue deferred from v3.12.0** (Plan 00107 Wave 4): Phase 3.5.2–3.5.7 (bootstrap-fallback wiring), Phase 4 (flock concurrency), Phase 5 (parameterised upgrade-cycle test), Phase 6 (docs) …

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

- [00266: AI-assisted handler decisions](00266-ai-assisted-handler-decisions/PLAN.md) - Dormant (native `prompt`/`agent` hooks measured live: they work, fail CLOSED, cost ~1.2s vs the daemon's ~51ms, and cannot override a daemon deny; dynamic prompting via `tool_use_id` is the leading architecture; parked as reference until a revival condition fires)

## Completed Plans

Older completed plans (below the retention window of the 30 highest-numbered) are archived verbatim in [Completed/README.md](Completed/README.md).

- [00320: stale goal intent sidecar on retirement](Completed/00320-stale-goal-intent-sidecar-on-retirement/PLAN.md) - Complete (a retired goal outlived its ledger entry and kept challenging session stop; the sidecar is now retracted when the ledger empties, and the trigger is anchored to the project root)

- [00318: supervisor audit via status line banner](Completed/00318-supervisor-audit-via-status-line-banner/PLAN.md) - Complete at f818727b (the audit trail was an INJECTED chat line costing a model turn and permanent context for a notice only the human needs; it is now a 30s self-counting-down status-line banner that no longer waits for an idle session, with decision.log keeping the full record)

- [00316: manual model choice must win](Completed/00316-manual-model-choice-must-win/PLAN.md) - Complete at 07871229 (a typed /model opus was fought by the auto-restore because the 120s manual window expired during a busy spell before the sidecar ever reported the switch; the manual note is now a latch consumed by the first matching reading and the daemon marker is written as soon as a session id exists — live-confirmed: no restore, no downgrade flag)

- [00317: supervisor host thin shim](Completed/00317-supervisor-host-thin-shim/PLAN.md) - Complete at c3eb83b2 (typed-command recognition moved worker-side via a fail-open RawInputTap; Ctrl+C byte-swallow audited as the one justified host-side stay; hot-reload live-confirmed — a recognition change now ships mid-session via worker reload alone)

- [00312: supervisor ctrl c double press guard](Completed/00312-supervisor-ctrl-c-double-press-guard/PLAN.md) - Complete at 5242b58f (lone 0x03 swallowed with a visible status hint, rapid second press always forwarded; both halves live-confirmed by owner — single accidental press killed nothing, deliberate spam shut the session down)

- [00315: hidden agent budget detection](Completed/00315-hidden-agent-budget-detection/PLAN.md) - Complete at 0ee38866 + 74f3405e (BUDGETS.md catalogue of opaque per-session budgets with source-of-truth honesty; generic budget_exhaustion_detector PostToolUse advisory with mandatory prominent user reporting and an untracked occurrence ledger; live dogfood closed a self-feeding-loop false-fire the same day)

- [00313: venv resolver cross-view reuse](Completed/00313-venv-resolver-cross-view-reuse/PLAN.md) - Complete at 3d71ff84, shipped in v3.59.0 (slug-mismatched `venv-*` candidates are now ineligible in the metadata and scan fallback resolution steps, so host and container views of the same repo each build their own venv; bash resolvers inherit via the Python SSOT)

- [00307: subagent file based report handoff](Completed/00307-subagent-file-based-report-handoff/PLAN.md) - Complete (dispatch_declaration + subagent_report_size_blocker handlers, both enabled by default; three live probe runs proved RED truncation, GREEN blocked+re-routed, third-run full convention compliance; owner called time on passive multi-session soak)

- [00309: lint on edit per language timeout](Completed/00309-lint-on-edit-per-language-timeout/PLAN.md) - Complete at 373db1f9, merged at 6ca8bf79 (per-language `options.timeouts.<Language>` for lint_on_edit; fail-open kept, fired timeouts now name the language, budget and config key)

- [00308: post upgrade config optimisation autorun](Completed/00308-post-upgrade-config-optimisation-autorun/PLAN.md) - Complete at 022dbcea (merged) (/optimise promoted as the canonical config-optimisation step with manifest-diff + run recording; upgrade/install flows invoke it with `--skip-config-optimisation` opt-out; `config_optimisation_reminder` SessionStart safety net)

- [00310: plan readme completed row ageout](Completed/00310-plan-readme-completed-row-ageout/PLAN.md) - Complete (Completed rows now age out: main README retains the 30 highest-numbered; older rows archived verbatim in Completed/README.md, enforced by test_plan_index_navigability.py)

- [00306: secret bash mention overbroad matching](Completed/00306-secret-bash-mention-overbroad-matching/PLAN.md) - Complete at 49befa8b (secret_file_guard Bash-mention false positives fixed, `git rm --cached` exempted, plus four same-subsystem review findings)

- [00299: multi plan goal support](Completed/00299-multi-plan-goal-support/PLAN.md) - Complete (goal ledger renders a combined goal line across every In-Progress plan; single-plan behaviour unchanged)

- [00298: failsafe cron blockage cadence](Completed/00298-failsafe-cron-blockage-cadence/PLAN.md) - Complete (blocked-on-human marker suppresses failsafe-cron ticks at zero token cost; every failure path fails open)

- [00297: supervisor drop anchor safety net](Completed/00297-supervisor-drop-anchor-safety-net/PLAN.md) - Complete at 4be5bbef (read-back-verified DROP ANCHOR forces Fable to low effort, with retry/escalation and ESC interrupt; observed firing live)

- [00305: v3580 release review followups](Completed/00305-v3580-release-review-followups/PLAN.md) - Complete at 5fd91df3 + 277a47bd (v3.58.0 deferred review findings: mock.patch removed from shipped CLI, {REPO_ROOT} placement validators, absolute secret-list degrade surfaced; playbook drift fixed incl. secret_file_guard bracket false positive and pipe_blocker quoted-argument producer attribution)

- [00304: degraded mode fail open and visibility](Completed/00304-degraded-mode-fail-open-and-visibility/PLAN.md) - Complete at the merge + archiving commits (php-qa-ci canary blocker: null legacy key tolerated, destructive-git safety net while degraded, degradation visible on status/check/config-validate)

- [00302: zero absolute paths config audit](Completed/00302-zero-absolute-paths-config-audit/PLAN.md) - Complete at `5bf8b8a6`/`b8c280a6` + the archiving commit (shared repo-relative validator across all path-typed config, fail-open runtime resolvers, documented exemptions, `{REPO_ROOT}` canonical token)

- [00301: monorepo single config hard cutover](Completed/00301-monorepo-single-config-hard-cutover/PLAN.md) - Complete at `aa914471`/`906eed45` + the archiving commit (owner-ruled hard cutover: alias hard-error, single test_dir anchoring, per-project `layout:` with DRY aggregation helpers, REPO/PROJECT `workspace_scope` taxonomy)

- [00296: monorepo workspace resolver](Completed/00296-monorepo-workspace-resolver/PLAN.md) - Complete at 9 merge commits + the archiving commit (one shared `Workspace`/`ProjectRegistry` resolver, declared-or-root `projects:` config, five handlers routed through it, monorepo detector advisory, degradation surfaced in `check`)

- [00294: relay transport safe toggle and reenable](Completed/00294-relay-transport-safe-toggle-and-reenable/PLAN.md) - Complete at `17f9446e` + the archiving commit (one-command verified auto-reverting `transport on|off|status`; relay dogfood re-enabled here via the toggle; canary run 5 proved client parity incl. client-side relay build)

- [00290: rust socket relay forwarder](Completed/00290-rust-socket-relay-forwarder/PLAN.md) - Complete at `54422e79` + the archiving commit (opt-in `daemon.transport` relay: per-event Unix sockets + std-only static Rust relay, measured 4.344 ms p50 vs 34.1 ms baseline; stop/subagent-stop excluded to keep the exit-2 contract; dogfooded live in this repo)

- [00292: codex cli dual host research](Completed/00292-codex-cli-dual-host-research/PLAN.md) - Complete (research-only, 9-agent Sonnet workflow: Codex CLI hooks are verdict-based but cover only shell/apply_patch/MCP calls today; 6 of our 31 wired events have any counterpart; recommendation in FINDINGS.md — host-adapter + verdict degradation, deferred until Codex Edit/Write hook coverage lands)

- [00288: project-layout config SSoT](Completed/00288-project-layout-config-ssot/PLAN.md) - Complete at `3aa68a72`…`e8dea14b` + the archiving commit (top-level `layout:` block and `ProjectLayout` facade as the single access API for directory truths)

- [00289: docs gold standard zero findings](Completed/00289-docs-gold-standard-zero-findings/PLAN.md) - Complete at `671b6eb7` + `01312f29` + the archiving commit (whole-repo `docs-qa --sweep` driven from 34 advisories to zero: two checker bug fixes, a new `scope_exclude_globs` corpus exclusion, a live-template link fix, root `CLAUDE.md` `@`-import conversion, module-doc thinning/promotion, and the `release-agent.md` duplicate)

- [00287: docs-qa pre-release punch list](Completed/00287-docs-qa-prerelease-punch-list/PLAN.md) - Complete at `94c41f61` (F1-F4 + N1 findings from the Plan 00284 post-completion review fixed; sweep re-verified at the 34-advisory baseline)

- [00286: plan-qa staged status/location coherence](Completed/00286-plan-qa-staged-status-location-coherence/PLAN.md) - Complete at `c7633e3f` + the archiving commit (adds the `archived-status-coherence` commit-gate check reading STAGED blobs, catching the git-mv-stages-rename-not-edits sequence that briefly landed Plan 00284 archived as In Progress)

- [00284: documentation SSoT enforcement](Completed/00284-documentation-ssot-enforcement/PLAN.md) - Complete at `674f6a11` + slices through `7f34718c` (R1–R13 ruleset in `CLAUDE/DocumentationStrategy.md`, docs_qa enforcement + agent + skill, repo sweep 168 → 34 advisories)

- [00285: skill bootstrap reexec breaks sibling source](Completed/00285-skill-bootstrap-reexec-breaks-sibling-source/PLAN.md) - Complete at `1ffb5e4a` + `798a5bc2` (self-bootstrap re-exec broke `$(dirname "$0")` sibling sourcing; fixed via re-exec-proof `DAEMON_DIR` + an `audit_shell.py` guard)

- [00283: standing-auth cadence + supervisor-typed channel](Completed/00283-standing-auth-cadence-supervisor-channel/PLAN.md) - Complete at `faf4fae0` + the archiving commit (bounded reinforcement cadence + opt-in ccy-supervisor-typed channel for `standing_authorisations`, plus a shared `utils/ccy_supervisor` liveness util)

## Blocked / On Hold Plans

- **00032, 00034, 00035** - On hold pending upstream Claude Code delegate mode fix (GitHub #23447, #25037)

## Cancelled Plans

- [00132: PostToolUse Progressive-Disclosure Reminder on Project-Doc Markdown Writes](Cancelled/00132-progressive-disclosure-md-write-reminder/PLAN.md) - Superseded by [00284](Completed/00284-documentation-ssot-enforcement/PLAN.md), whose edit-time/post-write surface absorbs this plan's nudge intent; never started, so no work is lost

- [00174: Status-Line Artefact + Per-Segment Cadence Redesign](Cancelled/00174-status-line-artefact-cadence-redesign/PLAN.md) - Superseded by Plan 00175, which concluded the artefact store is unnecessary because Claude Code's 1s refresh floor caps any benefit a cheaper render could unlock

- [00199: planlib — plan-orchestrator tooling in the daemon](Cancelled/00199-hooks-daemon-plan-lib/PLAN.md) - Superseded

  - Superseded by [00213](Completed/00213-planlib-plan-folder-orchestrator-tooling/PLAN.md), which targets the SAME upstream proposal and is the plan being executed. Both were authored independently five days apart and neither referenced the other; 00213 additionally tracks the proposal under version control (`PROPOSAL.md`) rather than pointing at `untracked/`. 00199 was never started, so no work is lost.

  - Preserved for `PROPOSAL-ASSESSMENT.md`, whose integration analysis 00213's owner reviewed and adopted wholesale: mode `0644` not `0755` (the library is sourced, not executed), adding it to `_EXPECTED_ROOT_FILES` so the sweep does not flag it, daemon-owned overwrite-on-upgrade, no default for `root_marker`, neutral config examples, the `bash -n` empty-stderr assertion, and deferring `plan_script_qa`.

- [00091: Hook Executable Permissions](Cancelled/00091-hook-executable-permissions/PLAN.md) - Cancelled

  - Superseded by [00102](00102-hook-exec-bit-defense/PLAN.md).

- [00081: Pseudo-Events & Nitpick Handler](Cancelled/00081-pseudo-events-nitpick-handler/PLAN.md) - Cancelled

  - Superseded by [00082](Completed/00082-pseudo-events-nitpick-handler/PLAN.md), the revised execution plan (Complete). Both plans share the same title and problem statement; this research-stage plan is preserved for history. Closed during Plan 00107 Wave 3.

- [00087: Post-Clear Auto-Execute](Cancelled/00087-post-clear-auto-execute/PLAN.md) - Cancelled

  - Hooks cannot solve `/clear <text>` auto-execution — client-side `local-command-caveat` and no auto-submit
  - Prototype handler remains enabled (marginal value), but core goal impossible via hooks

- [00044: Acceptance Testing Skill](Cancelled/00044-acceptance-testing-skill/PLAN.md) - Cancelled

  - Sub-agent acceptance testing retired in v2.10.0; main-thread testing is the standard

---

## Plan Statistics

- **Total Plans Created**: 321 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 264 (includes 1 reduced-scope plan and 5 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 41 (count = root `NNNNN-*` plan folders; includes the 3 upstream-blocked on-hold plans below and several dormant plans awaiting a scheduling/release window)

- **On Hold**: 3 (blocked by upstream Claude Code delegate mode fix)

- **Cancelled/Abandoned**: 7 on disk (count = `Cancelled/` folders: 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00132 superseded by 00284, 00174 superseded by 00175, 00199 superseded by 00213)

- **Folder-to-number reconciliation**: 41 + 264 + 7 = **312 folders**, spanning
  **309 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **12** of the
  321 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258, 00300, 00303 — abandoned drafts, numbers
  burned by transient probes (00195 during the v3.51.0 acceptance run, 00258
  during the v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a
  sub-agent that then found Plan 00208 already covered the work).
  309 + 12 = 321. ✅

  Note on **00191**: it stays folderless deliberately. The number was claimed
  by a branch that renumbered itself and was never merged; Plan 00267
  supersedes it, so no folder for 00191 will ever land in `main`.

- **Last reconciled at**: the Plan 00275 archival (40 root, 223 `Completed/`,
  6 `Cancelled/`, 266 distinct numbers against a counter of 276). The index
  carries NO reconciliation history — it states current truth only; every
  earlier recount is in git, and per-plan narrative belongs in that plan's
  `JOURNAL/`.

  One recount hazard worth keeping, because it recurs: an untracked stray
  directory (e.g. an accidental `CLAUDE/Plan/CLAUDE/Plan/` from a
  relative-path slip) is invisible to `git status` while still inflating a
  naive folder count by one.

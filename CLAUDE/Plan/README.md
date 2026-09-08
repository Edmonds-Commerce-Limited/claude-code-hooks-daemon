# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00346: pin qa toolchain versions](00346-pin-qa-toolchain-versions/PLAN.md) - Not Started (every QA tool is declared with a lower bound only and all have drifted past a major; the formatter is the sharp case because its QA step AUTO-FIXES, so a black release rewrites the tree and reports success rather than failing — the same shape ruff 0.14 already produced, answered then with ignores rather than a pin)

- [00344: stop hook deny rate classification](00344-stop-hook-deny-rate-classification/PLAN.md) - Not Started (Plan 00337 Task 5.0 shipped the instrumentation but the classification needs telemetry across many sessions — 49 instrumented rows exist and 48 are acceptance probes, because a real Stop event fires roughly once per session)

- [00330: hooks daemon skill surface coherence](00330-hooks-daemon-skill-surface-coherence/PLAN.md) - Not Started (the skill is the human-touching surface and has drifted: `optimise` scores 21 of 110 configurable handlers from a hardcoded list, so it cannot be current by construction; adds a registry-derived checklist, a single housekeeping command, and a release gate)

- [00329: post upgrade truth changes report bloat](00329-post-upgrade-truth-changes-report-bloat/PLAN.md) - Not Started (the upgrade flow's truth-changes reconciliation hands the agent up to 89KB / 74 entries with no bound and no supersession collapsing, so superseded truths are replayed and the step is skimmed rather than performed)

- [00327: hooks contract refresh audit](00327-hooks-contract-refresh-audit/PLAN.md) - Not Started (upstream's hooks documentation has changed since the 2.1.252 audit — `e2462deb…` vs META's `d514bf57…` — so the vendored contract needs its verified section-by-section extraction audit, and the mechanisable half of the refresh procedure folded into a `contract-status` command)

- [00319: supervisor release review followups](00319-supervisor-release-review-followups/PLAN.md) - Not Started (the ten non-blocking findings surviving the v3.60.0 code-review gate, grouped into silent failures, unbounded per-session growth, and writer/reader contract drift; the three BLOCKING siblings shipped in 55dd5b2e)

- [00311: v3.59.0 release review followups](00311-v3590-release-review-followups/PLAN.md) - Not Started (non-blocking findings ledger from the v3.59.0 code review: dispatch_declaration's hardcoded plan path, the secret_file_matching glob-heuristic maintenance surface, and the git rm --cached looseness verification)

- [00295: v3.57.0 release review followups](00295-v3570-release-review-followups/PLAN.md) - Not Started (non-blocking findings ledger from the v3.57.0 code review gate, tiered HIGH/MEDIUM/LOW)

- [00293: tool inventory disable and token savings](00293-tool-inventory-disable-and-token-savings/PLAN.md) - In Progress, 13 of 14 tasks done and the remainder human-gated (`source_disable`, the transcript analyser, `tool-report` and the advisory all shipped and are dogfooded here; Task 4.1 needs a `/context` spot check in a fresh interactive session, which an agent cannot perform)

- [00291: upgrade path hardening and guarded branch install](00291-upgrade-path-hardening-and-guarded-branch-install/PLAN.md) - Not Started (php-qa-ci canary findings: fresh-clone `upgrade_version.sh` hard-fail, UNRELEASED-manifest visibility, silent old-config retention, `v`-prefix handling — plus the owner-ruled guarded, non-obvious, loudly-warned first-party-only branch-install mechanism)

- [00280: workflow agent model cap in standing authorisation](00280-workflow-agent-model-cap-authorisation/PLAN.md) - Not Started (extend the built-in `workflow-orchestration` standing authorisation with a configurable model cap for workflow/sub-agents — default: Sonnet encouraged, Opus as required, Fable banned)

- [00264: cap the size of a GitHub issue/PR comment](00264-github-comment-size-cap/PLAN.md) - Not Started (field report: agent sessions flooded two issues with 44,467- and 22,398-character comments until neither ticket's state was findable by the humans reading it; a PreToolUse cap on `gh` comment bodies steering the content into `JOURNAL/`, plus seven open questions the report's proposed design asserts rather than settles)

- [00252: guards for premises no write-time hook sees](00252-guards-for-premises-no-write-time-hook-sees/PLAN.md) - Not Started (two defects, one argument from Core Standard 15's corollary: the ambient-git-premise class Plan 00245 fixed seven times by hand without a guard, and the fact that no guard inspects STAGED CONTENT for secret-list terms, so a file arriving by `mv` reached a pushed commit)

- [00250: CI must actually run the acceptance gates it calls blocking](00250-ci-runs-the-blocking-acceptance-gates/PLAN.md) - Not Started (Plan 00245's `-rs` flag named 11 acceptance tests that have skipped on every CI run for want of a daemon socket, three of the files being ones `RELEASING.md` Step 12.0 declares BLOCKING)

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

- [00110: Python Interpreter Discovery — DRY Consolidation & Latest-Always Policy](00110-python-discovery-dry-consolidation/PLAN.md) - In Progress, and only Phase 7 remains (Phases 1-6 had all shipped while the boxes said 8 of 60 — verified against disk and 107 green tests. Phase 7 is `/release`, which is human-gated, so this plan cannot be closed by an agent)

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

- [00345: harness payloads for shell and call syntax tests](Completed/00345-harness-payloads-for-shell-and-call-syntax-tests/PLAN.md) - Complete at `b34ab4cd`…`23fb248f` + the archiving commit (94 → 199 of 228 dispatchable blocks now run automatically, and every remaining skip carries a reason a reader can act on)

- [00328: human model choice cannot be read from keystrokes](Completed/00328-human-model-choice-cannot-be-read-from-keystrokes/PLAN.md) - Complete at `c4e22ac0`…`dd7f43f3` + the archiving commit (the picker types no text a parser can read, so the restore now arms only on Claude Code's OWN downgrade record and the keystroke-recognition channel is deleted)

- [00337: stop hook, human-input marker and failsafe cron retune](Completed/00337-stop-hook-human-input-cron-retune/PLAN.md) - Complete at `ea03f597`…`51e3694a` + the archiving commit (guidance states the consequence, not just the mechanism; `[awaiting-human]` anchored to the declaration position; the failsafe cron backs off to a 4h cap only when nothing is owed. The DENY-rate classification is Plan 00344)

- [00342: prose guard does not reach stop handlers](Completed/00342-prose-guard-does-not-reach-stop-handlers/PLAN.md) - Complete at the delivery + archiving commits (the prose guard now scopes by base class and carries a Stop axis whose predicate is the marker SIDE EFFECT — `_denies()` would have passed vacuously; quoting a frozen phrase no longer arms cron suppression, and the unquoted residue is asserted as a recorded limit rather than left implicit)

- [00343: flip the plan QA commit gate from warn to block](Completed/00343-plan-qa-commit-gate-warn-to-block/PLAN.md) - Complete at the delivery + archiving commits (a 253-commit replay found 18 would-be denials of which 7 blamed a commit for plan-tree state it never touched; six checks narrowed to BLOCK only what a commit introduced, replay then 11 denials with zero false positives, and the gate flipped to `block`)

- [00341: plan status header rots behind shipped work](Completed/00341-plan-status-header-rots-behind-shipped-work/PLAN.md) - Complete at `9a0bf7a8` + the archiving commit (a single ticked box now falsifies a `Not Started` header, and shipping `src/` code for a plan named in the commit SUBJECT does too; the subject scoping came from a 250-commit replay that exposed a 25% false-positive shape argument had missed)

- [00338: deployed skill tree invisible to review](Completed/00338-deployed-skill-tree-invisible-to-review/PLAN.md) - Complete at the archiving commit (the `.claude/.gitignore` pattern is anchored to `/hooks-daemon/`, so the 21-file deployed skill tree is tracked like its five siblings; both directions pinned by tests, and source-to-deployed drift is now a check rather than an accident)

- [00314: failsafe cron suppression marker never arms](Completed/00314-failsafe-cron-suppression-marker-never-arms/PLAN.md) - Complete at `923fd583` + the archiving commit (marker-write outcome now recorded in stop-events.jsonl, so a non-arm is diagnosable from disk; 16 live `marker_written: true` records closed the dogfood task)

- [00340: release review followups v3621](Completed/00340-release-review-followups-v3621/PLAN.md) - Complete at `6d0aad13`…`c9dfd4a8` + the archiving commit (the v3.62.1 review's non-blocking remainder: a real `/model` picker confirmed the supervisor's blind Enter persists a modal's default, so a resubmit now follows its own escape within 2s)

- [00339: supervisor injection lands unsubmitted](Completed/00339-supervisor-injection-lands-unsubmitted/PLAN.md) - Complete at `e98c19e4` + the archiving commit (probing a real TUI refuted the assumed mechanism: the trigger is Claude Code's paste detection on a large burst, inside which a carriage return is a literal newline, so the injection is now bracketed-paste framed)

- [00336: upgrade path residual findings](Completed/00336-upgrade-path-residual-findings/PLAN.md) - Complete at `c85d5e90`…`788ce6c8` + the archiving commit (config preservation now diffs against a true old-version baseline; `HOOKS-DAEMON.md` regenerated on both upgrade paths instead of never; 17 shipped commands our own `project_containment` denied moved in-repo, found by driving the doc corpus through the live handler)

- [00335: heredoc receiver policy and review followups](Completed/00335-heredoc-receiver-policy-and-review-followups/PLAN.md) - Complete at `745ff9c5` + the archiving commit (inverting the quoted-heredoc exemption to an allowlist of data sinks closed a fourth executor bypass found by probing, the word-expansion family recorded as unclosable, and the `jq` over-block in one change)

- [00334: core doc templates for client projects](Completed/00334-core-doc-templates-for-client-projects/PLAN.md) - Complete at `4e78f7c9` + the archiving commit (daemon guidance named client documents no install path created, so a client enforced a workflow whose documentation did not exist; ships three genericised core documents deployed DAEMON-owned beside a seed-once CLIENT-owned override, each gated on the subsystem that NAMES it, and replaces the hand-maintained citation list with a scan)

- [00333: no writes outside project root](Completed/00333-no-writes-outside-project-root/PLAN.md) - Complete at `bfe6e61a`…`75572df4` + the archiving commit (every path guard treated a failed absolute-to-relative conversion as allow, so `/tmp/notes.md` was silently permitted while `/workspace/notes.md` was denied; adds a deny-by-default containment guard over the Write/Edit and Bash surfaces, `untracked/scratch/` as the sanctioned location, and migrates the acceptance-test corpus off `/tmp`)

- [00332: docs qa vendor truth per project](Completed/00332-docs-qa-vendor-truth-per-project/PLAN.md) - Complete at `116207c7` + the archiving commit (a monorepo sub-project's `layout.vendor_dirs` never reached docs QA, which was handed one flat set from the ROOT block; the vendored-path predicate is now resolved per-path against the owning project, longest root winning)

- [00331: vendor dirs config is inert](Completed/00331-vendor-dirs-config-is-inert/PLAN.md) - Complete at `6b4fa867`…`ba7269d5` + the archiving commit (`layout.vendor_dirs` was a facade with zero production consumers, so declaring one did nothing; every reader now routes through it, resolved from the file's owning project)

- [00326: remote docs vendoring and staleness](Completed/00326-remote-docs-vendoring-and-staleness/PLAN.md) - Complete at `43cf91a0` through `ef342df4` (upstream docs vendored as markdown carrying provenance frontmatter, with a `fidelity` field that separates a citable corpus from a cache; four handlers gate writes and commits, route `WebFetch` to the local copy, and report staleness)

- [00324: skill invoke scripts never referenced](Completed/00324-skill-invoke-scripts-never-referenced/PLAN.md) - Complete (four skills kept 52-317 lines of procedure in an `invoke.sh` their SKILL.md never named, so every invocation ran on the summary and two of them discarded the caller's arguments)

- [00323: optimise checklist names retired handlers](Completed/00323-optimise-checklist-names-retired-handlers/PLAN.md) - Complete (the config-optimisation checklist scored four handlers Plan 00237 deleted, so a fully-configured project could never exceed 25/29 and was told to enable handlers that do not exist)

- [00322: post upgrade optimise deferral and client noise](Completed/00322-post-upgrade-optimise-deferral-and-client-noise/PLAN.md) - Complete (the mandatory post-upgrade config-optimisation review deferred itself to "your NEXT Claude Code session" and was duly filed as optional; it now claims the current session and lives at `/hooks-daemon optimise`)

- [00321: injected goal has no retraction path](Completed/00321-injected-goal-has-no-retraction-path/PLAN.md) - Complete (the supervisor could set the `/goal` slot but nothing could clear it; adds a no-payload `.goal-clear` trigger, a supervisor-typed `/goal clear`, and a `hooks-daemon clear-goal` CLI for the already-empty-ledger case)

- [00320: stale goal intent sidecar on retirement](Completed/00320-stale-goal-intent-sidecar-on-retirement/PLAN.md) - Complete (a retired goal outlived its ledger entry and kept challenging session stop; the sidecar is now retracted when the ledger empties, and the trigger is anchored to the project root)

- [00318: supervisor audit via status line banner](Completed/00318-supervisor-audit-via-status-line-banner/PLAN.md) - Complete at f818727b (the audit trail was an INJECTED chat line costing a model turn and permanent context for a notice only the human needs; it is now a 30s self-counting-down status-line banner that no longer waits for an idle session, with decision.log keeping the full record)

- [00316: manual model choice must win](Completed/00316-manual-model-choice-must-win/PLAN.md) - Complete at 07871229 (a typed /model opus was fought by the auto-restore because the 120s manual window expired during a busy spell before the sidecar ever reported the switch; the manual note is now a latch consumed by the first matching reading and the daemon marker is written as soon as a session id exists — live-confirmed: no restore, no downgrade flag)

- [00317: supervisor host thin shim](Completed/00317-supervisor-host-thin-shim/PLAN.md) - Complete at c3eb83b2 (typed-command recognition moved worker-side via a fail-open RawInputTap; Ctrl+C byte-swallow audited as the one justified host-side stay; hot-reload live-confirmed — a recognition change now ships mid-session via worker reload alone)

- [00312: supervisor ctrl c double press guard](Completed/00312-supervisor-ctrl-c-double-press-guard/PLAN.md) - Complete at 5242b58f (lone 0x03 swallowed with a visible status hint, rapid second press always forwarded; both halves live-confirmed by owner — single accidental press killed nothing, deliberate spam shut the session down)

- [00315: hidden agent budget detection](Completed/00315-hidden-agent-budget-detection/PLAN.md) - Complete at 0ee38866 + 74f3405e (BUDGETS.md catalogue of opaque per-session budgets with source-of-truth honesty; generic budget_exhaustion_detector PostToolUse advisory with mandatory prominent user reporting and an untracked occurrence ledger; live dogfood closed a self-feeding-loop false-fire the same day)

- [00313: venv resolver cross-view reuse](Completed/00313-venv-resolver-cross-view-reuse/PLAN.md) - Complete at 3d71ff84, shipped in v3.59.0 (slug-mismatched `venv-*` candidates are now ineligible in the metadata and scan fallback resolution steps, so host and container views of the same repo each build their own venv; bash resolvers inherit via the Python SSOT)

- [00309: lint on edit per language timeout](Completed/00309-lint-on-edit-per-language-timeout/PLAN.md) - Complete at 373db1f9, merged at 6ca8bf79 (per-language `options.timeouts.<Language>` for lint_on_edit; fail-open kept, fired timeouts now name the language, budget and config key)

- [00310: plan readme completed row ageout](Completed/00310-plan-readme-completed-row-ageout/PLAN.md) - Complete (Completed rows now age out: main README retains the 30 highest-numbered; older rows archived verbatim in Completed/README.md, enforced by test_plan_index_navigability.py)

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

- **Total Plans Created**: 346 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 287 (includes 1 reduced-scope plan and 6 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 42 (count = root `NNNNN-*` plan folders; includes the 3 upstream-blocked on-hold plans below and several dormant plans awaiting a scheduling/release window)

- **On Hold**: 3 (blocked by upstream Claude Code delegate mode fix)

- **Cancelled/Abandoned**: 7 on disk (count = `Cancelled/` folders: 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00132 superseded by 00284, 00174 superseded by 00175, 00199 superseded by 00213)

- **Folder-to-number reconciliation**: 42 + 287 + 7 = **336 folders**, spanning
  **333 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **13** of the
  346 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258, 00300, 00303, 00325 — abandoned drafts, numbers
  burned by transient probes (00195 during the v3.51.0 acceptance run, 00258
  during the v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a
  sub-agent that then found Plan 00208 already covered the work).
  333 + 13 = 346. ✅

  Note on **00191**: it stays folderless deliberately. The number was claimed
  by a branch that renumbered itself and was never merged; Plan 00267
  supersedes it, so no folder for 00191 will ever land in `main`.

- **Last reconciled at**: the Plan 00337 archiving (44 root, 283 `Completed/`,
  7 `Cancelled/`, 331 distinct numbers against a counter of 344). Every figure
  above was recounted from disk rather than incremented. The index carries NO
  reconciliation history — it states current truth only; every earlier recount
  is in git, and per-plan narrative belongs in that plan's `JOURNAL/`.

  One recount hazard worth keeping, because it recurs: an untracked stray
  directory (e.g. an accidental `CLAUDE/Plan/CLAUDE/Plan/` from a
  relative-path slip) is invisible to `git status` while still inflating a
  naive folder count by one.

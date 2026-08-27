# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00281: flag cleaning compaction on downgrade](00281-flag-cleaning-compaction-on-downgrade/PLAN.md) - In Progress (supervisor fires an opt-in, gated `/compact` on a REPEATED downgrade instructing Claude to summarise flaggable material at a high level, so the cleaned context stops re-tripping the classifier and the model-restore sticks)

- [00280: workflow agent model cap in standing authorisation](00280-workflow-agent-model-cap-authorisation/PLAN.md) - Not Started (extend the built-in `workflow-orchestration` standing authorisation with a configurable model cap for workflow/sub-agents — default: Sonnet encouraged, Opus as required, Fable banned)

- [00278: model-downgrade resilience](00278-supervisor-effort-restore-on-model-downgrade/PLAN.md) - In Progress (recovery: supervisor detects a fable→opus downgrade via the context sidecar and injects `/effort xhigh`; prevention: steer security-flavoured work into an Opus subagent so the fable context stays clean)

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

- [00132: PostToolUse Progressive-Disclosure Reminder on Project-Doc Markdown Writes](00132-progressive-disclosure-md-write-reminder/PLAN.md) - Not Started (awaiting sign-off)

  - Complements 00131's *block* with a *positive nudge*: a PostToolUse advisory that, after a project-doc `.md` write, re-hints the progressive-disclosure rules and asks "is this in the right place / is it the single source of truth?"
  - Scoped to `CLAUDE.md` + the `CLAUDE/` doc tree, **excluding** `CLAUDE/Plan/` and `CLAUDE/Journal/` (explicit locations); rate-limited by an in-memory cooldown counter mirroring `critical_thinking_advisory` so it never spams
  - Awaiting sign-off on Decision 1 (trigger path-set; `docs/`+`README` in or out) and the default cooldown size

- [00131: Block Untracked Claude Memory + Tracked-Docs Progressive Disclosure](00131-disable-auto-memory-tracked-docs-system/PLAN.md) - Shipped v3.23.0 (Phases 1–4; Phase 4 scaffolding-skill + Phase 6 dogfood deferred to follow-ups)

  - Shipped: `allow_untracked_claude_memory` option (default `true`) on `markdown_organization` — when `false`, **blocks** Write/Edit + bash redirect/tee writes to Claude memory files (reads always …
  - User-directed design: enforce by **blocking at the daemon layer**, not by disabling Claude's own (unreliable) memory engine
  - Deferred follow-ups: a scaffolding skill (inventory docs, `@`-import audit, auto-build rules/skills) and dogfooding the policy in this repo (migrate `MEMORY.md` into tracked docs)

- [00116: CLAUDE.md Token Compression via Stateful Progressive Disclosure](00116-claude-md-token-compression/PLAN.md) - In Progress (Phases 1–2 complete and merged; Phase 3 pending tracker-wiring decision)

  - Compresses the always-resident CLAUDE.md via stateful progressive disclosure so handler guidance loads on demand rather than inflating every session's base context; Phases 1–2 merged, Phase 3 awaits a tracker-wiring decision

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

- [00279: generic agent install subsystem](Completed/00279-generic-agent-install-subsystem/PLAN.md) - Complete at merges `6679da75` + `3abbc809` + the archiving commit (first-class daemon-shipped agent deployment: version + md5 ledger, customisation detection that never clobbers, config-gated deploy/remove lifecycle, `hooks-daemon agents` CLI; payloads: plan-dedupe scout migration + the opus-security quarantine agent v1.1.0)

- [00274: skill opportunity detector](Completed/00274-skill-opportunity-detector/PLAN.md) - Complete at the archiving commit (transcript mining → redacted digest → report embedding a judging rubric; an in-session subagent judges it — the model shell-out was removed per Decision 9; TTL-gated SessionStart advisory, report-only, ships disabled upstream)

- [00272: secret file read blocker](Completed/00272-secret-file-read-blocker/PLAN.md) - Complete at merges `4c7c5e53` + `0419b22a` + the archiving commit (deny-by-default `secret_file_guard`, `secret-meta` metadata helper, hygiene advisory, no escape hatch; read-route research classifies every route (b)/(c)/(d), class-(d) residuals closed only by OS-level controls)

- [00276: goal stack concurrent tracking](Completed/00276-goal-stack-concurrent-tracking/PLAN.md) - Complete at merge `74fa6e50` + the archiving commit (daemon-side goal ledger: every emission recorded, displacement advisory, Stop-time defence naming all still-live ledgered plans; live-verified by the production ledger's six-emission displacement history)

- [00269: supervisor goal message injection](Completed/00269-supervisor-goal-message-injection/PLAN.md) - Complete at merge `78665b51` + the archiving commit (goal_injection handler + inject-goal CLI + supervisor typing branch; live-verified by six armed-supervisor /goal injections and an on-demand CLI injection)

- [00277: release acceptance findings v3 55 0](Completed/00277-release-acceptance-findings-v3-55-0/PLAN.md) - Complete at `ebf7016a` + the archiving commit (all v3.55.0 gate findings closed: per-session block_once with session-attributed HandlerDecisionRecord, isolation-advisor test precondition, lint-clean error-hiding samples, validate_eslint_on_write deny branch verified live in the client fixture)

- [00275: github auto-close keyword blocker](Completed/00275-github-auto-close-keyword-blocker/PLAN.md) - Complete at merge `2bdafe05` (PreToolUse guard denying GitHub auto-closing keyword references in git commit/merge/tag and `gh pr` messages, inline or via `-F`/`--body-file`; enabled by default, `MUST_AUTO_CLOSE_BECAUSE` hatch)

- [00268: verification-result enforcement and the Ansible/YAML lint gap](Completed/00268-verification-result-enforcement-and-ansible-lint-gap/PLAN.md) - Complete at `24b4fb47` + `d3ebf1ba` (Ansible YAML strategy for `lint_on_edit`, the `verification_result_gate` verifier→mutator handler, and the `staged_lint_gate` commit-time backstop; blanket `;` → `&&` enforcement deliberately rejected)

- [00273: hook input payload validation](Completed/00273-hook-input-payload-validation/PLAN.md) - Complete at merge `e0f3dee9` + review fold `02957cb4` (input_contract QA check over the daemon's AST-derived read surface vs vendored input examples; Phase 2 runtime validation ruled NO-GO; Phase 3 channel question answered sentinel-free from transcript attachment typing — both SessionStart channels kept, each serving its own audience)

- [00271: hook contract alignment](Completed/00271-hook-contract-alignment/PLAN.md) - Complete at merge `18d35ba2` + the commit that archives it (DBF-first: vendored hook contracts + network-free `hook_contract` QA check landed RED against 59 findings, all 9 load-bearing drifts fixed, allowlist burned to 29 reasoned KEPT gaps; follow-ups in Plan 00273)

- [00270: bash safe mode forcer](Completed/00270-bash-safe-mode-forcer/PLAN.md) - Complete at merge `0f96b7ea` + the commit that archives it (opt-in `bash_safe_mode` handler enforcing `set -e`/`-o pipefail` preludes on multi-statement Bash invocations; shared `utils/bash_flags.py` scanner with an end-of-options guard, `verification_result_gate` refactored onto it; code-reviewed, dogfooded warn-mode scoped to mutator sequences)

- [00267: Worktree seeding and config suggestions](Completed/00267-worktree-seeding-and-config-suggestions/PLAN.md) - Complete at `79cd6fc6` + the commit that archives it (a fresh worktree now carries the project's git-ignored local files, symlink or copy chosen per entry; `check-worktree-seed` reports drift and runs at install/upgrade; dogfooding it found this repo seeding neither its daemon env nor its secret word list, the latter leaving `sensitive_content` silently inert in every worktree)

- [00265: static type safe handler results](Completed/00265-static-type-safe-handler-results/PLAN.md) - Complete at `6fc2db3a` + the commit that archives it (an undeliverable decision is now unwritable, not merely detectable: per-event bases narrow `handle()` once and all 84 handlers inherit it; a shipped example whose `SessionStart` refusal had never blocked anything was found and fixed en route)

- [00209: field feedback — daemon self-observability](Completed/00209-field-feedback-daemon-self-observability/PLAN.md) - Complete (verdict log + `hooks-daemon verdicts`, verified against a live daemon; Phase 3's investigation then found 15 phantom handlers in the shipped config template and extended the QA guard that could not see them)

- [00263: an escaped quote made the bash tokeniser invent a write target](Completed/00263-bash-tokeniser-escaped-quote-phantom-targets/PLAN.md) - Complete at `0e99b260` (non-POSIX `shlex` left escaped quotes unprocessed, exposing quoted text as live shell; fixed with `posix=True`)

- [00257: the protected ref nobody qualified, and a QA gate that fails during releases](Completed/00257-delete-branch-protected-ref-ambiguity-and-release-qa-deadlock/PLAN.md) - Complete at the commit that archives it (protected ref now resolved once before any proof; the release abort deadlock closed by NAMING the abort route rather than widening `matches()`; a `list(CONST)` argv shape was hiding a real unbounded git spawn from the guard)

- [00262: QA runs are not isolated from each other](Completed/00262-qa-runs-are-not-isolated-from-each-other/PLAN.md) - Complete at the commit that archives it (both QA entry points now share one `flock` and refuse a second run rather than race; a contended run made a GATING verdict unreliable in both directions)

- [00261: `Write` clobbers an existing file nobody read](Completed/00261-write-clobbers-unread-file-guard/PLAN.md) - Complete at the commit that archives it (a `Write` destroyed a tracked 58-line journal here, caught only by an ADVISE-level rule that happens to cover journals; `write_clobber_guard` tracks READS not sizes, because the clobbering write GREW the file)

- [00260: the Bash write side-door, and a handler that under-describes its own rule](Completed/00260-bash-write-side-door-and-stream-editor-guidance/PLAN.md) - Complete at `5094526e` (verified field report: 22 handlers keyed on `Write`/`Edit`, so a heredoc/redirect/`tee` write was seen by none of them; both linters now check Bash-AUTHORED files while relocation stays excluded, and a closing sweep found five blocking handlers the generated table advertised as advisory)

- [00259: block artefact publishing by default](Completed/00259-block-public-artefact-publishing-by-default/PLAN.md) - Complete at the commit that archives it (the `Artifact` tool mints a claude.ai URL outside the repository and was the one disclosure path with no guard; blocked by default, `action: "list"` still allowed, and deliberately NO agent-side escape hatch — verified live, not just by unit test)

- [00256: docs consistency round, found by the v3.54.0 release](Completed/00256-docs-consistency-round-for-v3540-release/PLAN.md) - Complete at `3ff4078e` + `4e064e15` + the commit that archives it (eight documents asserting something untrue of the tree, found by the release's own Step 7 and Step 10 gates; the durable half is the `unreleased-manifest-date` guard, since the placeholder it catches had already shipped silently in four manifests)

- [00255: bare refnames outside branch_safety](Completed/00255-bare-refname-ambiguity-outside-branch-safety/PLAN.md) - Complete at the commit that archives it (the filed cosmetic bug, plus a worse one the sweep found: an ambiguous base flipped the merged verdict; guard added for the checkable half)

- [00254: delete-branch must re-check a tip it proved](Completed/00254-delete-branch-tip-recheck-before-delete/PLAN.md) - Complete at `55dc8e1a` + the commit that archives it (a moved tip, and a same-named tag that made the proof describe the wrong object)

- [00253: Plan 00249 review findings](Completed/00253-plan-00249-review-findings/PLAN.md) - Complete at `c2a62f84` + the commit that archives it (six peer-review findings, all re-verified by execution before any fix)

- [00251: tdd_enforcement needs an exclusion escape and a declarable test root](Completed/00251-tdd-enforcement-exclude-paths-and-test-roots/PLAN.md) - Complete at `35b9d4e4` + the commit that archives it (field report, one finding of three misdiagnosed; `exclude_paths` on the two handlers Plan 00150 deferred, plus `test_path_map` so a project declares a test root instead of exempting it)

- [00249: delete-branch crashes on a branch merged into main but ahead of its own upstream](Completed/00249-delete-branch-merged-but-unpushed/PLAN.md) - Complete at `a74b0489` (field report: `git branch -d` measures a branch against its own UPSTREAM, a different predicate from the daemon's ancestry proof, so the dry run and the real run disagreed; fixed with a distinct `merged-unpushed` tier rather than by widening `merged` to force-delete)

- [00248: Plan 00246 review findings](Completed/00248-plan-00246-review-findings/PLAN.md) - Complete at `a74b0489` (six verified defects in the shipped `run_git` migration, two of them regressions it introduced — the centralisation imposed a 5s hook budget on `branch_safety`'s object walks, and `run_git`'s "never raises" contract was false)

- [00245: CI suite green again](Completed/00245-ci-suite-green-again/PLAN.md) - Complete at run 32033242091 / `4d1a553b1` (green on all three interpreters after 25+ red runs; four defects each hidden behind the one before it, plus the instrumentation that made them visible; spawned Plan 00250)

- [00247: Exactly one failsafe recovery cron per session](Completed/00247-one-recovery-cron-per-session/PLAN.md) - Complete at the commit that archives it (dogfooding report: the `recovery_cron_advisor` creation advisory said "create a cron NOW" with no check, so every plan in a session stacked another identical hourly cron; both it and the `background_process_tracker` watchdog advisory are now CronList-first, implementing Plan 00139's Decision D2 which the handler cited but never enforced)

- [00246: The daemon takes the git index lock it does not need](Completed/00246-git-index-lock-contention/PLAN.md) - Complete at `013b48e7` + `60ae1074` (dogfooding report of stale `.git/index.lock`: `git status` REWRITES the index, so three daemon paths contended with the agent for the lock; `run_git` is now the single spawn point declining the optional lock, with an AST guard so the 15 files that bypassed the declared facade cannot come back)

- [00244: Generated tracked docs must be path-agnostic](Completed/00244-path-agnostic-generated-docs/PLAN.md) - Complete at `6d7f8192` (client bug report: every daemon-CLI example in the tracked `CLAUDE.md` block named the rendering machine's absolute root, publishing a home directory and churning per machine; a second class hard-coded `/workspace`, true on no client machine at all — verified fixed in a real client install)

- [00241: v3.53.0 review findings — terminal-ALLOW shadowing and verdict-log retention](Completed/00241-v3530-review-findings-terminal-allow-and-verdict-log/PLAN.md) - Complete at `53cb6743` + `54757f46`, shipped in v3.53.0 (the release aborted at its own Step 10 gate: a terminal handler returning ALLOW ends the chain, disabling every handler behind it)

- [00240: delete hello world test handlers](Completed/00240-delete-hello-world-test-handlers/PLAN.md) - Complete at `44ce74e9` (the ten `hello_world` canaries and the `enable_hello_world_handlers` key that gated them, net -1,296 lines; dormant since v3.40.0 so nothing changes for anyone, and ten retired-registry entries keep an unedited client config out of degraded mode — verified in a real client install)

- [00162: Wire hello_world Handler Flag](Completed/00162-wire-hello-world-handler-flag/PLAN.md) - Complete at `ca03facb`, shipped in v3.40.0 (the dead `daemon.enable_hello_world_handlers` flag now gates the TEST handlers; default off, so the canary injection has been absent since v3.40.0 — closed as Plan 00240 Task 1.1, having sat In Progress with only the bookkeeping outstanding)

- [00239: daemon umask world-writable runtime files](Completed/00239-daemon-umask-world-writable-runtime-files/PLAN.md) - Complete at `d2d946f9` (`os.umask(0)` at daemonize made every create 0666/0777 — verdict log, `payload-capture/`, PID file; fixed to `0o077` plus explicit modes, after adversarial review refuted this plan's own `0o007` argument; ships `check-permissions --fix` because a umask retro-fixes nothing already on disk)

- [00234: handler value audit](Completed/00234-handler-value-audit/PLAN.md) - Complete (all ~100 handlers carry a recorded verdict, keeps included, so the next audit starts from a baseline; seven follow-ups shipped as plans 00235-00238, and the two defects the review itself surfaced were fixed in place at `0a280b8c` and `a1109437`)

- [00238: handler cost tuning](Completed/00238-handler-cost-tuning/PLAN.md) - Complete (git spawns 192 -> 44 per ~115 renders, 77% down: the render TTL was RESONANT rather than weak, and two of four calls per miss were asking git what it had just been told; plus one mtime gate replacing four uncached per-render reads, and a /proc walk throttled apart from the cheap detector it was priced with; delivery hashes in PLAN.md)

- [00237: remove the dead handlers](Completed/00237-remove-the-dead-handlers/PLAN.md) - Complete at `17131953` (12 handlers gone — 10 REMOVE plus 2 folded into plan QA — each with a retired-registry entry and upgrade manifest row, verified in a real client install; the shadowing guard it built then found this repo's own release blocker had never fired)

- [00236: fix what is broken pass](Completed/00236-fix-what-is-broken-pass/PLAN.md) - Complete at `54cb60e8` (repaired four Plan 00234 mechanisms that could not fire, plus the verdict log's 99% status-render noise; one audit finding was reversed by a live chain trace and a guard added instead)

- [00235: share the quoted-heredoc strip](Completed/00235-quoted-heredoc-body-shared-strip/PLAN.md) - Complete (a quoted heredoc body is literal text bash never parses, but only pipe_blocker knew it; enforce_llm_qa split on newlines and so denied a git commit message for merely naming the script it guards — the rule now lives in the shared scanner both use)

- [00233: remove the transcript archiver](Completed/00233-remove-transcript-archiver/PLAN.md) - Complete (it copied every transcript before each compaction, but compaction never deletes the original and the original already sits on the same persistent mount — 422 MB of copies nothing ever read; also added a retired-handler registry so removals never degrade a client's daemon)

- [00232: stream the transcript archive](Completed/00232-transcript-archiver-streaming/PLAN.md) - Complete (the PreCompact archiver read a 74.9 MB transcript into one string, peaking at 673.5 MB when memory is scarcest; streaming line by line cut that to 0.7 MB (922x), and the rewrite also closed an unredacted source path in the archive header)

- [00231: a bounded intent sat next to an unbounded read](Completed/00231-bounded-read-qa-rule/PLAN.md) - Complete (`deque(f, maxlen=20)` iterated all 74 MB of a transcript to keep 20 lines, in the path that runs during a deny/re-fire loop; a new QA check bans the shape repo-wide rather than patching the instance)

- [00230: plan-qa reported clean for what it never examined](Completed/00230-plan-qa-lint-false-clean-and-sweep-parity/PLAN.md) - Complete (the tree reported clean while holding 13 violations, 11 of them BLOCK; `--lint` certified any target it could not classify, and every document-level rule was write-time only, so nothing predating a rule was ever re-examined)

- [00229: QA report count implies reachable detail](Completed/00229-qa-report-count-implies-detail-guard/PLAN.md) - Complete (a report may claim a non-zero count and show nothing; the guard now binds every report's printed `jq` hint to a real detail array, and the artifact reports its own inconsistency at render time — which also surfaced two LIVE cases where a QA script recorded WHY it could not run and nothing ever showed it)

- [00228: prose guard for text-matching handlers](Completed/00228-prose-guard-for-text-matching-handlers/PLAN.md) - Complete (a recurring class — handlers denying text that NAMES their trigger vocabulary — now has a default-in-scope guard with reasoned exemptions; it surfaced three handlers on its first run, of which one was the real `pipe_blocker` quoted-heredoc defect, one a bug in the guard, and one correct behaviour)

- [00227: plan_number_helper matches text, not commands](Completed/00227-plan-number-helper-matches-text-not-commands/PLAN.md) - Complete (denied four legitimate housekeeping commands including a plain `echo` of English prose; shell literals are now blanked for the two rules that misread them, and a plan-dir reference naming ONE specific plan no longer arms the sort-and-truncate rule)

- [00226: QA runner discards failing test identities](Completed/00226-qa-runner-discards-failing-test-identities/PLAN.md) - Complete (a red QA run reported how many tests failed and never which, so diagnosis needed a full re-run; the text-fallback parser now names them, and Decision 2 records that the count/detail split is structural across every check rather than a pytest quirk)

- [00225: dismissive/hedging detectors use-mention false positive](Completed/00225-dismissive-hedging-detectors-use-mention-false-positive/PLAN.md) - Complete (substring matching could not tell a phrase USED to deflect from one MENTIONED while acknowledging, so the advisory's own instruction to acknowledge re-triggered it; quoted spans are now blanked before matching, at all four scan sites)

- [00224: nitpick offset reset replays whole transcript after daemon restart](Completed/00224-nitpick-offset-reset-replays-whole-transcript-after-daemon-restart/PLAN.md) - Complete (in-memory audit offset returns to 0 on restart, so a mandated restart replayed every past finding — 9,680 messages measured live; fixed by the daemon's own start time, and gated registry-wide so a future pseudo-event cannot inherit it)

- [00221: pipe blocker producer attribution and per-pipe evaluation](Completed/00221-pipe-blocker-command-substitution-producer-attribution/PLAN.md) - Complete (three bypasses, one root cause: the handler judged the whole command rather than each pipe, so a whitelisted outer command, a cheap earlier pipe, or an unrelated tail -f each laundered an expensive producer)

- [00216: plan duplicate source detection](Completed/00216-plan-duplicate-source-detection/PLAN.md) - Complete (a deterministic citation rule was measured out of existence in Phase 1, so this ships a namespaced read-only dedupe sub-agent instead; judgement verified correct across six real dispatches, self-reported coverage measured as unreliable and documented as such rather than tuned toward a guarantee the plan had declined)

- [00222: pipe blocker message redaction overbreadth](Completed/00222-pipe-blocker-message-redaction-overbreadth/PLAN.md) - Complete (the `-m` value blanking fired on any command and on double-quoted values the shell *does* substitute, so an executing pipe hid inside a commit message; the "double quotes execute" fact now has one home)

- [00223: standing subagent authorisation and system prompt overrides](Completed/00223-standing-subagent-authorisation-system-prompt-overrides/PLAN.md) - Complete (a project can now record a standing request in config and have it replayed each prompt; the mechanism ships on and every authorisation ships off, so the daemon never asserts consent nobody gave)

- [00203: advisory handler CLAUDE.md guidance coverage](Completed/00203-advisory-handler-claude-md-guidance-coverage/PLAN.md) - Complete (all six audit findings were correct as `None`; the two real gaps were a PostToolUse *blocking* handler and a Stop handler whose twin was covered, so the release-time sweep is replaced by a coverage gate that forces a reasoned verdict per handler)

- [00220: stale exclusion audit in qa suppression files](Completed/00220-stale-exclusion-audit-in-qa-suppression-files/PLAN.md) - Complete (a suppression file was only ever read to REMOVE findings, so nothing asked whether each entry still earned its place. An exclusion matching nothing is now a violation — it means the entry drifted off its target or its code was fixed. Found 6 dead entries on first run.)

- [00219: git commit message backtick substitution guard](Completed/00219-git-commit-message-backtick-substitution-guard/PLAN.md) - Complete (backticks in a double-quoted `-m` are EXECUTED by bash, not quoted, and the commit still succeeds — so the text vanishes silently, as it did in cc7dddc0. Blocking, justified by measurement: the rule would have fired on none of the 120 backticked messages in this repo's history.)

- [00218: plan index row length fast loop](Completed/00218-plan-index-row-length-fast-loop/PLAN.md) - Complete (inverse DBF — the batch guard existed and the fast one did not: the 500-char index row cap lived only in a pytest test, so the feedback loop was a full-suite run. Now an `index-row-length` check on all three `plan_qa` surfaces, reading the same single constant the test reads.)

- [00217: supervisor deployed into client owned path](Completed/00217-supervisor-deployed-into-client-owned-path/PLAN.md) - Complete (the report's premise was wrong: `ruff --isolated` passes the supervisor clean; its findings need `BLE`/`DTZ` selected. So the fix is the ownership boundary, not the rules — a DAEMON-OWNED banner on each deployed asset, a manifest, client docs, and a guard keeping them default-clean.)

- [00213: planlib plan folder orchestrator tooling](Completed/00213-planlib-plan-folder-orchestrator-tooling/PLAN.md) - Complete (adopts a client project's `planlib` bash library behind a `plan_workflow.scripts` block shipping OFF, deployed through the same seam as `mkplan.bash`. `root_marker` is deliberately defaultless and `.git` is rejected as a marker, since `.git` is the walk's boundary. Supersedes Plan 00199.)

- [00215: readme repositioning guardrails not hook tooling](Completed/00215-readme-repositioning-guardrails-not-hook-tooling/PLAN.md) - Complete (README now answers "why guardrails?" before "why a daemon?", and states the incident the project exists to prevent. Every number re-measured rather than carried over — three of the request's own figures were wrong. The origin story stayed BLANK until the maintainer supplied the facts, rather than being invented.)

- [00214: magic number scanner blindness](Completed/00214-magic-number-scanner-blindness/PLAN.md) - Complete (DBF: Core Standard 9 bans magic strings **and numbers**, but `check_magic_values.py` implemented only string-shaped rules, so `magic_values: 0 violations` had always meant "half the standard was checked". Identity/index numerics measured at 61% of literals and left unenforced, with the standard reworded rather than overclaiming.)

- [00207: ban squash merge to preserve ancestry](Completed/00207-ban-squash-merge-preserve-ancestry/PLAN.md) - Complete (measurement widened this from "ban squash" to "mandate ancestry-preserving merges": a rebase merge severs ancestry identically, and only a merge commit preserves it. Both stop a branch's commits ever becoming ancestors of the target, so `git branch -d` refuses permanently. 10/10 spellings verified through the production forwarder post-merge.)

- [00212: generic command hint handler](Completed/00212-generic-command-hint-handler/PLAN.md) - Complete (one config-driven PostToolUse handler mapping command patterns to hints, rather than a handler per command; TTL cooldown per (session, hint), extend-or-replace project config. Live-verified post-merge: fires on `agent-browser`, and three repeat probes were all suppressed.)

- [00211: plan-size guidance missing extract remedy](Completed/00211-plan-size-guidance-missing-extract-remedy/PLAN.md) - Complete (adds EXTRACT — relocate durable detail into a named supporting doc — as a third, first-listed remedy for oversized plans, and teaches `plan-shrink-without-journal` that a staged new `.md` in the plan folder is relocation, not deletion. The concept existed in the daemon's own internal docs and had never shipped to clients.)

- [00208: comment changelog and size handlers](Completed/00208-comment-changelog-and-size-handlers/PLAN.md) - Complete (blocks `Prior <version>:`/dated entries in comments; caps comment length with plan-doc-size-style tiering. A whole-repo self-scan demoted 3 of 5 planned blocking signals to advisory after measuring real false positives.)

- [00206: safe branch delete deterministic proof](Completed/00206-safe-branch-delete-deterministic-proof/PLAN.md) - Complete (`hooks-daemon delete-branch`: four tiers proven cheapest-first on blob identity, never path presence, since a rewrite leaves no ancestor route for `git branch -d`. `unproven` abandonment is human-gated at an interactive terminal.)

- [00202: Sensitive content git metadata surfaces](Completed/00202-sensitive-content-git-metadata-surfaces/PLAN.md) - Complete (contents and paths were 2 of the 7 surfaces cleaning this repo's history had to touch; the other 5 are git metadata — commit messages, author identity, tag/branch names, tag messages — all entering via Bash, which `matches()` rejected outright. Each surface now carries both a write-time and a batch guard, exercised in a 7×2 matrix.)

- [00201: Sensitive Content Secret-Word Blocking](Completed/00201-sensitive-content-secret-word-blocking/PLAN.md) - Complete (guard against recurrence of the ~160-place employer/client identifier leak found by the presentation-quality audit; five leak vectors closed, not the four scoped, and the live dogfood confirms the term reaches no log or capture.)

- [00200: QA Gate Integrity and Dogfooding False Positives](Completed/00200-qa-gate-integrity-and-dogfooding-false-positives/PLAN.md) - Complete (began as "a QA gate reports PASSED while checking nothing" and ended having found 11 handler defects, two of them live bypasses rather than the false positives the brief anticipated; durable outcome is the guards, not the fixes.)

- [00198: Installer Self-Destroying Symlink Fix](Completed/00198-installer-self-destroying-symlink-fix/PLAN.md) - Complete (presentation-quality audit found two git-tracked symlinks with absolute, author-local `/workspace` targets, one self-referential and dangling right now.)

- [00197: Journal Day-File Today-Only Guard](Completed/00197-journal-dayfile-today-only-guard/PLAN.md) - Complete (cheap journal hygiene, automated: a Write/Edit targeting a plan `JOURNAL/NNNNN-Journal-YY-MM-DD.md` day-file dated anything other than TODAY -- including yesterday -- is now BLOCKED, closing the …)

- [00196: `absolute_path` acceptance tests assert an unreachable premise](Completed/00196-absolute-path-acceptance-tests-stale-premise/PLAN.md) - Complete (raised by the v3.51.0 acceptance gate and fixed immediately after the release per RELEASING.md "Never Drop Findings".)

- [00194: `bin/hooks-daemon` targets a daemon by CWD, not by its own anchor](Completed/00194-wrapper-cwd-vs-anchor-daemon-targeting/PLAN.md) - Complete (the **behaviour** half of the Plan 00192 wrapper; the documentation half shipped in 00193.)

- [00193: Extend the `$PYTHON` guidance sweep to living docs](Completed/00193-python-var-guidance-sweep-living-docs/PLAN.md) - Complete (follow-up to Plan 00192, raised by the v3.50.0 release code-review gate and tracked rather than dropped per RELEASING.md "Never Drop Findings".)

- [00192: Replace `$PYTHON` guidance with real bash wrapper UX](Completed/00192-python-invocation-ux-bash-wrappers/PLAN.md) - Complete (diagnosed from a real misdiagnosis: an agent reported plan QA as "not installed" when it was fully functional.)

- [00130: Plan-Scaffolding Script Distribution (`mkplan.bash`)](Completed/00130-plan-scaffolding-script-distribution/PLAN.md) - Complete (closed out during Plan 00190 housekeeping after a `staleness-nag` sweep finding surfaced it 42 days quiet: every task and success criterion was already ticked and the work had shipped in **v3.23.0** …)

- [00190: PLAN-vs-JOURNAL separation & tiered plan size enforcement](Completed/00190-plan-journal-separation-and-size-enforcement/PLAN.md) - Complete (agents conflate `PLAN.md` with `JOURNAL/`, appending narrative into the plan until it exceeds 100 KB.)

- [00188: Hook event semantic response audit](Completed/00188-hook-event-semantic-response-audit/PLAN.md) - Complete (Plan 00170 gave **structural** hook coverage — every event dispatchable with a `{}` fail-open passthrough — but never verified each event's *semantic* response contract.)

- [00187: Socket discovery split-brain — CLI reconciliation](Completed/00187-socket-discovery-split-brain-cli-reconciliation/PLAN.md) - Complete (field report `FIELD-REPORT-socket-mixup-upgrade.md`: after a v3.47→v3.48 upgrade, `status`/`health`/`restart` reported `NOT RUNNING` while hooks fired fine, because a stale git-tracked …)

- [00186: Review follow-ups from Plan 00185 (DRY + hardening)](Completed/00186-review-followups-plan-00185-dry-hardening/PLAN.md) - Complete (closed the loop on the 3 non-blocking findings from the v3.48.0 code-review gate per RELEASING.md "Never drop a finding".)

- [00185: Installer/Upgrade settings.json SSoT reconciliation + plan-workflow provisioning](Completed/00185-installer-upgrade-settings-ssot-and-plan-provisioning/PLAN.md) - Complete (root-caused + fixed the session-start "Missing hook registration for {Event}" flood on installed/upgraded projects: settings.json hook reconciliation was neither SSoT-derived on every path nor …)

- [00184: venv accounting is symlink-aware and protects the live venv](Completed/00184-venv-accounting-symlink-aware/PLAN.md) - Complete (live dogfooding data-loss incident: `prune-venvs --legacy --force` deleted the venv the running daemon + hook forwarders were actually using, because `untracked/venv-py311-66bbc57c` was a **symlink** …)

- [00183: Supervisor dry-run fires once per session](Completed/00183-supervisor-dry-run-fire-once/PLAN.md) - Complete (live dogfooding bug: in **dry-run** mode the ccy PTY supervisor looped, re-emitting "would send [esc]" / "compact suggestion fired" markers on every tick and flooding the session with fake prompts.)

- [00181: disk usage time bomb audit](Completed/00181-disk-usage-time-bomb-audit/PLAN.md) - Complete (audit confirmed a systemic pattern: many `untracked/` writers grew unbounded with NO retention primitive anywhere in the codebase.)

- [00182: supervisor compact stacking / double-inject](Completed/00182-supervisor-compact-stacking-double-inject/PLAN.md) - Complete (live dogfooding bug: the ccy PTY supervisor injected TWO `/compact` commands back-to-back — the second no-op'd with "Not enough messages to compact." Code-VERIFIED root cause (review sub-agent + …)

- [00180: supervisor injection cap — reset on successful compaction](Completed/00180-supervisor-injection-cap-lifetime-reset/PLAN.md) - Complete (dogfooding bug caught live on a ~6.5h production session via its `decision.log`: the ccy PTY supervisor stopped driving `/compact` at CRITICAL context, logging \`noop: injection cap reached …)

- [00179: git upstream — drop auto-prune, add gone-branch advisory](Completed/00179-git-upstream-no-autoprune-gone-branch-advisory/PLAN.md) - Complete (follow-up to 00178: a session-start handler must never do anything potentially lossy automatically.)

- [00178: git upstream sync checker (fetch + pull policy on session start)](Completed/00178-git-upstream-sync-checker/PLAN.md) - Complete (new `SessionStart` handler `git_upstream_checker`: on new sessions runs a full `git fetch --all --prune`, computes ahead/behind vs `@{upstream}`, then applies a configurable `mode` — `warn` (default …)

- [00177: Stop hook false "daemon not running" on long sessions](Completed/00177-stop-hook-transcript-timeout-false-daemon-down/PLAN.md) - Complete (downstream field report, verified upstream at v3.44.0 and fixed TDD-first.)

- [00173: Supervisor Ctrl+Z guard + status-line message channel](Completed/00173-supervisor-ctrlz-guard-and-status-message/PLAN.md) - Complete (neutralises the Ctrl+Z-suspends-Claude footgun (upstream anthropics/claude-code#43596): the ccy PTY supervisor strips the `0x1a` SUSP byte from its forwarded stdin so it never reaches Claude's PTY …)

- [00171: supervisor_indicator /proc-scan negative caching](Completed/00171-supervisor-indicator-proc-scan-negative-caching/PLAN.md) - Complete (fast follow-up closing the three non-blocking v3.43.0 release code-review findings per Plan 00157 "never drop a finding".)

- [00169: Prior-Art / SOTA Research and Feature Brainstorm](Completed/00169-prior-art-sota-research-and-feature-brainstorm/PLAN.md) - Complete (pre-release research + ideation pass — no code shipped.)

- [00167: Statusline Wrap & Upgrade Notifier](Completed/00167-statusline-wrap-and-upgrade-notifier/PLAN.md) - Complete (the status line now wraps onto multiple rows on narrow terminals instead of dropping right-hand segments off the edge.)

- [00165: Install Permission Bug Fixes](Completed/00165-install-permission-bug-fixes/PLAN.md) - Complete (two upstream install-path bugs surfaced by a php-qa-ci field report, fixed here TDD-first.)

- [00164: Supervisor lifecycle and upgrade clarity](Completed/00164-supervisor-lifecycle-and-upgrade-clarity/PLAN.md) - Complete (shipped as **v3.41.0** (MINOR), all 7 phases in one release. (1) truthful upgrade transition messaging — client upgrades read the venv `.daemon-version` stamp so they report the real installed→target …)

- [00157: Review Followups — Perf Wave](Completed/00157-review-followups-perf-wave/PLAN.md) - Complete (closes the loop on the v3.38.0 release-review findings so no review value is lost as tech debt.)

- [00156: Performance Tuning Wave 2 — drop `jq`, slim `init.sh`](Completed/00156-performance-tuning-wave-2-drop-jq-slim-init/PLAN.md) - Complete (`Themes: performance`; Wave 2 off Plan 00154, the forwarder-side wins.)

- [00155: Performance Tuning Wave 1 (daemon-side, safe)](Completed/00155-performance-tuning-wave-1-daemon-side/PLAN.md) - Complete (`Themes: performance`; first implementation wave off Plan 00154 — pure-Python daemon-side wins, no transport-contract risk.)

- [00154: Daemon Performance — Rust vs Python Research](Completed/00154-daemon-performance-rust-vs-python-research/PLAN.md) - Complete (research-only, delegated to a Fable agent; five write-ups + reproducible benchmark harness/results in-folder.)

- [00153: Plan-QA Extensible Root Files](Completed/00153-plan-qa-extensible-root-files/PLAN.md) - Complete (additive `plan_workflow.qa.extra_root_files` allowlist threaded through `QaPolicy` → `PlanTree.scan` so clients can permit a legitimate non-plan file such as a sourced `_planlib.bash` at the plan …)

- [00152: Supervisor Graduated Compaction Bands](Completed/00152-supervisor-graduated-compaction-bands/PLAN.md) - Complete (split the ccy supervisor's compaction into three context bands — lower red `[red,mid)` waits for child output to settle before `/compact` (restores pre-00151 "blocked whilst busy"), elevated …)

- [00151: Supervisor tick starvation + CRITICAL tier](Completed/00151-supervisor-tick-starvation-and-critical-tier/PLAN.md) - Complete (fixed ccy supervisor `on_poll` starvation during child output streaming so context can no longer climb past red unchecked; added a CRITICAL tier above red — 200k ≥90%, 1000k ≥60% — surfaced as a …)

- [00150: Client-configurable exclude_paths for content-scanning blockers](Completed/00150-client-configurable-exclude-paths-for-content-blockers/PLAN.md) - Complete (shared stdlib glob-exclusion utility wired into security_antipattern / qa_suppression / error_hiding_blocker + project-wide `daemon.exclude_paths`; error_hiding_blocker gains sibling default skips …)

- [00149: ccy Supervisor — Sidecar Path + Empty-Box Guard](Completed/00149-ccy-supervisor-sidecar-path-and-empty-box/PLAN.md) - Complete

  - Two High-severity supervisor bugs surfaced once v3.34.0 made the ccy supervisor run in clients.

- [00148: ccy Supervisor Arm on Deploy](Completed/00148-ccy-supervisor-arm-on-deploy/PLAN.md) - Complete

  - Made the v3.33.0 ccy supervisor auto-deploy actually work end-to-end. v3.33.0 copied `claude-supervise.py` but never **armed** it (never wrote the `CCY_CLAUDE_WRAPPER` export the launcher sources) …

- [00147: ccy Supervisor Auto-Deploy](Completed/00147-ccy-supervisor-auto-deploy/PLAN.md) - Complete

  - Config-gated auto-deploy of the Plan 00135 PTY supervisor (`claude-supervise.py`) into a project's `.claude/ccy/` on install/upgrade.

- [00146: Hard-block rhetorical continue questions in explained stops](Completed/00146-stop-hard-block-rhetorical-continue/PLAN.md) - Complete

  - Dogfooding fix from live evidence: `auto_continue_stop` Branch 2 (`STOPPING BECAUSE:` -> ALLOW) short-circuited before confirmation-question detection, so rhetorical "want me to build slice 2 next?" …

- [00143: Loud Project-Handler Load-Failure Alert](Completed/00143-loud-project-handler-load-failure-alert/PLAN.md) - Complete

  - Closed a silent fail-open on the observability axis: when a project handler under `.claude/project-handlers/` fails to load (e.g. an upgrade made `get_claude_md` required and an older handler …

- [00142: Background-Shell Harvester & Root-Recursion Guard](Completed/00142-background-shell-harvester-and-root-recursion-guard/PLAN.md) - Complete

  - Two-layer defence from a post-incident report (an orphaned `ugrep -rl … /` ran ~115 min at >1000% CPU, surviving a compaction).

- [00141: `release-notes` CLI subcommand + skill route](Completed/00141-release-notes-subcommand/PLAN.md) - Complete

  - New `release-notes` daemon CLI subcommand + `/hooks-daemon release-notes` skill route (Plan 00141).

- [00140: Deep Code Review & Fix (Workflow-Orchestrated)](Completed/00140-deep-code-review-fix-workflow/PLAN.md) - Complete

  - Dynamic-Workflow deep review of the daemon source: 13 Opus reviewers + adversarial Opus verification → **101 findings, 77 confirmed** (`FINDINGS.md`).

- [00139: Failsafe Recovery Cron](Completed/00139-failsafe-recovery-cron/PLAN.md) - Complete

  - New opt-in `recovery_cron_advisor` PostToolUse handler: across a plan's lifecycle (create → progress → complete) it prompts the agent to run a **non-durable hourly failsafe recovery cron** that …

- [00138: Fix Plan-Number Handler False Positives](Completed/00138-plan-number-helper-false-positives/PLAN.md) - Complete

  - TWO plan-number handlers wrongly fired on a SPECIFIC, already-known plan folder (same disease).

- [00137: Install/Upgrade SSoT + KISS Audit & Remediation](Completed/00137-install-upgrade-ssot-kiss-audit/PLAN.md) - Complete

  - Remediated all six remaining findings from the Opus SSoT/KISS audit spawned by 00136.
  - Delivery commits `defe9fb`, `faa53e2`, `026dde9`, `18c4a65`, `d5c95cd`, `a7ef263`. The plan-workflow opt-in flip is a behaviour change — staged `config-changes`/`truth-changes` manifests under `UNRELEASED/` for the next release. 13/13 QA

- [00136: mkplan deployment driven by config SSoT](Completed/00136-mkplan-deploy-config-ssot/PLAN.md) - Complete

  - Fixed a v3.24.0 field bug (client `client-a-infra`): `mkplan.bash` (Plan 00130) was only deployed by `install_version.sh` behind the opt-in `PLAN_WORKFLOW=yes` and never deployed on upgrade, while …
  - Shipped in **v3.25.0** (release commit `a6f0717`, tag `v3.25.0`). Spawned the Opus SSoT/KISS audit → remaining findings tracked in Plan 00137

- [00134: Format CLAUDE.md After Handler-Guidance Injection](Completed/00134-format-claude-md-after-injection/PLAN.md) - Complete

  - Extracted the mdformat+gfm transform into `utils/markdown_format.format_markdown_text` (SSoT) and pointed the `markdown_table_formatter` handler, the `format-markdown` CLI, and `ClaudeMdInjector` at it (removed two duplicate copies)
  - The injector now formats CLAUDE.md after writing its `<hooksdaemon>` block (fail-safe; content-loss guard runs on the pre-format replace result), so a later edit no longer churns the injected block.

- [00133: Suggest Enabling New Features on Upgrade](Completed/00133-suggest-enabling-new-features-on-upgrade/PLAN.md) - Complete

  - Revived/strengthened/wired the abandoned config-changes upgrade advisory so upgrades actively recommend enabling dormant opt-in features (`recommended`/`dormant`/`recommended_value`; `changed`-value …
  - Added `Handler.get_default_enabled()` opt-in/opt-out SSoT (concrete, drift-guarded against the template); flipped `allow_untracked_claude_memory` default `true→false` (opt-out, with `critical` …
  - Shipped in **v3.24.0** (release commit `8248c40`, tag `v3.24.0` = `18caf51`)

- [00128: Lean SessionStart — silent-when-healthy + verbose `check` command](Completed/00128-lean-session-start/PLAN.md) - Complete

  - SessionStart printed ~80 lines every session (40-line dogfooding reminder, container banner, "all good" status lines).
  - `git_filemode_checker` + `hook_registration_checker` now emit only on problems; `optimal_config_checker` suppresses its 6-setting audit at session start (keeps silent settings-sync) …
  - New `cli check` subcommand + `/hooks-daemon check` skill sub-command surface the full verbose env/config audit (output tokens, bash working dir, container runtime, git fileMode, hook registration) on …
  - A fresh in-container SessionStart dropped from ~80 lines to 2. QA 13/13 (8628 tests, 95.1%); daemon RUNNING; live-verified both directions. Commits `4344d46` (Phase 1), `5490f24` (Phase 2), `a8fe650` (format)

- [00127: Parallel-Session Daemon Isolation & Reuse (+ LXC detection)](Completed/00127-parallel-session-daemon-isolation/PLAN.md) - Complete

  - Fixed the parallel-session bug (user report): multiple Claude Code processes sharing one `(hostname, project root)` — e.g. several agents in a single LXC container — fought over the daemon socket …
  - REUSE fix (Decision 1) across all layers: `init.sh` stops removing a live socket; `cli.cmd_start` runs a three-state liveness gate (LIVE/NOT_LIVE/INDETERMINATE) FIRST and reuses a live-or-busy …
  - LXC/LXD detection (Phase 4): cgroup-v2-safe via `/run/systemd/container` + `container=lxc` env + cgroup-v1 token + `/dev/lxd/sock` (no subprocess); 🧊 status icon; desktop invariant (Plan 00126) preserved
  - Two ultracode workflows (spec → TDD → QA → adversarial review); review caught 5 real bugs, all fixed. QA 13/13 (8617 tests, 95.1%); daemon restart + live parallel-start test verified. Commits `0176767` (lifecycle), `75c755c` (LXC)

- [00126: Container-detection conflation fix + status-line env indicator + memoisation](Completed/00126-statusline-env-indicator-and-memoisation/PLAN.md) - Complete

  - Root cause: container detection scored the tautological `CLAUDECODE=1` / `CLAUDE_CODE_ENTRYPOINT=cli` signals as container evidence — but this daemon ONLY runs under Claude Code, so those are always true and classified every desktop session as a container
  - Rewrote `container_detection` around three honest, separated predicates: `running_under_claude_code()`, `is_yolo_sandbox()`, and `detect_container_runtime()` / `in_container()` (honest OS markers …
  - New `EnvironmentIndicatorHandler` (status priority 11) shows 💻 desktop / 🐳 docker / 📦 podman, reading the runtime cached ONCE on `ProjectContext` at daemon startup — no per-render probing
  - Memoisation: container fact via `ProjectContext` startup cache; new shared `settings_reader` (mtime-cached) ends the `model_context` + `thinking_mode` double-parse of `~/.claude/settings.json`. …
  - QA 13/13 (8561 tests, 95.1%); daemon restarts RUNNING; live status line renders `📦 podman`

- [00125: Auto-detect containers → uv copy mode](Completed/00125-uv-container-copy-mode/PLAN.md) - Complete

  - Follow-up to v3.19.1: container installs/upgrades printed the `uv hardlink failed (likely overlay-fs) — retrying with UV_LINK_MODE=copy` warning on every run
  - Root cause: `create_venv_at_path`'s proactive copy-mode detection probed only the TARGET fs type (`overlay`/`nfs`); in a container the target is bind-mounted from the host (a normal fs) while uv's …
  - Fix: added `_uv_in_container` helper (signals: `container` env var, `/run/.containerenv`, `/.dockerenv`; marker paths overridable for tests) and wired it into the `first_link_mode` decision …
  - 4 new tests; QA 13/13 (8543 tests, 95.1%); live-verified detection in the Podman dev container

- [00124: ensure_venv missing project-path slug](Completed/00124-ensure-venv-missing-slug/PLAN.md) - Complete

  - Hotfix: `ensure_venv` (`scripts/install/venv.sh`) computed the venv fingerprint without passing its `daemon_dir`, so the venv was keyed by the bare slug-less `venv-py{MM}-{hash}` instead of the slugged `venv-{slug}-py{MM}-{hash}`
  - A desktop host and a containerised session sharing a bind-mounted project + the same Python (same `sys.version`/`base_prefix`/arch) collided on one venv and fought over it — the project-path slug …
  - Fix: pass `$daemon_dir` to `python_venv_fingerprint`; broadened the venv-discovery glob in `scripts/upgrade.sh` and four acceptance tests from `venv-py*` to `venv-*py3*` (matches both slugged and …
  - 1 new isolation test in `test_ensure_venv.py`; QA 13/13 (8539 tests, 95.1%); daemon RUNNING

- [00123: macOS Portability Follow-ups](Completed/00123-macos-portability-followups/PLAN.md) - Complete

  - Discovered during v3.19.0 release prep by a dedicated macOS-gotcha hunt agent — four further BSD/bash-3.2 incompatibilities Plan 00122 did not cover
  - **BUG 1 (critical)** — `init.sh` ran `_abs_project_path=$(realpath "$PROJECT_PATH")` under `set -euo pipefail` on every hook; `realpath` is absent on macOS < 12.3 so the substitution aborted every hook. The variable was dead → deleted
  - **BUG 2 (high)** — `resolve_venv.sh` hot-path cache used GNU `stat -c %Y` (sourced by init.sh per hook); returned empty on macOS so the cache never hit → 50-100ms Python fingerprint spawn every hook.
  - **BUG 3 (medium)** — `daemon_control.sh` used GNU BRE `\|` alternation in `pgrep -f` AND `grep -qi`; BSD treats it literally so neither matched on macOS.
  - **BUG 4 (medium)** — `hooks_deploy.sh` self-install short-circuit used `readlink -f` (no `-f` on BSD) → never fired on macOS; replaced with bash `-ef` (same-inode) operator
  - Repo-wide sweep confirmed no other executable `\|`, `readlink -f`, unguarded `stat -c`, `date -d`, `base64 -w`, `grep -P`, or `sed -i` in shell scripts.

- [00122: macOS Portability Fixes](Completed/00122-macos-portability/PLAN.md) - Complete

  - Downstream macOS field report (`untracked/mac-issues/`): the daemon was non-functional on macOS; six bugs reproduced and fixed (not yet released)
  - **BUG 1 (critical)** — when `$HOSTNAME` is unset (default on macOS/zsh, minimal containers), BOTH the Python daemon (`paths.py`) and the bash forwarder (`init.sh`) derived the runtime-file suffix …
  - **BUG 2** — `venv.sh` `stat -f -c %T` fs probe is GNU-only; now gated on `uname -s = Linux` (overlayfs is Linux-only), no stray BSD error
  - **BUG 3** — skill `install.sh` "already installed" guard now health-checks (venv python imports) and auto-escalates a broken dir to `--force` repair instead of bailing
  - **BUG 4** — `health-check.sh` EXIT trap makes silent non-zero exits honest; `debug_info.py` detects the client project root (not the daemon clone) and degrades gracefully (dumps runtime files/venv/processes) when init.sh detection fails
  - **BUG 5/6** — docs reconciled (CLAUDE.md Hostname-Based Isolation); user-facing scripts confirmed bash-3.2 clean (lone `mapfile` in dev-only `run_shell_check.sh` de-bash-4'd), with a regression-guard test scanning all repo shell scripts
  - bash↔Python suffix parity test pins the end-to-end fix; QA 13/13 (8527 tests, 95.1%); daemon RUNNING. Delivery commits `8d72594`, `e71df0c`, `28745d2`, `ec27240`, `a48dcb0`

- [00121: Additive extra_allowed_markdown_paths](Completed/00121-additive-markdown-paths/PLAN.md) - Complete

  - New `extra_allowed_markdown_paths` option for `markdown_organization`: additive allowed-location patterns layered on top of the built-in defaults (and over the legacy `allowed_markdown_paths` …
  - Generalised `is_adhoc_instruction_file` to allow all markdown inside `.claude/skills/` (not just `SKILL.md`); `.claude/rules/` already covered (commit 38d7d5d)
  - Dogfooded by migrating this repo's own config from a 17-pattern override to a 2-entry additive list; docs (HANDLER_REFERENCE, per-handler doc, get_claude_md, init_config installer comment) updated to prefer additive
  - Staged a post-upgrade-task + truth-change (anticipated v3.19.0) so upgrading projects migrate override → additive
  - 13 new unit tests; full QA 13/13 (8508 tests, 95.1%); live daemon probe verified allow/deny behaviour

- [00120: Git Hooks Executable Fixer Handler](Completed/00120-git-hooks-executable-fixer/PLAN.md) - Complete

  - New `GitHooksExecutableFixerHandler` (PostToolUse, priority 27, non-terminal): detects git's `hint: The '...' hook was ignored because it's not set as executable` in Bash output and auto-remediates it
  - Resolves the active hooks dir via `git rev-parse --git-path hooks` (worktree/`core.hooksPath` safe) and `os.chmod`s every non-`.sample`, non-executable hook with least-privilege exec bits (execute …
  - 23 unit tests, 100% handler-file coverage; full QA 13/13; live socket test verified 644 → 755 on a real pre-push hook through the running daemon

- [00119: Scope Single-Daemon Enforcement to Actual Daemon Server Processes](Completed/00119-enforcement-scope-to-daemon-server/PLAN.md) - Complete

  - Root-cause follow-up to the v3.18.2 "exit 143" upgrade false-failure: `find_all_daemon_processes` matched **any** `claude_code_hooks_daemon` cmdline, so single-daemon enforcement could SIGTERM …
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
  - **G1+G3**: every PreToolUse DENY now appends a warning that batched siblings were cancelled and must be re-issued separately (`core/hook_result.py` `_DENY_CONTINUATION_SUFFIX`), replacing the old "do …
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
  - Extracts the git-config access introduced in Plan 00112 into a reusable SOLID `GitRepo` value object (`utils/git_repo.py`): `resolve_for(path)`, `read_config(key)`, `write_config(key, value)` over …
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
  - **Phase 1** — Layer 1 `scripts/upgrade.sh` emits 10-field `UPGRADE_METADATA` block (sentinels `<<<UPGRADE_METADATA` / `UPGRADE_METADATA>>>`) on every successful upgrade; agent parses block and writes …
  - **Phase 2** — Skill-pushed `scripts/upgrade.sh` collapsed from ~280 lines of frozen logic to a ~23-line thin shim that walks for `.claude/hooks-daemon.yaml`, fetches the canonical script from …
  - **Phase 3** — Skill `upgrade.md` rewritten as 5-step agent workflow (run upgrade, parse metadata, verify RUNNING, stage daemon-owned paths only, commit with metadata in body)
  - **Phase 4** — Four new acceptance gates: `test_upgrade_metadata_emission.py`, `test_skill_upgrade_shim.py`, `test_upgrade_md_metadata_contract.py` (4 sub-tests), `test_skill_upgrade_end_to_end.py` …
  - **Phase 5** — MINOR release v3.15.0 published with all 5 release artifacts (`upgrade.sh`, `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh`, `bootstrap-checksums.txt`); manifest verified consistent
  - Long-term review of pull-from-`main` source vs `releases/latest/download` tracked in [gh issue #31](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/31)

- [00101: Recap-Stoppage Investigation](Completed/00101-recap-stoppage-investigation/PLAN.md) - Complete

  - Re-opened post-v3.13.0 after silent stop recurred with `preventedContinuation: false, level: suggestion` — same signature Phases 5/6/7 thought they had closed
  - **Phase 9** (commit `f08a2ff`) — bash wrappers `.claude/hooks/stop` and `.claude/hooks/subagent-stop` now translate daemon JSON `decision: block` into exit code 2 + reason on stderr (the contract …
  - **Phase 10** (commit `4c2688f`) — `SocketLimit.REQUEST_BUFFER_BYTES = 16 MiB` passed as `limit=` kwarg to `asyncio.start_unix_server` in `server.py`; eliminates \`LimitOverrunError("Separator is …
  - Closes the suggestion-level delivery gap and the PostToolUse separator-error class — both regression vectors that landed silent stops on top of Phases 5/6/7's `tool_use_error` Branch 2.5

- [00107: Batch Delivery Meta Plan — v3.12.0 Release Bundle](Completed/00107-batch-delivery-meta/PLAN.md) - Complete

  - Six-wave audit-and-close of the v3.x backlog shipped as v3.12.0 in commit `6c5c869`
  - **Closed in bundle**: 00063, 00077, 00081 (Superseded by 00082), 00086, 00089, 00096, 00099, 00101, 00106
  - **Residue Scope**: 00100 (Phases 0–3.9 shipped; 3.5/4/5/6 deferred to v3.13.0)
  - **Deferred**: 00085 (reminder pseudo-event system — 8-phase fresh-TDD scope, future release)

- [00063: FAIL FAST — Plugin Handler Bug & Error Hiding Audit](Completed/00063-fail-fast-plugin-handler-audit/PLAN.md) - Complete (Already Shipped)

  - Phase 1 (plugin handler suffix bug + crash-on-misconfigured-handler) delivered in original sprint
  - Phases 2–5 audited and found already-shipped during Plan 00107 Wave 2: `scripts/qa/audit_error_hiding.py` + `error_hiding_exclusions.json`; `error_hiding` registered as one of the 12 QA gates; live …
  - Closed out without further code action

- [00096: Live Daemon Smoke Tests in QA Stack](Completed/00096-live-daemon-smoke-tests/PLAN.md) - Complete (Already Shipped)

  - Delivered in commit `bce66248` — pre-dated Plan 00107 Wave 2 audit
  - `scripts/qa/run_smoke_test.sh` (3 probes: Stop no-explanation, Stop loop-guard, PreToolUse destructive git) + `llm_qa.py` integration + `tests/unit/qa/test_smoke_test.py` all in place
  - Plan 00107 Wave 2 audit confirmed every Phase 1/2/3 task satisfied; closed out without further code action

- [00099: Python-Fingerprint Venv Isolation](Completed/00099-python-fingerprint-venv-isolation/PLAN.md) - Complete (Already Shipped)

  - Every Phase 1–8 deliverable in tree across v3.7.0 / v3.10.0 / v3.11.0: fingerprint-keyed venv paths (`paths.py::project_path_slug` + `python_venv_fingerprint`); `ensure_venv()` auto-bootstrap with …
  - Phase 9 (Release) effectively executed across three releases; "In Progress" status was stale documentation. Closed during Plan 00107 Wave 4 audit.

- [00077: TranscriptReader Enhancement & AskUserQuestion Bug Fix](Completed/00077-transcript-reader-askuser-bugfix/PLAN.md) - Complete (Already Shipped)

  - Phase 1 (`ContentBlock` parsing + `tool_use` content blocks in `core/transcript_reader.py`) delivered in original sprint
  - Phases 2–5 audited and found already-shipped during Plan 00107 Wave 3: `utils/stop_hook_helpers.py` exists; all three Stop handlers (`auto_continue_stop`, `dismissive_language_detector` …
  - Closed out without further code action

- [00086: Plan Redirect System Improvement](Completed/00086-plan-redirect-system-improvement/PLAN.md) - Complete

  - **Handler fix**: `markdown_organization._handle_plan_write` now returns `Decision.ALLOW` (was `DENY`) so Claude Code's flat plan write succeeds and ExitPlanMode displays full plan content to the user for approval
  - **Empirical verification**: `plansDirectory: "./CLAUDE/Plan"` setting in `.claude/settings.json` causes Claude Code to write plans directly to project — proved by `idempotent-chasing-wadler.md` (Apr 10) sitting at the configured directory root
  - **Doc/impl sync**: `handle_planning_mode_write` docstring already said "Returns ALLOW" — Plan 00086 brings impl in line with the documented intent (pre-existing mismatch)
  - **Phase 2 sync check**: `_check_claude_code_sync()` already implemented at line 354 — no action needed
  - **Tests rewritten**: `TestPlanWriteDenyBehaviour` class replaced with `TestPlanWriteAllowBehaviour` (4 tests verifying ALLOW + context messaging for rename/cleanup after approval); integration test …
  - Delivered in Plan 00107 Wave 1

- [00106: Bypass-Permissions-Aware Auto-Approve](Completed/00106-bypass-permissions-aware-auto-approve/PLAN.md) - Complete

  - **Security fix**: `auto_approve_reads` now gates on `permission_mode == "bypassPermissions"` via new shared `utils/permission_mode.py::is_bypass_mode()` — defers to Claude Code's normal approval flow in default/plan/acceptEdits/dontAsk modes
  - **Sibling bug fixed under same umbrella (dogfooding)**: `HelloWorldPermissionRequestHandler` was silently auto-approving every PermissionRequest by emitting `Decision.ALLOW` from a non-terminal …
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

  - TDD enforcement handler now tries multiple candidate test paths (Python `tests/unit/`, PHP PSR-4 mirror, Java `src/test/`, Go co-located, Ruby `spec/`) before blocking, eliminating false positives …

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

- [00174: Status-Line Artefact + Per-Segment Cadence Redesign](Cancelled/00174-status-line-artefact-cadence-redesign/PLAN.md) - Superseded by Plan 00175, which concluded the artefact store is unnecessary because Claude Code's 1s refresh floor caps any benefit a cheaper render could unlock

- [00199: planlib — plan-orchestrator tooling in the daemon](Cancelled/00199-hooks-daemon-plan-lib/PLAN.md) - Superseded

  - Superseded by [00213](00213-planlib-plan-folder-orchestrator-tooling/PLAN.md), which targets the SAME upstream proposal and is the plan being executed. Both were authored independently five days apart and neither referenced the other; 00213 additionally tracks the proposal under version control (`PROPOSAL.md`) rather than pointing at `untracked/`. 00199 was never started, so no work is lost.

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

- **Total Plans Created**: 281 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 230 (includes 1 reduced-scope plan and 5 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 38 (count = root `NNNNN-*` plan folders; includes the 3 upstream-blocked on-hold plans below and several dormant plans awaiting a scheduling/release window)

- **On Hold**: 3 (blocked by upstream Claude Code delegate mode fix)

- **Cancelled/Abandoned**: 6 on disk (count = `Cancelled/` folders: 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00174 superseded by 00175, 00199 superseded by 00213)

- **Folder-to-number reconciliation**: 37 + 230 + 6 = **273 folders**, spanning
  **270 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **10** of the
  280 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258 — abandoned drafts, numbers burned by
  transient probes (00195 during the v3.51.0 acceptance run, 00258 during the
  v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a sub-agent
  that then found Plan 00208 already covered the work). 270 + 10 = 280. ✅

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

# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00344: stop hook deny rate classification](00344-stop-hook-deny-rate-classification/PLAN.md) - Not Started (Plan 00337 Task 5.0 shipped the instrumentation but the classification needs telemetry across many sessions — 49 instrumented rows exist and 48 are acceptance probes, because a real Stop event fires roughly once per session)

- [00329: post upgrade truth changes report bloat](00329-post-upgrade-truth-changes-report-bloat/PLAN.md) - Not Started (the upgrade flow's truth-changes reconciliation hands the agent up to 89KB / 74 entries with no bound and no supersession collapsing, so superseded truths are replayed and the step is skimmed rather than performed)

- [00291: upgrade path hardening and guarded branch install](00291-upgrade-path-hardening-and-guarded-branch-install/PLAN.md) - Not Started (php-qa-ci canary findings: fresh-clone `upgrade_version.sh` hard-fail, UNRELEASED-manifest visibility, silent old-config retention, `v`-prefix handling — plus the owner-ruled guarded, non-obvious, loudly-warned first-party-only branch-install mechanism)

- [00280: workflow agent model cap in standing authorisation](00280-workflow-agent-model-cap-authorisation/PLAN.md) - Not Started (extend the built-in `workflow-orchestration` standing authorisation with a configurable model cap for workflow/sub-agents — default: Sonnet encouraged, Opus as required, Fable banned)

- [00264: cap the size of a GitHub issue/PR comment](00264-github-comment-size-cap/PLAN.md) - Not Started (field report: agent sessions flooded two issues with 44,467- and 22,398-character comments until neither ticket's state was findable by the humans reading it; a PreToolUse cap on `gh` comment bodies steering the content into `JOURNAL/`, plus seven open questions the report's proposed design asserts rather than settles)

### Security / Presentation Audit

### Core / Hook Coverage

- [00170: Universal Hook Coverage + Hook-Support Enforcement](00170-universal-hook-coverage-and-enforcement/PLAN.md) - Dormant (fundamental: intercepting hook events is the daemon's raison d'être, yet only **10 of the 30** documented Claude Code hook events are wired — 20 are silently unwired, so a client project cannot even …)

- [00172: Close the HandlersConfig ↔ wired-events coverage gap](00172-handlerconfig-wired-events-coverage-gap/PLAN.md) - Not Started (follow-up from the `status_line` config-drop fix audit: `HandlersConfig` declares only 11 of 31 wired events, so `_build_handler_config_mapping` would silently drop config for any of the 20 …)

- [00204: security_antipattern — the three data-flow categories](00204-security-antipattern-dataflow-categories/PLAN.md) - Not Started (v3.52.0 corrected guidance that claimed SQL injection, weak cryptography and path traversal were blocked when no strategy implements any of them; this decides whether construct-level regexes can carry signal for them without the false-positive rate that gets a handler disabled.)

### Status Line / Agent View

- [00175: statusline refreshInterval first-class default + startup validation](00175-statusline-refresh-interval-first-class/PLAN.md) - Dormant, part-shipped (root-caused the Ctrl+Z notice lag to `statusLine.refreshInterval: 10` — Claude Code re-runs the status command only on events (Ctrl+Z is not one) plus this optional timer whose minimum is 1s, so an …)

- [00158: Agent Thread Navigation & Status Line](00158-agent-thread-navigation-statusline/PLAN.md) - Dormant (Phase 1 research/dogfood complete; Phases 2–4 waited on Plan 00174's `subagentStatusLine` rendering design, which is now Superseded — the dependency needs re-deciding, not merely re-pointing, since 00175 concluded the artefact store should not be built)

  - Documents the dogfood-verified Claude Code contract for the main `statusLine` and the newer `subagentStatusLine` surfaces; root-causes the "no status line / whose data?" symptoms under Agent View (arrow-key thread navigation)
  - Scopes daemon support for `subagentStatusLine` (per-thread agent-panel rows) plus a `statusLine` `refreshInterval` so the bar stays live while background agents run
  - Confirmed live: main bar payload carries NO agent-thread identity (always renders main session); we wire only `statusLine` today

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

- [00160: Supervisor Foreground Identity & Dead-File Reaping](00160-supervisor-foreground-identity-and-reaping/PLAN.md) - Dormant (00135 follow-up: reap dead sidecars/signals + bind the supervisor to the foreground session; remaining verification needs a live 2-thread Agent-View session that cannot be forced from inside a supervised one)

### Memory / Documentation Policy

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

- Field report from host `host-a` (`untracked/hooks-daemon-upgrade-python-version.md`): skill `install.sh` aborted on default `python3` (3.9.21) and suggested hardcoded `python3.11` despite `python3.13`/`python3.14` being on PATH
- Consolidates four WET Python-discovery implementations (`scripts/upgrade.sh`, `scripts/install/prerequisites.sh`, skill `install.sh`, `daemon/paths.py`) into one canonical bash helper + one canonical python helper
- Replaces hardcoded `(3.13, 3.12, 3.11)` candidate lists with glob `python3.[1-9][0-9]` + numeric sort — Python 3.14+ works the day it ships, no daemon release required
- Error messages must name interpreters **actually observed during the glob**, never hardcoded ones
- Adds Task 5.1 host-a replay to RELEASING.md Step 12.0 H-1 gate (count 19 → 20)

### Handler UX Adjustments

- Dogfooding alert: agent stalled twice asking tautological questions ("Should I push?"); the prefix-positive `ask_user_question_blocker` (Plan 00108 / v3.14.0) was shipped `enabled: false` so it never fired

- Phase 1 DONE: enabled in this project's config, daemon restarted, live probe confirms unprefixed AskUserQuestion is denied with `ASKING BECAUSE:` guidance

- Remaining: flip the shipped install/upgrade default to enabled (G2), regression test pinning the default (G4), upgrade-guide/changelog note (G5)

- Replace always-deny `ask_user_question_blocker` with prefix-positive `ASKING BECAUSE:` policy mirroring the Stop handler's `STOPPING BECAUSE:` convention

- DENY path instructs agent to state assumed-correct answer and proceed (audit log for the watching user)

- Ships `enabled: false`; flip to default-on in follow-up after dogfooding

### Stop-Quality Stack (dependency chain)

- [00085: Reminder Pseudo-Event System with Adaptive Triggers](00085-reminder-pseudo-event-system/PLAN.md) - Dormant (8-phase build deferred to a future release window)

  - 8 phases — AdaptiveTrigger, config parsing, dispatcher, WorkflowReminderSetup, handler, constants/registration, config, verification
  - Dependency chain resolved: 00077 (Already Shipped) and 00081 (Superseded by 00082) both closed in Plan 00107 Wave 3

### Long-Running / Carry-Forward

- [00100 (v3): Venv SSOT Consolidation](00100-venv-ssot-consolidation/PLAN.md) - Dormant (residue scope awaits scheduling; PLAN.md is past the size limit and needs splitting before it can be edited)

  - Phases 0–3.9 **shipped** in v3.9.0 / v3.10.0 / v3.11.0 (canonical SSOT resolver, `.daemon-metadata.json` writers, dead-code removal, path slug, eager upgrade cleanup, H-1 gate coverage)

  - **Residue deferred from v3.12.0** (Plan 00107 Wave 4): Phase 3.5.2–3.5.7 (bootstrap-fallback wiring), Phase 4 (flock concurrency), Phase 5 (parameterised upgrade-cycle test), Phase 6 (docs) …

  - Phases 1–4 complete (`bash <path>` invocation, auto-migration, self-heal, filemode checker)

  - **Task 5.3 pending**: acceptance gate at v3.12.0 release time (folded into meta plan 00107 Wave 6 `/release` execution)

- [00266: AI-assisted handler decisions](00266-ai-assisted-handler-decisions/PLAN.md) - Dormant (native `prompt`/`agent` hooks measured live: they work, fail CLOSED, cost ~1.2s vs the daemon's ~51ms, and cannot override a daemon deny; dynamic prompting via `tool_use_id` is the leading architecture; parked as reference until a revival condition fires)

## Completed Plans

Older completed plans (below the retention window of the 30 highest-numbered) are archived verbatim in [Completed/README.md](Completed/README.md).

- [00363: self-matching process watcher blocker](Completed/00363-self-matching-process-watcher-blocker/PLAN.md) - Complete at `003f3036` and `8ae8ac61` + the archiving commit (a process probe whose literal pattern is in the calling shell's own argv, and a wait on `$!` after `setsid`, are denied; Rules A and C shipped in v3.63.0, Rule B holds a callout for the next release)

- [00330: hooks daemon skill surface coherence](Completed/00330-hooks-daemon-skill-surface-coherence/PLAN.md) - Complete at `bf5da1f5`, `59b11a0a` and `f458057e` + the archiving commit (`optimise` scores every registered handler by a per-handler relevance declaration, one `housekeeping` invocation runs the full pass in a ruled order, the skill routes eight subcommands and documents the rest, and a gate fails when the skill surface drifts from the registry, CLI or schema)

- [00362: client upgrade report — fix all known defects](Completed/00362-client-upgrade-report-fix-all-known-defects/PLAN.md) - Complete + the archiving commit (the stability-release ledger: all eight client findings and every defect recorded in a live plan fixed or ruled out, v3.62.1's missing bootstrap assets repaired, full QA 26/26)

- [00361: supervisor worker crash loop visibility and backoff](Completed/00361-supervisor-worker-crash-loop-visibility-and-backoff/PLAN.md) - Complete at `da5b7258` + the archiving commit (a worker death is logged with its exit code and source fingerprint, a crash loop is held to a backoff and logged once, and the fallback transitions are logged; verified live)

- [00360: pending release notes holding area](Completed/00360-pending-release-notes-holding-area/PLAN.md) - Complete (a plan closes by leaving its callout in `UNRELEASED/release-notes/`, the project-only gate denies a Complete flip without the holding-area criterion, the release folds the callouts in and moves them with an ABORT if any remain, and `release-slate-check` lists them without changing its verdict)

- [00358: a worktree venv can silently test the WRONG source tree](Completed/00358-worktree-venv-tests-wrong-source-tree/PLAN.md) - Complete (a test session now refuses to start when the package resolves outside the invoking checkout, naming both paths and the setup script; the `worktree_create` guidance says a fresh worktree has no venv)

- [00356: secret guard bracket glob false positive](Completed/00356-secret-guard-bracket-glob-false-positive/PLAN.md) - Complete (a bracket expression at a token's edge was read as an open wildcard, so an ordinary jq array subscript was denied; fixed and merged by a worktree sub-agent, whose incidental finding shipped as Plan 00357)

- [00359: the release pipeline checks the slate is clean before it starts](Completed/00359-release-slate-clean-gate/PLAN.md) - Complete at `7f0f6f40`…`268dab5b` + the archiving commit (`release-slate-check` runs as Stage 0 of `/release`: HEAD's exact sha must be CI-green, mid-work plans and unlanded branches stop for a human, and `accept-wip` is the only way to proceed over them)

- [00357: a ValueError escapes glob expansion and fails a security guard open](Completed/00357-glob-expansion-valueerror-escapes-fail-open/PLAN.md) - Complete at `ce95acae` + the archiving commit (`Path.glob` is a generator, so the `ValueError` fired on iteration OUTSIDE the `try` and the quarantine artefact read guard was skipped for the whole tool call; the guard now wraps the consumption, proven by tests that failed pre-fix)

- [00355: supervisor announces every keystroke it sends](Completed/00355-supervisor-announces-every-keystroke-it-sends/PLAN.md) - Complete at `e105530e` + the follow-on supervisor commits and the archiving commit (the ESC injected to flush a stalled compaction was silent; every keystroke the supervisor sends now raises the status-line banner on the tick that sends it, and repeats collapse to a tally like `esc (20), compact (15)`)

- [00354: docs qa stale counterpart index](Completed/00354-docs-qa-stale-counterpart-index/PLAN.md) - Complete at `82bbd550`…`644ba92c` + the merge commit (the EDIT path reused every COUNTERPART index record without revalidating `mtime_ns`/`size`, so `duplicate-block` cited spans whose content had moved or gone and missed duplicates against files changed since the last sweep; `quote-source-stale` shared the shape, because the dividing line is the stage rather than the check)

- [00353: registry option injection clobbers compiled attributes](Completed/00353-registry-option-injection-clobbers-compiled-attributes/PLAN.md) - Complete at `883990ea` + the merge commit (the registry assigns each config option to `self._<key>` AFTER `__init__`, so `pipe_blocker`'s compiled `extra_whitelist` was overwritten with raw YAML strings and every piped command raised out of `matches()` — failing open, which silently disabled the whole handler for as long as the option was set)

- [00352: agent branches outlive their worktrees](Completed/00352-agent-branches-outlive-their-worktrees/PLAN.md) - Complete at `f6f1069c`…`f587a7f0` + the archiving commit (a branch whose worktree had already gone was invisible to `worktree-reap`, which enumerates from `git worktree list`; `--reap-branches` reports and prunes them)

- [00351: permission test skips everywhere including non root ci](Completed/00351-permission-test-skips-everywhere-including-non-root-ci/PLAN.md) - Complete at `b4a5226b`…`065f9610` + the archiving commit (a `skipif` guarded on `Path("/").stat().st_uid == 0` asks who OWNS `/` rather than who is running — constant `True`, so the test had never executed anywhere)

- [00350: ci builds the relay binary so transport gates run](Completed/00350-ci-builds-the-relay-binary-so-transport-gates-run/PLAN.md) - Complete at `5dc7bce1` + the archiving commit (14 transport gates skipped in CI because `untracked/bin/hooks-relay` is a gitignored artefact no runner had; CI now builds it, deliberately uncached)

- [00349: agent worktrees accumulate unreaped](Completed/00349-agent-worktrees-accumulate-unreaped/PLAN.md) - Complete at `ae4794a7`…`f2167f20` + the archiving commit (21 stale `agent-*` worktrees; the reap took `git worktree list` from 22 lines to 7, with 6 refused because a rebased commit that already landed is indistinguishable from one that did not)

- [00348: project context leaks across test files](Completed/00348-project-context-leaks-across-test-files/PLAN.md) - Complete at `b8fc7c23`…the fixing commit (four test files patched `ProjectContext.daemon_untracked_dir` while an autouse fixture already had, and the two unwound in the wrong order — leaving the fixture's `tmp_path` on the singleton so an unrelated file failed next, accusing correct code)

- [00347: handlers raise on unstattable paths](Completed/00347-handlers-raise-on-unstattable-paths/PLAN.md) - Complete at `f17fabcd`…`c731add6` + the gate and archiving commit (pathlib does not ignore EACCES, so a caller-supplied path behind an unreadable parent RAISED and the guard silently stopped applying on the client default; the fallback is now a required argument because no single value is safe — `write_clobber_guard` needs `True`, `comment_size` `False`, `plan_qa_edit` `None`)

- [00346: the QA venv ignores uv.lock](Completed/00346-pin-qa-toolchain-versions/PLAN.md) - Complete at `2de920a3`…`f8e852a1` + the archiving commit (the lockfile was committed and CI-gated while every provisioning path resolved `pyproject.toml` against PyPI instead; locking them fixed a live CI failure — `Format (black)` had been red on main because CI's floating black disagreed with the tree)

- [00345: harness payloads for shell and call syntax tests](Completed/00345-harness-payloads-for-shell-and-call-syntax-tests/PLAN.md) - Complete at `b34ab4cd`…`23fb248f` + the archiving commit (94 → 199 of 228 dispatchable blocks now run automatically, and every remaining skip carries a reason a reader can act on)

- [00337: stop hook, human-input marker and failsafe cron retune](Completed/00337-stop-hook-human-input-cron-retune/PLAN.md) - Complete at `ea03f597`…`51e3694a` + the archiving commit (guidance states the consequence, not just the mechanism; `[awaiting-human]` anchored to the declaration position; the failsafe cron backs off to a 4h cap only when nothing is owed. The DENY-rate classification is Plan 00344)

- [00342: prose guard does not reach stop handlers](Completed/00342-prose-guard-does-not-reach-stop-handlers/PLAN.md) - Complete at the delivery + archiving commits (the prose guard now scopes by base class and carries a Stop axis whose predicate is the marker SIDE EFFECT — `_denies()` would have passed vacuously; quoting a frozen phrase no longer arms cron suppression, and the unquoted residue is asserted as a recorded limit rather than left implicit)

- [00343: flip the plan QA commit gate from warn to block](Completed/00343-plan-qa-commit-gate-warn-to-block/PLAN.md) - Complete at the delivery + archiving commits (a 253-commit replay found 18 would-be denials of which 7 blamed a commit for plan-tree state it never touched; six checks narrowed to BLOCK only what a commit introduced, replay then 11 denials with zero false positives, and the gate flipped to `block`)

- [00341: plan status header rots behind shipped work](Completed/00341-plan-status-header-rots-behind-shipped-work/PLAN.md) - Complete at `9a0bf7a8` + the archiving commit (a single ticked box now falsifies a `Not Started` header, and shipping `src/` code for a plan named in the commit SUBJECT does too; the subject scoping came from a 250-commit replay that exposed a 25% false-positive shape argument had missed)

- [00338: deployed skill tree invisible to review](Completed/00338-deployed-skill-tree-invisible-to-review/PLAN.md) - Complete at the archiving commit (the `.claude/.gitignore` pattern is anchored to `/hooks-daemon/`, so the 21-file deployed skill tree is tracked like its five siblings; both directions pinned by tests, and source-to-deployed drift is now a check rather than an accident)

- [00340: release review followups v3621](Completed/00340-release-review-followups-v3621/PLAN.md) - Complete at `6d0aad13`…`c9dfd4a8` + the archiving commit (the v3.62.1 review's non-blocking remainder: a real `/model` picker confirmed the supervisor's blind Enter persists a modal's default, so a resubmit now follows its own escape within 2s)

- [00339: supervisor injection lands unsubmitted](Completed/00339-supervisor-injection-lands-unsubmitted/PLAN.md) - Complete at `e98c19e4` + the archiving commit (probing a real TUI refuted the assumed mechanism: the trigger is Claude Code's paste detection on a large burst, inside which a carriage return is a literal newline, so the injection is now bracketed-paste framed)

- [00336: upgrade path residual findings](Completed/00336-upgrade-path-residual-findings/PLAN.md) - Complete at `c85d5e90`…`788ce6c8` + the archiving commit (config preservation now diffs against a true old-version baseline; `HOOKS-DAEMON.md` regenerated on both upgrade paths instead of never; 17 shipped commands our own `project_containment` denied moved in-repo, found by driving the doc corpus through the live handler)

- [00335: heredoc receiver policy and review followups](Completed/00335-heredoc-receiver-policy-and-review-followups/PLAN.md) - Complete at `745ff9c5` + the archiving commit (inverting the quoted-heredoc exemption to an allowlist of data sinks closed a fourth executor bypass found by probing, the word-expansion family recorded as unclosable, and the `jq` over-block in one change)

- [00334: core doc templates for client projects](Completed/00334-core-doc-templates-for-client-projects/PLAN.md) - Complete at `4e78f7c9` + the archiving commit (daemon guidance named client documents no install path created, so a client enforced a workflow whose documentation did not exist; ships three genericised core documents deployed DAEMON-owned beside a seed-once CLIENT-owned override, each gated on the subsystem that NAMES it, and replaces the hand-maintained citation list with a scan)

## Blocked / On Hold Plans

- None. (00032, 00034 and 00035 were held on an upstream delegate-mode fix; the mode no longer exists, so they are cancelled below.)

## Cancelled Plans

- [00135: Event-Driven `send-keys` Injection](Cancelled/00135-event-driven-send-keys-injection/PLAN.md) - Superseded by the ccy supervisor workstream (Plans 00147 to 00339): Decision G's ARCH-B PTY supervisor shipped under its own plan numbers, so this folder is the design record and the ARCH-A revival note

- [00032: Sub-Agent Orchestration for Context Preservation](Cancelled/00032-subagent-orchestration-context-preservation/PLAN.md) - Cancelled, won't do (held for a fix to Claude Code's delegate-mode cascade; on 2.1.263 there is no delegate mode, teammates inheriting the lead's mode is documented behaviour, and the four tracked issues were auto-closed unfixed)

- [00034: Model-Aware Agent Team Advisor](Cancelled/00034-model-aware-agent-team-advisor/PLAN.md) - Cancelled, won't do (depended on 00032)

- [00035: StatusLine Data Cache + Model-Aware Advisor](Cancelled/00035-statusline-data-cache-model-advisor/PLAN.md) - Cancelled, won't do (depended on 00032)

- [00108: Nuanced AskUserQuestion Blocker](Cancelled/00108-question-blocker-nuanced/PLAN.md) - Superseded by Plan 00117, which shipped this exact design in v3.14.0 (`ASKING BECAUSE:` prefix, strict/advisory modes, guidance, rule id); the status header had simply never moved

- [00131: Block Untracked Claude Memory + Tracked-Docs Progressive Disclosure](Cancelled/00131-disable-auto-memory-tracked-docs-system/PLAN.md) - Cancelled, won't do the residue (Phases 1–5 shipped in v3.23.0 and Plan 00284 delivered the dogfood migration; the last item, a scaffolding skill held "until a client asks", is declined)

- [00132: PostToolUse Progressive-Disclosure Reminder on Project-Doc Markdown Writes](Cancelled/00132-progressive-disclosure-md-write-reminder/PLAN.md) - Superseded by [00284](Completed/00284-documentation-ssot-enforcement/PLAN.md), whose edit-time/post-write surface absorbs this plan's nudge intent; never started, so no work is lost

- [00174: Status-Line Artefact + Per-Segment Cadence Redesign](Cancelled/00174-status-line-artefact-cadence-redesign/PLAN.md) - Superseded by Plan 00175, which concluded the artefact store is unnecessary because Claude Code's 1s refresh floor caps any benefit a cheaper render could unlock

- [00199: planlib — plan-orchestrator tooling in the daemon](Cancelled/00199-hooks-daemon-plan-lib/PLAN.md) - Superseded

  - Superseded by [00213](Completed/00213-planlib-plan-folder-orchestrator-tooling/PLAN.md), which targets the SAME upstream proposal and is the plan being executed. Both were authored independently five days apart and neither referenced the other; 00213 additionally tracks the proposal under version control (`PROPOSAL.md`) rather than pointing at `untracked/`. 00199 was never started, so no work is lost.

  - Preserved for `PROPOSAL-ASSESSMENT.md`, whose integration analysis 00213's owner reviewed and adopted wholesale: mode `0644` not `0755` (the library is sourced, not executed), adding it to `_EXPECTED_ROOT_FILES` so the sweep does not flag it, daemon-owned overwrite-on-upgrade, no default for `root_marker`, neutral config examples, the `bash -n` empty-stderr assertion, and deferring `plan_script_qa`.

- [00091: Hook Executable Permissions](Cancelled/00091-hook-executable-permissions/PLAN.md) - Cancelled

  - Superseded by [00102](Completed/00102-hook-exec-bit-defense/PLAN.md).

- [00081: Pseudo-Events & Nitpick Handler](Cancelled/00081-pseudo-events-nitpick-handler/PLAN.md) - Cancelled

  - Superseded by [00082](Completed/00082-pseudo-events-nitpick-handler/PLAN.md), the revised execution plan (Complete). Both plans share the same title and problem statement; this research-stage plan is preserved for history. Closed during Plan 00107 Wave 3.

- [00087: Post-Clear Auto-Execute](Cancelled/00087-post-clear-auto-execute/PLAN.md) - Cancelled

  - Hooks cannot solve `/clear <text>` auto-execution — client-side `local-command-caveat` and no auto-submit
  - Prototype handler remains enabled (marginal value), but core goal impossible via hooks

- [00044: Acceptance Testing Skill](Cancelled/00044-acceptance-testing-skill/PLAN.md) - Cancelled

  - Sub-agent acceptance testing retired in v2.10.0; main-thread testing is the standard

---

## Plan Statistics

- **Total Plans Created**: 363 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 323 (includes 1 reduced-scope plan and 6 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 17 (count = root `NNNNN-*` plan folders; includes several dormant plans awaiting scheduling)

- **On Hold**: 0

- **Cancelled/Abandoned**: 13 on disk (count = `Cancelled/` folders: 00032/00034/00035 won't do — delegate mode no longer exists, 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00108 superseded by 00117, 00131 residue declined, 00132 superseded by 00284, 00174 superseded by 00175, 00199 superseded by 00213, 00135 superseded by the supervisor workstream)

- **Folder-to-number reconciliation**: 17 + 322 + 13 = **352 folders**, spanning
  **349 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **13** of the
  362 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258, 00300, 00303, 00325 — abandoned drafts, numbers
  burned by transient probes (00195 during the v3.51.0 acceptance run, 00258
  during the v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a
  sub-agent that then found Plan 00208 already covered the work).
  349 + 13 = 362. ✅

  Note on **00191**: it stays folderless deliberately. The number was claimed
  by a branch that renumbered itself and was never merged; Plan 00267
  supersedes it, so no folder for 00191 will ever land in `main`.

- **Last reconciled at**: the closure of Plan 00311, the v3.59.0 review
  ledger, worked to zero (29 root, 309 `Completed/`, 12 `Cancelled/`, 347 distinct numbers against a counter of 360 —
  350 folders, three of which share a number with another from before the
  counter existed: 00034, 00039, 00041). Every figure above was recounted from
  disk rather than incremented, and the folderless set was recomputed the same
  way. The index carries NO
  reconciliation history — it states current truth only; every earlier recount
  is in git, and per-plan narrative belongs in that plan's `JOURNAL/`.

  One recount hazard worth keeping, because it recurs: an untracked stray
  directory (e.g. an accidental `CLAUDE/Plan/CLAUDE/Plan/` from a
  relative-path slip) is invisible to `git status` while still inflating a
  naive folder count by one.

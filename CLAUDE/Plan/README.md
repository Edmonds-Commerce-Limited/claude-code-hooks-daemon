# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00385: niggles ledger four](00385-niggles-ledger-four/PLAN.md) - In Progress (successor to Plan 00381; the open ledger for small verified defects — record in the turn found, fix here or graduate with a pointer)

- [00384: daemon asserted cron and autonomous issue sdlc](00384-daemon-asserted-cron-and-autonomous-issue-sdlc/PLAN.md) - In Progress (an hourly tick takes ONE open GitHub issue from triage to merged-and-closed; `CronCreate` cannot persist across sessions — its `durable` flag has no effect — so the daemon declares crons in config and asserts them at SessionStart)

- [00344: stop hook deny rate classification](00344-stop-hook-deny-rate-classification/PLAN.md) - Not Started (Plan 00337 Task 5.0 shipped the instrumentation but the classification needs telemetry across many sessions — 49 instrumented rows exist and 48 are acceptance probes, because a real Stop event fires roughly once per session)

- [00280: workflow agent model cap in standing authorisation](00280-workflow-agent-model-cap-authorisation/PLAN.md) - Not Started (extend the built-in `workflow-orchestration` standing authorisation with a configurable model cap for workflow/sub-agents — default: Sonnet encouraged, Opus as required, Fable banned)

- [00264: cap the size of a GitHub issue/PR comment](00264-github-comment-size-cap/PLAN.md) - Not Started (field report: agent sessions flooded two issues with 44,467- and 22,398-character comments until neither ticket's state was findable by the humans reading it; a PreToolUse cap on `gh` comment bodies steering the content into `JOURNAL/`, plus seven open questions the report's proposed design asserts rather than settles)

### Security / Presentation Audit

### Core / Hook Coverage

- [00170: Universal Hook Coverage + Hook-Support Enforcement](00170-universal-hook-coverage-and-enforcement/PLAN.md) - Dormant (fundamental: intercepting hook events is the daemon's raison d'être, yet only **10 of the 30** documented Claude Code hook events are wired — 20 are silently unwired, so a client project cannot even …)

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

- [00376: pre-upgrade phase with migration and confirm gate](00376-pre-upgrade-phase-with-migration-and-confirm-gate/PLAN.md) - Not Started (an upgrade tells a project what changed only after changing it; the one confirm gate is skipped for every agent run and fires post-checkout anyway, and `post-upgrade-tasks/` has no runner — replace deprecation windows with detect-and-migrate plus an agent-usable proceed/abort gate)

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

- [00383: transport toggle trusts config over deployed state](Completed/00383-transport-toggle-trusts-config-over-deployed-state/PLAN.md) - Complete at `3a58ce16`…`3292cd09` + the archiving commit (`transport on`/`off` decided "already — nothing to do" from the config alone and never read the deployed forwarders, so a project whose config said the relay was off while its forwarders still carried the hot path was told so, exit 0)

- [00381: niggles ledger three](Completed/00381-niggles-ledger-three/PLAN.md) - Complete + the archiving commit (one entry, graduated rather than fixed in place: a test class that could not pass alone turned out to be reporting a product defect, which became Plan 00383. The NEXT niggle opens ledger four; SOP in `CLAUDE/PlanWorkflow.md`)

- [00382: push force guard misreads flag boundaries](Completed/00382-push-force-guard-misreads-flag-boundaries/PLAN.md) - Complete at `0edece84` + the archiving commit (GitHub #37 reported a branch named `...-f-...` denied as a force push; reproducing it exposed the opposite defect the reporter could not see — grouped short flags `-uf`/`-fu`/`-nf` are real force pushes that no release ever blocked. Long and short options now get separate rules: 14 cases, 6 wrong before, 0 after)

- [00380: worktree reap jammed by daemon own output](Completed/00380-worktree-reap-jammed-by-daemon-own-output/PLAN.md) - Complete at `83fe7bf7`…`30583859` + the archiving commit (five worktrees sat unreapable for days with zero commits unmerged to main; four were held by the daemon's OWN generated advisory reading as unsaved work, and the refusal text said "needs a human" when no hook ever blocked `git worktree remove --force`)

- [00379: niggles ledger two](Completed/00379-niggles-ledger-two/PLAN.md) - Complete + the archiving commit (five entries, all found by verifying a claim rather than hitting a symptom; shipped two guards — `index-retention-window` at the plan-QA commit gate and `plan-stats-arithmetic` in repo hygiene — each proved by breaking real data, not just fixtures)

- [00377: niggles ledger](Completed/00377-niggles-ledger/PLAN.md) - Complete + the archiving commit (the first niggles ledger: eleven small defects recorded the turn they were found, nine fixed here and two graduated — N10 to Plan 00378, N3 to Plan 00376. The NEXT niggle opens a new ledger; SOP in `CLAUDE/PlanWorkflow.md`)

- [00375: `plan-qa` and `docs-qa` JSON disagree on the severity key](Completed/00375-plan-qa-and-docs-qa-json-disagree-on-the-severity-key/PLAN.md) - Complete + the archiving commit (one concept under two names — `docs-qa` emitted `severity`, `plan-qa` emitted `level` — converged on `severity` with no deprecation window, since two live names IS the defect)

- [00378: agent asset ledger guard and backfill](Completed/00378-agent-asset-ledger-guard-and-backfill/PLAN.md) - Complete + the archiving commit (the ledger's guard compared the bundled file's digest with a value derived from that same file, so it could never fail; four revisions shipped unrecorded and froze those deployments as `CUSTOMISED`)

- [00374: the global `--project-root` is clobbered by a subparser default](Completed/00374-global-project-root-clobbered-by-subparser-default/PLAN.md) - Complete at `05d526be`…`692b32c5` + the archiving commit (`bin/hooks-daemon` refuses to run rather than let the CLI fall back to the caller's directory, but argparse's subparser default silently discarded the anchor it passed, and the anchoring suite asserted the argv rather than the behaviour)

- [00373: drift reached main unseen — merge bypass and QA blind spot](Completed/00373-drift-reached-main-unseen-merge-bypass-and-qa-blind-spot/PLAN.md) - Complete at `7a722965`…`016611de` + the archiving commit (a merge resurrected an archived plan folder and four plan-QA findings survived a green QA run, green CI and a release-slate check; both sweeps are now QA tools where any finding fails, and `merge_qa_report` reports what a merge/pull/rebase actually introduced)

- [00368: lsp is signal not noise](Completed/00368-lsp-is-signal-not-noise/PLAN.md) - Complete + the archiving commit (3,011 language-server errors down to zero with no suppression anywhere: the non-project trees are excluded, pyright is a blocking QA gate, and a session-start checker tells any project in five languages exactly how to silence its own noise)

- [00372: worktree reap two defects](Completed/00372-worktree-reap-two-defects/PLAN.md) - Complete + the archiving commit (a worktree with no commits yet passed every safety predicate vacuously, so a live agent's work was offered for deletion; and the branch delete had never once worked, passing a fully-qualified ref that `git branch -d` rejects)

- [00371: qa acceptance probes detect a stale daemon](Completed/00371-qa-acceptance-probes-detect-a-stale-daemon/PLAN.md) - Complete + the archiving commit (the acceptance harness graded whatever code the running daemon loaded at startup, so it could pass a broken tree; a startup source fingerprint now makes every live-dispatch test fail by name on a stale daemon)

- [00370: daemon restart verifier becomes a project handler](Completed/00370-daemon-restart-verifier-becomes-a-project-handler/PLAN.md) - Complete + the archiving commit (a handler that only ever fired inside this repository left the shared built-in library and became this repo's own project-handler reference example, with the retired key still validating cleanly in a client config)

- [00369: status line explained command](Completed/00369-status-line-explained-command/PLAN.md) - Complete + the archiving commit (every status-line handler now describes its own glyphs, how to read them and what the value means right now, surfaced by `hooks-daemon status-line-explained`)

- [00367: deployed docs in sync with daemon workflow](Completed/00367-deployed-docs-in-sync-with-daemon-workflow/PLAN.md) - Complete + the archiving commit (a deployed core doc that told agents a human must approve a step no config key backs is now blocked by the `unenforced-approval-gate` docs-QA check, and both gates became real opt-in keys, default off)

- [00366: supervisor own line follow up](Completed/00366-supervisor-own-line-follow-up/PLAN.md) - Complete + the archiving commit (an armed `/goal` pasted mid-turn was never submitted and sat in the input box for eight hours; the supervisor now remembers its own typed line, presses Enter for it at the next lull, holds the text families while it is pending, and the goal cap is a rolling hour rather than a process lifetime)

- [00365: markdown_organization — a declared project at any depth](Completed/00365-markdown-organization-nested-vendor-and-existing-file-edits/PLAN.md) - Complete at `a8111e72` + the archiving commit (field report: an `Edit` of an existing `.md` two `vendor/` levels deep was denied with no escape hatch; a `projects:` root now wins at any depth, nested vendor trees strip through, a repo-root-anchored extra pattern matches, and an existing `.md` is never a location violation)

- [00364: v3.63.0 release review follow-ups](Completed/00364-release-review-followups-v3630/PLAN.md) - Complete at `0560b5ff`…`b56c2621` + the archiving commit (every non-blocking Step 10 finding fixed: venv-lock misreport, slate check reading a git failure as clean, plan-QA gate spawning `git diff` per plan, bracket-range cost, lint temp dirs, dead pipe_blocker tests; a worktree's hooks reach its own daemon; project handler off priority 20; QA audits and runner work from a worktree)

Older completed plans (below the retention window of the 30 highest-numbered) are archived verbatim in [Completed/README.md](Completed/README.md).

- [00363: self-matching process watcher blocker](Completed/00363-self-matching-process-watcher-blocker/PLAN.md) - Complete at `003f3036` and `8ae8ac61` + the archiving commit (a process probe whose literal pattern is in the calling shell's own argv, and a wait on `$!` after `setsid`, are denied; Rules A and C shipped in v3.63.0, Rule B holds a callout for the next release)

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

- **Total Plans Created**: 385 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 345 (includes 1 reduced-scope plan and 6 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 17 (count = root `NNNNN-*` plan folders; includes several dormant plans awaiting scheduling)

- **On Hold**: 0

- **Cancelled/Abandoned**: 13 on disk (count = `Cancelled/` folders: 00032/00034/00035 won't do — delegate mode no longer exists, 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00108 superseded by 00117, 00131 residue declined, 00132 superseded by 00284, 00174 superseded by 00175, 00199 superseded by 00213, 00135 superseded by the supervisor workstream)

- **Folder-to-number reconciliation**: 17 + 345 + 13 = **375 folders**, spanning
  **372 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **13** of the
  385 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258, 00300, 00303, 00325 — abandoned drafts, numbers
  burned by transient probes (00195 during the v3.51.0 acceptance run, 00258
  during the v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a
  sub-agent that then found Plan 00208 already covered the work).
  372 + 13 = 385. ✅

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

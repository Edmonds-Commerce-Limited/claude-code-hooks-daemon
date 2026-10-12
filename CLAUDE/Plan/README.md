# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00501: session modes](00501-session-modes/PLAN.md) - Not Started, Medium (#91; first-class per-session modes shown in the status line: focus (`hooks-daemon focus <task>`), BLOCKED (awaiting-human, goal-blocked loop breaker), usage-paused; per-session awaiting-human storage; guards never gated)

- [00496: upstream feature requests and issue kinds](00496-upstream-feature-requests-and-issue-kinds/PLAN.md) - Not Started (owner request: a formal process for project agents to file feature requests and other non-defect issues, mirroring the defect generator, guard and forms; security reports routed privately)

- [00495: performance improvement programme](00495-performance-improvement-programme/PLAN.md) - In Progress (owner report: daemon startup and the status bar at session start got much slower; profile current main against earlier releases, fix the ranked causes, add a regression guard, and re-answer the Rust question from new numbers)

- [00497: hooks daemon mod](00497-hooks-daemon-mod/PLAN.md) - Not Started (owner-approved build from Plan 00494: daemon mod awareness with an exceptionally loud warning, a human task and question queue, one mod deployed by install and upgrade, suggested prompts, SessionStart messages, then session resilience)

- [00491: code quality and architecture review](00491-code-quality-and-architecture-review/PLAN.md) - Not Started (owner ruling B5: a read-only review of module size, DRY, architecture and code quality, then owner-chosen refactoring; N314 folds in)

- [00489: supervisor in-container restart primitive](00489-supervisor-in-container-restart-primitive/PLAN.md) - Not Started (owner decision D2 in Plan 00487, #71: 00487's Tasks 1.4 and 1.5, the in-container `Restart` and the host-half `before_spawn` that the fedora-desktop 00146 credential switch needs)

- [00485: split subagent full qa blocker](00485-split-subagent-full-qa-blocker/PLAN.md) - Not Started (owner-delegated Fable ruling on 00466 N96: pure-refactor split of the 5,300-line handler along its class seams; starts only once no open branch touches the file)

- [00484: DBF adoption and toolchain conformance](00484-dbf-adoption-and-toolchain-conformance/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)) (owner ruling: fully adopt Defence Before Fix and link it, #65 and #67; assess the daemon as a DBF toolchain against TOOLING-SPEC and let DBF tools enumerate its defences)

- [00482: handler crash containment](00482-handler-crash-containment/PLAN.md) - Not Started (owner ruling after #68: handlers must never crash; a crash gets a crash record and a bug-report request, non-safety handlers are disabled after N crashes, safety guards stay fail-closed pending the owner's decision)

- [00481: release 3.67 retrospective - how #68 shipped, and the QA gaps](00481-release-3-67-retrospective-qa-gaps/PLAN.md) - Not Started (owner request: a causal account, gate by gate, of how #68 reached a release, then a realistic-command corpus gate and an evaluation-error release signal, each proven against the pre-fix tree)

- [00479: subscription usage monitor and ceiling](00479-subscription-usage-monitor-and-ceiling/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)) (owner request: a status-line 5-hour/weekly usage segment, plus a per-host usage ceiling in a host-first `hosts:` block so unattended sessions stop before exhausting the subscription)

- [00478: unknown guard verdicts warn](00478-unknown-guard-verdicts-warn/PLAN.md) - Not Started (owner ruling "warn dont block": a safety guard that cannot decide allows with an advisory; a positive match still denies)

- [00477: provision a fresh clone](00477-provision-a-fresh-clone/PLAN.md) - Not Started (owner ruling: a fresh clone is brought up by a new `provision` verb that installs the daemon version the config names, and the hooks say loudly, to the human, when a checkout needs it)

- [00476: release through a pr with ci tagging](00476-release-through-a-pr-with-ci-tagging/PLAN.md) - Not Started (owner direction: a release branch and pull request exist for QA, running the whole suite in CI; acceptance tests, tagging and publishing stay local in `/release`; follows 00475's first batch)

- [00474: niggles ledger seventeen](00474-niggles-ledger-seventeen/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)), the OPEN ledger for new niggles (00466 reached its PLAN.md size limit with N261; numbering continues, opening with N262: the release procedure has no check that the notes fit a GitHub release body)

- [00473: post merge handlers judge the command repository](00473-post-merge-handlers-judge-the-command-repository/PLAN.md) - Not Started (graduated from 00468 G9: `daemon_sync_after_merge` and `merge_qa_report` judge the repository the payload `cwd` names, not the one the command ran in; blocked on Plan 00464's command-directory resolver)

- [00472: subagent model tier selection](00472-subagent-model-tier-selection/PLAN.md) - In Progress (owner request, not urgent: a top-tier main thread often gives subagents the top tier too, where Sonnet or Opus would do; record each dispatch's model and advise a cheaper tier when it fits, the model-choice twin of 00471 and a neighbour of 00470's orchestrator-model choice)

- [00471: subagent token budget protection](00471-subagent-token-budget-protection/PLAN.md) - In Progress (owner request after a usage-limit burn: subagents compacted only at about 570k tokens, finished agents were resumed with thousands of prior messages, and about nine Opus agents ran at once; the daemon sees every Agent, SendMessage and tool call plus the transcript's usage, so it can measure and bound the spend)

- [00470: persistent session optimisation](00470-persistent-session-optimisation/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)) (owner request: the always-on server session is the dogfood; cron refresh, usage-limit and restart recovery, a timed stand-in for a human block, and a measured orchestrator-model choice)

- [00467: recommend the defence before fix plugin to client projects](00467-recommend-the-defence-before-fix-plugin-to-client-projects/PLAN.md) - Blocked (owner request: dogfood the DBF plugin, then recommend it to clients. Phase 1 is done, with shortfalls filed upstream as #4-#6 and recommendation no-go for now. Waiting on the owner's go/no-go, and on one logged-in auto-trigger probe)

- [00465: commit gates see the index after same command staging](00465-commit-gates-see-the-index-after-same-command-staging/PLAN.md) - Not Started (from 00422 N26: gates read the index before the command runs, so `git add f && git commit` passes the secret-term scan and every other staged-content gate unexamined; starts after 00464, same gates)

- [00464: commit gates judge the checkout the command runs in](00464-commit-gates-judge-the-checkout-the-command-runs-in/PLAN.md) - Not Started (from 00422 N23: commit gates pick their repo from the payload `cwd`, which for a teammate is the main checkout, so a worktree commit is judged on main's staged tree — false denies, and its own content, secret terms included, never checked)

- [00453: supervisor modal overlay](00453-supervisor-modal-overlay/PLAN.md) - Not Started (the status-line banner from Plan 00173/00318 is a one-line TTL notification and structurally cannot hold history; this adds a hotkey-summoned inspection surface costing no model turn, no transcript entry and no status-line space — gated on the owner choosing a hotkey, F12 and F3 already rejected)

- [00452: prompt cache observability and invalidation protection](00452-prompt-cache-observability-and-invalidation-protection/PLAN.md) - Blocked on owner input (status segment shipped as main, sub and token-weighted total; what remains needs `/usage` run in-session and a gap profile from a human-paced project, Task 2.4)

- [00451: version bump completeness and dependency gate stale verdict](00451-version-bump-completeness-and-dependency-gate-stale-verdict/PLAN.md) - Not Started (three of six version-carrying files are found only when a gate goes red, and the `dependencies` gate leaves a stale `passed: true` on disk when `uv lock --check` aborts it)

- [00450: release skill mandates forbidden subagent acceptance gate](00450-release-skill-mandates-forbidden-subagent-acceptance-gate/PLAN.md) - Not Started (`release/invoke.sh` tells the agent to spawn parallel Haiku agents for Step 12; `acceptance-test/invoke.sh` forbids exactly that by name)

- [00448: plan completion gate has no commit time backstop](00448-plan-completion-gate-has-no-commit-time-backstop/PLAN.md) - Not Started (the Complete-flip gate keys on Write/Edit only, so a `PLAN.md` written through Bash escapes it — as Plan 00437 did)

- [00447: magic constant advisory policy](00447-magic-constant-advisory-policy/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #49: the reported constant is verified real and is a GrowthBook experiment gate on the bash-first injection, one of 642 `CLAUDE_CODE_*` tokens in the build — so whether the daemon should advise on cohort-assigned experiment flags at all is a policy question, and it subsumes 00428's blocker)

- [00428: auto compact window audit check](00428-auto-compact-window-audit-check/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #46: a seventh `optimal_config_checker` check for `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; the gap is real but the spec was retracted and replaced by one inferred from a compiled CLI, which triage could not verify)

- [00421: security detectors and ci enforcement](00421-security-detectors-and-ci-enforcement/PLAN.md) - Not Started (`qa.yml` runs no `scripts/qa/check_*.py` at all, so no Detector this project treats as binding has ever been enforced in CI. The single successor to 00412, carrying the four Fable rulings' unbuilt work: pin what makes a Detector binding, make the register state its own gaps, migrate the test-shaped Defences, then build the seven unwatched classes)

- [00420: dangerous command rule modes and config migration](00420-dangerous-command-rule-modes-and-config-migration/PLAN.md) - Not Started (per-rule-ID `block`/`warn`/`off` across the dangerous-command handlers, plus the loud, migrating config upgrade that a moved key requires)

- [00410: gitignore swallows deployed assets](00410-gitignore-swallows-deployed-assets/PLAN.md) - Not Started (an unanchored `hooks-daemon/` ignore pattern matches at every depth, so it hides the deployed `.claude/skills/hooks-daemon/` tree as well as the intended clone; this repo is already anchored, but nothing DETECTS the mistake, and an ignored file cannot drift visibly. Owner-reported from a client project)

- [00399: supervisor does not see tab completed slash commands](00399-supervisor-does-not-see-tab-completed-slash-commands/PLAN.md) - Blocked (ruled option 2 shipped: the supervisor reads a Tab-completed `/compact` from the daemon's `PreCompact` record, which now carries its origin. Only Task 2.1 remains, and it needs a human: typing `/comp`, Tab, Enter in the real tmux-wrapped session to show whether tmux changes the byte stream)

- [00396: detect a plan written without reading its domain docs](00396-detect-a-plan-written-without-reading-its-domain-docs/PLAN.md) - Not Started (a plan was filed about deployment by a session that had read none of the deployment docs; the signature is mechanical — a PLAN.md filled about domain X with zero reads of X's owning docs — and `write_clobber_guard` already tracks per-session reads. Advisory, inert until a project declares a topic map)

- [00391: plan close requires proven definition of done](00391-plan-close-requires-proven-definition-of-done/PLAN.md) - Not Started (a project declares its DoD in config; the close is denied until each item is CHECKED or attested with evidence in the plan's JOURNAL/, and a three-way policy — human_gate, encourage, neutral — subsumes Plan 00367's boolean. `encourage` is the direction that would have caught 00386/00389 sitting finished-but-open)

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

- [00469: qa packages import plan qa from shared layers](00469-qa-packages-import-plan-qa-from-shared-layers/PLAN.md) - Not Started (graduated from 00422 N14: the last two declared `utils`/`docs_qa` → `plan_qa` import edges; the status-line grammar and the tier constants move into shared `utils` modules so `_KNOWN_EDGES` empties. Starts after the 00466 goal-flip branch merges)

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

- [00502: merge requires approval](00502-merge-requires-approval/PLAN.md) - Not Started (owner rulings: the merge gate becomes "merge requires APPROVAL" with a configurable human or agent approver, default a clean sub-agent at minimum model `opus` or a named project review sub-agent; the core design is a daemon-written, tip-bound approval record the merging agent cannot forge, plus migration from the old human-approval boolean)

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

- [00100 (v3): Venv SSOT Consolidation](00100-venv-ssot-consolidation/PLAN.md) - Dormant (residue scope awaits scheduling)

  - Phases 0–3.9 **shipped** in v3.9.0 / v3.10.0 / v3.11.0 (canonical SSOT resolver, `.daemon-metadata.json` writers, dead-code removal, path slug, eager upgrade cleanup, H-1 gate coverage)

  - **Residue deferred from v3.12.0** (Plan 00107 Wave 4): Phase 4 (flock concurrency), Phase 5 (parameterised upgrade-cycle test), Phase 6 (docs) … Phase 3.5.2–3.5.7 (bootstrap-fallback wiring) is carried by [Plan 00456](Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md), no longer residue here

  - Phases 1–4 complete (`bash <path>` invocation, auto-migration, self-heal, filemode checker)

  - **Task 5.3 pending**: acceptance gate at v3.12.0 release time (folded into meta plan 00107 Wave 6 `/release` execution)

- [00266: AI-assisted handler decisions](00266-ai-assisted-handler-decisions/PLAN.md) - Dormant (native `prompt`/`agent` hooks measured live: they work, fail CLOSED, cost ~1.2s vs the daemon's ~51ms, and cannot override a daemon deny; dynamic prompting via `tool_use_id` is the leading architecture; parked as reference until a revival condition fires)

## Completed Plans

- [00507: rust lint uses the owning crate context](Completed/00507-rust-lint-uses-the-owning-crate-context/PLAN.md) - Complete at merge `601ba02f9` + `b7552acfb` + the archiving commit (#76, duplicate #89: the Rust lint runs from the owning crate with its Cargo.toml edition; crate-context errors are could-not-analyse and allowed with an advisory, syntax errors still deny; release note 029 in UNRELEASED)

- [00506: comment extractor ignores unterminated block openers](Completed/00506-comment-extractor-ignores-unterminated-block-openers/PLAN.md) - Complete at merge `65bdc7499` + the archiving commit (#75: a block/doc opener with no closer later in the content is not a comment, so a `/*` inside a string no longer swallows the file and `comment_size` stops denying comment-free code; the text-scanning limitation is stated in the handler guidance; release note 028 in UNRELEASED)

- [00505: tdd test path map anchors at the worktree](Completed/00505-tdd-test-path-map-anchors-at-the-worktree/PLAN.md) - Complete at merge `c436dc918` + the archiving commit (#74, duplicate #102: a declared `test_path_map` `test_dir` and its `source_glob` anchor at the checkout holding the source, the nearest `.git` ancestor below the project root, so a Write in a git worktree anywhere in the project finds its own test; release note 027 in UNRELEASED)

- [00504: remote docs refresh keeps recorded fidelity](Completed/00504-remote-docs-refresh-keeps-recorded-fidelity/PLAN.md) - Complete at merge `78f03e21e` + the archiving commit (#73: `remote-docs refresh` re-fetches each document in the fidelity its provenance records, so verbatim stays verbatim; `--verbatim` still forces verbatim for every target; release note 026 in UNRELEASED)

- [00488: status line visible during daemon outage](Completed/00488-status-line-visible-during-daemon-outage/PLAN.md) - Complete at `2790de8eb` + `7e8e71e5b` + `a468e29c7` + `9517a3c7f` + the archiving commit (owner request, #72: the status-line forwarder exits 0 on its down path and names venv building, venv missing and version mismatch; a raw self-install clone builds its own venv; the build window fails open, announced, per a coordinator ruling (RULING-3.2); a startup race no longer denies)

- [00503: remove upgrade owner approval](Completed/00503-remove-upgrade-owner-approval/PLAN.md) - Complete at merge `6976bf009` + the archiving commit (owner request, #112: the exit-4 owner approval, `approve-upgrade`, the approval markers and `upgrade_approval_guard` removed; breaking items lead the exit-3 reading, large jumps get phasing advice, and an old config naming the guard still validates; release note 022 in UNRELEASED)

- [00500: full qa timing and speed](Completed/00500-full-qa-timing-and-speed/PLAN.md) - Complete at merge `c02cf9838` + the archiving commit (owner request: per-step timing, a resumable and sharded gate, and the measured hot spots cut; total wall-clock deferred to the Actions runs, #107)

- [00483: threat model conformance audit](Completed/00483-threat-model-conformance-audit/PLAN.md) - Complete at batch (c) `4981618fc` + the Task 3.2 re-probe `8e84e6b76` + the archiving commit (owner ruling: the daemon is guardrails, not armour; every guard, open ledger entry and uncovered corpus row checked against the careless-not-hostile threat model, the out-of-scope ones dismissed on record, the rest narrowed or filed as 00474 N400-N409)

- [00499: write-protected paths, and the ccy.env.local.dist template](Completed/00499-write-protected-paths-and-ccy-env-local-dist/PLAN.md) - Complete at Phase 1b merge `64823600a` + the archiving commit (owner rulings: `ccy.env.local` is IaC-written only; an opt-in `write_protected_paths` guard denies every Write/Edit/Bash route onto a listed path, live-probed; the dist template was cancelled because ccy writes it)

- [00480: plan fact checker and debounce](Completed/00480-plan-fact-checker-and-debounce/PLAN.md) - Complete, the feed shipped in v3.69.0, with the N359 delivery fixes at merge `7aa463588` + the archiving commit (owner ruling after ledger 00474 N290: a Sonnet fact itemiser/verifier wired into plan QA through a first-class debounce; the final live run refuted a planted false claim delivered unasked)

- [00487: Supervisor plugin API and the ccy restart plugin](Completed/00487-supervisor-plugin-api-and-ccy-restart-plugin/PLAN.md) - Complete, shipped as beta in v3.69.0 + the archiving commit (owner request, #71: a crash-isolated plugin API for the ccy supervisor and a ccy max-age restart and deadline plugin on fedora-desktop; every supervisor-side live-test step passed, and the three launcher-only steps were handed to fedora-desktop#61 by owner ruling D11)

- [00498: autonomy only where allowed](Completed/00498-autonomy-only-where-allowed/PLAN.md) - Complete at merge `68dd20179` + the archiving commit (owner request after a desktop agent drifted off its one task: a top-level `autonomy:` block, keyed on the detected environment and role alias, decides whether crons, goal pressure and resume advice run; this repo allows them in containers only, and the owner's desktop session showed `no autonomy` with an empty CronList)

- [00494: Claude Code mods review](Completed/00494-claude-code-mods-review/PLAN.md) - Complete at `f794f4cd1` + the archiving commit (owner request: 21 mod docs vendored, an Opus review and brainstorm, then a one-mod proposal the owner approved with its build order and deployment route; the build is Plan 00497)

- [00493: upgrade silently disables opt-in handlers](Completed/00493-upgrade-silently-disables-opt-in-handlers/PLAN.md) - Complete at `3d696453b`, merged `4030e688f` + the archiving commit (client report: the v3.68.0 upgrade dropped unnamed opt-in handlers silently; the upgrade now names every handler it stops or starts, prints the restore snippet and the from-to version, and the config diff summary finds the real backup; auto-restore stays an owner question)

- [00486: Claude Code version tracking](Completed/00486-claude-code-version-tracking/PLAN.md) - Complete at `af0237910` + `b9e01a690` + `4d507be1a` + the archiving commit (owner request: each release records the Claude Code version it was built against, RELEASING.md Step 1c reviews the changelog per release, and `contract_staleness` advises once on a newer running version; backfill findings are 00474 N330–N337)

- [00492: docs fake values registry](Completed/00492-docs-fake-values-registry/PLAN.md) - Complete at `f6cb38ee0` + the QA fix-up + the archiving commit (owner ruling D1: one registry of approved fake values for docs, `.claude/fake-values.yaml`; an `unlisted-fake-value` docs QA check, a sensitive-content allowance for listed fakes only, and remote-docs swaps recorded in provenance as `value_swaps`; settles N309 and unblocks 00479 Task 1.1 and 00486 Task 1.3)

- [00475: targeted qa and small batches](Completed/00475-targeted-qa-and-small-batches/PLAN.md) - Complete at `d6caefded` + `301805f1f` + `b4576108a` (all shipped in v3.68.0) + the archiving commit (owner request: targeted QA for every change, the full gate only at release preparation, one QA run at a time, and small batches of branches; the branch-count and merge-QA advisories stay advisory by coordinator call)

- [00490: github issue assignment guard](Completed/00490-github-issue-assignment-guard/PLAN.md) - Complete at `8846f9d77` + `bb9bf1a98` + the archiving commit (owner request: issue-tied work requires the issue assigned to the signed-in GitHub account and opened by an approved author; a deterministic `issue-validity` checker and CLI claim an unassigned issue and stop on someone else's; the CLI refuses with no author list configured)

- [00466: niggles ledger sixteen](Completed/00466-niggles-ledger-sixteen/PLAN.md) - Superseded by [00474](00474-niggles-ledger-seventeen/PLAN.md) (the ledger for N1-N261; its 65 entries still open in the index are tracked from 00474, and every branch was landed or dropped with its branch-only entries carried into 00474. Opened when 00422 passed its size warning with N29, with N1: the venv fallback accepts an interpreter that cannot run on this host)

- [00468: claude code plugins are supported properly](Completed/00468-claude-code-plugins-are-supported-properly/PLAN.md) - Complete at `83e75879` + the archiving commit (from the 00467 plugin audit: 8 defects, 3 release-blocking, and 16 gaps, most resting on one missing resolver for the Claude config dir and its enabled plugins; the last criterion waited on 00463's simulate-record fix, now on main)

- [00463: full qa is a main thread gate](Completed/00463-full-qa-is-a-main-thread-gate/PLAN.md) - Complete at `5156a81f`, merged as `83e75879`, CI fix `fd78edce` + the archiving commit (owner request after five worktree agents ran the ~18-minute full suite at once: a guard denies configured full-QA commands in sub-agents, and a pytest sink plus a host-wide lock refuse a whole-suite run not made under the coordinator's gate; live dogfood Task 2.2 carried)

- [00461: journal entries only through the stamping tool](Completed/00461-journal-entries-only-through-the-stamping-tool/PLAN.md) - Complete at `e3f03f3e` + the archiving commit (owner directive after a session of hand-stamped entries, one 40 minutes in the future: an Edit/Write/Bash append to a plan `JOURNAL/` day-file, in the main checkout or a worktree, is DENIED and pointed at `mkplan.bash --journal`; remedies 00422 N21)

- [00460: report size blocker gives read only agents a way out](Completed/00460-report-size-blocker-gives-read-only-agents-a-way-out/PLAN.md) - Complete at `ca2b1ba5` + the archiving commit (owner report: the size blocker told every agent to write its report to a file, which a read-only type cannot do; the daemon now saves every stopping sub-agent's reply to a pruned file and the blocker points at it)

- [00462: php lsp advice keeps composer dependencies indexed](Completed/00462-php-lsp-advice-keeps-composer-dependencies-indexed/PLAN.md) - Complete at `830363e5` + the archiving commit (from #56: the PHP advice asked intelephense to exclude all of `**/vendor`, which drops every Composer dependency from its index; the strategy now keeps dependency roots indexed and asks only for intelephense's nested excludes, and flags an override that excludes the whole tree)

- [00456: missing venv self heals and repair runs without one](Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md) - Complete at `9e2f74cd` + the archiving commit (the rest of #53: a hook with no venv starts one detached, locked build; `repair` runs without a venv; the skill never auto-forces and a `--force` keeps other environments' venvs; carries Plan 00100 Phase 3.5)

- [00459: encrypted vault files are tracked not hidden](Completed/00459-encrypted-vault-files-are-tracked-not-hidden/PLAN.md) - Complete at `2a6a9b84` + the archiving commit (owner report: secret-file globs select by NAME, so Ansible Vault ciphertext was told to be untracked; a whole-file content check at each use, failing closed, now separates it from the plaintext password file)

- [00458: skip lists match path segments relative to the project](Completed/00458-skip-lists-match-path-segments-relative-to-the-project/PLAN.md) - Complete at `b8ce4b49`…`47999859` + the archiving commit (from 00422 N20: six guards matched skip lists as a bare substring, so a worktree named `…-venv` switched them off; they now match project-relative segments, and a QA detector keeps the class out)

- [00457: signal runs without a venv](Completed/00457-signal-runs-without-a-venv/PLAN.md) - Complete at `6eb51575` + the archiving commit (from #55: `signal` is dispatched before venv resolution through a standard-library-only entry point, so the host-side reboot warning works where the only venv was built in a container)

- [00455: self install exposes the conventional cli path](Completed/00455-self-install-exposes-the-conventional-cli-path/PLAN.md) - Complete at `e6a11e19` + the archiving commit (from #54: the self-install daemon generates the conventional CLI link under the gitignored directory, because a tracked one would reach every client clone as a nested install; install-mode checks now require a real clone. Review reverted a copied exemption, filed as 00422 N19)

- [00454: not installed message steers to destructive reinstall](Completed/00454-not-installed-message-steers-to-destructive-reinstall/PLAN.md) - Complete at `f299681f` + the archiving commit (first slice of #53: a clone with no venv for this path now gets its own diagnosis naming a version-pinned upgrade, not the install advice that `rm -rf`s the other view's venv; #53 stays open)

  Older completed plans (below the retention window of the 30 highest-numbered) are archived verbatim in [Completed/README.md](Completed/README.md).

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

- **Total Plans Created**: 507 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 433 (includes 1 reduced-scope plan and 6 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 51 (count = root `NNNNN-*` plan folders; includes several dormant plans awaiting scheduling)

- **On Hold**: 0

- **Cancelled/Abandoned**: 13 on disk (count = `Cancelled/` folders: 00032/00034/00035 won't do — delegate mode no longer exists, 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00108 superseded by 00117, 00131 residue declined, 00132 superseded by 00284, 00174 superseded by 00175, 00199 superseded by 00213, 00135 superseded by the supervisor workstream)

- **Folder-to-number reconciliation**: 38 + 413 + 13 = **464 folders**, spanning
  **461 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **13** of the
  474 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258, 00300, 00303, 00325 — abandoned drafts, numbers
  burned by transient probes (00195 during the v3.51.0 acceptance run, 00258
  during the v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a
  sub-agent that then found Plan 00208 already covered the work).
  461 + 13 = 474. ✅

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

# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

Ordered as the roadmap: tiers run top to bottom in the order the work will be done.

### Now (in flight)

- [00596: destructive git printed text captured or formatted](00596-destructive-git-printed-text-captured-or-formatted/PLAN.md) - In Progress (GitHub #197: printed git text captured by a substitution or piped to a formatter is read as a git command)

- [00560: scratch directory unrecorded assets](00560-scratch-directory-unrecorded-assets/PLAN.md) - In Progress (GitHub #155: scratch holds only files consumed in the same session; stop the steering, a scratch file-name whitelist, consume-then-remove for body files and a SessionStart sweep; ledger and stop gate dropped by the owner; Phase 1 design written, Q5 open for the owner)

- [00594: branch lifecycle and branch tip channel](00594-branch-lifecycle-and-branch-tip-channel/PLAN.md) - In Progress (DESIGN.md draft written, awaiting client-seat review; owner request via a client team: redesign the whole branch lifecycle (birth, finish, proof of merge, delete, park, owner) from nine failure classes seen in multi-agent client use, plus letting a client follow a daemon branch tip with a one-step return to the last tag; design first, no guard change ships before review)

### Next (ordered; work top to bottom)

Triage GitHub #169-#173 first (issue triage, not a plan). Then these plans, in this order:

- [00464: commit gates judge the checkout the command runs in](00464-commit-gates-judge-the-checkout-the-command-runs-in/PLAN.md) - Not Started (from 00422 N23: commit gates pick their repo from the payload `cwd`, which for a teammate is the main checkout, so a worktree commit is judged on main's staged tree — false denies, and its own content, secret terms included, never checked)

- [00465: commit gates see the index after same command staging](00465-commit-gates-see-the-index-after-same-command-staging/PLAN.md) - Not Started (from 00422 N26: gates read the index before the command runs, so `git add f && git commit` passes the secret-term scan and every other staged-content gate unexamined; starts after 00464, same gates)

- [00473: post merge handlers judge the command repository](00473-post-merge-handlers-judge-the-command-repository/PLAN.md) - Not Started (graduated from 00468 G9: `daemon_sync_after_merge` and `merge_qa_report` judge the repository the payload `cwd` names, not the one the command ran in; blocked on Plan 00464's command-directory resolver)

- [00481: release 3.67 retrospective - how #68 shipped, and the QA gaps](00481-release-3-67-retrospective-qa-gaps/PLAN.md) - Not Started (owner request: a causal account, gate by gate, of how #68 reached a release, then a realistic-command corpus gate and an evaluation-error release signal, each proven against the pre-fix tree)

- [00421: security detectors and ci enforcement](00421-security-detectors-and-ci-enforcement/PLAN.md) - Not Started (`qa.yml` runs no `scripts/qa/check_*.py` at all, so no Detector this project treats as binding has ever been enforced in CI. The single successor to 00412, carrying the four Fable rulings' unbuilt work: pin what makes a Detector binding, make the register state its own gaps, migrate the test-shaped Defences, then build the seven unwatched classes)

- [00482: handler crash containment](00482-handler-crash-containment/PLAN.md) - Not Started (owner ruling after #68: handlers must never crash; a crash gets a crash record and a bug-report request, non-safety handlers are disabled after N crashes, safety guards stay fail-closed pending the owner's decision)

- [00420: dangerous command rule modes and config migration](00420-dangerous-command-rule-modes-and-config-migration/PLAN.md) - Not Started (per-rule-ID `block`/`warn`/`off` across the dangerous-command handlers, plus the loud, migrating config upgrade that a moved key requires)

- [00582: guard rollout and transitional grandfathering](00582-guard-rollout-and-transitional-grandfathering/PLAN.md) - Not Started (owner request: one best-practice document for introducing or tightening a guard, and a shared shrink-only, deadline-bound grandfather snapshot recorded by a command, adopted first by the branch guards; past the deadline the normal deny applies)

- [00585: repository facts service](00585-repository-facts-service/PLAN.md) - Not Started (owner ruling: one rich, automatically refreshed cache of GitHub repository facts — visibility, native drafts, default branch, branch protection, the account's permission — with per-fact age and an `unknown` state, never hand-kept config; per-clone and untracked, not the Plan 00564 meta ref; Plan 00584 and `issue-validity` consume it)

- [00584: pull requests start as drafts](00584-pull-requests-start-as-drafts/PLAN.md) - Not Started (owner request: every PR is created with a `[DRAFT]` title prefix everywhere, plus `--draft` where GitHub offers native drafts; leaving draft removes the prefix in the same step, `gh pr ready --undo` re-adds it; the release flows comply)

- [00586: five small defects, verify then fix](00586-five-small-defects-verify-then-fix/PLAN.md) - Not Started, Medium (five defects noticed in passing: each task reproduces the defect first and closes with evidence and no change if it does not reproduce)

- [00448: plan completion gate has no commit time backstop](00448-plan-completion-gate-has-no-commit-time-backstop/PLAN.md) - Not Started (the Complete-flip gate keys on Write/Edit only, so a `PLAN.md` written through Bash escapes it — as Plan 00437 did)

- [00410: gitignore swallows deployed assets](00410-gitignore-swallows-deployed-assets/PLAN.md) - Not Started (an unanchored `hooks-daemon/` ignore pattern matches at every depth, so it hides the deployed `.claude/skills/hooks-daemon/` tree as well as the intended clone; this repo is already anchored, but nothing DETECTS the mistake, and an ignored file cannot drift visibly. Owner-reported from a client project)

- [00469: qa packages import plan qa from shared layers](00469-qa-packages-import-plan-qa-from-shared-layers/PLAN.md) - Not Started (graduated from 00422 N14: the last two declared `utils`/`docs_qa` → `plan_qa` import edges; the status-line grammar and the tier constants move into shared `utils` modules so `_KNOWN_EDGES` empties. Starts after the 00466 goal-flip branch merges)

- [00485: split subagent full qa blocker](00485-split-subagent-full-qa-blocker/PLAN.md) - Not Started (owner-delegated Fable ruling on 00466 N96: pure-refactor split of the 5,300-line handler along its class seams; starts only once no open branch touches the file)

### Blocked on the owner

- [00578: local settings files untracked and guarded](00578-local-settings-files-untracked-and-guarded/PLAN.md) - Blocked on the owner (GitHub #189, parked: this repository tracks `.claude/settings.local.json` by Plan 00468's design, and nothing ignores or guards it or `CLAUDE.local.md` in clients; Q1-Q4 decide untracking, client `.gitignore` entries and a new staging guard) **Blocked on: the owner must answer Q1-Q4 (untracking, client `.gitignore` entries, a new staging guard).**

- [00568: admin merge bypass guard](00568-admin-merge-bypass-guard/PLAN.md) - Not Started (GitHub #160, parked on owner questions: a configurable Bash handler denying `gh pr merge --admin`, the REST merge endpoint and the `mergePullRequest` mutation, so an admin token cannot merge past branch protection) **Blocked on: owner questions on the configurable admin-merge deny.**

- [00559: daemon clone follows expected version after pull](00559-daemon-clone-follows-expected-version-after-pull/PLAN.md) - Not Started (#148, parked `agent-needs-human`: a pull that moves `expected_version` should re-provision from a trigger outside the stale daemon; owner to choose the trigger, the retry rule and whether to add a scheduled check) **Blocked on: the owner must choose the re-provision trigger, the retry rule and whether to add a scheduled check.**

- [00550: per command bash task budget](00550-per-command-bash-task-budget/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #137: a `CLAUDE_CODE_SHELL_PREFIX` wrapper giving each Bash tool call its own task budget so one runaway fork chain cannot kill the session; it wraps every Bash call and hook, so shipping it and its default are owner decisions) **Blocked on: the owner must decide whether to ship the `CLAUDE_CODE_SHELL_PREFIX` wrapper and its default.**

- [00526: supervisor plugin relay result](00526-supervisor-plugin-relay-result/PLAN.md) - Not Started (#119, agent-needs-human: a plugin API 1.1 `Relay` result types external message text into the session; a new prompt-injection surface, so build or not is the owner's call) **Blocked on: the owner must decide whether to build a new prompt-injection surface (the `Relay` result).**

- [00519: minimum tool versions and relative worktrees](00519-minimum-tool-versions-and-relative-worktrees/PLAN.md) - Blocked on owner input (#110: relative worktrees need git 2.48, and this container runs 2.39.5; Phase 1, the declared minimum-version check, is not blocked) **Blocked on: the owner must decide on the git 2.48 requirement for relative worktrees (this container runs 2.39.5).**

- [00516: journal in place redaction](00516-journal-in-place-redaction/PLAN.md) - Not Started, Medium (#108; awaiting owner decisions: a bounded `mkplan.bash --journal-redact` to remove a leaked value from a past journal entry with an appended correction entry, since `journal-dayfile-is-today` blocks any past-day edit; ledger 00474 N389) **Blocked on: the owner must decide the bounded `--journal-redact` design.**

- [00515: per host handler overrides](00515-per-host-handler-overrides/PLAN.md) - Not Started, Medium (#93; awaiting owner decisions: per-host or per-role `handlers:` overlays in Plan 00479's top-level `hosts:` block, including whether an overlay may disable a guard) **Blocked on: the owner must decide whether a per-host overlay may disable a guard.**

- [00513: per model effort coverage check](00513-per-model-effort-coverage-check/PLAN.md) - Not Started, Medium (#87; awaiting owner decisions: a presence-only check naming every effort-capable model with no `modelSettings` level, which needs a maintained table of model IDs; the false OK text is ledger 00474 N439) **Blocked on: the owner must decide on the maintained model-ID table for the coverage check.**

- [00501: session modes](00501-session-modes/PLAN.md) - Blocked on the owner, Medium (#91; per-session modes: focus, BLOCKED, usage-paused; guards never gated) **Blocked on: Task 7.2 needs an owner-driven live acceptance session.**

- [00484: DBF adoption and toolchain conformance](00484-dbf-adoption-and-toolchain-conformance/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)) (owner ruling: fully adopt Defence Before Fix and link it, #65 and #67; assess the daemon as a DBF toolchain against TOOLING-SPEC and let DBF tools enumerate its defences) **Blocked on: the owner questions in Plan 00474's OWNER-QUESTIONS file.**

- [00479: subscription usage monitor and ceiling](00479-subscription-usage-monitor-and-ceiling/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)) (owner request: a status-line 5-hour/weekly usage segment, plus a per-host usage ceiling in a host-first `hosts:` block so unattended sessions stop before exhausting the subscription) **Blocked on: the owner questions in Plan 00474's OWNER-QUESTIONS file.**

- [00474: niggles ledger seventeen](00474-niggles-ledger-seventeen/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)), the OPEN ledger for new niggles (00466 reached its PLAN.md size limit with N261; numbering continues, opening with N262: the release procedure has no check that the notes fit a GitHub release body) **Blocked on: the owner questions in its OWNER-QUESTIONS file.**

- [00470: persistent session optimisation](00470-persistent-session-optimisation/PLAN.md) - Blocked on the owner ([owner questions](00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md)) (owner request: the always-on server session is the dogfood; cron refresh, usage-limit and restart recovery, a timed stand-in for a human block, and a measured orchestrator-model choice) **Blocked on: the owner questions in Plan 00474's OWNER-QUESTIONS file.**

- [00467: recommend the defence before fix plugin to client projects](00467-recommend-the-defence-before-fix-plugin-to-client-projects/PLAN.md) - Blocked (owner request: dogfood the DBF plugin, then recommend it to clients. Phase 1 is done, with shortfalls filed upstream as #4-#6 and recommendation no-go for now. Waiting on the owner's go/no-go, and on one logged-in auto-trigger probe) **Blocked on: the owner's go/no-go on recommending the DBF plugin, plus one logged-in auto-trigger probe.**

- [00452: prompt cache observability and invalidation protection](00452-prompt-cache-observability-and-invalidation-protection/PLAN.md) - Blocked on owner input (status segment shipped as main, sub and token-weighted total; what remains needs `/usage` run in-session and a gap profile from a human-paced project, Task 2.4) **Blocked on: a human running `/usage` in-session and a gap profile from a human-paced project (Task 2.4).**

- [00447: magic constant advisory policy](00447-magic-constant-advisory-policy/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #49: the reported constant is verified real and is a GrowthBook experiment gate on the bash-first injection, one of 642 `CLAUDE_CODE_*` tokens in the build — so whether the daemon should advise on cohort-assigned experiment flags at all is a policy question, and it subsumes 00428's blocker) **Blocked on: the owner's policy call.**

- [00428: auto compact window audit check](00428-auto-compact-window-audit-check/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #46: a seventh `optimal_config_checker` check for `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; the gap is real but the spec was retracted and replaced by one inferred from a compiled CLI, which triage could not verify) **Blocked on: the owner must settle the spec, which was retracted and replaced by one inferred from a compiled CLI.**

- [00399: supervisor does not see tab completed slash commands](00399-supervisor-does-not-see-tab-completed-slash-commands/PLAN.md) - Blocked (ruled option 2 shipped: the supervisor reads a Tab-completed `/compact` from the daemon's `PreCompact` record, which now carries its origin. Only Task 2.1 remains, and it needs a human: typing `/comp`, Tab, Enter in the real tmux-wrapped session to show whether tmux changes the byte stream) **Blocked on: a human running Task 2.1.**

- [00453: supervisor modal overlay](00453-supervisor-modal-overlay/PLAN.md) - Not Started (the status-line banner from Plan 00173/00318 is a one-line TTL notification and structurally cannot hold history; this adds a hotkey-summoned inspection surface costing no model turn, no transcript entry and no status-line space — gated on the owner choosing a hotkey, F12 and F3 already rejected) **Blocked on: the owner must choose a hotkey (F12 and F3 already rejected).**

### Later

- [00129: Wire llm-friendly-qa-wrappers in as a Major Dependency](00129-llm-qa-wrappers-integration/PLAN.md) - Not Started

  - GitHub Issue [#33](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/33)
  - Adopt [`edmondscommerce/llm-friendly-qa-wrappers`](https://github.com/edmondscommerce/llm-friendly-qa-wrappers) (terse-terminal + JSON-to-tempfile wrappers around ESLint/PHPStan/Ruff/etc.) as a major …
  - Single schema-validated `raw command → wrapper invocation` SSOT via Strategy + Registry (no hardcoded if/elif)
  - Secondary strand: global `--json` mode on [`lts/php-qa-ci`](https://github.com/LongTermSupport/php-qa-ci) (`bin/qa` Bash pipeline) so the whole PHP pipeline emits one machine-readable result, vs. wrapping each PHP tool individually
  - Reference repos cloned to `untracked/repos/`; wrapper repo audit captured in `AUDIT-llm-friendly-qa-wrappers.md`; adoption gated on the audit verdict

- [00204: security_antipattern — the three data-flow categories](00204-security-antipattern-dataflow-categories/PLAN.md) - Not Started (v3.52.0 corrected guidance that claimed SQL injection, weak cryptography and path traversal were blocked when no strategy implements any of them; this decides whether construct-level regexes can carry signal for them without the false-positive rate that gets a handler disabled.)

- [00264: cap the size of a GitHub issue/PR comment](00264-github-comment-size-cap/PLAN.md) - Not Started (field report: agent sessions flooded two issues with 44,467- and 22,398-character comments until neither ticket's state was findable by the humans reading it; a PreToolUse cap on `gh` comment bodies steering the content into `JOURNAL/`, plus seven open questions the report's proposed design asserts rather than settles)

- [00280: workflow agent model cap in standing authorisation](00280-workflow-agent-model-cap-authorisation/PLAN.md) - Not Started (extend the built-in `workflow-orchestration` standing authorisation with a configurable model cap for workflow/sub-agents — default: Sonnet encouraged, Opus as required, Fable banned)

- [00344: stop hook deny rate classification](00344-stop-hook-deny-rate-classification/PLAN.md) - Not Started (Plan 00337 Task 5.0 shipped the instrumentation but the classification needs telemetry across many sessions — 49 instrumented rows exist and 48 are acceptance probes, because a real Stop event fires roughly once per session)

- [00391: plan close requires proven definition of done](00391-plan-close-requires-proven-definition-of-done/PLAN.md) - Not Started (a project declares its DoD in config; the close is denied until each item is CHECKED or attested with evidence in the plan's JOURNAL/, and a three-way policy — human_gate, encourage, neutral — subsumes Plan 00367's boolean. `encourage` is the direction that would have caught 00386/00389 sitting finished-but-open)

- [00396: detect a plan written without reading its domain docs](00396-detect-a-plan-written-without-reading-its-domain-docs/PLAN.md) - Not Started (a plan was filed about deployment by a session that had read none of the deployment docs; the signature is mechanical — a PLAN.md filled about domain X with zero reads of X's owning docs — and `write_clobber_guard` already tracks per-session reads. Advisory, inert until a project declares a topic map)

- [00489: supervisor in-container restart primitive](00489-supervisor-in-container-restart-primitive/PLAN.md) - Not Started (owner decision D2 in Plan 00487, #71: 00487's Tasks 1.4 and 1.5, the in-container `Restart` and the host-half `before_spawn` that the fedora-desktop 00146 credential switch needs)

- [00491: code quality and architecture review](00491-code-quality-and-architecture-review/PLAN.md) - Not Started (owner ruling B5: a read-only review of module size, DRY, architecture and code quality, then owner-chosen refactoring; N314 folds in)

- [00496: upstream feature requests and issue kinds](00496-upstream-feature-requests-and-issue-kinds/PLAN.md) - Not Started (owner request: a formal process for project agents to file feature requests and other non-defect issues, mirroring the defect generator, guard and forms; security reports routed privately)

- [00497: hooks daemon mod](00497-hooks-daemon-mod/PLAN.md) - Not Started (owner-approved build from Plan 00494: daemon mod awareness with an exceptionally loud warning, a human task and question queue, one mod deployed by install and upgrade, suggested prompts, SessionStart messages, then session resilience)

- [00502: merge requires approval](00502-merge-requires-approval/PLAN.md) - Not Started (owner rulings: the merge gate becomes "merge requires APPROVAL" with a configurable human or agent approver, default a clean sub-agent at minimum model `opus` or a named project review sub-agent; the core design is a daemon-written, tip-bound approval record the merging agent cannot forge, plus migration from the old human-approval boolean)

- [00523: supervisor answers the rate limit menu](00523-supervisor-answers-the-rate-limit-menu/PLAN.md) - Not Started (owner request: press Enter on Claude Code's rate-limit menu so an unattended session waits for the reset)

- [00524: foreground blocking wait goes to the background](00524-foreground-blocking-wait-goes-to-the-background/PLAN.md) - Not Started (#117, agent-needs-human: deny or advise a foreground wait-only Bash call; the existing liveness-loop fix text recommends one)

- [00530: subagent tier enforcement follow up](00530-subagent-tier-enforcement-follow-up/PLAN.md) - Not Started (opened by the Plan 00472 build per its Fable rulings' section 3: confirm the Workflow advisor against a real payload, then decide the Workflow deny mode, `require_explicit` and the `CLAUDE_CODE_SUBAGENT_MODEL` flip from measured evidence)

- [00534: overload shedding and lint backoff](00534-overload-shedding-and-lint-backoff/PLAN.md) - Not Started (#124 follow-up from the owner's overload discussion: wait, then shed expensive non-safety work and never the guards; a consecutive-timeout lint backoff; linter timeouts that fit the chain budget; an honest "host overloaded: pause" deny)

- [00535: upgrade handover without live daemon rebuild](00535-upgrade-handover-without-live-daemon-rebuild/PLAN.md) - Not Started (#124 follow-up: an upgrade never rebuilds the venv or checks out source under a daemon still serving sessions)

- [00536: persistent daemon saturation log](00536-persistent-daemon-saturation-log/PLAN.md) - Not Started (#124 follow-up: a bounded journal of saturation episodes, straggler restarts and forced stops that survives a daemon restart, with a verb to print it)

- [00538: supervisor auto refocus and focus signal](00538-supervisor-auto-refocus-and-focus-signal/PLAN.md) - Not Started (#125 follow-up: a spike for a non-screen focus signal; auto-refocus and the mods route are owner decisions)

- [00548: python entry point shebang detector](00548-python-entry-point-shebang-detector/PLAN.md) - Not Started (follow-up to 00546 Q2: a detector for client-run Python entry points that do 3.11-only work before any floor guard; probe results recorded as a known gap)

- [00564: remote meta ref allocator](00564-remote-meta-ref-allocator/PLAN.md) - Not Started (owner proposal, not for the next release: plan numbers allocated by compare-and-swap on a remote metadata ref, `refs/hooks-daemon/meta`, with an offline fallback to Plan 00562's scan and a recovery step)

- [00574: plan decisions log document](00574-plan-decisions-log-document/PLAN.md) - Not Started (owner request, for later: a per-plan `PLAN-DECISIONS.md`, pre-created by mkplan, as an unbounded, parseable decision log keyed by task id, so PLAN.md stays the front page of tasks and progress and JOURNAL/ stays ad hoc; adversarial review in progress)

- [00575: release validated handler catalogue](00575-release-validated-handler-catalogue/PLAN.md) - Not Started (owner request, post-release: one generated catalogue of every handler with source and test links, validated by a CI test and a RELEASING.md gate)

### Dormant

- [00085: Reminder Pseudo-Event System with Adaptive Triggers](00085-reminder-pseudo-event-system/PLAN.md) - Dormant (8-phase build deferred to a future release window)

  - 8 phases — AdaptiveTrigger, config parsing, dispatcher, WorkflowReminderSetup, handler, constants/registration, config, verification
  - Dependency chain resolved: 00077 (Already Shipped) and 00081 (Superseded by 00082) both closed in Plan 00107 Wave 3

- [00100 (v3): Venv SSOT Consolidation](00100-venv-ssot-consolidation/PLAN.md) - Dormant (residue scope awaits scheduling)

  - Phases 0–3.9 **shipped** in v3.9.0 / v3.10.0 / v3.11.0 (canonical SSOT resolver, `.daemon-metadata.json` writers, dead-code removal, path slug, eager upgrade cleanup, H-1 gate coverage)
  - **Residue deferred from v3.12.0** (Plan 00107 Wave 4): Phase 4 (flock concurrency), Phase 5 (parameterised upgrade-cycle test), Phase 6 (docs) … Phase 3.5.2–3.5.7 (bootstrap-fallback wiring) is carried by [Plan 00456](Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md), no longer residue here
  - Phases 1–4 complete (`bash <path>` invocation, auto-migration, self-heal, filemode checker)
  - **Task 5.3 pending**: acceptance gate at v3.12.0 release time (folded into meta plan 00107 Wave 6 `/release` execution)

- [00144: Plan QA System — Real-Time Plan Validation & Drift Enforcement](00144-plan-qa-system/PLAN.md) - Dormant (all six phases shipped in v3.32.0; blocked only on a human go/no-go to ratchet `commit_gate_mode` from `warn` to `block`)

  - Pure `plan_qa` core (PlanTree/PlanDoc/ReadmeIndex parsers + declarative check registry) consumed by three surfaces: edit-time PreToolUse lint, `git commit` cross-file gate (warn→block ratchet), and …
  - Enforces status-header integrity, index-at-birth, terminal-state atomicity (`git mv` + README row + stats in one commit), number-collision defence, and required archive dirs (`Completed/`/`Cancelled/`, configurable)
  - Config under `plan_workflow.qa`; grandfathering for legacy plans; spec provenance: `untracked/hooks-daemon-plan-verify-qa.md` (31-sin audit catalogue)

- [00158: Agent Thread Navigation & Status Line](00158-agent-thread-navigation-statusline/PLAN.md) - Dormant (Phase 1 research/dogfood complete; Phases 2–4 waited on Plan 00174's `subagentStatusLine` rendering design, which is now Superseded — the dependency needs re-deciding, not merely re-pointing, since 00175 concluded the artefact store should not be built)

  - Documents the dogfood-verified Claude Code contract for the main `statusLine` and the newer `subagentStatusLine` surfaces; root-causes the "no status line / whose data?" symptoms under Agent View (arrow-key thread navigation)
  - Scopes daemon support for `subagentStatusLine` (per-thread agent-panel rows) plus a `statusLine` `refreshInterval` so the bar stays live while background agents run
  - Confirmed live: main bar payload carries NO agent-thread identity (always renders main session); we wire only `statusLine` today

- [00160: Supervisor Foreground Identity & Dead-File Reaping](00160-supervisor-foreground-identity-and-reaping/PLAN.md) - Dormant (00135 follow-up: reap dead sidecars/signals + bind the supervisor to the foreground session; remaining verification needs a live 2-thread Agent-View session that cannot be forced from inside a supervised one)

- [00163: Plan Journalling — first-class per-plan JOURNAL/ support](00163-plan-journalling/PLAN.md) - Dormant (Phases 1–2 shipped in v3.40.0; Task 3.2 is the sole open item)

  - Every plan folder gains a `JOURNAL/` of per-day append-only files `NNNNN-Journal-YY-MM-DD.md` — the linear activity log (findings, decisions, dead-ends, hand-offs) complementary to PLAN.md, with a fixed entry grammar (`## HH:MM · category · REF`)
  - First-class via the existing plan_qa surfaces (no new handler): six advise-first checks (`journal-dayfile-naming`, `journal-append-only`, `journal-folder-present`, `journal-freshness`, plus deferred …
  - Dogfood in this repo first (Plan 00163 journals itself), then client rollout with a copyable `CLAUDE/PlanJournalling.md` reference doc; `## Notes & Updates` subsumed into JOURNAL with a curated `## Delivery & Milestones` stub kept in PLAN.md

- [00170: Universal Hook Coverage + Hook-Support Enforcement](00170-universal-hook-coverage-and-enforcement/PLAN.md) - Dormant (fundamental: intercepting hook events is the daemon's raison d'être, yet only **10 of the 30** documented Claude Code hook events are wired — 20 are silently unwired, so a client project cannot even …)

- [00175: statusline refreshInterval first-class default + startup validation](00175-statusline-refresh-interval-first-class/PLAN.md) - Dormant, part-shipped (root-caused the Ctrl+Z notice lag to `statusLine.refreshInterval: 10` — Claude Code re-runs the status command only on events (Ctrl+Z is not one) plus this optional timer whose minimum is 1s, so an …)

- [00266: AI-assisted handler decisions](00266-ai-assisted-handler-decisions/PLAN.md) - Dormant (native `prompt`/`agent` hooks measured live: they work, fail CLOSED, cost ~1.2s vs the daemon's ~51ms, and cannot override a daemon deny; dynamic prompting via `tool_use_id` is the leading architecture; parked as reference until a revival condition fires)

## Completed Plans

- [00595: secret guard search string option value bold colon](Completed/00595-secret-guard-search-string-option-value-bold-colon/PLAN.md) - Complete at `eae5878e9` (main CI run 42912436475 green) + the archiving commit (GitHub #200, closed: a git search string, a grep/rg filter value and a colon-split bold are no longer judged as protected paths; release note 045)

- [00593: dependabot security lock bumps](Completed/00593-dependabot-security-lock-bumps/PLAN.md) - Complete at `d1d248e1d` + `cc6ace282` (main CI run 42769393325 green) + the archiving commit (open Dependabot alerts 77 to 18: nltk, anyio, virtualenv, urllib3, cryptography, idna bumped; filelock, mcp, opentelemetry-api held by the latest `safety`/`semgrep` pins; anyio's new `--anyio-mode` added to the full-QA blocker's option table; PR #193 closed)

- [00592: worktree create undo releases initializing lock](Completed/00592-worktree-create-undo-releases-initializing-lock/PLAN.md) - Complete at `fd7e894fa` (merge `c5c9deb82`) + `37d8d31e0` (main CI run 42739985119 success) + the archiving commit (GitHub #173, closed: the failed-add undo releases git's own `initializing` lock and removes the worktree and new branch; another lock is never overridden; leftovers are named in the error; release note 026)

- [00591: claude md auto commit waits for handler sources](Completed/00591-claude-md-auto-commit-waits-for-handler-sources/PLAN.md) - Complete at `7e9a03f28` (merge `a9e0dacdb`; main CI run 42732895459 success) + the archiving commit (GitHub #172, closed: the restart auto-commit of CLAUDE.md is held while a plugin/project handler source is untracked or modified, logging the file; library handlers never hold it; release note 025)

- [00590: daemon dir cd reads only command position](Completed/00590-daemon-dir-cd-reads-only-command-position/PLAN.md) - Complete at `fee5dc457` (merge `46cf5c71a`; main CI run 42724555662 success) + the archiving commit (GitHub #194, closed: R-DAEMON-DIR-CD blanks only `grep`/`rg` search arguments nothing can run, so a search for `"cd "` over a daemon path is allowed; every executing twin still denies; release note 024)

- [00589: explain rule covers plugin handlers](Completed/00589-explain-rule-covers-plugin-handlers/PLAN.md) - Complete at `bb6dbcb58` (merge `5ba1d98a2`; main CI run 42718913878 success) + the archiving commit (GitHub #171, closed: `explain-rule`/`explain-handler` also load the `plugins:` section through the daemon's own loader; a broken plugin is logged and contributes nothing; release note 023)

- [00588: lsp_enforcement leaves stdin greps and git grep alone](Completed/00588-lsp-enforcement-stdin-and-git-grep/PLAN.md) - Complete at `a0ac71f37` (main CI run 42706023447 success) + the archiving commit (GitHub #169, closed: a grep fed by a pipe, `<` or `<<<` with no file target, and any `git grep`, are not judged as symbol lookups; real lookups stay enforced; release note 021)

- [00587: containment follows a cd into compound command bodies](Completed/00587-containment-cd-into-compound-bodies/PLAN.md) - Complete at `f05530f35` (main CI run 42697064932 success) + the archiving commit (GitHub #195, closed: a `../` redirect in a loop, `if` or `( )` body after a `cd` is resolved from the `cd` target; a `cd` that may have failed still denies; release note 020)

- [00583: branch guard notices state intent and action](Completed/00583-branch-guard-notices-state-intent-and-action/PLAN.md) - Complete at `d60da0fda` (merged via `7d954f213`; main CI run 42682133539, full suite, success) + the archiving commit (GitHub #192, closed: the dormancy Stop line, `branch-sweep`'s Dormant section and the `wip.cap` deny each carry `BRANCH_LIMIT_PRINCIPLE` and a next action per branch, and the session is told to take that work on first; release note 018)

- [00581: provision repairs a stale venv](Completed/00581-provision-repairs-a-stale-venv/PLAN.md) - Complete at `cfa601263` (CI run 42650039659 success) + the archiving commit (GitHub #168, closed: at the expected version `provision.sh` checks the venv's lock hash; a foreground run repairs a stale venv through the bootstrap repair, a background run names `hooks-daemon repair`, an unreadable hash counts as stale; release note 017)

- [00580: optional seed entries are not missing](Completed/00580-optional-seed-entries-are-not-missing/PLAN.md) - Complete at `1b1cbb079` (CI run 42636878356 success) + the archiving commit (GitHub #167, closed: `check-worktree-seed` no longer lists an absent `optional: true` seed entry as MISSING or tells the reader to remove it; an absent required entry still is; release note 016)

- [00579: copy seeded files and worktree removal](Completed/00579-copy-seeded-files-and-worktree-removal/PLAN.md) - Complete at merge `a26be56b0` (main CI run 42762876632 green) + the archiving commit (#164, closed: a copy-mode seed byte-identical to its source in the main checkout no longer blocks a worktree removal; a diverged, missing or worktree-resolving source still blocks and is named; bounded comparison; release note 030)

- [00577: forwarder stubs shellcheck clean](Completed/00577-forwarder-stubs-shellcheck-clean/PLAN.md) - Complete at `43250b5fb` (CI run 42627973690 success) + the archiving commit (GitHub #163, closed: generated hook stubs export the relay-unused marker the sourced init.sh reads, so `shellcheck --severity=warning` is clean with no suppression; a test shellchecks the stub generated for every event; release note 015)

- [00576: hotfix release fast path](Completed/00576-hotfix-release-fast-path/PLAN.md) - Complete at merge `8bfcad71f` (PR #190) + the archiving commit (owner request after v3.73.1: `/release hotfix` runs the RELEASING.md "Hotfix fast path" and the state file and `release_blocker` name the mode; advise-severity plan/docs QA findings never fail CI; a test pins the release gate's cancel-in-progress concurrency, which the journal shows did cancel the superseded v3.73.1 run; release note 013)

- [00572: ci wall clock sharding arm and hygiene](Completed/00572-ci-wall-clock-sharding-arm-and-hygiene/PLAN.md) - Complete at merge `f2d532f89` (PR #187) + the archiving commit (owner request: `qa.yml` reuses release-gate's shard matrix, so the nightly fell from 116 to 28.5 min; every `main` push gets a verdict; native and released aarch64 relay and hooks-screen, a non-blocking arm64 test leg, SHA-pinned actions; release notes 006, 012)

- [00571: branch pools parked merged caps](Completed/00571-branch-pools-parked-merged-caps/PLAN.md) - Complete at merge `9314a6e4c` (PR #186) + `7a917cff9` (green CI) + the archiving commit (GitHub #165, closed: open, parked and merged branches are three pools, each with its own cap, max age and deny rule; `branch-keep`, `branches.bot_owned`, safe `branch-sweep --clean --remote`; release note 007)

- [00573: admin seat issue assignment override](Completed/00573-admin-seat-issue-assignment-override/PLAN.md) - Complete at merge `a2b7f27e9` + the archiving commit (owner ruling: a repository admin seat is never blocked by a non-admin's issue assignment; it gets an advisory, and `issue-validity --claim` performs a recorded takeover; non-admin seats and other admins' claims keep the duplicate-work block; dogfooded live on #155; ships in the release after v3.73.0, release note 004)

- [00570: branch containment remote archive refs](Completed/00570-branch-containment-remote-archive-refs/PLAN.md) - Complete at merge `df4a928e9` (green CI run 42404687976) + the archiving commit (GitHub #166: branch-sweep and delete-branch accept a remote ref outside `refs/remotes`, such as an archive namespace, as proof of containment via one bounded `ls-remote`; the offline wording says only what it checked; release note 004)

- [00569: hooks screen target by host arch](Completed/00569-hooks-screen-target-by-host-arch/PLAN.md) - Complete at merge `ae0af5761` (green CI run 42404687976) + the archiving commit (GitHub #174: the ccy supervisor and `screen/build.sh` choose the hooks-screen musl target triple from the host architecture, x86_64 or aarch64, and the failure note names the architecture; release note 003)

- [00567: lsp coverage extensionless file targets](Completed/00567-lsp-coverage-extensionless-file-targets/PLAN.md) - Complete at merge `6ab6b7bfb` + the archiving commit (GitHub #162: named file targets are judged by their own suffix, an extensionless file counts as unserved, so a grep over extensionless scripts gets the same advisory as a search of their directory; release note 002)

- [00566: nested worktree create root anchoring](Completed/00566-nested-worktree-create-root-anchoring/PLAN.md) - Complete, already delivered (GitHub #161: Plan 00474 N563 `dc45486fa` had anchored `worktree_create` on the main checkout in v3.72.0; this plan adds regression tests only, merged via `82673feec`; no release-bound consequence)

- [00565: gh view comments suggestion hides body](Completed/00565-gh-view-comments-suggestion-hides-body/PLAN.md) - Complete at merge `eed7fd934` + the archiving commit (GitHub #158: `gh_issue_comments` / `gh_pr_comments` suggest `--json title,body,state,comments` instead of `--comments`, which prints only comments without a TTY; release note 001)

- [00563: optimise suggests claudemd excludes](Completed/00563-optimise-suggests-claudemd-excludes/PLAN.md) - Complete at merge `d95c988f1` + `3f5a5dff3` + the archiving commit (owner ruling on Plan 00561 Q1: `/hooks-daemon optimise` lists an unscored `claudeMdExcludes` suggestion for worktree roots under the project that no glob covers; never writes it; release note 001)

- [00562: cross clone plan number allocation](Completed/00562-cross-clone-plan-number-allocation/PLAN.md) - Complete at merge `5289e8fad` + `9b21e9c5c` + the archiving commit (GitHub #154: `mkplan.bash` fetches with a time limit and reads the plan folders on every remote branch before allocating; hooks read already-fetched refs only; release note 033; the not-yet-pushed race is Plan 00564)

- [00558: branch WIP limit and hygiene](Completed/00558-git-branch-hygiene-sweep/PLAN.md) - Complete at the Plan 00558 merges + `0c75cfa0b`, `42502078a`, `bce4f829c` + the archiving commit (GitHub #152: a blocking WIP cap of 10 over every branch, dormancy limits, park and lossless delete, a Stop/SubagentStop guard against abandoned branches, lossless cleanup after merge and worktree removal; release notes 023-032)

- [00561: worktree sub-agents load the root CLAUDE.md twice](Completed/00561-worktree-claudemd-duplicate-load/PLAN.md) - Complete at merge `3d50b7077` + the archiving commit (#156: `claudeMdExcludes` skips the worktree-root `CLAUDE.md` copies, so a worktree agent loads the root file once; a test derives every worktree root from the code; no release-bound consequence; owner question Q1, whether to recommend or install it for clients, stays open)

- [00556: secret guard bare dotted token mentions](Completed/00556-secret-guard-bare-dotted-token-mentions/PLAN.md) - Complete at merges `209c8d334`, `88d63f4b7`, `3b65a47dc`, `ef9a9042d`, `3ba274408` and the #145/#143 merges + the archiving commit (#141–#146, owner-approved: the secret-guard and write-protected-paths false positives fixed with every true-positive test still denying; release notes 012, 013, 014, 016, 018)

- [00554: rust relay transport default](Completed/00554-rust-relay-transport-default/PLAN.md) - Complete at merge `654ec98e1`, reverted `bce74f191`, reapplied `0bef7acaa` + the archiving commit (owner request: the Rust relay is the default hook transport where the host can run it when `relay_enabled` is absent; `relay_enabled: false` is the legacy opt-in; release note 009)

- [00555: self install venv python version lockout](Completed/00555-self-install-venv-python-version-lockout/PLAN.md) - Complete at merge `ed18bf779` + the archiving commit (the self-install venv was locked out after a system Python moved under it; venv checks compare the `pyvenv.cfg` major.minor, daemon-down access is read-only, Stops are bounded; release note 010)

- [00557: Claude Code idle compact enforcement](Completed/00557-claude-code-idle-compact-enforcement/PLAN.md) - Complete at merge `5577aee1d` + the archiving commit (owner request: idle compaction defaults on and only autoCompactEnabled:false, DISABLE_AUTO_COMPACT, DISABLE_COMPACT and FORCE_PROMPT_CACHING_5M switch it off; the optimal config check reports any disabler and the SessionStart sync writes idleCompaction:true only when absent; release note 011)
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

- **Total Plans Created**: 596 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 503 (includes 1 reduced-scope plan and 6 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 70 (count = root `NNNNN-*` plan folders; includes several dormant plans awaiting scheduling)

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

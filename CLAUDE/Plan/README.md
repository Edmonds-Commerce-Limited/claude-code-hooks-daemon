# Plans Index

This directory contains implementation plans for the Claude Code Hooks Daemon project. Plans follow the workflow defined in `/workspace/CLAUDE/PlanWorkflow.md`.

## Active Plans

- [00464: commit gates judge the checkout the command runs in](00464-commit-gates-judge-the-checkout-the-command-runs-in/PLAN.md) - Not Started (from 00422 N23: commit gates pick their repo from the payload `cwd`, which for a teammate is the main checkout, so a worktree commit is judged on main's staged tree — false denies, and its own content, secret terms included, never checked)

- [00463: full qa is a main thread gate](00463-full-qa-is-a-main-thread-gate/PLAN.md) - Not Started (owner request after five worktree agents ran the ~18-minute full suite at once: a `scope: SUB` guard denies configured full-QA commands in sub-agents and names the targeted forms; the coordinator runs the full gate serially on each branch before merge)

- [00462: php lsp advice keeps composer dependencies indexed](00462-php-lsp-advice-keeps-composer-dependencies-indexed/PLAN.md) - In Progress (#56: `lsp_noise_checker` tells a PHP project to exclude all of `**/vendor` from intelephense, which removes every Composer dependency from the index, so every library type is undefined; Phase 1 implemented and QA-green, Phase 2 merge/close pending)

- [00461: journal entries only through the stamping tool](00461-journal-entries-only-through-the-stamping-tool/PLAN.md) - In Progress (owner directive after a session of hand-stamped entries, one 40 minutes in the future: an Edit/Write/Bash append to a plan `JOURNAL/` day-file is DENIED and pointed at `mkplan.bash --journal`, which shipped in v3.66.0 and was never used)

- [00460: report size blocker gives read only agents a way out](00460-report-size-blocker-gives-read-only-agents-a-way-out/PLAN.md) - Not Started (owner report: the SubagentStop size blocker tells every agent to write its report to a file, so a read-only type either cannot comply or writes it through a Bash heredoc that no content guard sees)

- [00457: signal runs without a venv](00457-signal-runs-without-a-venv/PLAN.md) - Not Started (from #55: the host-side reboot warning is refused where the only venv was built in a container; a standard-library-only entry point, handled before venv resolution using 00456's mechanism, so it starts after 00456 merges)

- [00453: supervisor modal overlay](00453-supervisor-modal-overlay/PLAN.md) - Not Started (the status-line banner from Plan 00173/00318 is a one-line TTL notification and structurally cannot hold history; this adds a hotkey-summoned inspection surface costing no model turn, no transcript entry and no status-line space — gated on the owner choosing a hotkey, F12 and F3 already rejected)

- [00452: prompt cache observability and invalidation protection](00452-prompt-cache-observability-and-invalidation-protection/PLAN.md) - Blocked on owner input (status segment shipped as main, sub and token-weighted total; what remains needs `/usage` run in-session and a gap profile from a human-paced project, Task 2.4)

- [00451: version bump completeness and dependency gate stale verdict](00451-version-bump-completeness-and-dependency-gate-stale-verdict/PLAN.md) - Not Started (three of six version-carrying files are found only when a gate goes red, and the `dependencies` gate leaves a stale `passed: true` on disk when `uv lock --check` aborts it)

- [00450: release skill mandates forbidden subagent acceptance gate](00450-release-skill-mandates-forbidden-subagent-acceptance-gate/PLAN.md) - Not Started (`release/invoke.sh` tells the agent to spawn parallel Haiku agents for Step 12; `acceptance-test/invoke.sh` forbids exactly that by name)

- [00449: unlocked eviction race survives in other handlers](00449-unlocked-eviction-race-survives-in-other-handlers/PLAN.md) - Not Started (Plan 00437 named the class and fixed two of eight-plus sites; `write_clobber_guard` at priority 16 claims to fail CLOSED and does not under contention)

- [00448: plan completion gate has no commit time backstop](00448-plan-completion-gate-has-no-commit-time-backstop/PLAN.md) - Not Started (the Complete-flip gate keys on Write/Edit only, so a `PLAN.md` written through Bash escapes it — as Plan 00437 did)

- [00447: magic constant advisory policy](00447-magic-constant-advisory-policy/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #49: the reported constant is verified real and is a GrowthBook experiment gate on the bash-first injection, one of 642 `CLAUDE_CODE_*` tokens in the build — so whether the daemon should advise on cohort-assigned experiment flags at all is a policy question, and it subsumes 00428's blocker)

- [00428: auto compact window audit check](00428-auto-compact-window-audit-check/PLAN.md) - Not Started, BLOCKED ON THE OWNER (from issue #46: a seventh `optimal_config_checker` check for `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; the gap is real but the spec was retracted and replaced by one inferred from a compiled CLI, which triage could not verify)

- [00422: niggles ledger fifteen](00422-niggles-ledger-fifteen/PLAN.md) - Blocked on four stated owner questions, the OPEN ledger (opens with four entries inherited from 00419 — N8/N11/N12/N13 — because an unresolved entry left inside an archived ledger is indistinguishable from a resolved one; three of them are one class in three costumes: a guard right about the state it judges and wrong about the moment it judges it)

- [00421: security detectors and ci enforcement](00421-security-detectors-and-ci-enforcement/PLAN.md) - Not Started (`qa.yml` runs no `scripts/qa/check_*.py` at all, so no Detector this project treats as binding has ever been enforced in CI. The single successor to 00412, carrying the four Fable rulings' unbuilt work: pin what makes a Detector binding, make the register state its own gaps, migrate the test-shaped Defences, then build the seven unwatched classes)

- [00420: dangerous command rule modes and config migration](00420-dangerous-command-rule-modes-and-config-migration/PLAN.md) - Not Started (per-rule-ID `block`/`warn`/`off` across the dangerous-command handlers, plus the loud, migrating config upgrade that a moved key requires)

- [00415: config is invisible to the freshness guard](00415-config-is-invisible-to-the-freshness-guard/PLAN.md) - Not Started (the source fingerprint hashes `.py` only, exactly as documented, but its consumers gate a LIVE DISPATCH on it — so editing config without restarting yields FRESH while every dispatch is graded against the old config. Graduated from 00413 N17; deferred in 00371's non-goals and again by 00395)

- [00414: absent protected path is silent](00414-absent-protected-path-is-silent/PLAN.md) - Not Started (a configured protected path that does NOT exist produces no advisory, so "your word list is fine" and "that guard has been inert since you cloned" are reported identically — by silence. Graduated from 00413 N3, which was filed with the wrong fix)

- [00410: gitignore swallows deployed assets](00410-gitignore-swallows-deployed-assets/PLAN.md) - Not Started (an unanchored `hooks-daemon/` ignore pattern matches at every depth, so it hides the deployed `.claude/skills/hooks-daemon/` tree as well as the intended clone; this repo is already anchored, but nothing DETECTS the mistake, and an ignored file cannot drift visibly. Owner-reported from a client project)

- [00408: handler hygiene from the release review](00408-handler-hygiene-from-the-release-review/PLAN.md) - Not Started (the non-user-visible half of the v3.64.0 review: raw hook-field literals where `HookInputField` is the declared SSoT, `merge_qa_report` building the docs corpus on the hook budget while a sibling argues against exactly that, and four sub-bar items carried so they are not lost. Graduated from 00407 N6)

- [00402: restart path leaves generated handler doc stale](00402-restart-path-leaves-generated-handler-doc-stale/PLAN.md) - Not Started (a restart regenerates the `CLAUDE.md` block but never `.claude/HOOKS-DAEMON.md`, which sat a whole handler short for days and no test could see it. Regenerating on restart is the WRONG fix — that file's marker is the deployed-from version `upgrade.sh` reads. Graduated from 00400 N6; blocked on a ruling)

- [00399: supervisor does not see tab completed slash commands](00399-supervisor-does-not-see-tab-completed-slash-commands/PLAN.md) - Not Started (Tab autocomplete expands `/comp` inside Claude Code and emits no keystrokes, so the raw-input tap never sees `/compact` and the supervisor fails to DEFER — risking a duplicate inject, never a missed compaction. Blocked on a ruling between three options)

- [00396: detect a plan written without reading its domain docs](00396-detect-a-plan-written-without-reading-its-domain-docs/PLAN.md) - Not Started (a plan was filed about deployment by a session that had read none of the deployment docs; the signature is mechanical — a PLAN.md filled about domain X with zero reads of X's owning docs — and `write_clobber_guard` already tracks per-session reads. Advisory, inert until a project declares a topic map)

- [00394: failsafe cron coverage starts at first plan write](00394-failsafe-cron-coverage-starts-at-first-plan-write/PLAN.md) - Not Started (the cron that resumes a stalled session is established by a PostToolUse handler gated on a plan write, so a session has no recovery net until it touches a plan file; Plan 00384 left it undeclared believing `recovery_cron_advisor` already asserted at SessionStart, and it does not. Blocked on an owner ruling between three options)

- [00391: plan close requires proven definition of done](00391-plan-close-requires-proven-definition-of-done/PLAN.md) - Not Started (a project declares its DoD in config; the close is denied until each item is CHECKED or attested with evidence in the plan's JOURNAL/, and a three-way policy — human_gate, encourage, neutral — subsumes Plan 00367's boolean. `encourage` is the direction that would have caught 00386/00389 sitting finished-but-open)

- [00388: failsafe marker wiped by other crons in multi cron sessions](00388-failsafe-marker-wiped-by-other-crons-in-multi-cron-sessions/PLAN.md) - Not Started (`[awaiting-human]` never suppresses a tick in a session with more than one cron — any non-failsafe tick reads as "the owner is back" and clears the marker and cadence; reproduced against the real handler, blocked on an owner ruling between three approaches)

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

- [00100 (v3): Venv SSOT Consolidation](00100-venv-ssot-consolidation/PLAN.md) - Dormant (residue scope awaits scheduling)

  - Phases 0–3.9 **shipped** in v3.9.0 / v3.10.0 / v3.11.0 (canonical SSOT resolver, `.daemon-metadata.json` writers, dead-code removal, path slug, eager upgrade cleanup, H-1 gate coverage)

  - **Residue deferred from v3.12.0** (Plan 00107 Wave 4): Phase 4 (flock concurrency), Phase 5 (parameterised upgrade-cycle test), Phase 6 (docs) … Phase 3.5.2–3.5.7 (bootstrap-fallback wiring) is carried by [Plan 00456](Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md), no longer residue here

  - Phases 1–4 complete (`bash <path>` invocation, auto-migration, self-heal, filemode checker)

  - **Task 5.3 pending**: acceptance gate at v3.12.0 release time (folded into meta plan 00107 Wave 6 `/release` execution)

- [00266: AI-assisted handler decisions](00266-ai-assisted-handler-decisions/PLAN.md) - Dormant (native `prompt`/`agent` hooks measured live: they work, fail CLOSED, cost ~1.2s vs the daemon's ~51ms, and cannot override a daemon deny; dynamic prompting via `tool_use_id` is the leading architecture; parked as reference until a revival condition fires)

## Completed Plans

- [00456: missing venv self heals and repair runs without one](Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md) - Complete at `9e2f74cd` + the archiving commit (the rest of #53: a hook with no venv starts one detached, locked build; `repair` runs without a venv; the skill never auto-forces and a `--force` keeps other environments' venvs; carries Plan 00100 Phase 3.5)

- [00459: encrypted vault files are tracked not hidden](Completed/00459-encrypted-vault-files-are-tracked-not-hidden/PLAN.md) - Complete at `2a6a9b84` + the archiving commit (owner report: secret-file globs select by NAME, so Ansible Vault ciphertext was told to be untracked; a whole-file content check at each use, failing closed, now separates it from the plaintext password file)

- [00458: skip lists match path segments relative to the project](Completed/00458-skip-lists-match-path-segments-relative-to-the-project/PLAN.md) - Complete at `b8ce4b49`…`47999859` + the archiving commit (from 00422 N20: six guards matched skip lists as a bare substring, so a worktree named `…-venv` switched them off; they now match project-relative segments, and a QA detector keeps the class out)

- [00455: self install exposes the conventional cli path](Completed/00455-self-install-exposes-the-conventional-cli-path/PLAN.md) - Complete at `e6a11e19` + the archiving commit (from #54: the self-install daemon generates the conventional CLI link under the gitignored directory, because a tracked one would reach every client clone as a nested install; install-mode checks now require a real clone. Review reverted a copied exemption, filed as 00422 N19)

- [00454: not installed message steers to destructive reinstall](Completed/00454-not-installed-message-steers-to-destructive-reinstall/PLAN.md) - Complete at `f299681f` + the archiving commit (first slice of #53: a clone with no venv for this path now gets its own diagnosis naming a version-pinned upgrade, not the install advice that `rm -rf`s the other view's venv; #53 stays open)

- [00446: subagent report path claim is verified](Completed/00446-subagent-report-path-claim-is-verified/PLAN.md) - Complete at `10b6d6f7` + the archiving commit (from 00422 N15: a false `Report written to:` path — closed by neither remedy the entry listed, since one was costed against a call rather than its coverage and the other named a field SubagentStop does not carry)

- [00445: acceptance harness honours the socket override](Completed/00445-acceptance-harness-honours-the-socket-override/PLAN.md) - Complete at `c4eeebdf` + the archiving commit (from 00422 N6 fault 2, which was not the worktree fault that entry assumed: the autouse env-isolation fixture strips the documented `CLAUDE_HOOKS_SOCKET_PATH` workaround from every wrapper subprocess)

- [00444: gitfacts generic core moves to utils](Completed/00444-gitfacts-generic-core-moves-to-utils/PLAN.md) - Complete at `4db75ead` + the archiving commit (from 00422 N14: `docs_qa` depended on `plan_qa` for read-only git plumbing, and the ledger's "nothing about it is plan-specific" was overstated — `plan_counter()` is — so the generic core split out to `utils/git_facts.py` with `GitFacts` subclassing it, taking the ratchet's declared edges from four to two)

- [00443: acceptance skip reason names the overflow](Completed/00443-acceptance-skip-reason-names-the-overflow/PLAN.md) - Complete at `0d84fb7e` + the archiving commit (from 00422 N6 remedy 2: the acceptance fixtures blamed a stopped daemon for an absent socket, so an over-limit checkout was told to restart — which reproduces the skip; remedy 3 declined with reasoning now that remedy 1 refuses loudly at creation time)

- [00442: host name ladder falls through](Completed/00442-host-name-ladder-falls-through/PLAN.md) - Complete at `9acb1684` + the archiving commit (from 00422 N5 row (e): the documented "ladder, first hit wins" stopped at rung 2 when `gethostname()` cleaned to nothing — and the suite already asserted the fall-through principle for a rung where it could never be exercised)

- [00441: the two link resolvers agree](Completed/00441-the-two-link-resolvers-agree/PLAN.md) - Complete at `c607a6d6` + the archiving commit (from 00422 N5 rows (j)(k)(l): one finding per link instead of per occurrence at all three stages, one shared literal-resolution rule instead of two copies, and a relocation message that no longer calls a plan archived when the resolver deliberately found it in the LIVE root)

- [00440: cached config for per event handlers](Completed/00440-cached-config-for-per-event-handlers/PLAN.md) - Complete at `8d42b548` + the archiving commit (from 00422 N5 row (b): `cron_stop_enforcer` re-parsed the whole config from both `matches()` and `handle()`, ~153 ms at every turn end; now 23.5 µs warm, invalidated on `(st_mtime_ns, st_size)` so an operator's edit still lands without a restart)

- [00439: fence splitter moves out of plan qa](Completed/00439-fence-splitter-moves-out-of-plan-qa/PLAN.md) - Complete at `712cbf2e` + the archiving commit (from 00422 N5 row (h): `utils/markdown_links.py` said "it imports neither of them" six lines above an import of `plan_qa.model`; the splitter moved to `utils/markdown_fences.py`, and the guard written to prove it found six such edges where the ledger named one — the other four are now a declared ratchet, filed as N14)

- [00438: kill suggestion can name the protected group](Completed/00438-kill-suggestion-can-name-the-protected-group/PLAN.md) - Complete at `d9990531` + the archiving commit (from 00422 N5 row (i): `exclude_pgids` was honoured when deciding what breaches and ignored when building the `kill --` the report prints, so the harvester could recommend killing its own group)

- [00437: session advice counter is shared and locked](Completed/00437-session-advice-counter-is-shared-and-locked/PLAN.md) - Complete at `2fbe655e` + the archiving commit (from 00422 N5 row (c): two handlers carried the same unlocked eviction on a daemon-lifetime singleton, and dispatch really is threaded — the test had to drive CPython's switch interval to its floor before the KeyError would appear at all)

- [00436: empty truncated cron prompt matches anything](Completed/00436-empty-truncated-cron-prompt-matches-anything/PLAN.md) - Complete at `0e4c2d11` + the archiving commit (from 00422 N5 row (g): a delivered cron prompt that is nothing but a truncation marker strips to an empty prefix, which every declaration starts with, so a cron that was never created was reported as live)

- [00435: priority band table contradicts shipped handlers](Completed/00435-priority-band-table-contradicts-shipped-handlers/PLAN.md) - Complete at `96577149` + the archiving commit (from 00422 N5 rows (a) and (d): the documented 0-9 band said no built-in ships there while three Stop-family handlers must sit there to be reachable at all, and the Advisory row read 56-69 against an ADVISORY_MAX of 73 — a test now compares the table with the constants it cites)

- [00434: dedupe scout count checked externally](Completed/00434-dedupe-scout-count-checked-externally/PLAN.md) - Complete at `e4429677` + `408cc759` + the archiving commit (from 00422 N13: the scout's `Checked N live plans.` could only be reconciled against the enumeration that went wrong, so `mkplan.bash` states the count instead; its step 3b also named a shell grep it has no Bash tool to run)

- [00433: setup worktree refuses to nest](Completed/00433-setup-worktree-refuses-to-nest/PLAN.md) - Complete at `ba7192b9` + the archiving commit (from 00422 N9: an agent already isolated in a worktree ran the copy of the setup script sitting right there, nesting a second one under it)

- [00432: scoped qa scan overwrites repo artefact](Completed/00432-scoped-qa-scan-overwrites-repo-artefact/PLAN.md) - Complete at the delivery-and-archiving commit (from 00422 N10: seven checkers wrote this repository's published artefact even when pointed elsewhere, so a full run left three of them describing a pytest fixture)

- [00431: socket path preflight needs no venv](Completed/00431-socket-path-preflight-needs-no-venv/PLAN.md) - Complete at `18a9b01b` + the archiving commit (from 00422 N8: the worktree socket-path pre-flight needed a venv to do arithmetic, so it stood down in a nested worktree — exactly where the path is long enough to matter)

- [00430: block report attributes before project context init](Completed/00430-block-report-attributes-before-project-context-init/PLAN.md) - Complete at `08349246`…`47409996` + the archiving commit (from issue #48: five handlers could not be constructed during rule discovery, so their denies were unattributed; 2185 tracebacks to 0 and 44 unattributed to 31 on an identical corpus — the residual 31 are a different cause)

- [00429: format markdown crosses repo boundaries](Completed/00429-format-markdown-crosses-repo-boundaries/PLAN.md) - Complete at `50c27581`…`cd15122c` + the archiving commit (from issue #47: the walk applied no exclusion at all, so `format-markdown .` rewrote markdown inside vendored nested checkouts; review caught the config being read from the WALK root, which made every exclusion match nothing below it)

- [00423: per handler scope main sub](Completed/00423-per-handler-scope-main-sub/PLAN.md) - Complete at `93f2a1c0`…`48733f1b` + the archiving commit (from issues #40/#41: handlers declare `scope: ALL|MAIN|SUB`, keyed on `agent_id` presence because `agent_type` was measured empty in 4 of 5 subagent stops; #41's three destructive controls are scoped but deliberately not built)

- [00427: journal timestamps agent authored and timezone naive](Completed/00427-journal-timestamps-agent-authored-and-timezone-naive/PLAN.md) - Complete at `c631d4dc`…`a208959e` + the archiving commit (from issue #45: a correct writer was not enough — `--journal` stamps UTC, but the future-dated check still read a naive LOCAL clock, so a correct entry looked 239 minutes ahead on `America/New_York`)

- [00426: shipped plugins examples do not validate](Completed/00426-shipped-plugins-examples-do-not-validate/PLAN.md) - Complete at `904d63ed`…`fd414e5e` + the archiving commit (from issue #44, which asked which of two documented `plugins:` schemas is real: neither, because the required `event_type` appears in no example — and both YAML copies are commented out, so no config-loading test could ever have seen them)

- [00425: remote docs index goes stale on delete](Completed/00425-remote-docs-index-goes-stale-on-delete/PLAN.md) - Complete at `edd91533`…`9282c9ea` + the archiving commit (from issue #43: `rm` is the one tree mutation that runs no daemon command, so `check` called the corpus fresh while the index named a deleted file. `check` now detects and reports; the network-free `remote-docs index` repairs)

- [00424: remote docs add overwrites existing capture](Completed/00424-remote-docs-add-overwrites-existing-capture/PLAN.md) - Complete at `ad8e79b3`…`08f8b9c9` + the archiving commit (from issue #42: a second `add` of one URL silently replaced the first capture. The catch the report could not see is that `check` PRINTS plain `add` as the licence-drift remedy, so the refusal and that remedy moved together, welded by a test — nothing pinned that line before, in either direction)

- [00419: niggles ledger fourteen](Completed/00419-niggles-ledger-fourteen/PLAN.md) - Complete at `6a6f9a43`…`2778206f` + the archiving commit (fifteen entries, eleven terminal; the four that were not are re-filed into 00422 rather than counted as closed, because nothing downstream re-reads a closed plan. N1: `debug_hooks.sh` could not run in the repository that dogfoods it)

- [00418: orchestrator only mode greenfield](Completed/00418-orchestrator-only-mode-greenfield/PLAN.md) - Complete at `0f03ef83`…`8011858b` + the archiving commit (restrict the MAIN THREAD to coordination tools; built once and deleted because hooks could not tell which agent fired an event, and `agent_id` now can. Greenfield by ruling, project-level handler, simulate-only before ever blocking. From issue #14)

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

- **Total Plans Created**: 464 (count = `hooksdaemon.latestPlanNumber` git counter)

- **Completed**: 399 (includes 1 reduced-scope plan and 6 found already-shipped when audited; count = `Completed/` folders)

- **Active**: 42 (count = root `NNNNN-*` plan folders; includes several dormant plans awaiting scheduling)

- **On Hold**: 0

- **Cancelled/Abandoned**: 13 on disk (count = `Cancelled/` folders: 00032/00034/00035 won't do — delegate mode no longer exists, 00044 approach retired, 00081 superseded by 00082, 00087 client-side limitation, 00091 superseded by 00102, 00108 superseded by 00117, 00131 residue declined, 00132 superseded by 00284, 00174 superseded by 00175, 00199 superseded by 00213, 00135 superseded by the supervisor workstream)

- **Folder-to-number reconciliation**: 42 + 399 + 13 = **454 folders**, spanning
  **451 distinct plan numbers** — three numbers carry two folders each, the
  historic collisions already held in `collision_allowlist` (00034, 00039,
  00041). Plans 1–3 are on disk under the pre-zero-padding names
  (`001-`, `002-`, `003-`), so they count as present. That leaves **13** of the
  464 allocated numbers with no folder: 00005, 00015, 00036, 00073, 00074,
  00145, 00191, 00195, 00210, 00258, 00300, 00303, 00325 — abandoned drafts, numbers
  burned by transient probes (00195 during the v3.51.0 acceptance run, 00258
  during the v3.54.0 one), and one withdrawn duplicate (00210, scaffolded by a
  sub-agent that then found Plan 00208 already covered the work).
  451 + 13 = 464. ✅

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

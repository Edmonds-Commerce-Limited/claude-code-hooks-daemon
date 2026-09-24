# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

N16 is filed on the unmerged `worktree-n466-guard-defects` branch; it joins this file at integration.

### N19 — the registry's options-collection failure is logged at debug level

**Found by the N13/N14 agent.** The handler registry's pass-1 `except Exception` logs a failure to collect a handler's options at debug level only. During the N14 work, a local variable that shadowed the new accessor made the registry silently drop EVERY handler's options, and only an existing registry test caught it before commit. In production, that failure would have looked like every handler running on defaults, with nothing at a visible log level.

**Candidate remedy:** narrow the catch to the exceptions that option collection can legitimately raise, and log anything else at error level with the handler name. If a handler's configured options cannot be applied, that is a degraded protection state and should surface in `health`. RED test: an injected failure while collecting options is visible at error level and in health.

### N18 — PlanWorkflow.core.md says the plan index is linted against one rule

**Found by the N13/N14 agent.** `CLAUDE/core/PlanWorkflow.core.md:407` and its deployed template copy say the plan index is linted "against one rule". `index-no-log` already made that false, and N13 adds `plan-stats-arithmetic` to the commit gate. The page is a deployed template pair, so it ships to clients.

**Candidate remedy:** name the rules, or better, point at the plan QA rule list, which is the source of truth, instead of counting. Change both copies of the pair together, and pin it with a doc-truth test that the page names no count that disagrees with the registry.

### N17 — `skill_opportunity_detector` never receives its configured options

**Found by the N13/N14 agent.** `_options()` reads `self.config["options"]`, which only `configure()` populates. Nothing in `src/` calls `configure()`; the registry injects options as `_<key>` attributes instead. So a configured `check_interval_days` is ignored at runtime, and only the unit tests, which call `configure()` directly, exercise the option.

**Candidate remedy:** read options the way the registry delivers them, through the shared accessor. RED test: a handler built by the real registry from a config with a non-default `check_interval_days` uses it. Then audit every handler for a `configure()`-only options path, and pin the class with a test that instantiates each handler through the registry with a non-default value for every declared option and checks that it is honoured.

### N15 — `remote-docs add` scans a capture with an unconfigured `sensitive_content` handler

**Found by the Plan 00468 docs agent.** `daemon/cli.py` (~:6377) builds `SensitiveContentHandler()` with none of its configured options for the capture-time `scan_text` in `remote-docs add`. So the scan at the moment a page is vendored runs with no public patterns at all. That is how 28 example UUIDs were vendored into `hooks.md` without a warning, to be caught only later by the tree-wide QA scan. The secret word list happens to be found only because the configured path equals the default. This is the same class as N14: a component reads a handler's behaviour without that handler's configured options.

**Candidate remedy:** construct the handler from the project's resolved config, through the same shared handler-options accessor N14 introduces. RED test: `remote-docs add` of a page carrying a configured public-pattern match reports it at capture time, and a non-default `secret_word_list_path` is honoured. Add the construct-without-config shape to N14's class audit.

### N14 — log and payload redaction ignore a configured secret word list path

**Found by the 00414/00415 agent**, outside its brief. `utils/secret_redaction.py` `_resolve_active_path` reads `handler_cfg.get("options", {})` only when `isinstance(handler_cfg, dict)`. But `Config` coerces every handler entry to a `HandlerConfig` model (`type(c.handlers.pre_tool_use.get("sensitive_content"))` is `HandlerConfig`), so the isinstance test is never true. The daemon-wide resolver therefore never reads a configured `secret_word_list_path`, and always falls back to the default `.claude/block-words.secret`. The `sensitive_content` handler reads its own option correctly, so blocking still works. But payload capture and log redaction silently use the wrong list, or no list, in any project whose word list lives somewhere else. That is exactly how a secret term reaches a log. This repository is unaffected only because its configured path equals the default. `secret_file_matching.resolve_configured_patterns` carries a comment about this same mistake and fixed its own copy, so this is the second sighting of the class.

**Candidate remedy:** read the option through `HandlerConfig.options`, via one shared accessor for handler options that accepts either shape. RED test: with a non-default `secret_word_list_path`, a term from that list is redacted from a captured payload and a log line. Then audit every `isinstance(<handler config>, dict)` read of handler config across `src/`, and pin the class with a test or QA check that fails when handler config is read as a dict.

### N13 — the plan-index statistics arithmetic is checked only by full QA, so a wrong count reaches main

**Found by the coordinator**, through Plan 00421's agent. Opening Plan 00468 updated the README statistics bullets (468 allocated, 455 distinct) but missed the closing self-check line (`454 + 13 = 467`). `check_repo_hygiene.py`'s `plan-stats-arithmetic` check catches exactly this. But it runs only in `llm_qa.py all`, and the commit-time plan QA gate that runs on every README commit does not include it. The inconsistent index was therefore committed and pushed (d10bbf13), and was found only when an agent ran the hygiene checker by hand. The same README gate already enforces row length and the 30-row completed window at commit time.

**Candidate remedy:** run the `plan-stats-arithmetic` check in the commit-time plan QA gate whenever the staged tree touches the plan index, or move the check into plan QA and have repo_hygiene call it. Either way there is one implementation. RED test: a commit staging a README whose statistics disagree with the self-check line is denied, and names the line to fix.

### N12 — a hand-built probe payload is logged as real traffic, because nothing tells a prober to mark it

**Found by the Plan 00467 plugin audit.** The audit fed synthetic PreToolUse payloads through `.claude/hooks/pre-tool-use` to probe handler verdicts. They carried no `synthetic_source` field, and their session ids (`plugin-audit-probe` and similar) match no known synthetic shape. So `daemon/synthetic_traffic.py` classed them as REAL traffic in `verdicts.jsonl`, including the orchestrator-simulate record that Plan 00418's enforcement decision will be read from. The marker (`SYNTHETIC_SOURCE_FIELD`, `synthetic_traffic.py:39`) is documented only in that module's docstring. CLAUDE/DEBUGGING_HOOKS.md, the handler-development guide and the agent-facing docs never mention it, so a prober cannot know to set it.

**Candidate remedy:** document the marker wherever probing a handler is taught (DEBUGGING_HOOKS.md, HANDLER_DEVELOPMENT.md, and the acceptance and playbook guidance), with a copy-paste payload that sets it. Consider a small `bin/hooks-daemon probe <event> <json>` helper that sets the marker itself. Add a test that the probing docs name the field.

### N11 — any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under the default `strict_mode: false` the chain logs the exception and allows the call. This repository runs `strict_mode: true`, so here the crash denied, but a client on the defaults fails open. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

### N9 — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

### N8 — `reference_repo_freshness` says BLOCKED on a call it allows

**Found by the coordinator.** A Read of a fresh clone under `untracked/repos/` was denied (`R-REFERENCE-REPO-NOT-VERIFIED`), as the default `block_once` posture intends. The next command that named that clone, a `mv` moving it to `untracked/work/`, RAN. Its hook context still opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]: a read of a governed reference clone...`.

`_verdict()` (`handlers/pre_tool_use/reference_repo_freshness.py:575-576`) returns `GatingResult(decision=Decision.ALLOW, context=[message])` for a repeat in `block_once` mode, and for `advise` mode at :565. `message` is the verbose DENY rendering (`self._formatter.verbose(rule)`), which starts with `BLOCKED`. An agent reading its context is therefore told a call was blocked when it ran. It either retries something that already happened, or learns that "BLOCKED" means nothing.

**Candidate remedy:** the allow paths render the advisory form of the rule (no `BLOCKED` prefix, same detail and fix line). Pin it with a test for each mode (`advise`, a `block_once` repeat): an ALLOW result's context never contains the deny headline. Then audit every other handler that returns `Decision.ALLOW` with a context built by the verbose deny formatter (`block_once` handlers especially, such as `lsp_enforcement`), and pin the class with a test that walks every handler's acceptance tests or allow paths.

### N7 — the regenerated CLAUDE.md guidance block is not deterministic, so every daemon restart can commit a reorder

**Found by the coordinator** at the batch A merge. The integration worktree's daemon had just regenerated CLAUDE.md, and that result was committed. The main checkout's daemon then restarted on the same tree and auto-committed `ce31d6d8` ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). The commit changed 18 lines both ways. Every change is the same handler markers in a new order: `tool-disable-advisor`, `project-handler-load-checker`, `hook-registration-checker`, `routine-qa-sweep` and `secret-file-hygiene-checker` among them. The earlier 00462 merge restart committed `6359ad0c`, changing 83 lines both ways, with the same shape.

`ClaudeMdInjector._collect_tiers()` emits handlers in the order of `self._handlers` (`core/claude_md_injector.py:642`) and never sorts them. Two daemons on one tree can therefore produce different blocks, apparently for handlers that share a priority. The results:

- A spurious auto-commit on restart.
- A CLAUDE.md conflict whenever two branches merge. This happened twice while building batch A.
- A worktree's regenerated block that never matches main's.

**Candidate remedy:** emit in a total order that depends only on the handler set, for example tier, then priority, then handler name. Test that two injector runs over the same handlers in shuffled input order produce byte-identical blocks. Check whether `HOOKS-DAEMON.md` generation has the same tie problem, and give it the same fix.

**Remedy shipped in commit `0dba7bfb`.** `_collect_tiers()`
(`core/claude_md_injector.py`) now sorts each of the three tier lists
(`promoted`, `progressive`, `fallback`) by handler name before returning
them — name alone is a complete total order because two active handlers
never share a name, and priority is not consulted because handlers from
different event chains are mixed into one flat CLAUDE.md tier where
priority carries no meaningful cross-event-type ordering. `daemon/ controller.py`'s handler collection was reading the chain's private,
unsorted `_handlers` list instead of its public `handlers` property (which
already sorts by `(priority, name)` on access, the same pattern
`EventRouter.get_all_handlers()` uses) — fixed to use `chain.handlers`.
`TestGuidanceOrderIsIndependentOfDiscoveryOrder`
(4 tests, RED against the pre-fix code) asserts forward- and
reverse-ordered handler lists inject byte-identical `<hooksdaemon>`
blocks. The sibling tie in `.claude/HOOKS-DAEMON.md` generation
(`daemon/docs_generator.py`'s `_render_handler_table()`) sorted by
priority only, so same-priority handlers kept registry order; fixed to
sort by `(priority, config_key)`, pinned by
`test_same_priority_handlers_are_order_independent` (1 test, RED against
the pre-fix code). Verified idempotent: `regenerate-docs` run twice in a
row produces the identical diff both times.

**Correction (00466 review, minor m6):** the commit message and the
paragraph above blamed `pkgutil.walk_packages()` for the unsorted input.
That is wrong — `pkgutil` sorts `os.listdir` output internally
(`_iter_file_finder_modules` calls `filenames.sort()`). The real unsorted
source is `HandlerRegistry`'s two `event_dir.glob("*.py")` loops
(`handlers/registry.py:467` and `:511`), which iterate in `os.scandir`
order; a third loop in the same file (line 198) already wraps its glob in
`sorted(...)`. The injector-level and docs_generator-level sorts above
still make each rendered artefact a pure function of the handler set on
their own — this correction is to the narrative, not to the fix's
soundness. Both `registry.py` glob loops are now wrapped in `sorted(...)`
too, so discovery order is deterministic at its source as well as at
every rendering layer.

**Also fixed (00466 review, nit n6):** the promoted tier's alphabetical
sort lost the reason a handler is promoted at all — the config author's
own `promoted_handlers` list order, chosen so the most-triggered guidance
reads first. `_collect_tiers()` now sorts the promoted tier by each
entry's INDEX in `self._promoted_handlers_order` (the author-authored
config list, kept alongside the pre-existing `frozenset` used for the O(1)
membership check) instead of alphabetically — still a complete,
deterministic total order, because that config list is a fixed value, not
a filesystem walk. The progressive and fallback tiers are unaffected;
alphabetical is the right call there, since nothing about them carries
author-chosen intent. Pinned by
`test_promoted_tier_follows_the_authors_promoted_handlers_order` (RED
against the pre-fix alphabetical code).

### N3 — `goal_injection` treats any edit of an In Progress plan as the plan starting, and displaces the live goal

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

**Remedy shipped in commit `5676772d`.** `GoalInjectionHandler` gained
`_is_real_flip_to_in_progress`: for `Edit` it parses `old_string` with
`PlanDoc.parse` and answers directly from that fragment's own Status line
(absent → this edit never touched it → not a flip; present and not In
Progress → a flip). For `Write` there is no pre-write disk copy left by the
time PostToolUse runs, so git HEAD stands in for "before" — deliberately
not the Write/Edit `tool_response`, whose shape this codebase has never
verified for either tool (see this same folder's
`POSTTOOLUSE_FIXTURE_VERIFICATION.md`). A path absent at HEAD (new or never
committed) reads as nothing to flip FROM, matching the pre-existing
single-plan contract. The once-per-`(plan, session)` latch and the
retirement-refresh path are unchanged. `TestStatusFlipDetection` (8 tests,
3 RED against the old code) pins the contract; the module docstring, the
class docstring and `get_claude_md()` now state it explicitly.

**Follow-up in commits `6699fbbd` and `4813adc8`**, after review. The first
`_head_plan_text` caught `RuntimeError`/`OSError`/`ValueError` and returned
`None`, which `error_hiding`'s `return-none-on-error` check flagged; the
initial fix added an exclusion, which the review correctly rejected —
this project allows no new QA suppressions. Restructured instead: path
membership is now a plain `Path.is_relative_to` comparison, never a caught
`ValueError`, and `ProjectContext.project_root()` is called unguarded — by
the time any handler dispatches the daemon has always initialised it, so a
`RuntimeError` here means genuine misconfiguration and is left to propagate
to the dispatcher (`core/chain.py`'s existing per-handler exception
handling), rather than being swallowed into a false "nothing to compare
against". The lookup moved out to
`utils.git_facts.project_relative_head_text` so it has one home instead of
a per-handler copy. `error_hiding` now passes with zero violations and no
exclusion for this code.

The review also asked for the sibling to be fixed, not just documented as
accepted: `recovery_cron_advisor`'s Write-path completion check
(`_STATUS_COMPLETE_RE.search(content)` against the whole new file) shared
the exact same state-vs-transition defect shape for `**Status**: Complete`
— "only an advisory" was not a reason to keep it. `_detect_lifecycle_phase`
now calls `_write_is_real_completion`, which reuses
`project_relative_head_text` rather than a second copy: a Write whose
content reads Complete is COMPLETION only when the plan was not already
Complete at HEAD; otherwise the event matches no phase at all (never falls
through to PROGRESS/CREATION). `TestWriteCompletionIsTransitionBased` (4
tests, 1 RED against the pre-fix code) pins the contract. Its Edit path
(`_edit_results_in_status_complete`) already required the edit's own
`old_string`/`new_string` to assert Complete and needed no change.
`plan_close_approval._is_terminal_flip` was already transition-based
(compares `PlanDoc.parse(current).status` against the proposed status).
`plan_qa_edit.py`'s "In Progress" occurrences are guidance prose, not
status-detection logic.

**Second review pass (majors M2/M3, minors m4/m5, nits n3/n4/n7)**, fixed
together on the same branch:

- **M2 — a daemon restart silently disabled the retirement refresh.**
  `_maybe_refresh_on_retirement` gated on the IN-MEMORY `self._fired`
  latch, which a restart (`daemon_restart_verifier` requires one before
  every commit) empties, and N3's flip-only rule meant a later non-flip
  write no longer re-latched either — so a plan flipped in one daemon
  lifetime and completed in the next never dropped out of the combined
  `/goal` signal. Fixed by asking the PERSISTENT `GoalLedger` instead
  (`GoalLedger.has_live_entry`, via the new `_session_ledgered_plan`),
  which survives the restart the latch does not. Pinned by
  `test_completing_a_plan_after_a_daemon_restart_still_refreshes_signal`
  (a fresh `GoalInjectionHandler` instance simulates the restart; RED
  against the pre-fix code).
- **M3 — the "goal survives a session restart" contract was silently
  dropped, not replaced.** Plan 00269 Task 2.1 deliberately chose "the
  first edit to an already-In-Progress plan in a NEW session re-fires" so
  a resumed session got its `/goal` back; N3's flip requirement removed
  that with no replacement, and the original release note wrongly called
  it "no action needed". Restored via `GoalLedger.reassert_session` (two
  new ledger methods: `session_has_entries` decides whether THIS session
  is new at all; `reassert_session` transfers ownership of the plan's
  already-live entry with NONE of `record_emission`'s displacement
  bookkeeping) and `_maybe_reassert_for_new_session`: a session with no
  ledger entries whatsoever that touches an already-live plan without
  itself producing a real flip gets its own signal written, no new ledger
  record, no "GOAL DISPLACED" advisory, and no risk of wrongly displacing
  some OTHER live plan. A session that already has its own live goal is
  unaffected. Pinned by three new tests in
  `TestNewSessionReassertion` (one RED against the pre-fix code) plus
  three new `GoalLedger` test classes. Release note 13 and the module
  docstring corrected to describe the restored contract instead of
  claiming no behaviour changed.
- **m4 — an Edit whose `old_string` carried only the bare status VALUE
  (no `**Status**:` prefix) missed a genuine flip.** `PlanDoc.parse` on
  `old_string` alone then found no Status line and read "never touched
  it". Fixed by reconstructing the pre-edit text from what is already on
  disk when this happens — reversing the SAME substitution the Edit tool
  performed (`_reconstruct_pre_edit_text`, honouring `replace_all`) — and
  parsing that instead of giving up. Pinned by
  `test_edit_whose_old_string_is_only_the_status_value_still_emits` (RED
  against the pre-fix code) plus a no-op control test.
- **m5 — a Write in a nested repository (a linked worktree, any nested
  clone) read HEAD from the PROJECT ROOT's repo, which never tracks the
  nested path, so it always answered "absent" and misread every write
  there as a genuine flip.** `project_relative_head_text` now resolves
  the FILE's own enclosing repository via `GitRepo.resolve_for` (the same
  `git -C <dir> rev-parse --show-toplevel` this project already
  centralises) and reads HEAD relative to THAT root; a project root that
  is itself a plain checkout is unaffected. Pinned by
  `test_a_file_in_a_nested_repository_reads_from_its_OWN_head` (RED
  against the pre-fix code) in `test_git_facts.py`, which also fixes
  `recovery_cron_advisor`'s Write-path COMPLETION check for the same
  reason (it shares the helper).
- **n3 — `git_facts.py` imported `core.project_context`, breaking its own
  documented "docs QA depends on this module alone" claim.**
  `project_relative_head_text` now takes `project_root` as a plain
  parameter instead — both callers already resolve
  `ProjectContext.project_root()` for other purposes, so nothing is lost.
- **n4 — acknowledged, not changed.** `_is_inside_project` fails open on
  an uninitialised `ProjectContext`; `project_relative_head_text` lets it
  propagate (by design, from the first review pass). Both new M2/M3
  helpers (`_session_ledgered_plan`, `_maybe_reassert_for_new_session`)
  now follow the SAME unguarded-propagation convention for consistency
  (and because `error_hiding` flagged the None-returning one) — the
  review itself called this "only reachable uninitialised", i.e. never on
  the real dispatch path, so the two conventions differing is intentional
  per the first review's explicit design, not an oversight.
- **n7 — release note 13's title said "already-terminal-status"; In
  Progress is not terminal.** Corrected to match the filename's wording.

`TestStatusFlipDetection`, `TestCombinedGoalSignal`,
`TestNewSessionReassertion`, `TestWriteCompletionIsTransitionBased`,
`TestProjectRelativeHeadText` and the new `GoalLedger` test classes all
pass; 518 tests across every touched handler/utils/core/daemon test file.

**Third review pass (major RV-M1, minors RV-m1 through RV-m5, nits RV-n1
through RV-n3)**: the second pass's M3 re-assert and M2 retraction worked
AGAINST each other — fixed together with an ownership schema change:

- **RV-M1 — `reassert_session`'s single-owner TRANSFER broke retraction the
  moment a second session touched a plan.** Once TEAMMATE reasserted a plan
  LEAD had flipped, `has_live_entry`'s exact `session_id` match stopped
  matching LEAD, so LEAD's own signal could never be retracted again when
  the plan completed — and a pre-existing gap on `main` meant a DIFFERENT
  completing session never retracted the flipping session's stale signal
  either. Fixed by making ownership ADDITIVE: `GoalLedgerEntry` gained a
  `sessions: list[str]` field that `record_emission`/`reassert_session` both
  APPEND to, never overwrite; `has_live_entry` checks membership in
  `sessions`; a new `GoalLedger.owning_sessions(plan_number)` (accepting an
  entry retired a moment ago for `RETIRED_TERMINAL_STATUS` too, subsuming
  RV-m2 below) feeds `_maybe_refresh_on_retirement`, which now refreshes
  EVERY owning session's own combined signal on a terminal write, not just
  whichever session's write triggered the check. Pinned by
  `TestOwnershipSurvivesASecondSession` (single plan, two plans, a second
  session owning a plan it never flipped — all RED against the pre-fix
  code) plus `TestReassertSession`/`TestOwningSessions` in
  `test_goal_ledger.py`.
- **RV-m2 — subsumed by RV-M1's fix.** `owning_sessions`' terminal-status
  grace window (live OR just-retired-as-terminal) means a concurrent
  reconciliation racing between a terminal write landing and this read
  cannot suppress a real owner's retraction.
- **RV-m3 — a SAME-session-id resume (`--resume`/`--continue`) never got
  its `/goal` back**, because the M3 gate (`session_has_entries`) reads the
  PERSISTED ledger, which still "knows" the session from its OWN earlier
  real flip even after its signal FILE was lost across a restart. Fixed
  with a second in-memory latch, `self._reasserted: dict[(session_id, plan_number), bool]`, reset every daemon lifetime and independent of
  `self._fired` — "have I, this process, already confirmed a signal for
  this pair" answers both a genuinely new session id and a same-id resume
  identically. The busy-session contract (a session that already
  real-flipped a DIFFERENT plan must not implicitly absorb an unrelated
  one) still holds via `session_has_entries`, now checked only when the
  session is NOT already a stakeholder of THIS specific plan
  (`has_live_entry`). Pinned by
  `test_same_session_id_after_a_restart_gets_its_signal_rewritten` (RED
  against the pre-fix code).
- **RV-m1 — the m4 reconstruction reversed the FIRST occurrence of
  `new_string`, not necessarily the actual edit site.** A table cell or
  title sharing the same text as the Status VALUE (e.g. "In Progress")
  could reconstruct the wrong span and report a false flip. Fixed:
  `_is_flip_via_reconstruction` now tries every occurrence of `new_string`
  as a candidate, keeps only candidates whose reversal leaves `old_string`
  unique (the Edit tool's own precondition for a non-`replace_all` edit),
  and reports a flip only when every surviving candidate agrees; disagreement
  or no viable candidate reads conservatively as "not a flip".
  `replace_all` has no uniqueness precondition to exploit, so it instead
  requires `old_string` to be ABSENT from the post-edit text (a clean
  application leaves none behind) before reversing every occurrence at
  once — otherwise conservatively "not a flip", the same trade-off as a
  contrived title-collision missed-flip case this review accepted as
  out of scope. Pinned by two RED tests (a table-cell collision, its
  `replace_all` variant) plus a regression control.
- **RV-n1 — the m6 fix narrative still blamed `pkgutil.walk_packages()`**,
  which already sorts its own directory scan; the real (now fixed) source
  was `HandlerRegistry.register_all`'s two previously-unsorted
  `event_dir.glob("*.py")` passes. Corrected in `claude_md_injector.py`,
  `docs_generator.py`, and both files' test docstrings.
- **RV-n2 — the fail-open convention split flagged by the first review's n4
  was read as unresolved, not intentional.** Unified behind one helper,
  `_open_ledger()`, that every ledger-opening call site in the class now
  goes through — catching `RuntimeError` and logging, matching
  `_write_combined_signal`/`_ledger_record`'s pre-existing convention
  rather than the unguarded propagation the retirement-refresh/reassert
  paths used before.
- **RV-n3 — no test covered the RV-M1 scenarios or RV-m1's collision case
  (now fixed above); a registry test read the chain's PRIVATE
  `._handlers` list, which only worked because the lazy `.handlers` sort
  had not run yet.** Made the precondition explicit: the test now asserts
  `chain._sorted is False` before reading `._handlers`, so an accidental
  earlier `.handlers` access fails loudly instead of silently passing for
  the wrong reason.

Release note 13 and the module/class docstrings corrected again to
describe the ADDITIVE ownership and per-daemon-lifetime reassert latch
instead of the second pass's (now superseded) single-owner transfer.

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.

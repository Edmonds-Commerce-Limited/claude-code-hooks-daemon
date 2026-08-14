# Cohort C — plan-workflow handler family

Scope: `plan_completion_advisor`, `plan_number_helper`, `plan_qa_commit_gate`, `plan_qa_edit`,
`plan_time_estimates`, `plan_workflow`, `validate_plan_number` (all
`src/claude_code_hooks_daemon/handlers/pre_tool_use/`), plus
`src/claude_code_hooks_daemon/handlers/utils/plan_numbering.py` and the
`src/claude_code_hooks_daemon/plan_qa/` check catalogue they interact with.

## Cohort summary

| Handler                   | Signal                 | One-clause reason                                                                                                                                                                                                                                                                                                       |
| ------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plan_completion_advisor` | **MERGE-INTO-PLAN-QA** | Duplicates `terminal-placement-hint` (EDIT) + `terminal-state-atomic` (COMMIT); both are more complete (real doc-state diff, all terminal statuses, commit-time teeth) and **co-fire in the same tool call** as demonstrated below                                                                                      |
| `plan_number_helper`      | **KEEP**               | Unique duty (blocks bash-discovery-idiom commands) that plan_qa cannot see — plan_qa never inspects Bash command strings; genuinely `terminal=True`/DENY with realistic regression tests                                                                                                                                |
| `plan_qa_commit_gate`     | **KEEP**               | This IS the plan_qa Stage-2 surface; heavily iterated (6 plans), catches real field incidents (Plan 00190, 00211), not vacuous                                                                                                                                                                                          |
| `plan_qa_edit`            | **KEEP**               | This IS the plan_qa Stage-1 surface; same evidence base as above, `edit_mode: block` actually enforced                                                                                                                                                                                                                  |
| `plan_time_estimates`     | **KEEP**               | Zero overlap with plan_qa catalogue (no check anywhere mentions estimates/ETA/deadline); extensive false-positive-driven regression tests (`test_bug_does_not_match_*`) prove real iteration against real prose                                                                                                         |
| `plan_workflow`           | **SUSPECT**            | Its per-Write advisory AND its `get_claude_md()` both restate content that is *already* resident every session — once via its own `get_claude_md()`, and again via the eagerly-`@`-imported `CLAUDE/PlanWorkflow.md` (1,000+ lines, inlined per the project's own `@`-import mechanics) — for zero marginal information |
| `validate_plan_number`    | **MERGE-INTO-PLAN-QA** | Never blocks (always `Decision.ALLOW`, despite "YOU MUST FIX THIS NOW" text) and carries `get_claude_md() -> None`, so the agent has no idea it exists; the same substantive check (`counter-sanity` + `no-new-collisions`) runs again at commit time where it can actually block                                       |

## Overlap map

| Handler duty                                                                                   | plan_qa check id(s)                                                                                                                                     | Which is more complete                                                                                                                                                                                                          |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "PLAN.md flipped to Complete → remind to `git mv` + update README" (`plan_completion_advisor`) | `terminal-placement-hint` (Stage EDIT, ADVISE) + `terminal-state-atomic` (Stage COMMIT, BLOCK-capable)                                                  | plan_qa — parses the actual `PlanDoc` before/after (real state, not regex-on-string), covers Cancelled/Superseded too (not just Complete/Completed), and the COMMIT check is flip-aware (only fires when HEAD was non-terminal) |
| "Plan number chosen for a new folder must equal `counter+1`" (`validate_plan_number`)          | `counter-sanity` (Stage COMMIT, BLOCK) + `no-new-collisions` (Stage COMMIT/SWEEP, BLOCK)                                                                | plan_qa — the only one of the two that is actually mode-gateable to BLOCK; `validate_plan_number` is structurally advisory-only                                                                                                 |
| "Correct next plan number, don't discover it via bash" (`plan_number_helper`)                  | *(none)*                                                                                                                                                | No overlap — plan_qa operates on file content / staged git diffs, never on Bash command text. This is the one PreToolUse-only surface plan_qa structurally cannot reach.                                                        |
| "General plan-file guidance on Write" (`plan_workflow`)                                        | `template_metadata` (Stage EDIT, new-doc headers) covers a slice; the size-tier/remedy content overlaps `plan_qa_edit`'s own `get_claude_md()` verbatim | Neither is "more complete" — they say the *same* size-tier numbers (18,000/350, 25,000/500, 35,000/900) and the same three-remedies list in two independently-maintained strings                                                |
| "Time estimates banned in plan docs" (`plan_time_estimates`)                                   | *(none)*                                                                                                                                                | No overlap — no check module in `plan_qa/checks/` mentions estimates, ETA, deadline, or duration                                                                                                                                |

## plan_completion_advisor

**CLAIM** (`plan_completion_advisor.py:36-43`): advise that a plan being marked Complete needs `git mv` to `Completed/`, a README update, and a statistics update.

**MECHANISM**: `matches()` (`:58-94`) fires on `Write`/`Edit` to `CLAUDE/Plan/NNNNN-*/PLAN.md` (not already in `Completed/`) whose content/`new_string` matches `**Status**:\s*complete[d]?\b` (case-insensitive, word-anchored so "Completely blocked" doesn't false-positive — regression-tested at `test_plan_completion_advisor.py:177-207`). `handle()` always returns `Decision.ALLOW` with a fixed three-line reminder (`:105-115`). Non-terminal, priority 48.

**OVERLAP WITH plan_qa**: Direct and demonstrable. `terminal-placement-hint` (`plan_qa/checks/terminal_placement_hint.py:23-47`) is registered at `Stage.EDIT` (confirmed live in the catalogue, `checks/__init__.py:65`) and fires under the exact same condition — a PLAN.md whose parsed doc `is_terminal` and is not `in_archive` — with the same remediation text (`git mv` + README + statistics). Since `plan_qa_edit` (priority 44) dispatches *before* `plan_completion_advisor` (priority 48) and both are non-terminal, **a single Write that sets `**Status**: Complete` on an active-root PLAN.md fires both handlers in the same PostToolUse response**, producing two independently-worded copies of the same instruction. `terminal-state-atomic` (`plan_qa/checks/terminal_state_atomic.py`, Stage COMMIT) additionally covers Cancelled/Superseded (this handler only matches the literal string "complete[d]") and is flip-aware (only fires when HEAD was non-terminal, so it doesn't nag on every subsequent edit to an already-complete plan the way the regex-based handler's Write path can — a full-file `Write` that merely fixes a typo in an already-Complete plan still contains the status string and re-fires `plan_completion_advisor` every time).

**VACUITY**: Not vacuous as a matcher — `matches()` reliably fires on realistic Write/Edit payloads and the test suite (`test_plan_completion_advisor.py`, 27 tests) includes true regression cases (`test_does_not_match_status_completely_prose`, `test_does_not_match_complete_in_body_only`) proving iteration against real false positives. The finding here is redundancy, not inability to match.

**CONFIG**: `enabled: true`, priority 48 (`.claude/hooks-daemon.yaml:360-362`). No mode knob — always fires when matched.

**COST**: `get_claude_md() -> None` (`:117-118`) — zero resident CLAUDE.md cost. Per-event cost is one small context string (~250 chars) only on the (rare) event of a plan being completed — cheap in isolation, but duplicative given `plan_qa_edit` fires in the same turn.

**HISTORY**: `git log --follow`: introduced Plan 00027 (`97e1afc0`), predates the plan_qa subsystem entirely (Plan 00144, `0491c5d5`, landed years of commits later). Never touched again except mechanical refactors (Strategy Pattern migration, `get_claude_md()` scaffolding, an "advisory not visible in system-reminders" bugfix in `9353733a`, and an unrelated Plan 00140 fix). No sign it was ever revisited in light of `terminal-placement-hint`/`terminal-state-atomic` landing.

**FALSE-POSITIVE RECORD**: One real false positive fixed in-file (finding #62, "Completely blocked" prefix match) — see `test_plan_completion_advisor.py:177-193`. No entry in `CLAUDE/development/LESSONS.md`.

**SIGNAL: MERGE-INTO-PLAN-QA** — strongest evidence: `terminal-placement-hint` is registered at `Stage.EDIT` and literally co-fires with this handler on the same Write/Edit event, so the redundancy isn't theoretical, it's observable in a single tool call's context payload.

## plan_number_helper

**CLAIM** (module docstring, `:1-20`): prevent Claude from using broken bash idioms (`ls ... | sort | tail -1`, `find`, glob-echo) to discover the next plan number; inject the correct number via the git-anchored counter instead.

**MECHANISM**: `matches()` (`:160-304`) is a dense set of regex rules over the Bash command string (with quoted-literal spans blanked first, `blank_shell_literal_spans`) detecting `ls`/`find`/`echo`/`printf`/sort-and-truncate idioms scoped to the configured plan directory, with explicit carve-outs for `| wc` (counting, not discovery — Plan 00200 regression) and commands that demonstrably reach `Completed/`/`Cancelled/` while not also extracting a single latest value (Plan 00227 "reconciliation, not discovery"). `handle()` (`:306-350`) is `terminal=True` and **DENIES** — despite the ADVISORY tag, which the docstring explicitly explains describes content, not force. Priority 33.

**OVERLAP WITH plan_qa**: None. plan_qa's `CheckContext` is built from file content and `git diff`/staged-tree state (`plan_qa/context.py`, `plan_qa/gitfacts.py`) — it has no visibility into a Bash command string at all. This is the one PreToolUse-only duty in the cohort that plan_qa is structurally incapable of covering, since plan_qa only ever sees what's already written to a file or staged, never the shell command that led there.

**VACUITY**: Not vacuous. `test_plan_number_helper.py` (742 lines) and a dedicated `test_plan_number_helper_text_vs_command.py` file test against commands an agent would plausibly type (`ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1` is literally the handler's own acceptance test, `:398-408`, and reads as a command a model would genuinely emit when asked "what's the next plan number"). The negative test at `:409-426` (`find ... | wc -l`) documents an actual dogfooding false positive (Plan 00200) that was found and fixed, not manufactured.

**CONFIG**: `enabled: true`, priority 33 (`.claude/hooks-daemon.yaml:317-319`). Gated on `_track_plans_in_project` being set (i.e. `plan_workflow.enabled: true`, which it is).

**COST**: `get_claude_md()` is ~2,483 chars, resident every session (this is the block visible verbatim in the system CLAUDE.md under `## plan_number_helper`). It is doing real work — it's the text that tells the agent to use `mkplan.bash` instead of scanning, which is the actual behaviour-change lever for this whole family.

**HISTORY**: Present since near the initial commit (`edeb66d8`, pre-Plan-numbering) and has been actively maintained through at least 5 subsequent false-positive fixes: Plan 00138 (two-handler false-positive fix), a newline-spanning `echo` false positive (`463c7761`), Plan 00200 Task 6.4 (`wc` counting vs discovery), a reconciliation-scan false positive (`c7c8f39c`), and most recently Plan 00227 ("matches commands, not text about them", `a68e3966`) — i.e. this handler has a long, active, still-ongoing correction history, which is evidence of real production usage triggering it, not a dormant rule.

**FALSE-POSITIVE RECORD**: The richest false-positive history in the cohort — five distinct fix commits, several referencing specific plan numbers (00138, 00200, 00227) as the source. Not mentioned in `LESSONS.md` directly but the commit trail is self-documenting.

**SIGNAL: KEEP** — strongest evidence: it is the only handler in the cohort inspecting Bash command text, which plan_qa cannot do by construction, and its five-commit false-positive-fix history shows it firing on and being corrected against real agent behaviour, not sitting dormant.

## validate_plan_number

**CLAIM** (module docstring, `:27-50`): validate a new plan folder's number is sequential, running at PreToolUse (before directory creation) to avoid a PostToolUse TOCTOU bug.

**MECHANISM**: `matches()` (`:67-108`) fires on `Write` to a new (not-yet-existing) `CLAUDE/Plan*/NNNNN-*/` path, or a `mkdir` of same, skipping doc/command files and heredocs. `handle()` (`:134-206`) extracts the number, computes `expected_number` via the shared `next_plan_number_for_target` (the same git-counter function `plan_number_helper` and `counter-sanity` both use), and — critically — **on mismatch it returns `HookResult(decision=Decision.ALLOW, context=[error_message])`** (`:200`), never `deny`. The dramatic "YOU MUST FIX THIS NOW" text (`:189`) is advisory only. On a *correct* number it calls `_record_allocation` (`:208-223`) to advance the git counter — this is the one piece of real side-effecting behaviour, and it's best-effort (logs and swallows on git failure).

**OVERLAP WITH plan_qa**: Direct. `counter-sanity` (`plan_qa/checks/counter_sanity.py`, Stage COMMIT) checks a newly-staged plan folder's number against the same `hooksdaemon.latestPlanNumber` counter and is genuinely `Level.BLOCK` (gated by `commit_gate_mode`, currently `warn` project-wide — see below). `no-new-collisions` (Stage COMMIT/SWEEP, BLOCK) catches the case this handler's `(expected, expected-1)` tolerance window can miss (a reused low number). Both plan_qa checks run on the STAGED tree, i.e. strictly later than this handler's PreToolUse point, but they are the only ones of the pair that can ever actually deny a commit.

**VACUITY**: Not vacuous as a matcher — 634 lines of tests cover TOCTOU races, nested-repo counters, 5-digit vs 3-digit numbers, bootstrap-from-scan, and date-directory false positives (`test_handle_not_poisoned_by_date_directories`). But its *enforcement* is structurally inert: `test_handle_write_incorrect_plan_number_too_high`/`too_low` (`:183-204`) assert only on the context text, never on `decision == Decision.DENY`, because the handler never denies. Given `commit_gate_mode: warn` and `sweep_mode: advise` are BOTH the project's actual live config, **the number-correctness check has no enforceable BLOCK path anywhere in this project's runtime today** — every layer (this handler, the commit gate, the sweep) is advisory-only in practice, despite `counter-sanity`'s own `Level.BLOCK` declaration.

**CONFIG**: `enabled: true`, priority 41 (`.claude/hooks-daemon.yaml:336-338`).

**COST**: `get_claude_md() -> None` (`:237-238`, confirmed by its own test `test_get_claude_md_returns_none`) — the agent has zero resident awareness this handler exists. Per-event cost is a ~15-line dramatic-sounding warning block that never actually enforces anything, which risks training the agent to treat "YOU MUST FIX THIS NOW" text as safely ignorable (it always was allowed through).

**HISTORY**: Present since the initial commit / Plan 00112 era (`bc4cccb0`, Plan 00112 Phase 3: "wire plan handlers to git-anchored numbering"), predating plan_qa (Plan 00144) by roughly 30+ plans. Six bugfix commits in its history (TOCTOU race `3c4e1c12`, hardcoded plan dir `11dbffd3`, date-directory false positive `0ecdff00`, archive-move false positives `99184f8d`/`b4dc88de`, Plan 00138 combined fix `595db286`) — a real, actively-corrected handler, just one whose substantive check has since been re-implemented, with actual teeth, in `counter-sanity`.

**FALSE-POSITIVE RECORD**: Substantial — 4-5 distinct historical false-positive fixes (archive moves, date directories, TOCTOU). No `LESSONS.md` entry found.

**SIGNAL: MERGE-INTO-PLAN-QA** — strongest evidence: the handler's own test suite proves it never denies on a wrong number (`decision` is asserted as `ALLOW` even in the "incorrect" test cases), and it carries no CLAUDE.md guidance, so the only thing standing between an agent and a wrong number is `counter-sanity`/`no-new-collisions` at commit time — which this handler doesn't replace, it just adds an earlier, toothless echo of the same check.

## plan_workflow

**CLAIM** (`:17-18`): provide guidance when creating plan files.

**MECHANISM**: `matches()` (`:33-45`) fires on `Write` (not `Edit`) to `CLAUDE/Plan/*/PLAN.md` (case-insensitive on the filename). `handle()` (`:47-61`) always returns a fixed advisory: task status icons (⬜🔄✅), "Include Success Criteria section", "Break tasks into manageable phases", "Update task status as you work", and a pointer to `CLAUDE/PlanWorkflow.md`. Non-terminal, priority 46.

**OVERLAP WITH plan_qa**: Partial and indirect. `template_metadata` (Stage EDIT, new-doc headers) covers a slice of "new plan doc guidance" territory. More significant is the overlap **between this handler's own `get_claude_md()` and `plan_qa_edit`'s `get_claude_md()`**: both independently state the identical size-tier numbers (18,000 bytes/350 lines advisory, 25,000/500 escalated, 35,000/900 blocked) and the identical three-remedies-none-is-deletion list (`plan_workflow.py:98-108` vs `plan_qa_edit.py:208-219` — the latter even shares a `remedy_sentence()`/`remedy_markdown_list()` helper from `plan_qa/remedy.py`, so the *prose* is DRY at the source-code level, but the two `## plan_workflow` / `## plan_qa_edit` sections both land in CLAUDE.md as full, separate, permanently-resident blocks restating the same numbers).

**VACUITY**: Not vacuous as a matcher (26 tests, realistic Write-tool payloads). The concern is not "does it fire on real input" but "does firing add information the agent doesn't already have."

**CONFIG**: `enabled: true`, priority 46 (`.claude/hooks-daemon.yaml:356-358`).

**COST**: `get_claude_md()` is ~3,442 chars, resident every session. **Separately**, the top-level `CLAUDE.md` (visible in this session's system prompt) contains `**See @CLAUDE/PlanWorkflow.md for complete workflow and templates**` under "## Planning Workflow" — an `@`-import, which per this project's own `markdown_organization` guidance principle ("avoid `@`-imports (they re-inline eagerly rather than defer)") means the full ~1,000-line `CLAUDE/PlanWorkflow.md` document is **already eagerly inlined into every session's context** (confirmed: its full contents were supplied verbatim in this session's system reminder alongside CLAUDE.md). That document already contains, verbatim in substance: task status icons and their meanings ("Task Status Icons" section), "Include a Success Criteria section", phase/task breakdown guidance, and "Update task status in real-time." So the per-Write `handle()` context this handler injects is a **third** copy of content already resident twice over (once via `PlanWorkflow.md`'s eager import, once via this handler's own `get_claude_md()`), for a file-creation event that, by definition, only happens once per plan.

**HISTORY**: Present since the initial commit (`74b0989c`)/Plan 00012-era migration, predating plan_qa by the same ~130-plan gap as `validate_plan_number`. Touched by Plan 00190 ("PLAN-vs-JOURNAL separation") and Plan 00211 ("wire plan_qa_edit and plan_workflow to shared remedy module") — i.e. it was consciously kept in sync with plan_qa's size-tier language rather than removed when plan_qa grew the same content, which suggests a deliberate (if not necessarily correct) decision to keep both.

**FALSE-POSITIVE RECORD**: None found — matcher correctness was never the issue for this handler; one bugfix (`e1214a33`, "advisory not visible in system-reminders") was a plumbing bug (wrong HookResult field), not a false-positive/negative match.

**SIGNAL: SUSPECT** — strongest evidence: the exact size-tier figures (18,000/350, 25,000/500, 35,000/900 and the "none is deletion" remedy list) are stated in full, three separate times, permanently or per-event, in a project whose own CLAUDE.md documents `@`-imports as an anti-pattern to avoid for precisely this reason (eager, non-deferred re-inlining).

## plan_time_estimates

**CLAIM** (module docstring, `:1`): block time estimates in plan documents.

**MECHANISM**: `matches()` (`:75-107`) fires on `Write`/`Edit` to any `.md` under `/Plan/`, excluding journal files (`is_journal_file`, a shared config-independent predicate). It runs content through ~17 `ESTIMATE_PATTERNS` regexes (effort/duration/ETA/deadline/target-completion-date shapes) line-by-line, with a co-located `TECHNICAL_PATTERNS` exemption list (TTL, cache, retention, session, rate limit, etc.) scoped to the *same line* as the estimate (deliberately, to prevent a single whole-document bypass — `:103-107`). `handle()` (`:134-151`) DENIES with a fixed explanation. Non-terminal-tag but effectively blocking (no `terminal=` override shown, default). Priority 45.

**OVERLAP WITH plan_qa**: None found — `grep -rl "estimate\|ETA\|deadline\|timeline" src/claude_code_hooks_daemon/plan_qa/` returns nothing. No check module in the catalogue references time/effort/duration content at all.

**VACUITY**: Not vacuous — the strongest evidence in the cohort. `test_plan_time_estimates.py` (660 lines) contains a whole named block of `test_bug_does_not_match_*` regression tests (cache TTL, API usage window, retention policy, rolling window, day-tracking feature, trial period — `:328-417`) proving this handler previously over-blocked *legitimate* technical-duration language and was iteratively fixed against real plan prose, plus `test_bug_still_matches_*` tests proving the fix didn't regress real positive cases (Phase time estimate, total effort, implementation time). This is exactly the "positive match against input a real agent would plausibly produce" bar the rubric asks for — the technical-term exemption patterns (`cache`, `TTL`, `rate limit`, `session`, `trial`) read as generalisations from encountered false positives, not hypothetical ones.

**CONFIG**: `enabled: true`, priority 45 (`.claude/hooks-daemon.yaml:352-354`). No mode knob — always denies on match.

**COST**: `get_claude_md()` ~1,513 chars, resident every session — reasonably tight, states the blocked/allowed shapes concisely, no duplication found elsewhere.

**HISTORY**: Present since the initial commit (`74b0989c`) — one of the oldest handlers in the project. Iterated substantially: Plan 00190 (twice — journal exemption by location not just filename, `2ffb869d`/`60b68d08`), Plan 00140 fix batch, and a dedicated "always-on guidance" addition (`93aa8393`) predating `get_claude_md()`'s general rollout.

**FALSE-POSITIVE RECORD**: The richest *documented, resolved* false-positive record of any handler in the cohort based on test-file naming alone (six `test_bug_does_not_match_*` cases, each a distinct legitimate technical term that used to false-positive).

**SIGNAL: KEEP** — strongest evidence: zero catalogue overlap plus the most convincing "real, not fixture-reverse-engineered" test evidence in the cohort (named `test_bug_*` regressions for cache TTL, API windows, retention policy, trial periods — each reads as a genuine plan-document sentence, not a regex fixture).

## plan_qa_edit (Stage 1 surface)

**CLAIM** (`:1-12`): lint the would-be content of a `PLAN.md`/index/journal-day-file write against the plan-QA edit-stage rule set; block on new-material violations in `edit_mode: block`.

**MECHANISM**: `matches()` (`:66-79`) gates on Write/Edit under the plan dir to a lintable file (`PLAN.md`, the plan-root `README.md`, or a journal day-file when journalling is active). `handle()` (`:119-148`) computes the would-be content (applying the Edit's old→new replacement itself for Edit calls, `:150-171`), builds a `CheckContext`, and runs every `Stage.EDIT`-registered check from the catalogue. Blockers deny (`edit_mode: block`, the live default here); non-blockers become advisory context.

**OVERLAP WITH plan_qa**: N/A — this handler *is* one of the two plan_qa dispatch surfaces the rest of the cohort is being compared against.

**VACUITY**: Not vacuous. Four acceptance tests (`:261-326`) exercise real Write-tool payloads including a same-day-vs-stale-date journal distinction that depends on wall-clock `date.today()` — a genuinely dynamic, non-fixture-reverse-engineered condition.

**CONFIG**: `enabled: true`, priority 44, `plan_workflow.qa.edit_mode: block` (`.claude/hooks-daemon.yaml:344-346`, `:731`) — this is the one surface in the family actually enforcing at BLOCK by default in this project.

**COST**: `get_claude_md()` ~5,019 chars — the largest single resident block in the cohort, but it is the authoritative statement of the whole rule set (status-line, task-grammar, doc-size, journal rules) and other handlers' guidance overlaps *into* it rather than the reverse.

**HISTORY**: Landed Plan 00144 (`4b7e829b`) and has been the active integration point for essentially every subsequent plan-QA feature (00163 journal checks, 00190 PLAN-vs-JOURNAL, 00192, 00197 today-only guard, 00211 shared remedy module, 00218 index-row-length) — i.e. this is where the family's real engineering investment has gone for the last ~74 plans.

**FALSE-POSITIVE RECORD**: Plan 00190/00211 field reports (see `plan_shrink_without_journal` / `has_staged_supporting_doc` docstring at `plan_qa/checks/common.py:413-433`) document a real production false positive (a legitimate PLAN.md-shrink-via-extraction commit was flagged) that was found and fixed with a named remedy (`has_staged_supporting_doc`).

**SIGNAL: KEEP** — this is the mechanism, not a duplicate of it.

## plan_qa_commit_gate (Stage 2 surface)

**CLAIM** (`:1-15`): evaluate the STAGED tree against cross-file plan-QA invariants at `git commit` time; warn-first rollout.

**MECHANISM**: `matches()` (`:161-170`) gates on a tokenised `git commit` Bash command with plan_qa policy enabled and `commit_gate_mode != off`. `handle()` (`:172-205`) resolves staged context (commit message + pathspecs extracted via careful `shlex` tokenisation that correctly separates `-m` values and value-taking flags from pathspecs, `:92-140`), runs every `Stage.COMMIT` check, and either denies (blockers present + `commit_gate_mode: block`) or returns all findings as advisory context. Explicitly exempts foreign/nested repos (`_is_foreign_repo`, `:207-218`).

**OVERLAP WITH plan_qa**: N/A — same as `plan_qa_edit`, this is a dispatch surface, not a duplicate.

**VACUITY**: Not vacuous — its own acceptance test (`:274-293`) exercises a real terminal-flip-without-archive-move scenario end to end via an actual `git commit`.

**CONFIG**: `enabled: true`, priority 44, `commit_gate_mode: warn` (**not** `block` — `.claude/hooks-daemon.yaml:348-350`, `:732`) — this is the mode that makes `validate_plan_number`'s and `plan_completion_advisor`'s advisory-only overlap findings (above) practically significant: in this project today, none of `counter-sanity`, `no-new-collisions`, `terminal-state-atomic`, `index-at-birth` etc. can actually block a commit; they only ever warn.

**COST**: `get_claude_md()` ~2,948 chars.

**HISTORY**: Landed Plan 00144 (`0491c5d5`), extended through Plan 00163 (journal coupling), 00190, 00192, 00200 (pathspec-commit resolution fix, `6b35f265` — a real bug: the handler used to check the wrong tree for `git commit <pathspec>` invocations), 00218.

**FALSE-POSITIVE RECORD**: Plan 00200's pathspec fix (`6b35f265`) is a genuine correctness bug (not false-positive but a false-negative/miss class) found and fixed.

**SIGNAL: KEEP** — same reasoning as `plan_qa_edit`; note for the judge that its `warn`-mode default is load-bearing evidence for two other handlers' MERGE verdicts above.

## Cross-cutting observations

1. **The family splits cleanly into "pre-plan_qa" and "is-plan_qa."** `validate_plan_number`, `plan_completion_advisor`, `plan_workflow`, and `plan_time_estimates` all predate Plan 00144 by 30-130+ plans (initial-commit or Plan 00112/00027-era). Two of the four (`validate_plan_number`, `plan_completion_advisor`) had their substantive checks independently re-implemented, *more completely*, inside plan_qa without ever being reconciled or removed. `plan_time_estimates` was never re-implemented (genuine gap-fill, correctly still standalone). `plan_workflow` sits in between — not re-implemented as a *check*, but its resident text was substantially re-derived inside `plan_qa_edit`'s own guidance.
2. **`get_claude_md() -> None` correlates with "safe to merge."** Both MERGE candidates (`plan_completion_advisor`, `validate_plan_number`) return `None` from `get_claude_md()` — the agent has no standing awareness these handlers exist, so their sole value is the per-event advisory, which is exactly the content plan_qa already produces (with more precision) on the same or a later surface. Neither loses meaningfully by being retired in favour of the plan_qa equivalent.
3. **`commit_gate_mode: warn` (project-wide default) quietly downgrades every COMMIT-stage plan_qa check to advisory-only in THIS project**, which is the load-bearing fact behind both MERGE verdicts: the "more authoritative" plan_qa check is not, today, actually more authoritative in enforcement terms — only in precision and completeness of the underlying logic. A judge weighing "should we just delete the legacy handler and lean on plan_qa" should note this file-level enable state, since flipping `commit_gate_mode` to `block` would be a prerequisite for that merge to be a pure improvement rather than a net loss of the (weak) early-warning layer.
4. **Resident CLAUDE.md duplication is real and measurable**, not just plausible: `plan_workflow`'s `get_claude_md()` (~3.4K chars) and `plan_qa_edit`'s (~5.0K chars) both state the identical 18,000/350·25,000/500·35,000/900 size-tier numbers and remedy list, permanently, every session — on top of the ~1,000-line `CLAUDE/PlanWorkflow.md` being eagerly `@`-imported into the same context already.

# Plan 00234 — Handler Verdicts

**Judge**: Fable (Opus-class), 2026-08-13
**Scope**: every handler in `src/claude_code_hooks_daemon/handlers/` — 97 rows
(96 production handlers plus the 8-variant `hello_world` diagnostic family as
one row), **plus Cohort H**: the two project-level handlers in
`.claude/project-handlers/` and the one plugin handler. **100 rows total.**

Cohort H was outside every research cohort's brief and was judged separately by
the main thread after the judge flagged the gap. That gap mattered: it holds the
audit's single highest-impact finding (H-2), and it was invisible to the cohort
structure because the defect is a contradiction *between* a handler and the
project's resident documentation, not a defect inside either one.

## Evidence basis — and what this is NOT based on

Verdicts rest on: the seven cohort dossiers (`RESEARCH-A` through `-G`), the
verdict-log measurement note (`RESEARCH-verdict-log-is-blind.md`), direct
source reads by the judge where a removal-grade claim needed confirmation
(`remind_prompt_library`, `cleanup_handler`, `bash_error_detector`, plus
filesystem checks for `CLAUDE/PromptLibrary/` and `untracked/temp/`), git
history, and the Plan 00233 precedent.

**No verdict rests on firing counts.** The daemon's own `hooks-daemon verdicts` report retains a **65-minute** window dominated 99.43% by status-line
renders, and its "Never-fired handlers (59)" list names the project's most
load-bearing safety handlers — rarity is what success looks like for a guard
on a rare-but-catastrophic operation. Every REMOVE below is grounded in
*cannot fire*, *nothing consumes it*, or *repeats information already in
context* — established from code and tests, never from absence in the log.
Where a dossier leaned on the never-fired list (Cohort A presented it as
context only), it was disregarded.

**Verdicts**: `KEEP` (sound, leave alone) / `FIX` (duty wanted, mechanism
broken or overpriced) / `MERGE→target` (duty wanted, better served elsewhere) /
`REMOVE` (no duty served) / `NEEDS-HUMAN-CALL`.

## Totals

| Verdict | Count |
| ------- | ----- |
| KEEP    | 76    |
| FIX     | 12    |
| REMOVE  | 10    |
| MERGE   | 2     |

Plus one instrument fix outside the handler roster: the verdict log itself
(see `RESEARCH-verdict-log-is-blind.md`).

---

## Cohort A — PreToolUse safety (18)

| Handler                   | Event      | Verdict | Confidence | Basis                                                                                                                                                                                                       |
| ------------------------- | ---------- | ------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| absolute_path             | PreToolUse | KEEP    | high       | Fired 3× in sampled window on its real audience (non-Claude-Code socket clients); trivial cost                                                                                                              |
| ancestry_preserving_merge | PreToolUse | KEEP    | high       | Narrow, tested, purpose-built for a real ancestry problem                                                                                                                                                   |
| ask_user_question_blocker | PreToolUse | KEEP    | high       | Real prefix-gate mechanism; only defect is a stale "disabled by default" docstring (one-line doc fix)                                                                                                       |
| curl_pipe_shell           | PreToolUse | KEEP    | high       | Classic RCE vector, cheap regex, evasion-hardened                                                                                                                                                           |
| dangerous_permissions     | PreToolUse | KEEP    | high       | Precise octal/symbolic world-writable match                                                                                                                                                                 |
| destructive_git           | PreToolUse | KEEP    | high       | Most load-bearing safety handler; history of closing real bypasses                                                                                                                                          |
| error_hiding_blocker      | PreToolUse | KEEP    | medium     | Researcher SUSPECT overturned: blocks a real LLM failure mode (`\|\| true`, bare except-pass) no default linter catches at write time                                                                       |
| git_message_backtick      | PreToolUse | KEEP    | high       | Built from a named production incident (cc7dddc0)                                                                                                                                                           |
| git_stash                 | PreToolUse | KEEP    | high       | Correct allowlist-first design, complements destructive_git                                                                                                                                                 |
| lock_file_edit_blocker    | PreToolUse | KEEP    | high       | Pure filename table, cannot false-positive                                                                                                                                                                  |
| pip_break_system          | PreToolUse | KEEP    | high       | Narrow, disjoint from sudo_pip                                                                                                                                                                              |
| pipe_blocker              | PreToolUse | KEEP    | medium     | Researcher STRONG-SUSPECT overturned: it fires, every fix closed a real bug, and the echd-capture workflow depends on it; complexity is earned — simplification is optional future work, not a removal case |
| root_recursion_guard      | PreToolUse | KEEP    | high       | Built from a named 115-min CPU incident                                                                                                                                                                     |
| sed_blocker               | PreToolUse | KEEP    | high       | Fired 3× in window; documented LLM failure mode                                                                                                                                                             |
| security_antipattern      | PreToolUse | KEEP    | high       | Researcher SUSPECT overturned: the doc-overclaim (SQL-injection etc.) was fixed at v3.52.0 and Plan 00204 owns the follow-up; shipped mechanism is sound — lesson feeds the guidance-truth guard proposal   |
| sensitive_content         | PreToolUse | KEEP    | high       | Densest documented false-positive-fix history in cohort; covers git metadata nothing else reaches                                                                                                           |
| sudo_pip                  | PreToolUse | KEEP    | high       | Narrow, hardened against real respellings                                                                                                                                                                   |
| worktree_file_copy        | PreToolUse | KEEP    | medium     | 3-way AND cannot misfire; narrow trigger surface but worktree usage is actively promoted                                                                                                                    |

## Cohort B — PreToolUse quality/workflow (18)

| Handler                      | Event      | Verdict | Confidence | Basis                                                                                                                                                                                                                |
| ---------------------------- | ---------- | ------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| qa_suppression               | PreToolUse | KEEP    | high       | Load-bearing anti-suppression block; note a batch sweep for pre-existing suppressions is a DBF gap worth closing                                                                                                     |
| tdd_enforcement              | PreToolUse | KEEP    | high       | Enforces (not restates) the project's core TDD policy                                                                                                                                                                |
| comment_changelog            | PreToolUse | KEEP    | high       | Measured zero-false-positive self-scan (Plan 00208); exemplary calibration                                                                                                                                           |
| comment_size                 | PreToolUse | KEEP    | high       | Grow/shrink tiering prevents the legacy-trap failure mode by construction                                                                                                                                            |
| markdown_organization        | PreToolUse | KEEP    | high       | Load-bearing (memory policy, plan routing); 44-commit churn is broad-surface hardening, each fix a distinct named scenario                                                                                           |
| daemon_location_guard        | PreToolUse | KEEP    | high       | Enforces the physical precondition of the do-not-edit-daemon rule                                                                                                                                                    |
| gh_issue_comments            | PreToolUse | KEEP    | high       | Real bypass found and fixed with regression test; DRY-pair note with gh_pr_comments                                                                                                                                  |
| gh_pr_comments               | PreToolUse | KEEP    | high       | Twin of the above, inherited the fix at birth                                                                                                                                                                        |
| daemon_restart_verifier      | PreToolUse | FIX     | medium     | Duty wanted, but the same paragraph reaches context three ways on every commit with zero rate-limiting — add per-session gating or trim                                                                              |
| task_tdd_advisor             | PreToolUse | REMOVE  | medium     | ~30-line payload is fully resident already via CLAUDE.md's eager `@`-imports of Features.md/PlanWorkflow.md; broad regex (`build`, `develop`) fires often; `get_claude_md()` is None so it adds nothing discoverable |
| agent_isolation_advisor      | PreToolUse | KEEP    | high       | Postmortem-driven, conditions on a live signal (thread count), silent in the common case                                                                                                                             |
| lsp_enforcement              | PreToolUse | FIX     | high       | Live reproduced false positive: multi-line Bash commands escape the single-file exemption (no `\n` in segment terminators); also verify the LSP tools it prescribes are reachable where it fires                     |
| global_npm_advisor           | PreToolUse | KEEP    | high       | Portable client-project rule; dormant here is expected                                                                                                                                                               |
| npm_command                  | PreToolUse | KEEP    | high       | Safe degrade-to-advisory default, largest test suite in cohort                                                                                                                                                       |
| validate_instruction_content | PreToolUse | KEEP    | high       | Guards CLAUDE.md/README stability; confirmed active (no explicit stanza — runs on base default; minor config-hygiene note)                                                                                           |
| daemon_docs_guard            | PreToolUse | KEEP    | high       | Client-install-only audience by design; structural dormancy in self-install mode is expected, not a defect                                                                                                           |
| web_search_year              | PreToolUse | KEEP    | high       | Self-updating year computation, cannot go stale                                                                                                                                                                      |
| british_english              | PreToolUse | KEEP    | high       | DBF gap (82 pre-existing violations) found and closed with a batch companion sharing the pattern dict by identity                                                                                                    |

## Cohort C — plan-workflow family (7)

| Handler                 | Event      | Verdict       | Confidence | Basis                                                                                                                                                                                                                            |
| ----------------------- | ---------- | ------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| plan_completion_advisor | PreToolUse | MERGE→plan_qa | high       | `terminal-placement-hint` (EDIT) + `terminal-state-atomic` (COMMIT) demonstrably co-fire on the same tool call with a more complete check                                                                                        |
| plan_number_helper      | PreToolUse | KEEP          | high       | The one duty plan_qa structurally cannot cover (Bash command text); five real false-positive fixes prove live use                                                                                                                |
| plan_qa_commit_gate     | PreToolUse | KEEP          | high       | IS the plan_qa Stage-2 surface                                                                                                                                                                                                   |
| plan_qa_edit            | PreToolUse | KEEP          | high       | IS the plan_qa Stage-1 surface, the family's active investment point                                                                                                                                                             |
| plan_time_estimates     | PreToolUse | KEEP          | high       | Zero catalogue overlap; richest documented false-positive regression suite in cohort                                                                                                                                             |
| plan_workflow           | PreToolUse | FIX           | medium     | Size-tier numbers + remedies stated three times in resident context; drop the per-Write advisory and dedupe the tier text with plan_qa_edit's guidance — keep its unique PLAN/doc/JOURNAL contract table                         |
| validate_plan_number    | PreToolUse | MERGE→plan_qa | medium     | Never denies (own tests assert ALLOW on wrong numbers) and `get_claude_md()` is None; `counter-sanity`/`no-new-collisions` are the real check — but its `_record_allocation` counter-advance side effect must be relocated first |

## Cohort D — PostToolUse + lifecycle (12)

| Handler                    | Event          | Verdict | Confidence | Basis                                                                                                                                                                                                                                                                            |
| -------------------------- | -------------- | ------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| bash_error_detector        | PostToolUse    | REMOVE  | medium     | Injects "output contains 'error'" about output already fully in the agent's context; fires on any stderr or common-word hit (110×/65min, the most active behavioural handler); dates to initial commit, never justified. Alternative if the nudge is wanted: narrow + rate-limit |
| validate_eslint_on_write   | PostToolUse    | KEEP    | high       | Correctly scoped to .ts/.tsx; dormant here because this repo is pure Python                                                                                                                                                                                                      |
| lint_on_edit               | PostToolUse    | KEEP    | high       | Denies on real failures; covers 9 languages the commit-time QA gate never touches                                                                                                                                                                                                |
| markdown_table_formatter   | PostToolUse    | KEEP    | high       | Self-consuming; correctly exempts JOURNAL/                                                                                                                                                                                                                                       |
| git_hooks_executable_fixer | PostToolUse    | KEEP    | high       | Narrow, real problem, least-privilege fix                                                                                                                                                                                                                                        |
| background_process_tracker | PostToolUse    | FIX     | high       | Writer never emits the `pgid` key `read_tracked_pgids` searches for — the designed wall-TTL breach can never fire; emit pgid or drop the dead path                                                                                                                               |
| command_hints              | PostToolUse    | KEEP    | high       | Config-driven, TTL-limited, verified live                                                                                                                                                                                                                                        |
| recovery_cron_advisor      | PostToolUse    | KEEP    | high       | Rate-limited advisory, iteratively corrected against real false positives                                                                                                                                                                                                        |
| compaction_signal          | PreCompact     | KEEP    | high       | Writer with a confirmed live reader (claude-supervise.py)                                                                                                                                                                                                                        |
| cleanup                    | SessionEnd     | REMOVE  | high       | Reaper with no producer: `temp/hooks/` is written by nothing anywhere in the codebase and does not exist on disk; the 00233 shape exactly                                                                                                                                        |
| worktree_create            | WorktreeCreate | KEEP    | high       | Mandatory — the event's stdout-as-path contract breaks without it                                                                                                                                                                                                                |
| worktree_remove            | WorktreeRemove | KEEP    | high       | Cheap, safe counterpart cleanup                                                                                                                                                                                                                                                  |

## Cohort E — SessionStart (12)

| Handler                      | Event        | Verdict | Confidence | Basis                                                                                                                                                                                                                                                                                                                         |
| ---------------------------- | ------------ | ------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| yolo_container_detection     | SessionStart | REMOVE  | medium     | Structurally cannot fire: `show_on_session_start` defaults False independent of `enabled: true`, in every install; its duty (environment awareness) is covered by environment_indicator and the permission_mode field. Removal cost: any client that flipped the nested flag loses a notice — name it in the upgrade manifest |
| project_handler_load_checker | SessionStart | KEEP    | high       | Textbook DBF: makes a silent protection failure loud                                                                                                                                                                                                                                                                          |
| hook_registration_checker    | SessionStart | KEEP    | high       | Self-heals and narrates only the repair — the reference pattern                                                                                                                                                                                                                                                               |
| optimal_config_checker       | SessionStart | KEEP    | high       | One-shot, silent when healthy; machine-wide-scope oddity noted, not worth churn                                                                                                                                                                                                                                               |
| git_filemode_checker         | SessionStart | KEEP    | high       | Cheap, rare condition, single-command fix                                                                                                                                                                                                                                                                                     |
| gitignore_safety_checker     | SessionStart | KEEP    | high       | Hash-cached, silent once fixed                                                                                                                                                                                                                                                                                                |
| suggest_status_line          | SessionStart | FIX     | high       | Only "decide once" handler with no cache/dismissal — fires every session forever for projects that deliberately declined; add the decay its siblings have                                                                                                                                                                     |
| git_upstream_checker         | SessionStart | KEEP    | high       | Real per-session condition; rewrite-detection is genuinely protective; note the unconditional per-session `git fetch --all` latency                                                                                                                                                                                           |
| version_check                | SessionStart | KEEP    | high       | 24h-cached, silent when current                                                                                                                                                                                                                                                                                               |
| plan_qa_sweep                | SessionStart | KEEP    | high       | Verified live: real findings in this repo right now                                                                                                                                                                                                                                                                           |
| ccy_supervisor_integrity     | SessionStart | KEEP    | high       | Narrow opt-in scope, silent-when-healthy verified                                                                                                                                                                                                                                                                             |
| plan_workflow_asset_checker  | SessionStart | KEEP    | medium     | Near-zero post-deploy firing, but guards the provisioning gap cheaply and silently                                                                                                                                                                                                                                            |

## Cohort F — status_line (14)

| Handler               | Event  | Verdict | Confidence | Basis                                                                                                                                                                                                                                |
| --------------------- | ------ | ------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| multithread_indicator | Status | KEEP    | high       | Bounded I/O, silent when single-threaded, fills a real Agent-View gap                                                                                                                                                                |
| model_context         | Status | KEEP    | high       | Best-cached handler in cohort; drives the sidecar thresholds                                                                                                                                                                         |
| environment_indicator | Status | KEEP    | high       | Memoised, zero per-render cost                                                                                                                                                                                                       |
| context_sidecar       | Status | KEEP    | high       | Writer with confirmed reader (claude-supervise.py); renders nothing                                                                                                                                                                  |
| supervisor_indicator  | Status | FIX     | medium     | Sound here, but a never-ccy project pays a full `/proc` walk every ~5s of rendering forever — lengthen/persist the negative cache                                                                                                    |
| current_time          | Status | KEEP    | medium     | Duplicates the terminal clock, but costs zero; removal machinery (registry, manifests, docs) costs more than the handler — deliberate leave-it                                                                                       |
| git_branch            | Status | FIX     | high       | 2.0s TTL vs ~1.15s render interval provably locks a 50% cache-miss rate ⇒ ~6,200 git subprocess spawns/hour from one handler; widen the TTL                                                                                          |
| git_repo_name         | Status | KEEP    | medium     | Memoised, zero cost; 📁-glyph overlap with working_directory is cosmetic                                                                                                                                                             |
| daemon_stats          | Status | KEEP    | high       | Cleared on cost (0 subprocess, confirmed); off-by-default upstream is the correct scoping                                                                                                                                            |
| upgrade_notifier      | Status | KEEP    | high       | Silent by default with stale-cache defence; mtime-gate is an optional micro-fix                                                                                                                                                      |
| account_display       | Status | FIX     | low        | Only handler with zero caching of any kind — uncached read+regex ~3,130×/hour for a static value; reuse settings_reader's mtime pattern                                                                                              |
| startup_cleanup       | Status | KEEP    | high       | Real writer/reader pair; un-windowed read is trivial (optional short-circuit)                                                                                                                                                        |
| usage_tracking        | Status | REMOVE  | high       | `matches()` hardcoded False since commit 71593163; config says `enabled: true` (a lie about runtime state); live data confirms 0 of 44,180 records; hardcoded model-limits table doubly stale; takes `stats_cache_reader.py` with it |
| working_directory     | Status | KEEP    | high       | Zero cost, silent at project root                                                                                                                                                                                                    |

## Cohort G — Stop / prompt / notification (16 rows)

| Handler                      | Event             | Verdict | Confidence | Basis                                                                                                                                                                                                                                         |
| ---------------------------- | ----------------- | ------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| auto_continue_stop           | Stop              | KEEP    | high       | Most heavily tested handler in the tree; enforces the STOPPING BECAUSE contract; stop-events.jsonl side-write has a documented forensic reader and a cap                                                                                      |
| task_completion_checker      | Stop              | REMOVE  | medium     | Unconditional static ~9-line checklist on every Stop; the substance is *enforced*, not just reminded, by auto_continue_stop; no plan, no measured effect                                                                                      |
| hedging_language_detector    | Stop              | KEEP    | high       | Mechanism wanted once; carries the resident guidance and (dismissive twin's) dedup — keep this side of the duplicated pair                                                                                                                    |
| dismissive_language_detector | Stop              | KEEP    | high       | Same — keep the Stop-side pair, resolve the duplication in nitpick's triggers                                                                                                                                                                 |
| dismissive_language          | nitpick (pseudo)  | FIX     | high       | Confirmed structural double-fire with its Stop twin on every Stop (`triggers: stop:1/1`, merge does not dedupe); drop the stop leg, keep the justified `pre_tool_use:1/5` coverage                                                            |
| hedging_language             | nitpick (pseudo)  | FIX     | high       | Identical duplication; same fix                                                                                                                                                                                                               |
| remind_prompt_library        | SubagentStop+Stop | REMOVE  | high       | Fires on every sub-agent completion AND every Stop, recommending `npm run llm:prompts` (no package.json exists) and `CLAUDE/PromptLibrary/README.md` (directory does not exist); no existence gating anywhere; verified by the judge directly |
| subagent_completion_logger   | SubagentStop+Stop | REMOVE  | high       | Writer with zero readers ever (repo-wide), independently tabulated `Consumer: NONE` by Plan 00181 and superseded in intent by Plan 00209's verdict log; 3.4 MB live                                                                           |
| notification_logger          | Notification      | REMOVE  | high       | Same class, same corroboration; observed content is 54 entries of one repeated event type                                                                                                                                                     |
| auto_approve_reads           | PermissionRequest | KEEP    | high       | Narrow, bypass-mode-gated, regression-tested against its own past security bug (Plan 00106)                                                                                                                                                   |
| git_context_injector         | UserPromptSubmit  | FIX     | medium     | Duty wanted (git state genuinely informs decisions) but ~460-token minimum payload on every prompt with zero change-detection — inject only on change                                                                                         |
| post_clear_auto_execute      | UserPromptSubmit  | REMOVE  | medium     | Its own originating plan is Cancelled as fundamentally unachievable and rates the surviving code "marginal"; fires on the first prompt of every session, not post-`/clear`                                                                    |
| critical_thinking_advisory   | UserPromptSubmit  | KEEP    | medium     | Best-gated advisory in the tree (~1-in-15); unmeasurable value is not evidence of no value at this cost                                                                                                                                       |
| idle_housekeeping_advisory   | UserPromptSubmit  | KEEP    | high       | Off-by-default upstream, bounded, documented dogfood opt-in                                                                                                                                                                                   |
| standing_authorisations      | UserPromptSubmit  | KEEP    | high       | Ships disabled, absence-tested, the anti-fabrication pattern this audit wants everywhere                                                                                                                                                      |
| hello_world family (×8)      | all events        | KEEP    | high       | Doubly gated off by default, excluded from docs when off, 520 lines of gate tests — governed diagnostics, not stray debug code                                                                                                                |

## Cohort H — project + plugin handlers (3)

Judged by the main thread from direct source reads; no research dossier.

| Handler               | Event        | Verdict | Confidence | Basis                                                                                                                                                                                               |
| --------------------- | ------------ | ------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enforce_llm_qa`      | PreToolUse   | KEEP    | high       | Sound per-segment mechanism with a real false-positive fix history (Plan 00200) and a shared `split_unquoted` scanner — but see H-2: the project's own resident docs instruct the command it denies |
| `release_blocker`     | Stop         | FIX     | high       | Matches any uncommitted edit to `README.md`/`CLAUDE.md` and then DENIES every Stop as "RELEASE IN PROGRESS"; also cites a moved path and a drifted test count                                       |
| `dogfooding_reminder` | SessionStart | KEEP    | high       | One line, ~30 tokens per session, already trimmed from ~40 lines by Plan 00128; cheapest advisory in the tree                                                                                       |

### H-1: `release_blocker` false-positives on ordinary documentation edits

`RELEASE_FILES` includes `README.md` and `CLAUDE.md` (`release_blocker.py:40-46`),
and `matches()` returns True on *any* uncommitted modification to them
(`release_blocker.py:94`). Both files are edited routinely for reasons that have
nothing to do with a release — the last eight commits touching them are ordinary
doc work — and **`CLAUDE.md` is regenerated and auto-committed by the daemon
itself** on restart.

When it fires, it is `terminal=True` and DENIES the Stop with "RELEASE IN
PROGRESS: Cannot end session until acceptance tests complete". So an ordinary
README edit, left uncommitted, traps the session until the file is committed or
the handler is disabled. It has not fired in the observed window, which is why
this is latent rather than a live incident.

Two smaller defects in the same DENY message: it cites
`CLAUDE/Plan/00060-release-blocker-handler/example-context.md`, which moved to
`Completed/` and no longer resolves; and it hardcodes "**89** EXECUTABLE
acceptance tests", a count that has drifted from the release documentation.

**Not a removal.** The duty is real and postmortem-backed — a v2.13.0 release
where acceptance testing was repeatedly skipped, and the testing caught a
shipping bug. Narrow the trigger to the files that genuinely only change during
a release (`pyproject.toml`, `version.py`, `CHANGELOG.md`, `RELEASES/v*.md`),
and derive the test count instead of hardcoding it.

### H-2: the resident documentation instructs the exact command a handler denies

`enforce_llm_qa` denies `scripts/qa/run_all.sh`. **Sixteen places in the
always-in-context documentation instruct the agent to run it**, including the
two that matter most:

- `CLAUDE.md:84` — the release QA gate: "Main Claude manually runs:
  `./scripts/qa/run_all.sh`"
- `CLAUDE/development/RELEASING.md:352` — Step 8, a **BLOCKING GATE**

Plus `CodeLifecycle/{General,Features,Bugs}.md`, which are the documents
`CLAUDE.md` names as mandatory reading before any code change.

An agent following the release procedure verbatim is denied by a project
handler at the blocking gate. Whichever side is wrong, the project currently
tells the agent to do something it then forbids — and both sides are resident in
every session, so the contradiction is always present.

This is the **claim-vs-mechanism drift** class Cohort A identified in
`pipe_blocker` and `security_antipattern`, but worse: those were a handler's own
guidance drifting from its own regex. Here two independent sources of truth
disagree, and the one with authority in the reader's mind (RELEASING.md, a
documented blocking gate) is the one the daemon overrules.

Fix in the docs, not the handler: point them at `./scripts/qa/llm_qa.py all`,
which is what the handler's own DENY message recommends. Noted in passing:
`CLAUDE/CodeLifecycle/README.md:76` describes the suite as "6 automated checks"
while it currently runs 21 — the same stale-count drift `CLAUDE.md` already
warns about having happened once before.

### H-3: `enforce_llm_qa` denies a git commit message written as a quoted heredoc

Found by hitting it: the commit recording H-1 and H-2 was itself DENIED, because
its message contains the script's name.

That should not happen, and the handler knows it. It carries a deliberate VCS
allowlist so a commit message mentioning the script is not treated as running
it, and its own docstring records fixing that exact false positive once
already — the whole-string `startswith("git ")` test that lost the exemption on
the ubiquitous `cd /workspace; git commit -m ...`.

The remaining hole is the **heredoc**. `_SEGMENT_SEPARATORS`
(`enforce_llm_qa.py:53`) includes `"\n"`, so a `git commit -F - <<'EOF'` body is
split into pseudo-commands and each line is judged on its own leading word. The
shell never expands a QUOTED heredoc — the body is literal text — so nothing in
it can invoke anything.

Measured directly against the handler (`matches()`, live):

| Command shape                                  | Verdict  | Correct? |
| ---------------------------------------------- | -------- | -------- |
| `git commit -m '…<script>…'` (single-quoted)   | allow    | yes      |
| `cd /workspace && git commit -m '…<script>…'`  | allow    | yes      |
| `git commit -F - <<'EOF'` … `<script>` … `EOF` | **DENY** | **no**   |
| `./scripts/qa/<script>`                        | DENY     | yes      |
| `cat scripts/qa/<script>`                      | allow    | yes      |

Segment split of the failing case: `[0] git`, `[1] Subject`, **`[2] prose`** ←
carries the script name with a non-allowlisted leading word, `[3] EOF`.

The sibling `pipe_blocker` already treats a quoted-delimiter heredoc as literal
and exempt, and `CLAUDE.md` documents that behaviour as deliberate. This handler
reuses that module's `split_unquoted` scanner but not its heredoc rule.

**Not the intentional-false-positive class.** `CLAUDE.md` says blocking handlers
matching dangerous patterns inside commit messages is intentional and must not
be "fixed", because acceptance tests depend on it. That reasoning does not apply
here: this handler explicitly *intends* to exempt git metadata, and the
exemption simply fails to reach one spelling of it.

Fix: treat a quoted-delimiter heredoc body as literal, as `pipe_blocker` does —
ideally by lifting that rule into the shared scanner so the two cannot disagree
again, which is exactly the reasoning `_split_top_level`'s docstring already
gives for sharing the scanner in the first place.

---

## Overturned researcher findings

| Handler                    | Researcher signal   | Judge verdict | Why overturned                                                                                                                                                                                                                               |
| -------------------------- | ------------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pipe_blocker               | STRONG-SUSPECT      | KEEP          | Every one of its 14 fix commits closed a real bug in a handler that demonstrably fires; the echd-capture workflow depends on it; "too complex" is an argument for future simplification, not for removal, and rewrites are a stated non-goal |
| security_antipattern       | SUSPECT             | KEEP          | The claim-exceeds-mechanism defect was documentation, already fixed at v3.52.0 with Plan 00204 owning the remainder; the shipped mechanism was never vacuous                                                                                 |
| error_hiding_blocker       | SUSPECT             | KEEP          | "Zero fires + zero hardening" is exactly what the anti-inference rule forbids treating as evidence; the constructs it blocks are real LLM habits nothing else catches at write time                                                          |
| daemon_docs_guard          | KEEP (scope caveat) | KEEP          | Concur, recorded to note the caveat was correctly reasoned: self-install dormancy is by design                                                                                                                                               |
| plan_workflow              | SUSPECT             | FIX           | Upgraded to an actionable verdict: the triplication is real but the handler's PLAN/doc/JOURNAL contract table is unique and valuable — dedupe, don't delete                                                                                  |
| remind_prompt_library      | SUSPECT             | REMOVE        | Upgraded: judge verified its two referenced targets (PromptLibrary dir, npm script) do not exist and it has no existence gating                                                                                                              |
| cleanup (session_end)      | STRONG-SUSPECT      | REMOVE        | Confirmed by direct source read + filesystem check: no producer, directory absent                                                                                                                                                            |
| current_time               | SUSPECT             | KEEP          | Zero cost; per Plan 00233's own accounting, a removal's client-facing cost (retired-handler entry, manifest, docs) exceeds this handler's total cost                                                                                         |
| daemon_stats               | SUSPECT             | KEEP          | Researcher's own evidence cleared it on cost; the config-appropriateness concern is already solved (off by default upstream)                                                                                                                 |
| git_repo_name              | SUSPECT             | KEEP          | Memoised and free; glyph overlap is cosmetic                                                                                                                                                                                                 |
| critical_thinking_advisory | SUSPECT (weak)      | KEEP          | Cost is tiny by design; "no measured behavioural effect" applies to almost every advisory and cannot alone justify removal                                                                                                                   |

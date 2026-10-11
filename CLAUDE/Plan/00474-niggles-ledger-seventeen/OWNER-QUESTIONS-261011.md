# Owner questions, 2026-10-11 (Plan 00474)

One sheet for the 15 rows (section 16, N419, added later) of [STATUS-INDEX.md](STATUS-INDEX.md) marked "Owner decision" (section 9, N373, turned out
already settled in code and stays only as a note). Each section gives the
question, the options, what each does, the coordinator's recommendation (a recommendation, not a ruling), and who can
implement it. Quoted text and line numbers are from [NIGGLES.md](NIGGLES.md). To answer, reply with the row id and a
letter, for example "N396 A".

## 1. N280: an older `CLAUDE.md` guidance section was written into main during a test run

Quote (line 545): "Owner decision, cause not found ... Changing the fixture to skip the restore when the post-test bytes
equal `HEAD` would weaken a guard, so it is left as a proposal rather than made."

- (a) Question: should the `no_test_writes_tracked_generated_docs` fixture skip its restore when the post-test bytes equal `HEAD`?
- (b) Options: A, change the fixture as proposed. B, leave it; keep the working rule "never restart the daemon while a test run is in progress".
- (c) A removes the one unproven candidate but weakens a guard. B keeps the guard and leaves the cause unfound.
- (d) Recommendation: B. No reproduction in three runs; do not weaken a guard for an unproven cause.
- (e) An agent can implement A once ruled (a fixture change with tests). B needs nothing.

## 2. N330: read `rate_limits.spend_limit` in `core/usage_snapshot.py`

Quote (line 3593): "verified ... adopt when a consumer is wanted (owner call)".

- (a) Question: is there a consumer for `spend_limit` now, so that it should be read?
- (b) Options: A, adopt it now. B, leave it until a consumer exists.
- (c) A adds an unused field to the snapshot. B changes nothing.
- (d) Recommendation: B.
- (e) An agent can implement A.

## 3. N333: `usage_pause` and Claude Code's "continue automatically at usage limit"

Quote (line 3596): "when a real limit is hit despite the ceiling, should the daemon leave Claude Code's auto-continue alone (current behaviour ...) or hold the auto-continued prompt behind the pause until `resume_at`?"

- (a) Question: leave auto-continue alone, or hold its prompt behind the pause until `resume_at`?
- (b) Options: A, leave it alone (current). B, hold the auto-continued prompt behind the pause.
- (c) A keeps today's behaviour: the daemon records `quota_auto_resume_*` and re-briefs. B stops a session spending on a limit the daemon knows is hit, at the cost of new gating logic.
- (d) Recommendation: A. Hitting a real limit despite the ceiling is the rare case, and A needs no code.
- (e) An agent can implement B in the daemon (hook handler); user settings that turn auto-continue on are the owner's or IaC's.

## 4. N334: the supervisor's post-compaction `/goal` and `continue` re-injection

Quote (line 3597): "Re-check the supervisor's post-compaction `/goal` and `continue` re-injection against the 2.1.274 fix (possibly redundant)."

- (a) Question: should the re-injection be re-checked and removed if Claude Code 2.1.274 made it redundant?
- (b) Options: A, re-check and remove if redundant. B, leave it as it is.
- (c) A removes dead behaviour if proven redundant. B keeps a harmless duplicate.
- (d) Recommendation: A for the check only; remove nothing without evidence from a live compaction.
- (e) The edit is in the live supervisor (`.claude/ccy/claude-supervise.py`), so the owner's or the infrastructure setup's to apply. An agent can do the read-only re-check.
- Re-check done ([report](subagent-reports/261011-n334-recheck-sonnet.md)): `continue` is still needed, since the 2.1.274
  fix covers only a `/goal` lost on `--continue`/`--resume` of a compacted session, while `continue` restarts the
  interrupted turn in a live one. Whether the `/goal` side is redundant cannot be told without a live compaction with
  an active `/goal`, which needs the owner (the live supervisor). So the question narrows to: run that live check, or
  leave the supervisor as it is.

## 5. N336: red-zone `/compact` aware of the `/autocompact` window

Quote (line 3599): "Make the supervisor's red-zone `/compact` aware of the `/autocompact` window."

- (a) Question: should the supervisor's forced compact consider Claude Code's own `/autocompact` window?
- (b) Options: A, make it aware. B, leave it as it is.
- (c) A avoids a double compaction near the window edge. B keeps the supervisor independent of Claude Code's setting.
- (d) Recommendation: B until a double compaction is actually observed.
- (e) Live supervisor: the owner's or infrastructure's to apply.

## 6. N337: gate the idle `/compact` on `prompt_cache.warm`

Quote (line 3600): "Gate the supervisor's idle `/compact` on `prompt_cache.warm`, so that compaction does not run against a cold cache."

- (a) Question: should the idle compact wait until the prompt cache is warm?
- (b) Options: A, gate on `prompt_cache.warm`. B, leave it as it is.
- (c) A avoids paying for a cold-cache compaction but may delay compaction. B keeps today's timing.
- (d) Recommendation: A, since a compaction against a cold cache is the costly case. The changelog review found no Claude Code idle compaction, so this one is the supervisor's own.
- (e) Live supervisor: the owner's or infrastructure's to apply.

## 7. N342: `setup_worktree.sh` cannot create a worktree from a host checkout with a long path

Quote (lines 3576-3580): "Every fix changes a convention, so it is the owner's call. Which of: (a) let the worktrees live at a short path outside the repo (a `WORKTREES_DIR` override) ...; (b) teach the acceptance gates to follow the socket discovery file and drop the refusal for an over-length path; or (c) declare a maximum host-checkout path length and document it?"

- (a) Question: which of the three conventions changes?
- (b) Options: A, `WORKTREES_DIR` override outside the repo. B, gates follow the socket discovery file; drop the refusal. C, declare and document a maximum host path length.
- (c) A touches `project_containment` and the worktree-isolation guards. B touches the acceptance gates only; the daemon already falls back to `/tmp` for its socket. C changes no code, but that one host stays unable to make worktrees.
- (d) Recommendation: B; the daemon already copes and only the gates insist on the path.
- (e) An agent can implement A or B with tests; C is a documentation edit. The host's checkout location is the owner's.

## 8. N361: fake-values registry has no commit-time BLOCK for a bad entry

Quote (line 3108): "Not done: a commit-time BLOCK for a bad entry (the sweep advises only); the owner ruling C7 names no severity."

- (a) Question: should an entry that is not visibly fake block the commit, or stay an advisory?
- (b) Options: A, BLOCK at commit. B, keep the ADVISE sweep check.
- (c) A makes the rule enforced but the "visibly fake" test is a substring heuristic (line 3109), so it may deny legitimate entries. B leaves enforcement to the large header comment and the sweep.
- (d) Recommendation: B; only this repository's agents write the file.
- (e) An agent can implement A.

## 9. N373: `bash_safe_mode` setters drop the whole handler on a bad value (settled in code, no question)

The fact-check of this sheet ([report](subagent-reports/261011-fact-check-blocked-status-sonnet.md)) found the
question stale: option A was already implemented as N374 item 12 (commit fa264c98f). `BashSafeModeHandler.validate_options`
(`handlers/pre_tool_use/bash_safe_mode.py:244-262`) reports a bad `mode` or `exempt_patterns` and keeps the handler on
its defaults. That was a coordinator change, not your ruling; it is listed under the limits below for confirmation.

## 10. N376: performance sweeps fail under the full gate's concurrent load

Quote (lines 2810-2812): "left for the owner or coordinator to choose between (a) that redesign, (b) a `--serial` pass after the matrix that runs the marked sweeps alone (which would add a stage), or (c) leaving the sweeps and accepting a re-run on a loaded host. Never loosen a threshold."

- (a) Question: how are the sweeps to run outside the concurrent phase?
- (b) Options: A, redesign `run_test_matrix.py` for a serial primary shard. B, add a `--serial` pass after the matrix. C, leave and re-run on a loaded host.
- (c) A is the largest change (checkpoint keys, result keying, coverage combine). B adds one gate stage. C costs a re-run now and then.
- (d) Recommendation: B.
- (e) An agent can implement A or B; C needs nothing.

## 11. N389: the development host's real name is in two tracked journal lines

Quote (lines 2371-2373): "To decide: whether the two journal lines may be edited in place, whether to add the host name to the secret word list, and whether history matters for this name."

- (a) Question: which of the three clean-ups, if any, do you want?
- (b) Options: A, edit the two lines in `Completed/00413-niggles-ledger-thirteen/JOURNAL/` in place. B, add the name to the secret word list. C, rewrite history. D, none.
- (c) A removes the working-tree copies only. B stops recurrence at write time. C removes it from published history, at the cost of a rewrite. D leaves it.
- (d) Recommendation: A and B; not C unless this name is more sensitive than a host name usually is.
- (e) B is yours only (a human edits the list). C is yours to run. A is blocked for agents by R-JOURNAL-HAND-WRITTEN-ENTRY, so an owner edit or an explicit exception is needed.

## 12. N396: the supervisor's self-install rule uses `.exists()`

Quote (lines 2219-2220): "Remedy: change `.exists()` to `.is_dir()` in the supervisor (then dogfood the hot reload per `CLAUDE/development/CcySupervisor.md`) and add the file-at-the-marker layout to the parity test."

- (a) Question: should the supervisor's `_daemon_untracked_dir` use `.is_dir()` to match the daemon?
- (b) Options: A, change it. B, leave it.
- (c) A removes a disagreement for a file at the marker path. B keeps a corner case where supervisor and daemon disagree.
- (d) Recommendation: A, as it is a one-word change.
- (e) Live supervisor: the owner's or infrastructure's to apply; an agent can write the parity test.

## 13. N397: copy-flag parsing is duplicated per handler

Quote (lines 2206-2207): "Remedy, if wanted: decide the clustered-flag verdicts on purpose in `worktree_file_copy` (a behaviour change with its own tests), then move the grammar onto a shared reader."

- (a) Question: do you want the clustered-flag verdicts decided on purpose and the copy grammar unified?
- (b) Options: A, do it. B, leave the duplicate.
- (c) A changes which word is the destination for `rsync -avze ssh src dst` and `cp -rS x a b`. B keeps two copies of the flag grammar.
- (d) Recommendation: B; the find-exec half is already shared and A changes verdicts.
- (e) An agent can implement A.

## 14. N402 part (b): commit gate that cannot place the repository

Quote (lines 2096-2098): "whether a commit gate that cannot place the repository for any other expansion (`cd $PROJ`) should allow with an advisory, as owner ruling A1 ... did for the secret guards, or stay fail-closed. Until (b) is ruled, `cd $PROJ && git commit` stays denied."

- (a) Question: should `cd $PROJ && git commit` be allowed with an advisory, or stay denied?
- (b) Options: A, allow with an advisory. B, stay fail-closed.
- (c) A removes a nuisance but lets an unchecked commit through. B keeps every commit checked; the one-level `$(git rev-parse --show-toplevel)`, `$PWD` and `$(pwd)` forms already pass.
- (d) Recommendation: B. The secret guards guard a leak; this gate guards history integrity.
- (e) An agent can implement A.

## 15. N411: Stop-hook 8-continuation cap

Quote (lines 1731-1733): "should auto-continue stand down (allow the stop) when `stop_hook_active` is set and it cannot read the transcript, or keep treating that stop as fresh? ... Behaviour is unchanged until decided."

- (a) Question: should auto-continue stand down when it cannot read the transcript on a re-entry?
- (b) Options: A, stand down. B, keep treating it as fresh.
- (c) A bounds the daemon at one block per chain in every case. B keeps blocking a stop whose earlier block it cannot confirm, so an unreadable transcript could reach the cap of 8.
- (d) Recommendation: A, on the principle of a bounded daemon; measured sessions never came near the cap, so B is also safe today. Do not set `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` in the supervisor.
- (e) An agent can implement A. Any cap variable would be the supervisor's, and so the owner's.

## 16. N419: `subagent_full_qa_blocker` judges an unknown program by flag shape (GitHub Issue #69)

Added after the sheet was written, from the issue-sdlc triage of #69.

- (a) Question: should the inline-code check judge only known interpreters, or keep judging every unknown program and extend the exempt list?
- (b) Options: A, an allow-list of interpreters. B, keep the shape rule and exempt `ps`, `file` and `docker` (for `-e`).
- (c) A fixes the whole class, but an interpreter missing from the list then passes silently. B stays fail-closed, but fixes only the spellings reported so far; 9 of the 11 in #69 are already silent on main.
- (d) Recommendation: B. It follows the N302/N416 precedent, and the default policy is an advisory, so a miss costs context, never a denial.
- (e) An agent can implement either.

## Deliberate limits recorded on the coordinator's judgement

These carry the 🚫 marker in STATUS-INDEX and were recorded as limits, not ruled by you:

- N415 residual: a one-branch `if` rebind and a function defined before the read, in `subagent_full_qa_blocker`.
- N418 residual: a helper that calls its own parameter ranks every call through it as may-run.
- N403: a never-run loop and `eval "$name"` in `project_containment`.
- N385: the careless spellings left open in the raw-text guards.
- N374: the one cold-index glob advisory residual in the v3.69.0 review.
- N354: a name built at run time is unseen by the upgrade guard (threat model).
- N378 is also marked as a limit but was ruled by you ("fine to leave"); it is listed for completeness.

Also a coordinator call rather than yours: N373's `bash_safe_mode` now keeps the handler on defaults and reports a bad
option (section 9).

Single question: confirm all of these (and the N373 call), or name the ones to reopen.

## N53 (ledger 00466)

The WorktreeCreate exit 127 under the daemon has two reproduced origins (git unspawnable on the daemon PATH, or a git hook running a missing command), and the error now names both and the PATH searched. The live cause awaits a recurrence. Nothing needs ruling.

## Other plans

- **00470** ([PLAN.md](../00470-persistent-session-optimisation/PLAN.md), [RUNBOOK.md](../00470-persistent-session-optimisation/RUNBOOK.md)). Three items, none an agent's to do:
  - Task 3.5: "Owner input: the host's restart unit around ccy is outside this repository." Gaps for infrastructure: nothing restarts a crashed `claude` or supervisor; `autoContinueAtUsageLimit` is not provisioned; the hostname override is not set. Question: will you provision the restart unit and these settings, or hand them to the infrastructure setup?
  - Task 4.1: "the transcripts item, `cleanupPeriodDays` in user settings, is for the owner or IaC". Question: what value, if any?
  - Task 4.3: "A/B the orchestrator: Sonnet main loop vs Opus ... Owner decides from the record." Question: run the model A/B, or drop it?
- **00479** ([PLAN.md](../00479-subscription-usage-monitor-and-ceiling/PLAN.md)). Open question 5: "should anything pause a session through the owner's override? ... (a) No change. (b) A hard backstop, for example 95%, that pauses even under an override. Recommended ... (c) Re-arm when usage rises a set number of points above the level recorded at clear time. (d) Scope the override to the windows that were breaching when it was written." Blocks Task 6.2.
- **00484** ([PLAN.md](../00484-dbf-adoption-and-toolchain-conformance/PLAN.md)). Success criterion 3, "The owner has ruled on every gap", "waits on the owner to confirm these calls and the earlier ones for G3, G10, G11, G14 and G16"; it gates Task 3.3, "Publish the conformance declaration (section 9.2), with its known gaps, from the README." Question: confirm the coordinator calls, so the declaration can be published?
- **00500** ([PLAN.md](../Completed/00500-full-qa-timing-and-speed/PLAN.md)). "For the owner: accept the per-hot-spot savings as the outcome, or ask for a controlled before/after run on a quiet host."

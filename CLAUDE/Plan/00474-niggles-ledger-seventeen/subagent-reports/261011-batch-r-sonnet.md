# Batch R report: N403 residuals and the N411 assessment

## Part 1: N403 residuals (fixed, test-first)

Both new test groups were written and seen failing before the code changed (13 failures), then passing.

### (a) `D=/tmp; cd $D && echo x > x`

`ProjectContainmentHandler._targets_after_cds` (`src/claude_code_hooks_daemon/handlers/pre_tool_use/project_containment.py`)
passed `step.directory` to `placed_moves` as written, so `$D` was an unplaceable move and the step drew only the
advisory. It now runs the chain through the new `_literal_moves`, which applies `substitute_known_variables` with the
`known_variables(command)` set the function already computes for the step text. That set is conservative by
construction: plain top-level literal assignments only, a name assigned once and not read earlier, none where the command
could write a variable by a route the daemon cannot see. A name nothing pins is left as written, so `cd $E` stays an
advisory (owner ruling B5: deny only on a positive finding).

### (b) Redirect on a group

`_walk` (`src/claude_code_hooks_daemon/utils/git_commit_parsing.py`) emitted the closer step (`}`, `fi`, `done`) with
the directory in effect AFTER the group's `cd`. It now keeps a stack of `(directory, uncertain)` pairs pushed where
`{`, `if`, `while`, `until`, `for` or `select` opens (read through leading reserved words, so `then { ...` counts), and
a closer step is emitted with the popped pair. The running directory is untouched, so a `cd` inside a `{ }` group still
carries on afterwards, as the shell does: `{ cd /tmp; }; echo x > y` still writes in `/tmp`. `case ... esac` is not
handled and reads as before.

### Tests and corpus

- `tests/unit/handlers/pre_tool_use/test_project_containment.py`: 4 literal-assignment deny cases, an in-repo
  variable `cd` that is allowed, an unpinned variable that stays an advisory, 5 group redirects that are allowed and 5
  that still deny (`cd /tmp && { make; } > x`, `{ true; } > /tmp/x`, `{ cd /tmp; }; echo x > x`, ...).
- `tests/unit/utils/test_git_commit_parsing.py`: closer step directory for `{`, `if`, `while`; the directory after a
  group still carries the `cd`.
- `tests/fixtures/ordinary_command_corpus.yaml`: `n403-group-redirect-read-before-the-group-cds`,
  `n403-if-group-redirect-read-before-the-group-cds`, `n403-cd-through-literal-assignment-stays-inside`.

Results: targeted run of the ordinary-command gate, `test_commit_location`, `test_git_facts*`,
`test_git_invocation_directory`, `test_git_commit_parsing`, `test_project_containment`, `test_command_journal` and the whole
`tests/unit/handlers/pre_tool_use` directory: 11327 passed.

### Red on main (round 3)

`PYTHONPATH=/workspace/src` is refused by the suite's source-tree guard, so the base commit (`96401a58e`, the branch
point) was checked out in a throwaway worktree, this branch's two test files were copied over it and the new tests were
run against its code. Result: 17 failed, 6 passed. Failing on main: all 4 `test_a_cd_through_a_literal_assignment_is_placed_and_denied`
cases, both `test_a_variable_move_is_denied_as_the_literal_move_is` cases, `test_a_combined_closer_reads_the_outer_loop_redirect_before_the_loop`,
all 5 `test_a_redirect_on_a_group_is_read_before_the_group_opened` cases, the 3 `test_a_group_redirect_keeps_the_directory_before_the_group`
cases and both `test_a_combined_closer_pops_one_group_per_closer_word` cases. Passing on main (guards, not proofs):
the unpinned-variable advisory test, `test_the_stack_stays_balanced_after_a_combined_closer`, and the group tests that
still deny. Pyright on the four touched `.py` files: 0 errors.

## Part 2: N411, the Stop continuation cap

Claude Code ends the turn after 8 consecutive Stop-hook continuations with no tool call between. Question: can any
daemon handler get there, and what does each assume about an overridden block?

### Which handlers can block, and how often

| Handler                                                                       | Where                                                                                                             | Re-entry rule                                                                                                                                                                                                                             |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auto_continue_stop`                                                          | `handlers/stop/auto_continue_stop.py` `matches` 728-774                                                           | stands down when `stop_hook_active` AND a `hook_blocking_error` / `Stop hook feedback:` marker is in the last 20 transcript lines (`utils/stop_hook_helpers.py` `has_recent_stop_hook_block`); with no marker it treats the stop as fresh |
| `cron_stop_enforcer`                                                          | `handlers/stop/cron_stop_enforcer.py:179-202` via `utils/cron_enforcement.py:352` and `utils/cron_refresh.py:211` | allows on `stop_hook_active` (logs a warning)                                                                                                                                                                                             |
| `usage_pause_stop_gate`                                                       | `handlers/stop/usage_pause_stop_gate.py:134-162`                                                                  | entry block delivered once regardless; later blocks allow on `stop_hook_active` (line 153)                                                                                                                                                |
| `stand_in_verdict` (called by auto-continue)                                  | `utils/stand_in_cron.py:143`                                                                                      | `None` on `stop_hook_active`                                                                                                                                                                                                              |
| `teammate_reap_advisor`                                                       | `handlers/stop/teammate_reap_advisor.py`                                                                          | never denies                                                                                                                                                                                                                              |
| Unattended-mode interceptor                                                   | `core/mode_interceptor.py:71`                                                                                     | skips on `stop_hook_active`                                                                                                                                                                                                               |
| project `release_blocker`                                                     | `.claude/project-handlers/stop/release_blocker.py:258`                                                            | `matches` is False on `stop_hook_active`                                                                                                                                                                                                  |
| SubagentStop: `subagent_report_size_blocker`, `subagent_report_path_verifier` | `matches` returns `not stop_hook_active` (lines 126 and 166)                                                      | one deny per chain                                                                                                                                                                                                                        |
| SubagentStop: `cron_subagent_stop_enforcer`                                   | scope MAIN, so a real subagent stop never reaches it; same shared gate as the Stop twin                           | one deny per chain                                                                                                                                                                                                                        |
| SubagentStop: `subagent_report_persistence`, `subagent_cache_aggregator`      | always ALLOW                                                                                                      | not blocking                                                                                                                                                                                                                              |

Stacking: non-terminal blockers (`cron_stop_enforcer`, `usage_pause_stop_gate`) and the terminal auto-continue run in
one dispatch and merge into one response (most restrictive wins), so they are ONE continuation, not several. A
re-entry loop is the other route to the cap. Every handler above except auto-continue breaks it on the first re-entry.
Auto-continue breaks it only while the block marker is visible: `has_recent_stop_hook_block`
(`utils/stop_hook_helpers.py:161-167`) returns False for a missing transcript path, a missing or unreadable file, or a
marker more than 20 lines back, and `matches` (`auto_continue_stop.py:758-766`) then treats the stop as fresh and blocks
again on every re-entry. Nothing in the code bounds that, so an unreadable transcript can take it to the cap of 8. What
keeps the daemon under the cap in practice is the marker being found, which is measured, not guaranteed.

### Measured

- 5 Claude Code session transcripts of this workspace (`~/.claude/projects/-workspace/*.jsonl`), counting Stop
  `hook_blocking_error` attachments since the last assistant `tool_use`: 95 chains, every one of length 1, so the
  marker auto-continue relies on is present in the current Claude Code transcript format. (Script kept in
  `untracked/scratch/transcript_runs.py`, not committed.)
- `untracked/stop-events.jsonl` (daemon's own log), real sessions only (UUID session ids, not marked synthetic): 3762
  records over 4 sessions; 54 denies; the longest run of consecutive denies is 4; all 7 deny-to-deny pairs show more than 20 KB of
  transcript growth, so there were tool calls between and the cap counter reset. 12 denies carried
  `stop_hook_active=true`, all `R-STOP-NO-REASON`, i.e. the "no marker found" fresh-stop path in `matches`.
  Caveat: the same file also holds test and probe sessions (ids such as `phase9-*`, `socket-*`) with runs of 91 to 213
  consecutive denies and zero transcript growth; they carry no real transcript and say nothing about Claude Code.
- Not observable from here: what Claude Code does at the cap (whether any hook is called again), so "ends unrecorded" is
  inferred from the documentation text, not tested.

### What each handler assumes about an overridden block

- No handler reads state recorded at block time as proof the block was honoured. `stop-events.jsonl` is written by
  `_log_stop_event` (`auto_continue_stop.py:1233`) and read by nothing in `src/`.
- Disclosure ladder: `_render_branch_message` marks a rule disclosed when it renders the verbose text. An overridden
  block would make the next one terse, but the model has already seen the verbose text on the first block of the chain.
- Human-blocked marker: written on the ALLOW path of a `STOPPING BECAUSE: [awaiting-human]` stop BEFORE the stand-in
  block (`auto_continue_stop.py:831-836`). It states the stop's content, not that the block held. If the stand-in block is
  overridden, the end state (marker armed, no stand-in cron) is the same one the re-entry allow already produces by
  design (`stand_in_cron.py:143` logs a warning).
- `usage_pause_stop_gate.matches` calls `try_start_pause` (a write) before `handle` delivers the directive. An overridden
  entry block would leave a pause with no resume cron. Reaching that needs eight prior continuations the daemon cannot
  cause, and the pause is entered by the tool and prompt gates the same way, so Stop is not special.
- Cron enforcers are stateless on the deny path (the `SessionAdviceCounter` advances only on the allow-with-context path).
- `subagent_report_persistence` runs on every SubagentStop including re-entries, so an overridden block still persists
  the reply.

Conclusion: no behaviour change; N411 stays open on the owner question below. The measured sessions never came near
the cap.

### Owner question (not acted on)

Should auto-continue stand down (allow the stop) when `stop_hook_active` is set and it cannot read the transcript, or keep
treating that stop as fresh? Standing down bounds the daemon at one block per chain in every case; keeping it blocks a
stop whose earlier block it cannot confirm.

### Recommendation (separate, not acted on)

The measurements give no reason for the ccy supervisor to set `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`; a raised cap also
widens the loop a non-daemon Stop hook could run.

Nothing under `.claude/ccy/`, no settings.json and no `ccy.env.local` was touched.

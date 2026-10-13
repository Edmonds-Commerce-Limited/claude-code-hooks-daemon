# Fact-check: #106 corrections (commit c8fd0a490)

Scope: claims added or changed in MANUAL-GOALS.md and PLAN.md by c8fd0a490. Searched with `git grep` excluding tests/fixtures/cyber-flag; the secret word list was not opened.

## REFUTED / PARTLY REFUTED (most consequential first)

1. Claim 5: "the sidecar directory ... today only the daemon writes" (MANUAL-GOALS.md trade-off bullet). PARTLY REFUTED.

   - `claude-supervise.py --emit-model-switch <family>` (`_run_emit_model_switch`, line 9628) calls `write_model_switch_signal(sidecar_dir, ...)` (line 9653, writer at 3078-3111). `sidecar_dir` comes from `_default_sidecar_dir()` (1763), the same directory that holds `*.goal-intent`.
   - So the supervisor script already writes one file type there, as a manual CLI test trigger. The running supervisor loop does not write there; its other writes go to the status dir `sidecar_dir.parent` (e.g. 2147, 9250) or the ccy state dir (8585).
   - Plan change: reword to "the supervisor's running loop writes nothing into the sidecar directory today; only the daemon does, plus the supervisor's manual `--emit-model-switch` CLI trigger". The "new write path to review" conclusion still holds for the loop, but "first file the supervisor writes there" is wrong.

2. Claim 1 (partial): "it types `/goal` only from a `*.goal-intent` signal". PARTLY REFUTED (incomplete).

   - The supervisor also types `/goal clear` from a `*.goal-clear` signal (`_GOAL_CLEAR_GLOB` 2614, `_GOAL_CLEAR_COMMAND` 2615, Plan 00321). The daemon writes that signal too.
   - It does not affect the conclusion: the plain `/goal <text>` form (7281) is typed only from `*.goal-intent`, and a goal-clear is a separate path. Add "(and `/goal clear` from a `*.goal-clear` signal)" if exactness is wanted. It bears on Task 5.2, "goal-clear outranking goal-intent".

## Verified

| #   | Claim                                                                               | Verdict                                                  | Evidence                                                                                                                                                                                          |
| --- | ----------------------------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | After a compaction the supervisor injects only `continue`                           | VERIFIED                                                 | `claude-supervise.py` 5983-6001: on a detected compaction the only decision is `WOULD_CONTINUE`. The payload is `_CONTINUE_BODY = "continue"` (6285, 6546-6547). No `/goal` is sent on that path. |
| 2   | The supervisor types `/goal <text>` only from `*.goal-intent`                       | VERIFIED (see item 2 above for the `/goal clear` caveat) | `_GOAL_SIGNAL_GLOB = "*.goal-intent"` (1198), loader at 2706, payload `f"{_GOAL_COMMAND} {goal_line}"` at 7281.                                                                                   |
| 3   | The daemon writes `*.goal-intent`                                                   | VERIFIED                                                 | `handlers/post_tool_use/goal_injection.py:148` (`_SIGNAL_SUFFIX = ".goal-intent"`) and `:486`.                                                                                                    |
| 4   | "No goal-intent signal written while the mode is on" is the right suppression point | VERIFIED                                                 | The signal writer is the daemon's `goal_injection`. PLAN.md line 58 already uses the same "no goal signal" wording for BLOCKED.                                                                   |
| 5   | Question 7 of PLAN.md is BLOCKED suppressing the post-compact `continue`            | VERIFIED                                                 | PLAN.md:94, "Under BLOCKED, suppress the supervisor's post-compact `continue`? Default: yes".                                                                                                     |
| 6   | PLAN.md question 11 wording matches MANUAL-GOALS.md item 2                          | VERIFIED                                                 | PLAN.md:99, "whether it also suppresses the post-compaction `continue`". MANUAL-GOALS.md item 2 is titled "Post-compaction `continue`".                                                           |
| 7   | Task 8.1 is the `/goal clear` spike                                                 | VERIFIED                                                 | PLAN.md:168 and MANUAL-GOALS.md:49 agree. No stale "Phase 0 gains a spike" text remains in MANUAL-GOALS.md.                                                                                       |
| 8   | Task 8.3 adds `manual-goals` to the precedence list                                 | VERIFIED                                                 | PLAN.md:171-172. The precedence list is in PLAN.md Goals at line 71 (Goals runs from line 30 to line 76), and it does not yet contain `manual-goals`, consistent with a future task.              |
| 9   | The supervisor already reads modes from the per-session file (Task 5.1)             | VERIFIED                                                 | PLAN.md:144 is the supervisor reader for the session-modes file. This is a plan task, not existing code.                                                                                          |

Totals: 11 claims checked, 9 verified, 2 partly refuted (items 1 and 2 above), 0 unverifiable.

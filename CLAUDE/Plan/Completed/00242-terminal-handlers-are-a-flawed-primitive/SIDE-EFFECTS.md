# Plan 00242 — Side-effect audit (Phase 2, Task 2.1)

## The hazard

`handle()` runs before the chain has decided. Any handler that mutates
durable state there — spends a cooldown, advances a counter, marks
something "already said" — does so for a tool call that a LATER handler may
deny. The tool call never runs, but the state says it did, and the next
real call is silenced.

Before Plan 00242 the exposure was narrow: a deny from a terminal handler
ended the chain, so only the handlers AHEAD of the denier ran. Under the
invariant (an ALLOW never ends the chain) nothing changes for a deny, but in
collect-all mode every matching handler runs after a deny, so every
side-effecting handler is exposed on every denied call. Phase 2 audits them
and gates the side effects on the final decision.

## The mechanism

- `Handler.commit_side_effects(hook_input, chain_decision)` — a concrete
  no-op on the base class, called by `HandlerChain.execute()` once per
  EXECUTED handler after the merged decision is settled, in every mode. A
  crash in it is logged and surfaced as context; it can never change the
  decision.
- `core/side_effect_journal.py` — `SideEffectJournal.snapshot(mapping, key)`
  before each mutation in `handle()`, then `rollback()` on a restrictive
  decision or `commit()` otherwise. `handle()` commits any previous,
  never-committed journal on entry so a caller outside the chain (a unit
  test) sees today's behaviour unchanged.
- The handler history (`data_layer.history`) now records each handler's OWN
  verdict from `ChainExecutionResult.decisions`, not the merged decision
  attributed to every matched handler.

## Audit

| Handler                               | Event        | State                                                                                                                                                                         | Exposure                                                                                                                                                   | Remedy                                                                                                                                                                |
| ------------------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `command_hints`                       | PostToolUse  | per `(session, hint)` TTL + calls-since-fire map                                                                                                                              | A hint fired on a call that `lint_on_edit` then blocked stays silent for the whole TTL                                                                     | Journalled; `commit_side_effects` rolls back on deny. Tests: `TestCooldownIsNotSpentOnADeniedCall`                                                                    |
| `recovery_cron_advisor`               | PostToolUse  | per-plan creation-seen / completion-seen markers, progress counter                                                                                                            | A creation advisory spent on a blocked PLAN.md write is never repeated; denied edits advance the every-Nth counter                                         | Journalled (including the bounded-map eviction); rolls back on deny. Tests: `TestAdviceIsNotSpentOnADeniedCall`                                                       |
| `lsp_enforcement`                     | PreToolUse   | `history.count_blocks_by_handler` (block-once)                                                                                                                                | The controller recorded the MERGED decision for every matched handler, so another handler's deny counted as lsp's block                                    | Controller records per-handler verdicts. Test: `test_history_records_each_handlers_own_verdict`                                                                       |
| `DisclosureTracker` users             | PreToolUse   | verbose-once ladder per `(transcript, rule)` (`bash_safe_mode`, `curl_pipe_shell`, `comment_size`, `docs_qa_*`, `gh_*_comments`, `lint_on_edit`, `ask_user_question_blocker`) | `mark_disclosed` fires when the handler DENIES and the verbose text is what is shown — the deny is delivered (lead or excerpt) so the disclosure is honest | None needed. Accepted edge: an excerpt cut at `COLLECT_ALL_DENY_EXCERPT_CHARS` (1500) could truncate a verbose message once; bound chosen to hold a full rule message |
| `write_clobber_guard`                 | PreToolUse   | per-session set of paths whose contents were read                                                                                                                             | Records on a Read, which nothing denies in practice; a Write it denies records nothing                                                                     | None needed                                                                                                                                                           |
| `git_index_watch` / plan asset probes | SessionStart | filesystem probes, no per-call state                                                                                                                                          | Not exposed: SessionStart has no deny path that gates later work                                                                                           | None needed                                                                                                                                                           |
| Status-line handlers                  | Status       | render caches                                                                                                                                                                 | Status never denies                                                                                                                                        | None needed                                                                                                                                                           |

### What "burnt for a denied call" does not cover

A handler that DENIES and records its own verbose-disclosure or block-once
state has not burnt anything: its deny is in the response (as the lead or
as an `Also denied by:` excerpt), so the agent saw it. The audit is about
ADVISORY state spent on a call the agent never got to make.

## Decision (Task 2.1: "decide whether side effects move to a post-decision phase")

Side effects stay in `handle()` — moving every stateful handler to a
two-phase compute/apply split would touch far more code for the same
result — and are **committed or rolled back after the decision** through
`commit_side_effects`. The journal keeps each handler's change to two lines
per mutated key. The hook fires in every mode, so the pre-existing (narrow)
exposure in the default mode is closed as well, not just the collect-all one.

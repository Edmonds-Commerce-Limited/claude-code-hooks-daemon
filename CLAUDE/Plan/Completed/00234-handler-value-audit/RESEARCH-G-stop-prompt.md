# Cohort G: Stop / Prompt behavioural-nagging handlers — audit dossier

## Cohort summary

| Handler                                           | Signal         | One-clause reason                                                                                                                                                                                                                 |
| ------------------------------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auto_continue_stop` (stop)                       | KEEP           | Verified load-bearing: 2,939-line unit test file + dedicated integration test + bug-regression file; enforces the `STOPPING BECAUSE:` convention CLAUDE.md documents                                                              |
| `dismissive_language_detector` (stop)             | SUSPECT        | Fires redundantly alongside `nitpick/dismissive_language` on every Stop event (see resolution below); real "cry wolf" incidents fixed same-day (Plan 00224, 00225)                                                                |
| `hedging_language_detector` (stop)                | SUSPECT        | Same duplication + same incident history as above                                                                                                                                                                                 |
| `task_completion_checker` (stop)                  | SUSPECT        | Always-match, static generic checklist, zero evidence of behavioural effect, overlaps conceptually with the Stop-explanation contract already in resident `CLAUDE.md`                                                             |
| `dismissive_language` (nitpick)                   | STRONG-SUSPECT | Genuinely double-fires with its Stop twin on every Stop event (`triggers: ["stop:1/1"]`); no plan documents why both need Stop coverage                                                                                           |
| `hedging_language` (nitpick)                      | STRONG-SUSPECT | Same double-fire as above                                                                                                                                                                                                         |
| `remind_prompt_library` (subagent_stop)           | SUSPECT        | Fires on **every** sub-agent completion with static "capture your prompt" nag; no evidence anyone (human or agent) has ever run the command it suggests                                                                           |
| `subagent_completion_logger` (subagent_stop)      | STRONG-SUSPECT | Writer-with-no-reader — the exact defect class `transcript_archiver` was deleted for, confirmed independently by two later plans (00181, 00209)                                                                                   |
| `notification_logger` (notification)              | STRONG-SUSPECT | Same writer-with-no-reader defect, same corroborating plans                                                                                                                                                                       |
| `auto_approve_reads` (permission_request)         | KEEP           | Narrow, safety-gated (`bypassPermissions` only), fixed a real security bug (Plan 00106), has a negative acceptance test                                                                                                           |
| `critical_thinking_advisory` (user_prompt_submit) | SUSPECT (weak) | Reasonable rationale and well-gated (3 gates, ~1-in-15 firing rate), but zero evidence of demonstrated behavioural impact since Plan 00051 shipped                                                                                |
| `git_context_injector` (user_prompt_submit)       | SUSPECT        | Fires unconditionally on **every** prompt, no cache/dedup/throttle — measured ~460 tokens per injection in this repo's own clean `git status`, repeated verbatim between prompts when nothing changes                             |
| `idle_housekeeping_advisor` (user_prompt_submit)  | KEEP           | Off-by-default upstream, bounded (max 1 pass/session), report-only, only enabled here for deliberate dogfooding                                                                                                                   |
| `post_clear_auto_execute` (user_prompt_submit)    | SUSPECT        | Its own originating plan (Cancelled 00087) concluded the goal is **impossible via hooks** and rated the surviving prototype's value "marginal"; also fires on the first prompt of *every* session, not specifically post-`/clear` |
| `standing_authorisations` (user_prompt_submit)    | KEEP           | Ships disabled-by-default upstream, this repo deliberately enabled one entry, clean audit trail, no red flags                                                                                                                     |
| `hello_world` × 8 (all event types)               | KEEP           | Globally gated off (`enable_hello_world_handlers: false`), excluded from generated docs when off, covered by 520 lines of dedicated tests — legitimate scaffolding, not stray debug code                                          |

---

## nitpick vs stop — resolved

**Not two independent implementations.** `handlers/nitpick/dismissive_language.py:17-30` and `handlers/nitpick/hedging_language.py:17-30` directly `import` the class-level pattern-list constants (`NOT_OUR_PROBLEM_PATTERNS`, `MEMORY_PATTERNS`, etc.) from `handlers/stop/dismissive_language_detector.py` and `handlers/stop/hedging_language_detector.py` respectively. The regex patterns are a genuine single source of truth.

**But both classes are independently-registered `Handler` subclasses that both actually fire, on the same event, in production — and both are enabled in this repo's own config right now.** This is the important finding, verified via code, not speculation:

- `.claude/hooks-daemon.yaml:777-786` — `pseudo_events.nitpick.enabled: true`, `triggers: ["pre_tool_use:1/5", "stop:1/1"]`, and both `dismissive_language`/`hedging_language` nitpick handlers `enabled: true`.
- `.claude/hooks-daemon.yaml:605-611` — the Stop-event `hedging_language_detector` (priority 30) and `dismissive_language_detector` (priority 58) are *also* `enabled: true`.
- `daemon/controller.py:726-735` — on **every** real event (Stop included), after the real handler chain runs, `PseudoEventDispatcher.check_and_fire()` is called unconditionally and any pseudo-event result is merged into the same response via `merge_pseudo_results()`, which `context.extend()`s — it does not deduplicate against what the real chain already injected.

Net effect: when a Stop-time message contains a genuine dismissive/hedging phrase, the agent receives **two** advisories in the same turn — the Stop handler's full multi-paragraph block (`dismissive_language_detector.py:264-292`) *and* the nitpick handler's one-line summary (`nitpick/dismissive_language.py:109-113`) — from two separately-priced dispatch paths. This is not a false positive; it is confirmed structural duplication of a real finding.

**Historical origin explains the PreToolUse leg, not the Stop leg.** Plan 00081 (`CLAUDE/Plan/Cancelled/00081-pseudo-events-nitpick-handler/PLAN.md:13`) created the nitpick pseudo-event specifically because "the Stop-event-based `DismissiveLanguageDetectorHandler` failed to fire" during Plan 00080 — Stop events fire once per session, so mid-plan deflection went uncaught. That justifies `pre_tool_use:1/5` as new coverage. No plan document found explains why `stop:1/1` was *also* added to nitpick's triggers rather than the dedicated Stop handlers being retired in its favour, or the Stop leg being dropped from nitpick.

**Resolution for the judge**: this is real, confirmed, in-production duplication at the Stop event specifically (not at PreToolUse, where nitpick is the only coverage and is justified). Whichever of the two Stop-level mechanisms is kept, the other's Stop coverage is redundant.

---

## `auto_continue_stop` (stop) — priority 10, TERMINAL

1. **CLAIM**: "Intercept Stop events and enforce explicit stop reasons or auto-continue" (HOOKS-DAEMON.md); enforces the `STOPPING BECAUSE:` convention.
2. **MECHANISM**: Fires on every Stop; DENY if the last assistant message doesn't start with `STOPPING BECAUSE:` and there's no unresolved tool error requiring recovery; also hard-blocks rhetorical continue-questions smuggled inside an explained stop (Plan 00146).
3. **CONSUMER**: The handler's primary function (DENY/ALLOW enforcement) has no consumer in the logging sense — it acts directly. But it ALSO has a side-effect write channel: `_log_stop_event()` (`auto_continue_stop.py:698-728`) appends one JSON line per Stop event to `{project}/untracked/stop-events.jsonl` ("for debugging"). **Measured live in this repo**: `untracked/stop-events.jsonl` is **953,601 B** — same defect shape as the two STRONG-SUSPECT loggers below, but with one documented difference: `CHANGELOG.md:1386` (the v3.31.0 Sev-1 infinite-advisory-loop postmortem) states the bug was "confirmed directly in `untracked/stop-events.jsonl`, which showed `stop_hook_active=true`/`decision=allow` repeating with no bound" — i.e. this file WAS read at least once, manually, during a real incident investigation. That is a genuine (if occasional, manual, forensic-only) consumer, which the other two logs below have zero evidence of ever having.
4. **VACUITY**: N/A — this is exercised on every single real stop in every session; not a rare-input concern.
5. **DUPLICATION**: None found.
6. **CONFIG**: `enabled: true`, priority 10 (`.claude/hooks-daemon.yaml`); `daemon_restart_verifier`/`ask_user_question_blocker` and this doc's own `Stop Explanation Required` section reference it directly.
7. **COST**: One DENY-check per Stop; cheap. The `stop-events.jsonl` side-write is capped at `_STOP_EVENTS_MAX_BYTES = 2 MiB` (line 57, front-truncated on breach, Plan 00181) — current 953,601 B is ~45% of that cap.
8. **HISTORY**: `git log --follow` shows 40,403-byte file, 2,939-line test file (`tests/unit/handlers/stop/test_auto_continue_stop.py`), a dedicated bug-regression test file (`test_auto_continue_stop_bug.py`), and an integration test (`tests/integration/test_auto_continue_stop_daemon_flow.py`). This is the most heavily tested file in the cohort by a wide margin.
9. **FALSE-POSITIVE RECORD**: Plan 00146 hard-blocked a rhetorical-continue-question loophole found in production.

**SIGNAL: KEEP** — the enforcement logic is verified load-bearing and does not warrant further budget. The `stop-events.jsonl` side-write is a minor, separable concern (see cross-cutting note below): it is the ONE log in this cohort with any evidence of a real reader, but that reader was a human doing manual forensics during a Sev-1, not an automated or routine consumer — closer to `verdict_log.py`'s territory than to a genuinely dead write.

---

## `dismissive_language_detector` (stop) — priority 58, ADVISORY

1. **CLAIM**: Detects the agent deflecting responsibility ("pre-existing issue", "out of scope") or dressing up a premature halt ("natural checkpoint") instead of fixing/continuing (`dismissive_language_detector.py:1-17`).
2. **MECHANISM**: Reads `transcript_path`, extracts the **last assistant message only** (`_get_last_assistant_message`), scans against 5 pattern categories (37 total regexes) with quoted-span blanking (Plan 00225). Injects one of two multi-paragraph advisory blocks depending on category. Per-session dedupe on identical (session, phrase-set) key.
3. **CONSUMER**: N/A — advisory context, read by the agent in the next turn.
4. **VACUITY**: `test_dismissive_language_detector.py:64-70` (`test_a_genuine_deflection_is_still_reported`) asserts against `"That is out of scope for this change."` — a short synthetic sentence built directly from the phrase list, not an excerpt from a real transcript. Every other positive test (`test_matches_pre_existing_issue`, etc.) is the same shape: phrase embedded in a minimal carrier sentence. No test asserts against organic multi-sentence agent prose.
5. **DUPLICATION**: See "nitpick vs stop" above — genuinely double-fires with `nitpick/dismissive_language.py` on every Stop event when a match exists.
6. **CONFIG**: `enabled: true`, priority 58 (`.claude/hooks-daemon.yaml:609-611`).
7. **COST**: Only fires on a match (not every Stop), so baseline cost is low; cost concern is the duplication above, not standalone frequency.
8. **HISTORY**: Traces to Plan 00080/00081 (agent used dismissive language to deflect shellcheck warnings; Stop-only detection was found unreliable, motivating the nitpick pseudo-event). Predates `get_claude_md()` infrastructure (added later, commit `4416f1ee`).
9. **FALSE-POSITIVE RECORD**: Two real, measured incidents in this exact repo, both same-day (2026-08-13):
   - **Plan 00225** (`CLAUDE/Plan/Completed/00225-.../PLAN.md:27-40`): the advisory text asks the agent to "acknowledge" — but naming the matched phrase to acknowledge it re-triggered the same advisory. Measured table: a message that *did exactly what was asked* ("I called it out of scope; that was wrong, I will fix it...") still fired. Fixed via quoted-span blanking.
   - **Plan 00224** (`CLAUDE/Plan/Completed/00224-.../PLAN.md:24-35`): NitpickState is in-memory; a mandatory daemon restart (which this project's own CLAUDE.md requires after every handler change) resets the byte offset to 0, replaying the **entire transcript** as new. Measured: 6 advisories fired at Stop (3 hedging + 3 dismissive) with **zero** pattern hits in the 6 most recent messages — the real match was 114 messages old. This is the nitpick surface specifically, but the pattern set and failure class are shared with the Stop detector.

**SIGNAL: SUSPECT** — strongest evidence: confirmed duplicate firing with its nitpick twin on every Stop event (not hypothetical — traced through `daemon/controller.py:726-735`), plus two real same-day "cry wolf" incidents against the identical pattern set it shares.

---

## `hedging_language_detector` (stop) — priority 30, ADVISORY

1. **CLAIM**: Detects guessing-instead-of-verifying language ("if I recall", "probably", "I believe") in the last assistant message.
2. **MECHANISM**: Same shape as the dismissive detector — last-message-only scan, 3 categories / 21 regexes, quoted-span blanking, no per-session dedupe (unlike its dismissive sibling, this one has **no** `_last_advisory_key` dedup logic — it will re-fire identically on repeated Stop events if the same hedge persists as the "last message", though in practice the last message changes each Stop).
3. **CONSUMER**: N/A — advisory context.
4. **VACUITY**: `test_hedging_language_detector.py:33-39` (`test_a_genuine_hedge_is_still_reported`) — `"I think it probably works, from memory."`, same reverse-engineered-from-phrase-list shape as the dismissive detector's test.
5. **DUPLICATION**: Same Stop-event double-fire with `nitpick/hedging_language.py` as its sibling.
6. **CONFIG**: `enabled: true`, priority 30.
7. **COST**: Match-gated, low baseline.
8. **HISTORY**: Same Plan 00081/00082 origin as the dismissive detector (built as a pair).
9. **FALSE-POSITIVE RECORD**: Same Plan 00224/00225 incidents — the 00224 evidence table explicitly counted "3 hedging" categories among the 6 stale advisories replayed after a daemon restart.

**SIGNAL: SUSPECT** — identical evidence profile to `dismissive_language_detector`; same duplication + same incident pair.

---

## `task_completion_checker` (stop) — priority 20, ADVISORY

1. **CLAIM**: "Remind agent to verify task completion before stopping" (docstring, `task_completion_checker.py:1`).
2. **MECHANISM**: `matches()` is unconditionally `True` (`return True`, line 39) for every Stop event; `handle()` returns one hardcoded static checklist string every time — no state, no gating, no variation.
3. **CONSUMER**: N/A.
4. **VACUITY**: Not applicable in the usual sense (it never fails to match) — but that is itself the concern: it fires on literally every Stop with the same text regardless of whether the agent's message already demonstrates completion.
5. **DUPLICATION**: `get_claude_md()` returns `None` (line 64), so it is not resident in CLAUDE.md text, but its content ("All requested tasks are complete", "Tests are passing", "Files are saved and committed", "User has been informed") substantially overlaps the semantic ground the `Stop Explanation Required` / `STOPPING BECAUSE:` convention in resident `CLAUDE.md` already covers, and which `auto_continue_stop` actively *enforces* (not just reminds).
6. **CONFIG**: `enabled: true` (per HOOKS-DAEMON.md active handler table — priority 20).
7. **COST**: Fires on every single Stop, unconditionally — the injected text is fixed-size and fairly small (~9 lines), but it is 100% of stops, every session, with zero variation and zero measured effect.
8. **HISTORY**: No dedicated plan found (`git log --follow` on this path was not distinctly separated from bulk handler-scaffolding commits in the time available).
9. **FALSE-POSITIVE RECORD**: None found — it cannot have false positives since it always matches.

**SIGNAL: SUSPECT** — strongest evidence: unconditional match with static, unvarying content and no test or plan evidence it ever changed agent behaviour; `auto_continue_stop` already enforces the substance of what this only reminds.

---

## `dismissive_language` (nitpick) — priority per `NITPICK_DISMISSIVE`, ADVISORY

1. **CLAIM**: "Detect dismissive language in assistant messages via nitpick pseudo-event" (`nitpick/dismissive_language.py:34-42`).
2. **MECHANISM**: Not a real-event handler — runs inside the `nitpick` pseudo-event chain. `NitpickSetup` (`pseudo_events/nitpick.py`) reads the transcript **incrementally** since the last audit (byte-offset state) and hands over all new assistant messages since then, which this handler scans, deduping by category (not by phrase) across the whole batch.
3. **CONSUMER**: N/A.
4. **VACUITY**: `matches()` (line 63-76) only checks that `assistant_messages` is non-empty — all real detection logic is unconditionally run in `handle()`, so a "match" here is nearly meaningless as a gate; the true filter is `NitpickSetup`'s trigger frequency (`pre_tool_use:1/5`, `stop:1/1`) plus the regex scan inside `handle()`. Tests: `tests/unit/handlers/nitpick/test_dismissive_language.py` not fully read in this pass, but the underlying patterns are identical to the Stop twin's (imported, not reimplemented), so the same reverse-engineered-fixture concern applies.
5. **DUPLICATION**: See "nitpick vs stop" resolution — this is the confirmed duplicate.
6. **CONFIG**: `pseudo_events.nitpick.enabled: true`, `handlers.dismissive_language.enabled: true` (`.claude/hooks-daemon.yaml:777-786`) — this is genuinely ENABLED and firing in this repo's live config, not dormant scaffolding.
7. **COST**: Fires on 1-in-5 PreToolUse events (every 5th tool call) AND on every single Stop event, for the ENTIRE session lifetime. This is a much higher firing rate than the Stop-only twin.
8. **HISTORY**: Plan 00082 Phase 4 (commit `c5d1e017`), "Nitpick handlers as full Handler subclasses (TDD)" — the pseudo-event architecture itself was revised once already (Plan 00081 was cancelled/superseded by the revised Plan 00082 after "the initial implementation... was architecturally wrong").
9. **FALSE-POSITIVE RECORD**: Plan 00224 — this is the specific handler whose false-positive storm (6 stale advisories, 114-messages-stale match, triggered by the very daemon-restart workflow this project mandates) was measured and fixed. Plan 00228 then generalised the fix into a shared "prose guard" for all text-matching handlers.

**SIGNAL: STRONG-SUSPECT** — strongest evidence: this handler is the directly-measured source of Plan 00224's false-positive storm, AND it structurally duplicates its Stop-event twin every single time a Stop event fires (confirmed via `pseudo_events.nitpick.triggers: ["stop:1/1"]` + `daemon/controller.py:726-735`), for no documented reason.

---

## `hedging_language` (nitpick) — priority per `NITPICK_HEDGING`, ADVISORY

Same architecture, same evidence profile as `dismissive_language` (nitpick) above — imports `HedgingLanguageDetectorHandler`'s pattern lists (`nitpick/hedging_language.py:17-30`), same trigger config, same Plan 00224 incident (3 of the 6 stale advisories in that measured incident were hedging categories), same Stop-event duplication with `hedging_language_detector`.

**SIGNAL: STRONG-SUSPECT** — identical reasoning to its dismissive sibling.

---

## `remind_prompt_library` (subagent_stop + stop) — ADVISORY

1. **CLAIM**: "Reminds to capture successful prompts to the library" (docstring).
2. **MECHANISM**: `matches()` unconditionally `True` (line 21); `handle()` returns a fixed multi-line advisory naming a specific command (`npm run llm:prompts -- add --from-json <prompt-file>`) and a doc path (`CLAUDE/PromptLibrary/README.md`) — fires after **every single sub-agent completion**, with zero gating on whether the sub-agent's work was in fact "successful" or reusable.
3. **CONSUMER**: N/A — this is a UI nudge, not a logger.
4. **VACUITY**: No test proves the advisory changes behaviour; only that it returns the static string. It fires on failed/trivial sub-agent runs exactly as readily as successful/valuable ones — there is no success-detection logic despite the message conditionally saying "If this prompt worked well".
5. **DUPLICATION**: `get_claude_md()` returns `None` — not resident in CLAUDE.md.
6. **CONFIG**: Registered in both SubagentStop (priority 20) and Stop (priority 100, per HOOKS-DAEMON.md `remind_prompt_library` row) — i.e. this single concept is wired to fire from **two different event types**.
7. **COST**: Fires after every sub-agent completion, every session — for a project that dogfoods heavy sub-agent delegation (per `standing_authorisations`' own text: "use the Agent tool on your own initiative wherever it genuinely helps"), this could be dozens of times per session.
8. **HISTORY / NOTE**: File permissions are `-rw-------` (600) — the only file in the entire cohort with restricted permissions, unlike every sibling handler (644). Possibly an artefact of how it was created rather than a deliberate security decision; worth the judge independently confirming this isn't masking something (no content-level red flag was found — the file content itself is unremarkable).
9. **FALSE-POSITIVE RECORD**: None found in CLAUDE/Plan/ or LESSONS.md.

**SIGNAL: SUSPECT** — strongest evidence: unconditional firing with no success-detection despite claiming to target "successful" prompts, no evidence the CLI command it recommends (`npm run llm:prompts -- add --from-json`) has ever actually been run as a result of this nudge (a `PromptLibrary/` usage-history check was outside this cohort's budget — flagging for the judge to verify against `CLAUDE/PromptLibrary/` if that directory's contents can confirm adoption).

---

## `subagent_completion_logger` (subagent_stop) — priority 10, NON-TERMINAL

1. **CLAIM**: "Log subagent completion events to a JSONL file... for debugging and tracking" (docstring).
2. **MECHANISM**: Unconditional match; on every SubagentStop, appends a JSON line (full `hook_input` + timestamp) to `<daemon-untracked>/logs/hooks/subagent_completions.jsonl`, then calls `cap_log_file()` to front-truncate at 5 MiB (`subagent_completion_logger.py:19,78-80`, Plan 00181).
3. **CONSUMER — the highest-value question in this cohort**: `rg -n "subagent_completions\.jsonl"` across the ENTIRE repo (source, scripts, docs, tests) finds **zero** readers. Every hit is either (a) the writer itself, (b) its own unit test asserting the write, or (c) documentation *about* the file's existence/size/cap. No CLI subcommand, no script, no dashboard, no handler ever reads this file back.
   - **Measured live from this install just now** (team-lead's numbers, not an estimate): `untracked/logs/hooks/subagent_completions.jsonl` is **3,419,802 B** (~3.3 MiB) — 65% of the way to its own 5 MiB cap, and by far the largest of the three logs the team lead sampled (vs 953,601 B for `stop-events.jsonl` and 534,803 B for `notifications.jsonl`). It is also the only one of the three with genuinely **zero** documented reads anywhere, ever — `stop-events.jsonl` has one forensic read on record (CHANGELOG.md:1386, Sev-1 postmortem); this one has none.
   - **This is independently confirmed by two later plans, not just this audit**: Plan 00181 (`CLAUDE/Plan/Completed/00181-disk-usage-time-bomb-audit/PLAN.md:60`) explicitly tabulated it as `Consumer: NONE`, verdict `BOMB` (unbounded growth) — the fix applied there was only to CAP it at 5 MB, not to add a reader or remove the writer. Plan 00209 (`CLAUDE/Plan/00209-field-feedback-daemon-self-observability/PLAN.md:66-68`, still open) states outright: *"what exists today is `notifications.jsonl` and `subagent_completions.jsonl`. Neither records which handler fired, on which tool call, with what verdict. Decisions are emitted to the agent and discarded."* — and goes on to build a **separate** `verdict_log.py` / `verdicts.jsonl` mechanism specifically because this one is not fit for that purpose.
4. **VACUITY**: N/A (logging handler, always "matches").
5. **DUPLICATION**: None with other cohort handlers, but functionally superseded in intent by `daemon/verdict_log.py` (Plan 00209), which — unlike this file — DOES have a documented reader (`docs/guides/VERDICT_LOG.md`: "`hooks-daemon verdicts` reporting").
6. **CONFIG**: `enabled: true` by default (active handler per HOOKS-DAEMON.md, SubagentStop priority 10).
7. **COST**: Bounded (5 MiB cap, front-truncated) so no longer an *unbounded*-disk risk, but at 3.4 MB and climbing it is the largest write-with-no-reader in the whole cohort — pure write cost (disk I/O + JSON serialization of the full `hook_input`, which includes transcript-adjacent fields) on every sub-agent completion, for a value nothing reads.
8. **HISTORY**: `git log` shows this file modified July 20 (retention cap added, Plan 00181). Original logger predates that.
9. **FALSE-POSITIVE RECORD**: N/A (not a pattern-matcher).

**SIGNAL: STRONG-SUSPECT** — strongest evidence: this is the exact "writer with no reader" defect class the `transcript_archiver` deletion exists to warn against, and it is not this audit's inference alone — two separate prior plans in this repo (00181, 00209) independently reached the same "Consumer: NONE" / "discarded" conclusion and neither one removed the writer, only bounded its damage.

---

## `notification_logger` (notification) — priority 10, NON-TERMINAL

Identical architecture, identical evidence, identical "Consumer: NONE" verdict from Plan 00181 (`PLAN.md:61`) and identical "decisions are emitted to the agent and discarded" framing from Plan 00209 (`PLAN.md:66-68`). `rg` across the repo for `notifications\.jsonl` finds the same pattern: writer, its own tests, and documentation-about-it — zero consumers. One extra data point: Plan 00209's `FEEDBACK.md:120` records a live sample — *"`untracked/logs/hooks/notifications.jsonl` 54 entries, all `notification_type=idle_prompt`"* — i.e. in observed practice the file's entire content is one repeated, low-information event type.

**Measured live from this install just now**: `untracked/logs/hooks/notifications.jsonl` is **534,803 B** (~522 KiB, ~10% of its own 5 MiB cap) — the smallest of the three logs the team lead sampled, consistent with the low-diversity single-event-type content Plan 00209 already observed. Bound: `cap_log_file(max_bytes=5 MiB, retain_bytes=2.5 MiB)` (`notification_logger.py:19,78-80`, Plan 00181) — same front-truncate-on-breach mechanism as its sibling, currently well under it. Reader: none, at any size — same as `subagent_completion_logger`, not partially mitigated the way `stop-events.jsonl` is.

**SIGNAL: STRONG-SUSPECT** — same class of finding as `subagent_completion_logger`, corroborated by the same two independent plans, plus a direct observation that the real-world content is low-diversity.

---

## `auto_approve_reads` (permission_request) — priority 10, TERMINAL

1. **CLAIM**: Auto-approve `Read`/`Glob`/`Grep` permission requests, but **only** when `permission_mode == "bypassPermissions"`.
2. **MECHANISM**: `matches()` gates on `is_bypass_mode(hook_input)` first (line 63) — in any other mode it defers entirely, letting Claude Code's native prompt show. Only inside bypass mode does it auto-approve reads and (defensively) deny anything else that reaches `handle()`.
3. **CONSUMER**: N/A.
4. **VACUITY**: Not a text-pattern matcher — deterministic on `tool_name` + `permission_mode`, both real structured fields, not natural-language guesswork. Low vacuity risk.
5. **DUPLICATION**: None.
6. **CONFIG**: `enabled: true` per HOOKS-DAEMON.md; documented in resident CLAUDE.md's `## auto_approve_reads` section verbatim, matching the handler's own `get_claude_md()`.
7. **COST**: Cheap, deterministic, only fires in YOLO/bypass mode.
8. **HISTORY**: Explicitly references and fixes **Plan 00106**, a real security bug: "Silently auto-approving in non-YOLO modes... converted a default session into YOLO behaviour without user consent" (docstring, lines 8-11). This is a case of the handler existing specifically *because* an earlier, less-gated version caused a real incident.
9. **FALSE-POSITIVE RECORD**: Plan 00106 is itself the false-positive/false-approval record, already fixed; acceptance tests include a dedicated negative case (`Defer Read in default mode (Plan 00106 fix)`, lines 137-156) verifying the fix holds.

**SIGNAL: KEEP** — strongest evidence: narrowly scoped, gated on a real structured field (not text pattern matching), with a documented past incident and a regression test guarding specifically against that incident recurring.

---

## `critical_thinking_advisory` (user_prompt_submit) — ADVISORY

1. **CLAIM**: "Periodically inject advisory context encouraging critical evaluation" of user requests, to counter LLM over-agreeableness and catch XY problems (docstring; Plan 00051 Overview).
2. **MECHANISM**: Three sequential gates — Gate 1 length (`prompt >= 80 chars`), Gate 2 cooldown (3 handler-events since last fire), Gate 3 random (20% chance) — designed for an expected ~1-in-15-to-20 firing rate on eligible prompts. On success, injects ONE of three fixed messages chosen at random.
3. **CONSUMER**: N/A.
4. **VACUITY**: The three advisory messages are generic enough to always be "relevant" in a trivial sense (any request could theoretically have an XY problem), which makes the advisory difficult to falsify — there's no test or plan evidence that it ever caught a real XY problem or changed a real decision; it can only be shown to fire, not to help.
5. **DUPLICATION**: Checked against the resident `CLAUDE.md` provided in this session's context — no phrase-level overlap found ("XY problem", "speak up", "pause and evaluate" do not appear in the resident CLAUDE.md text). `get_claude_md()` returns `None`, so it is not separately documented there either. Not duplicative, but also invisible to anyone reading CLAUDE.md — its existence is undiscoverable outside the source or `.claude/hooks-daemon.yaml`.
6. **CONFIG**: `enabled: true` (HOOKS-DAEMON.md priority 55, "critical_thinking_advisory").
7. **COST**: By design, low — ~1-in-15-20 eligible prompts, 3-5 lines. This is the best-engineered "avoid flooding context" handler found in the cohort.
8. **HISTORY**: Plan 00051 (`Completed/00051-critical-thinking-advisory`), single-purpose plan, explicit anti-flood design constraint from the start.
9. **FALSE-POSITIVE RECORD**: None found — advisory text is generic enough that "false positive" doesn't really apply; the concern is unmeasured value, not wrong firing.

**SIGNAL: SUSPECT (weak)** — well-engineered and cheap, so this is the mildest finding in the cohort; flagged because there is genuinely zero evidence anywhere in the repo's plans/journals that this has ever changed an outcome, only that the gating logic works as designed.

---

## `git_context_injector` (user_prompt_submit) — priority 10, NON-TERMINAL

1. **CLAIM**: "Inject current git status as context when user submits a prompt... to help the agent make better decisions" (docstring).
2. **MECHANISM**: `matches()` is unconditionally `True` — fires on **every** UserPromptSubmit event with no exceptions. `handle()` shells out to `git status` (subprocess, 2s-class timeout) and injects the full raw stdout verbatim, every single time, with no caching, no diffing against the previous injection, and no "only if git state changed since last prompt" logic.
3. **CONSUMER**: N/A (direct context injection to the agent, not a log).
4. **VACUITY**: N/A — deterministic on real git output, not a text-pattern guess.
5. **DUPLICATION**: None with cohort siblings, but this is the single highest per-prompt fixed cost in the cohort by design (see COST).
6. **CONFIG**: `enabled: true`, priority 10 (`.claude/hooks-daemon.yaml:544-546`) — no `mode`/`throttle`/`dedupe` option exists in the handler or its config block.
7. **COST — measured directly in this repo**: `git status` on this repo's current (clean) tree produced **1,855 bytes / 37 lines** (~460 tokens at a 4-chars/token estimate) — and that is the *minimum* case; an active work session with many modified files would be larger. Because this fires unconditionally on every prompt with no dedup, a session with N prompts pays this cost N times even when git state hasn't changed between consecutive prompts (a very common case — most prompts in a single work unit don't change branch or staged files).
8. **HISTORY**: No dedicated plan found in the time budget; appears to be original/early scaffolding (file timestamp `Apr 2`, among the oldest files in the cohort by mtime).
9. **FALSE-POSITIVE RECORD**: None applicable (not a matcher).

**SIGNAL: SUSPECT** — strongest evidence: unconditional per-prompt firing with a measured ~460-token minimum payload and zero dedup/throttle logic, for context (current branch + uncommitted files) the agent can already obtain on demand via `Bash(git status)` whenever it's actually relevant to the task at hand.

---

## `idle_housekeeping_advisor` (user_prompt_submit) — priority 56, ADVISORY (BETA)

1. **CLAIM**: After N consecutive no-op failsafe-recovery ticks (session is idle-and-caught-up), advise entering a bounded, report-only housekeeping mode via specialist sub-agents (docstring, Plan 00161).
2. **MECHANISM**: `count_trailing_noop_recovery_ticks()` walks the transcript tail counting consecutive recovery-cron ticks with no real work between them; only past a configurable threshold (default 2) does it fire, and only up to `max_passes_per_session` (default 1).
3. **CONSUMER**: N/A — advisory guidance.
4. **VACUITY**: Detection logic is structural (tool_use presence / role / marker string), not natural-language guessing — low vacuity risk, and the marker string is exact-matched against the daemon's own authored cron prompt (not inferred).
5. **DUPLICATION**: None found.
6. **CONFIG**: Ships **off by default upstream** (per its own `get_claude_md()`-equivalent doc block in HOOKS-DAEMON.md: "Off by default; enable via..."); this repo's `.claude/hooks-daemon.yaml:556-560` explicitly comments *"Off by default upstream; dogfood-enabled here"* — a deliberate, documented opt-in, not an accidental default-on nag.
7. **COST**: Self-limiting by design — max 1 pass per session, gated behind a run of idle ticks that by definition means nothing else is happening.
8. **HISTORY**: Plan 00161 (`idle-housekeeping-mode`), explicit BETA/Decision-4 framing in the docstring itself.
9. **FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — well-scoped, honestly labelled BETA, off-by-default upstream with an explicit dogfooding opt-in comment in this repo's own config — the opposite pattern from a handler that silently accreted scope.

---

## `post_clear_auto_execute` (user_prompt_submit) — priority `critical_thinking_advisory - 1`, ADVISORY

1. **CLAIM**: "When users run `/clear execute plan 85`... this handler detects the first prompt of a new session and injects strong guidance to execute it immediately" (docstring, lines 1-7).
2. **MECHANISM**: Tracks `_last_session_id`; matches whenever `session_id` differs from the last seen value — i.e. it fires on the **first prompt of every new session**, regardless of whether `/clear` was actually used. There is no detection of the `/clear` command itself (no `source: "clear"` check, no `<command-args>` parsing) — the name promises something narrower than the mechanism delivers.
3. **CONSUMER**: N/A.
4. **VACUITY**: Deterministic on `session_id` change — will always fire on session 1's first prompt too, which by definition cannot be post-`/clear`.
5. **DUPLICATION**: `get_claude_md()` returns `None`; not documented in resident CLAUDE.md.
6. **CONFIG**: `enabled: true` (HOOKS-DAEMON.md priority 54).
7. **COST**: Once per session — cheap.
8. **HISTORY — the decisive evidence**: the originating plan, **`CLAUDE/Plan/Cancelled/00087-post-clear-auto-execute/PLAN.md`, is CANCELLED**, with an explicit "Outcome: Cancelled — Fundamental Client-Side Limitation" (line 16). The plan's own investigation found: (a) Claude Code wraps post-`/clear` text in a `<local-command-caveat>` that explicitly instructs the LLM to **ignore** it (Finding 2); (b) "No hook can force an LLM turn" (Finding 3); (c) live-testing the prototype found only "marginal improvement" (Finding 4, line 54) and (d) the plan's own closing "What Was Built" section (lines 69-78) states the handler "remains enabled" but "the core goal of zero-touch post-clear execution is **not achievable** via hooks" and characterises its value as making "the LLM more responsive to first message of any session" — i.e. the project's own retrospective already generalised the mechanism's real effect beyond its name.
9. **FALSE-POSITIVE RECORD**: N/A in the pattern-matching sense, but the plan's own Finding 2 is effectively a documented "this actively fights against a client-side instruction to ignore it" limitation.

**SIGNAL: SUSPECT** — strongest evidence: the feature's own creating plan was cancelled as fundamentally unachievable and explicitly rated the surviving code's value as "marginal," yet the prototype was never revisited or removed and still ships enabled by default three-plus months later (Plan 00087 created 2026-03-11; this audit 2026-08-13).

---

## `standing_authorisations` (user_prompt_submit) — priority 57, ADVISORY

1. **CLAIM**: Replay a project's recorded standing authorisations (e.g. "use the Agent tool without asking") on every prompt, because the restriction it answers is itself re-sent by the system prompt on every request (docstring, Plan 00223).
2. **MECHANISM**: Config-driven allowlist of `{id, enabled}` entries; only `subagent-delegation` and `workflow-orchestration` exist as built-ins; every built-in ships **disabled** upstream by design (Decision 3, enforced — the handler is enabled so the *options* are discoverable, but nothing is authorised until a project explicitly flips a flag). Full text for the first `_FULL_TEXT_DELIVERIES` (3) prompts per session, then decays to a shorter form — but never skips a prompt entirely, by design (Task 3.3, to avoid the exact SessionStart-single-delivery gap Phase 1 measured).
3. **CONSUMER**: N/A.
4. **VACUITY**: Deterministic on config content, not text-pattern guessing.
5. **DUPLICATION**: `get_claude_md()` deliberately does NOT restate the authorisation text itself (to avoid a second copy going stale) — points at config instead. No overlap found.
6. **CONFIG — confirmed live**: `.claude/hooks-daemon.yaml:567-581` — this repo has `subagent-delegation: enabled: true`, `workflow-orchestration: enabled: false`. This is a genuine, deliberate, audited opt-in (with an explanatory comment: "Enabled here because in this repo the authorisation is real and on the record") — not a vacuous or forgotten default.
7. **COST**: Bounded per-session delivery-count map (max 512 tracked sessions, FIFO eviction); text decays after 3 deliveries, so cost per session is self-limiting.
8. **HISTORY**: Plan 00223, well-documented rationale measured against a real 37,475-record transcript (cited in the module docstring) comparing SessionStart vs UserPromptSubmit delivery reliability.
9. **FALSE-POSITIVE RECORD**: None — a test explicitly asserts the ABSENCE of injected text in the shipped-disabled default state (`get_acceptance_tests()`, lines 235-258), guarding against the daemon ever fabricating unrequested consent.

**SIGNAL: KEEP** — strongest evidence: this is the one handler in the cohort explicitly designed against the failure mode the whole audit exists to prevent (fabricated/unverified justification) — it ships opt-out-by-default, records *why* it was turned on in this repo, and is enforced by a dedicated absence-test.

---

## `hello_world` × 8 (pre_tool_use, post_tool_use, session_start, session_end, stop, subagent_stop, user_prompt_submit, notification, permission_request, pre_compact — combined section)

1. **CLAIM**: "Simple test handler that confirms [event] hook is working" (uniform docstring across all variants).
2. **MECHANISM**: Unconditional match, returns a fixed `"✅ [Event] hook system active"` context string. Purely diagnostic.
3. **CONSUMER**: A human/agent running `daemon.enable_hello_world_handlers: true` temporarily to smoke-test that the hook pipeline is wired correctly.
4. **REGISTRATION — real, not stray**: Every variant is gated behind ONE global config flag, `daemon.enable_hello_world_handlers`, consumed identically in `handlers/registry.py:336` (skips registration when false and `HandlerTag.TEST` is present) and mirrored in `daemon/docs_generator.py:252` (excludes them from generated docs when off). `constants/config.py:57` defines the key centrally.
5. **CURRENT STATE — confirmed OFF**: `.claude/hooks-daemon.yaml:13` — `enable_hello_world_handlers: false # Disabled - using real handlers instead`, and each individual `hello_world_*` entry is *also* explicitly `enabled: false` in its own config block (e.g. line 42-44 for `hello_world_pre_tool_use`). Double-gated off. `daemon/init_config.py:49,111` generates this same `false` default for every new project.
6. **TESTS**: `tests/unit/handlers/test_hello_world.py` (312 lines) + `tests/unit/test_hello_world_config.py` (208 lines) — 520 lines total dedicated to proving the gate itself works correctly (registered when flag true, skipped when false, correct tags, correct priority) across all 8+ variants, not just handler-by-handler smoke tests.
7. **COST**: Zero in production — not registered at all when the (default, and this repo's actual) config has the flag off.
8. **HISTORY**: Consistent `Apr 2` timestamps across all 8 files — created together as a deliberate diagnostic suite, not organically accreted debug scaffolding.
9. **FALSE-POSITIVE RECORD**: N/A.

**SIGNAL: KEEP** — strongest evidence: unlike ad-hoc debug code, this is a governed, globally-gated, doubly-disabled-by-default diagnostic suite with more dedicated test code (520 lines) than several of the "real" handlers in this cohort, and it costs nothing when off (which is the observed, confirmed state in both this repo and the generated-default template for new installs).

---

## Cross-cutting observations for the judge

1. **The writer-with-no-reader defect (the audit's founding example) recurs twice more in this cohort**, and — unlike `transcript_archiver` — both recurrences (`notification_logger`, `subagent_completion_logger`) were already independently flagged by name in two prior plans (00181 "BOMB"/"Consumer: NONE" table; 00209 "decisions are emitted to the agent and discarded"). Plan 00181's fix bounded the damage (5 MiB cap) but did not address the root question of whether either file should be written at all. Plan 00209 is still open and is building a *different*, actually-consumed mechanism (`verdict_log.py` / `hooks-daemon verdicts`) seemingly as the intended eventual replacement — worth the judge checking whether Plan 00209's completion is meant to retire these two loggers.
   - **Measured live, three comparable logs, ranked by size**: `subagent_completions.jsonl` **3,419,802 B** (zero readers, ever) > `stop-events.jsonl` **953,601 B** (one manual forensic read on record, `CHANGELOG.md:1386`) > `notifications.jsonl` **534,803 B** (zero readers, ever; Plan 00209 sampled it as 54 entries all `notification_type=idle_prompt` — low-diversity content even when it IS looked at). All three share the identical Plan-00181 mitigation shape (`cap_log_file`, front-truncate on breach) at different byte caps (5 MiB / 2 MiB / 5 MiB respectively) and none has ever been reduced in scope or removed — only capped. The size ranking tracks firing frequency, not value: `subagent_completion_logger` is the largest specifically because sub-agent delegation is the behaviour `standing_authorisations` actively encourages in this repo, so the writer-with-no-reader grows fastest exactly where the project is pushing hardest on the workflow that feeds it.
2. **The "cry wolf" failure mode this project's own `CLAUDE.md` names as Standard 15 (DBF)** — "a guard that only fires at write time does not cover what predates it" / a defect fixed by hand recurs — played out almost verbatim in Plans 00224/00225/00228, all dated the SAME day as this audit (2026-08-13), all in this exact cohort (dismissive/hedging detectors). That is a fast turnaround from defect to fix, which is a point in the project's favour, but it also means the underlying design (unbounded natural-language substring matching against agent-authored text, run through two independent dispatch paths) produced three separate incident plans in one cohort within one day.
3. **`post_clear_auto_execute` is the cleanest example in this cohort of a prototype outliving its own cancelled plan** — worth comparing against `transcript_archiver`'s "never justified against a stated need" framing: this one *was* justified against a stated need, the need was investigated and found unmeetable, and the code shipped anyway as a consolation "marginal" improvement that nobody has revisited since March.

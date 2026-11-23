# Independent adversarial review: PR #226 (owner_wait_stop_guard)

- Branch: `plan-00636-stop-guard`
- Worktree: `.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440`
- Scope: read-only review.
- Light checks run:
  - The three new unit files (`test_owner_wait_stop_guard.py`, `test_owner_wait_check.py`,
    `test_owner_wait_bus.py`): 83 passed.
  - A `python -I -c` probe of `_text_declares_waiting` on 11 strings (F2).
  - No full suite.

Paths are relative to `src/claude_code_hooks_daemon/` unless stated.

## Verdict

**Not safe to merge as is.**

- **F1 (HIGH):** the guard hides the `[awaiting-human]` stand-in cron requirement for every
  coordinator seat. It fires on every waiting coordinator stop, because the production adapter
  always reports the bus as unreadable. `persistent_crons.enabled: true` is set in this
  project's `.claude/hooks-daemon.yaml:1675-1676`, so it hits today.
- **F2 (HIGH):** the first stop gets through the guard unchecked whenever the wait is phrased
  in ordinary words.
- **Sound:** the pure decision module, the thread-id quoting and the option validation.
- **F3 to F5:** fail-open paths. Two of them are documented choices that the owner should
  confirm explicitly.

## Findings (ranked)

### F1 HIGH: the guard's refusal hides auto_continue_stop's stand-in deny, and the re-stop then skips both

**Where:**

- `handlers/stop/owner_wait_stop_guard.py:260, 309`
- `handlers/stop/auto_continue_stop.py:777-787, 863-868`
- `core/chain.py:1076-1080, 413`
- `utils/stop_hook_helpers.py:183-207`

**What happens:**

1. The guard runs at priority 3 and is non-terminal, so `auto_continue_stop` (priority 10 in
   this project) also runs on the same stop.
2. On a `STOPPING BECAUSE: [awaiting-human] ...` stop with no stand-in cron, auto_continue
   returns the R-STOP-STAND-IN-MISSING deny (lines 863-868).
3. `collect_all_violations` defaults to False. So `chain.py:1076-1080` keeps the FIRST
   restrictive result's reason, which is the owner-wait deny, and the stand-in instruction
   never reaches the model.
4. The re-stop is a confirmed re-entry: `stop_hook_active=true`, plus a "Stop hook feedback:"
   or `hook_blocking_error` marker in the transcript tail (`stop_hook_helpers.py:183-207`).
   At that point:
   - auto_continue's `matches()` returns False (lines 785-787);
   - the guard's `matches()` returns False (line 260).
5. The stop is allowed, and no stand-in cron was ever scheduled.

**Why it is systematic:** `TeamchatOwnerWaitBus.read` always returns `BusUnreadable`
(`utils/owner_wait_bus.py:71-73`), and the default policy is `refuse`. So this happens on every
coordinator `[awaiting-human]` stop.

**Class:** `idle_workable_issue_stop_gate` (priority 4) can already hide the stand-in deny the
same way. This PR makes that existing class far more frequent rather than creating it.

**Tests:** no test runs the two handlers together on one stop.

**Fix direction:** any one of these:

- the owner-wait deny also carries the stand-in requirement;
- auto_continue merges both denials;
- the guard stands aside when the stand-in deny is due.

Add a chain-level test with both handlers on one `[awaiting-human]` stop.

### F2 HIGH: the waiting detector misses ordinary phrasings, so the first stop is never checked

**Where:** `owner_wait_stop_guard.py:104-108` and `233-242`.

**How detection works:** a stop counts as waiting on a human only through one of:

- auto_continue's fixed human-blocked phrases;
- `_WAITING_RE`, which requires "waiting on/for" or "awaiting" on the SAME line as `STOPPING BECAUSE:`;
- the BLOCKED session mode, which is not set yet on the first stop, because auto_continue sets
  it after this guard runs.

**Probe results:**

| Stop text                                            | Detected?                          |
| ---------------------------------------------------- | ---------------------------------- |
| `blocked on the owner choosing A or B`               | not detected (allowed)             |
| `pending the owner decision`                         | not detected (allowed)             |
| `need Joseph to pick A or B`                         | not detected (allowed)             |
| `the owner must answer Q61 first`                    | not detected (allowed)             |
| `waiting on Joseph` (a name, not owner/human/user)   | not detected (allowed)             |
| a wait on the line BELOW `STOPPING BECAUSE:`         | not detected (allowed)             |
| `STOPPING BECAUSE:` with the reason on the next line | not detected (allowed)             |
| `not waiting on any user input`                      | detected (false positive: refused) |

**Consequences:**

- A coordinator can make a silent wait without ever hitting the guard, by wording alone.
- If the stop also omits `[awaiting-human]`, the mode is never set, so later stops are not caught either.

**Also:**

- An unreadable transcript makes the reader None and `text` empty, so `matches()` returns
  False and the stop is allowed (line 254-256). `on_unreadable_bus=refuse` never sees this case.
- The guard reads `get_last_assistant_text()`. auto_continue uses `_resolve_current_turn_message`
  to make sure it reads the current turn's message. I did not verify how stale the guard's read can be.

**Fix direction:**

- Search the whole declaring message, not only the prefix line.
- Widen the patterns: blocked on, pending, needs/need X to, must answer/decide.
- Or key on the `[awaiting-human]` token alone, and make the guidance require it for every wait.

### F3 MEDIUM: any earlier Stop deny lets the waiting stop through unchecked, and so does the silent-stop re-entry

**Where:** `owner_wait_stop_guard.py:260` uses the raw `is_stop_hook_active`.

**Case 1: another handler denied first.**

1. Stop 1 has no reason, or follows a QA failure, or meets the idle-issue gate or the branch
   stop guard. That handler denies it.
2. Stop 2 is `STOPPING BECAUSE: waiting on the owner` with `stop_hook_active=true`.
3. The guard never evaluates stop 2.

So the "one refusal per stop chain" rule means zero refusals whenever another handler spoke first.

**Case 2: spurious re-entry.** auto_continue tells a genuine re-entry (a block marker in the
transcript) apart from Claude Code's spurious `stop_hook_active` (no marker), at lines 766-791.
The guard does not, so the spurious case also lets the stop through unchecked.

**Fix direction:** allow a re-stop only when this guard's own rule (R-STOP-OWNER-WAIT-UNBUMPED)
produced the last block. Otherwise evaluate the stop normally.

### F4 MEDIUM (owner decision): an unresolved probe or unknown role disarms the guard

**Where:** `owner_wait_stop_guard.py:287-290`.

**What happens:**

- An UNRESOLVED probe (timeout or unreadable `whoami`) returns no seats.
  `SeatContext.teams_held()` (`utils/teamchat_seat.py:255-256`) is therefore empty, the loop
  never runs, and the stop is allowed.
- A ROLE_UNKNOWN team is skipped (`continue`).

**Why it matters:** this contradicts the 00631 contract that `TeamRoleAnswer.guards_armed`
states (`teamchat_seat.py:228-236`): "an unreadable state must never disarm a seat". It also
cuts against the `refuse` default for the bus. A coordinator whose probe flakes goes unguarded.

**Status:** the guard's docstring documents this (lines 17-18), so it is a deliberate choice.
The owner should rule on whether an UNRESOLVED or UNKNOWN probe should count as `_Unconfirmed`
under `refuse`.

**What is fine:** a worker cannot be armed, because arming needs a DECLARED `coordinator`
(`holds_role`, `teamchat_seat.py:224-226`).

### F5 LOW-MEDIUM (owner decision): an exception outside the bus read lets the stop through

**Where:**

- `owner_wait_stop_guard.py:279-309`: only `self._bus.read` is wrapped.
- Not wrapped: `_resolve_seats`, `teams_held`, `stale_threads`, `_render`, `self._clock`, and in
  `matches()` any `session_policy` error other than RuntimeError or OSError.

**What happens:** the handler is not tagged SAFETY, so `chain.py:1239-1244` (non-strict, non-SAFETY)
logs the error and lets the stop through.

**Status:** this is a recorded choice. The PR adds the guard to `_AUDITED_BLOCKING_ONLY_REASONS`
in `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py` ("never traps a session. Not a
dangerous-action guard").

**Why it still matters:** "on_unreadable_bus: refuse = fails CLOSED" in the docstring and in the
guidance covers the adapter only. Either say so in the docs, or map any exception in the
`handle()` loop to `_Unconfirmed` under `refuse`. The second option cannot trap a session,
because the re-stop is allowed.

### F6 LOW: `bump_command` drops the team

**Where:** `utils/owner_wait_bus.py:75-80` ignores `team`. Neither `teamchat bump Q61` nor
`--waiting` carries `--team`, while `notify_commands` does (line 88).

**Effect:** a seat that coordinates two teams gets two identical commands.

**Status:** this path cannot run today, but it ships live the moment `read` is implemented.

### F7 LOW: the boilerplate filter is very weak

**Where:** `utils/owner_wait_check.py:33-35, 92-95`.

**Problem:** any one word outside {still, waiting, bump, bumped, ping, re} counts as a meaningful body.
These all qualify:

- `bump Q61` ("q61" counts as a word);
- `still waiting on @owner` ("on" counts);
- `ping please`.

**Fix direction:** strip thread-id shapes and stopwords, or require a minimum number of content words.

**Status:** this path cannot run today.

### F8 LOW: traps in the adapter contract for whoever implements `read`

- `owner_wait_check.py:63`: `started_at` defaults to 0.0. If an adapter leaves it unset, any past
  self-reply satisfies an owner-started thread. Make the field required.
- `owner_wait_check.py:118`: compares timestamps in seconds against `time.time()`. Matrix
  `origin_server_ts` is in milliseconds. Without conversion nothing ever qualifies. That errs
  toward refusing, so it is safe but noisy. State the unit in the contract.

### F9 LOW: the BLOCKED mode is broader than "waiting on a human"

**Where:** `owner_wait_stop_guard.py:246`. `is_blocked` includes `goal-blocked`
(`utils/session_modes.py:390-392`).

**Effect:** a goal-blocked coordinator is treated as waiting on every stop until a human prompt arrives.

## Checked and found sound

**Option validation:**

- An invalid `on_unreadable_bus` (wrong type or value) falls back to `refuse` with a warning (lines 197-207).
- `window_minutes` rejects bool, non-int and out-of-range values (lines 179-195).

**Thread-id injection:**

- `printable_thread_id` (`owner_wait_check.py:98-109`) prints only `Q\d{1,6}` or a constrained
  `$...` event id, and shlex-quotes the event id.
- Any id it cannot print switches the command to `--waiting`.
- The team is shlex-quoted in `notify_commands`. The team named in the prose comes from `normalise_name`.

**Thread relation:**

- `_qualifies` keys only on the `m.thread` root (`thread_root`) and requires `relation_readable`.
- `in_reply_to` is never consulted.
- An unknown `from_self` or `notifying` does not qualify (fails closed).

**Sub-agents and teammates:**

- `HandlerScope.MAIN` goes through `scope_admits` → `acts_as_main_thread` (`core/handler_scope.py:160-173`).
- `role_gate` re-checks the main thread.
- The handler lives in `stop/` only (the Stop event).
- A teammate that is the main thread of its own session is guarded only if its own seat probes
  as coordinator, which is the per-seat design.
- A usage-paused session is left alone.

**Re-stop after a refusal:** it cannot loop forever, because the re-stop is allowed. The risk
runs the other way: too permissive (F1, F3). The stop text cannot set `stop_hook_active`,
because the harness owns that flag.

**Secrets:** the adapter runs nothing and opens nothing. The only subprocess is the existing
00631 probe. It runs `$TEAMCHAT_KIT/bin/teamchat whoami --json` with a fixed argv, an allowlisted
environment and the runtime passed as an environment variable only (`teamchat_seat.py:173, 588-593, 619-658`).
The daemon itself opens no seat store, run directory or password file.

## Not verified

- What `teamchat whoami` itself reads. It is outside this repository.
- How stale `get_last_assistant_text()` can be compared with auto_continue's current-turn resolution.

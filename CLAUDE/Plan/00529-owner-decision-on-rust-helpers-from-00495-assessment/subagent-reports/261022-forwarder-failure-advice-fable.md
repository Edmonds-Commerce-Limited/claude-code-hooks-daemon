# Plan 00529 open owner question: a safety forwarder when the relay binary is missing or broken

Adviser ruling, delegated by the owner. Read-only; nothing edited or committed.

## Ruling: CLEAR

**Reject deny-all lockout. Adopt a LOUD fall-through to the bash path: every guard still judges the call, every
answer carries a warning naming the binary and the one-command fix, repair runs automatically at session start and
on upgrade, and the one genuinely fail-open case today (a broken binary) is closed.**

The ruling is CLEAR because it does not depend on product intent beyond the three rulings already given, and every
fact it rests on is established in the repository:

1. **A missing relay is a performance fault, not a safety fault.** The bash path enforces every rule; only speed is
   lost (79-82 ms against 4.3-5.6 ms client CPU per call, task-3 report). Deny-all is the measure this repository
   reserves for calls NO guard judged: python3 missing (`init.sh:374`), the daemon unreachable (`init.sh:685-697`,
   Plan 00466 MA4), a mid-exchange relay failure (`relay/hooks_relay.rs:785-816`). Applying it to a call that every
   guard DID judge is a category error, and it contradicts the install/upgrade decision already merged at
   `59320d842` (task-2b report §3: warn loudly and continue, because failing there would leave no daemon or roll
   back an upgrade on an offline host without rustc).

2. **Lockout denies the fix.** The recovery carve-out admits exactly `restart status logs stop start repair`
   (`init.sh:157`); `transport on` is not among them, and the relay's own deny names only `restart`
   (`relay/hooks_relay.rs:335-373`). The owner saw this at once (JOURNAL 26-10-21 16:18: "Denying every tool call
   would also deny the commands that rebuild the relay"). Widening the carve-out would add a provisioning command
   (network download or a 300 s build, `relay_deploy.py:62`) to the one list of commands that run while every guard
   is bypassed, and where repair cannot succeed (no rustc, no network) the session is dead for a speed binary.

3. **"No silent fallbacks" is satisfied by loudness, not by refusal.** The owner's words are "silent fallbacks ...
   that is error hiding ... LOUD AND CLEAR FAIL FAST" (JOURNAL 16:18). The defect in a silent fallback is that nobody
   is told. The project's own definition of handling an error is "log them, return them to the caller, or propagate
   them" (CLAUDE.md, error_hiding_blocker). A warning on every hook answer propagates the fault to the caller, the
   agent, on every call until it is fixed. The owner-approved status fast path (Plan 00542, merged under the same
   ruling) is exactly this shape: it keeps the one "no daemon answered" hand-off and makes every other fault a loud
   line (`forwarder_generator.py:425-432`). The safety forwarders should match it.

4. **Fail-fast at the right level.** The fast failure belongs at session start and upgrade (repair, then a banner),
   where it costs nothing; at the tool-call level it would block the only channel through which the fault can be
   fixed.

The residual the owner could overturn, but which does not make the ruling UNCLEAR: per-call warnings are noisy. That
is the point. The fix is one command, and the noise ends when it is run. Throttling to once per session is itself a
silence and is not recommended.

## What is wrong today (evidence)

- **Silent fall-through.** The generated guard is `if [[ -x "$_rl_bin" && -S "$_rl_sock" ]]; then exec ...; fi`
  (`src/claude_code_hooks_daemon/install/forwarder_generator.py:350-357`; deployed
  `/workspace/.claude/hooks/pre-tool-use:25-30`). A missing or non-executable binary falls into `source init.sh`
  with no record. The `-S` half is legitimate: no socket means no daemon, and the bash path IS the start-up path,
  which reports loudly (`init.sh` `ensure_daemon`). Only the `-x` half is the silent fallback.

- **A BROKEN binary fails OPEN.** `-x` passes for a truncated or wrong-architecture file; `exec` then fails, and a
  failed `exec` terminates a non-interactive bash script with 126 and nothing on stdout (verified:
  `bash -c 'set -euo pipefail; exec /etc/hostname; echo after'` exits 126 with no "after"). Claude Code treats a
  non-2 exit with nothing on stdout as a non-blocking error and runs the tool
  (`remote-docs/code.claude.com/docs/en/hooks.md:813-821`). So today a corrupt relay silently disables every PreToolUse
  guard. This is a safety defect independent of the owner question and must be fixed whichever way the question went.

- **The loud channels exist.** PreToolUse carries a warning as `hookSpecificOutput.additionalContext` without
  changing the decision; other events use `additionalContext` where their contract has it, else `systemMessage`
  (`init.sh:443-493`). One warning text already exists and is used by `status`, the status line and the SessionStart
  `relay_binary_checker`: `relay_binary_missing_warning(binary, fix_command)` (`relay_deploy.py:122`), with
  `missing_configured_relay_binary` (`relay_deploy.py:109`).

- **Repair exists.** `ensure_relay_binary` (`transport_toggle.py:311-353`) provisions via `relay_source` (`auto`
  builds, else digest-verified download) and is what `transport on` runs. Install and upgrade already provision and
  regenerate the forwarders (`scripts/install/relay_provision.sh`, merged `59320d842`). A detached-from-the-hook
  background precedent exists: the session-start forwarder spawns `provision.sh --background` with `setsid`/`nohup`
  (`/workspace/.claude/hooks/session-start:19-28`), with once-per-target state files and a lock
  (`src/claude_code_hooks_daemon/install/background_sync.py:1-17`).

- **The daemon can tell transports apart** (legacy FrontController socket against per-event listeners,
  `daemon/server.py:1112, 1497-1506, 1737-1776`), but the legacy socket also serves worktree copies of the forwarders
  by design (`CLAUDE/Worktree.md:108-121`), `--no-relay` hand-offs and relay-ineligible events, so "arrived on the
  legacy socket" is not by itself "the configured relay was not used". The forwarder must say why it fell through.

## Implementation tasks

Ordered; each is small. TDD applies (the hooks daemon's own gate).

1. **Guard: fall through loudly and close the fail-open hole.** In `build_relay_guard_block`
   (`forwarder_generator.py:348-357`) split the test: when `-S "$_rl_sock"` holds, `shopt -s execfail` (a builtin;
   bash then survives a failed `exec` instead of dying with 126) and `exec` only when `-x "$_rl_bin"`; if the exec
   returns, or `-x` failed, set a marker, e.g. `HOOKS_DAEMON_RELAY_UNUSED="$_rl_bin"`, and continue into `init.sh`.
   Still zero spawns. Stdin is unread at that point (the relay connects before reading, `hooks_relay.rs:906-908`), so
   the bash path judges the call whole. Regenerating the deployed forwarders follows from the generator change
   (`transport on` / upgrade already re-apply the guard).

2. **init.sh: carry the marker.** Capture and `unset` it at source time exactly as `_HOOKS_DAEMON_RELAY_FAILED` is
   (`init.sh:113-119`), so a daemon this hook starts never inherits it; pass it to `send_request_stdin`'s python
   transport (`init.sh:3143-3145, 3644`) and put it in the request envelope beside `event` and `hook_input`.

3. **Daemon: one warning line on the answer, never a changed decision.** When the envelope names an unused relay
   binary, append `WARNING: ` + `relay_binary_missing_warning(binary, daemon_cli_command("transport", "on"))` to the
   response context in the event's shape (`additionalContext` for PreToolUse and the events that have it,
   `systemMessage` otherwise; the per-event shaping is already in the response encoders). Same text as `status`,
   the status line and `relay_binary_checker`, so all five channels agree. Apply this on every relay-eligible event
   (`EventIDMeta.relay_eligible`, `constants/events.py:172`), not only PreToolUse.

4. **Repair at session start, detached and once per cause.** From the SessionStart path (forwarder or the
   `relay_binary_checker` handler, which already knows the binary is unusable) start a detached provisioning
   (`ensure_relay_binary` plus forwarder regeneration, i.e. the `transport on` routine without the toggle) modelled on
   `background_sync`: a state file keyed by binary path and daemon version so a failing build is attempted once, not
   at every session start, and a lock so two sessions never build at once. Never run it in the hook's foreground
   (build timeout 300 s, `relay_deploy.py:62`). The SessionStart WARNING then says "repair started in the background;
   if the next session still warns, run `transport on`". Upgrade repair is already merged (`59320d842`); install too.

5. **Tests, red first.** (a) Generator: the new guard text, `shopt -s execfail` present, marker set on both the
   missing and the exec-failed branch. (b) `init.sh` integration: PreToolUse with (i) no binary and (ii) an
   executable file of garbage bytes at the binary path; assert exit 0, a valid PreToolUse JSON verdict identical to
   the bash path's, and the warning in `additionalContext`. Case (ii) is red today (exit 126, empty stdout) and is the
   safety regression test. (c) Daemon: envelope field present adds the context; absent adds nothing; decision
   unchanged in both. (d) Session-start repair: state-file once-per-cause and lock behaviour, with `run_fn`/`fetch_fn`
   injected as `relay_deploy` tests already do. (e) Worktree copies must stay unaffected (the `BASH_SOURCE` test
   precedes the new branch).

6. **Docs and release note.** `CLAUDE/Worktree.md:108-121` and the transport docs: "a missing or broken relay never
   changes a verdict; every answer says so until `transport on`". Release note alongside 011 and 013. Record in
   PLAN.md Task 2 that the open question is ruled, and tick the second Success Criterion once 1-3 are merged.

7. **Follow-up for the coordinator, not the owner.** A worktree's forwarders always take the bash path by design
   (`Worktree.md:116-121`) and say nothing. Under the same "loud, not silent" rule that is worth a one-line notice
   per worktree session, but it is a separate decision with its own trade (worktrees are short-lived and many).

## Why not the alternatives

- **Deny-all with a carve-out** (the coordinator's recommendation): see points 1, 2 and 4 of the ruling. It also needs
  the carve-out widened to a network-or-build command, and a lockout a human must break with `!` where repair cannot
  succeed.
- **Fail-closed only for PreToolUse, loud fall-through for the rest**: the same category error for the one event
  where it costs most, and PreToolUse is where the fix command runs.
- **Silence with session-start and `status` warnings only** (today, plus what is merged): violates the ruling in the
  moment of the call, and leaves the corrupt-binary fail-open hole.

# Plan 00470 Tasks 6.1 and 6.2: hostname-matched crons

Branch `worktree-p470-cron-hosts`. Addresses #60, #62.

## How the session's environment reaches the evaluator

The daemon's environment is whatever started it, not the session's. Three
transports deliver a payload to it, and only one of them can edit the payload:

| Transport                                             | Edits the payload?              | How the override arrives                                                                                                              |
| ----------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `init.sh` python rung (legacy socket)                 | yes                             | stamped as `hooks_daemon_hostname`, from the hook's own `HOOKS_DAEMON_HOSTNAME` then `CCY_HOST_HOSTNAME`; omitted when neither is set |
| `hooks-relay` (Rust, byte pump; enabled in this repo) | no, it never parses the request | the daemon reads it from the connected hook process                                                                                   |
| `nc` rung (byte pump)                                 | no                              | as for the relay                                                                                                                      |

For the byte pumps, `_handle_event_client` calls `_stamp_session_hostname`
(`src/claude_code_hooks_daemon/daemon/server.py`): `SO_PEERCRED` gives the peer
pid, then `/proc/<pid>/environ` (the environment the hook was executed with,
which is the session's) gives the override. Linux only; elsewhere, or for a peer
in another PID namespace, nothing is stamped and the daemon falls back to its own
environment and then the system hostname. A value already on the payload is never
overwritten; a session that set neither variable stamps nothing.

I did not change the Rust relay: it is a std-only byte pump by design, and
rewriting the request there would break that contract and need a new release
binary. Reading the peer's environment needs no forwarder or binary change.

One resolver and one matcher: `src/claude_code_hooks_daemon/utils/cron_hosts.py`
(`effective_hostname(hook_input)`, `hostname_matches`, `hostname_override_of_process`).
`effective_hostname` prefers the stamp, then this process's environment
(right for the CLI, which runs in the session), then `socket.gethostname()`.

## Consumers of `persistent_crons` (LSP findReferences was unavailable for yaml/md; found by grep)

Changed to apply `hosts:` (all via `active_jobs(hostname)` or `declares_failsafe_cron(config, hostname)`):

- `PersistentCronAssertorHandler` (SessionStart): lists only jobs declared here.
- `CronStopEnforcerHandler` (Stop) and `CronSubagentStopEnforcerHandler`
  (SubagentStop): demand only jobs declared here. `utils/cron_enforcement.py`
  takes the already-filtered job list, so it needed no change.
- `FailsafeCronBlockageSuppressorHandler._handle_other_tick` (tick suppression by
  job id, via `runs_while_awaiting_human(job_id, hostname)`): a job declared only
  for other hosts is not vouched for, so its tick stays suppressed.
- `declares_failsafe_cron` and its two callers, `RecoveryCronAdvisorHandler`
  (completion guidance) and `FailsafeCronSessionAdvisorHandler`.
- `cron-pause` / `cron-resume` (`_resolve_cron_pause_target` in `daemon/cli.py`):
  resolves from the process environment, which is the session's; the refusal now
  says "for this host".

Not changed: `utils/cron_pause.py`, `utils/cron_tick.py`, `utils/cron_enforcement.py`
(they consume job lists or sentinels, not the config), and
`handlers/stop/auto_continue_stop.py` and `standing_authorisations.py` (guidance
text only).

## Config model

`PersistentCronConfig.hosts: list[str] | None` (`config/models.py`). An empty list
is rejected with "hosts must not be empty: a job that runs nowhere is almost
certainly a mistake"; blank entries are rejected; entries are stripped.
`PersistentCronsConfig.active_jobs(hostname=None)` filters; None resolves from the
process environment.

## TDD red output

Tests written first. First run, before any source existed:

```
ImportError while importing test module '.../tests/unit/utils/test_cron_hosts.py'.
tests/unit/utils/test_cron_hosts.py:25: in <module>
    from claude_code_hooks_daemon.utils.cron_hosts import (
E   ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.cron_hosts'
1 error in 0.25s
```

The handler, config, CLI, forwarder and server tests were written in the same
pass and fail for the same reason (no `hosts` field, no `SESSION_HOSTNAME`, no
stamping); I did not capture a separate red run for each.

Tests cover: exact match, glob (`*`, `?`, `[...]`), no match, case sensitivity,
precedence (`HOOKS_DAEMON_HOSTNAME` over `CCY_HOST_HOSTNAME` over system),
empty and blank `hosts` rejected, a global job unaffected, the Stop and
SubagentStop enforcers not demanding a non-matching job, the assertor, the tick
suppression, `cron-pause`, `declares_failsafe_cron`, the `init.sh` stamp
(Stop and SessionStart, three env shapes), and the daemon reading a REAL separate
client process's environment while its own lacks the variable
(`tests/unit/daemon/test_event_socket_session_hostname.py`).

A finding worth knowing: after the change,
`test_event_socket_hook_event_name_enrichment` failed because this sandbox
exports `CCY_HOST_HOSTNAME=dc-lts-dev-vm`, and the in-process test client's
`/proc/self/environ` carried it. That is the stamp working on a real peer. The test
now stubs `hostname_override_of_process`, since `monkeypatch.delenv` cannot change
`/proc/self/environ`. `test_forwarder_jq_free` likewise scrubs both variables, so a
session exporting them does not leak into its exact-payload assertions.

## Docs and release bookkeeping

- `get_claude_md()` of `persistent_cron_assertor` and `cron_stop_enforcer`.
- `CLAUDE/development/IssueSdlc.md`: new section "Where the hourly cron runs".
- No `docs/guides/CONFIGURATION.md` or config template mentions `persistent_crons`,
  so there was nothing to update there.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/188-a-declared-cron-can-be-limited-to-named-hosts.md`.
- Config-changes entry `persistent_crons.jobs[].hosts` in
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml`.
- Task 6.2: `.claude/hooks-daemon.yaml` `issue-sdlc` gets `hosts: [cchd-sdlc-runner]`;
  `failsafe-recovery` stays global. PLAN.md 6.1 and 6.2 marked done; 6.3 and 6.4
  untouched.

## Results

Targeted pytest (utils, config, handlers/stop, subagent_stop, session_start,
user_prompt_submit, recovery advisor, cron-pause CLI, the new server test,
`test_forwarder_jq_free`, config-changes manifest, guidance coverage, dogfooding
config, rule parity): 7269 passed, 1 failed, 1 skipped. The failure,
`test_rule_parity.py::test_every_allowlist_entry_names_a_real_denying_handler`
("CronSubagentStopEnforcerHandler no longer has a Decision.DENY path"), is not
caused by this change: the twin never denies since the issue #62 scope work, which
this branch does not touch. It needs `CronSubagentStopEnforcerHandler` removed
from `_DENY_WITHOUT_RULES_ALLOWLIST`. I left it, as outside the brief.

`black`, `ruff check` and `mypy` clean on every touched file. `llm_qa.py changed`
was queued behind another worktree's host-wide QA lock when I committed; see the
commit hashes in the hand-off message for whether it finished.

## Unverified

- End to end with a real Claude Code session that exports
  `HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`: not run (I cannot restart a session).
  What is proven: a real separate process with the variable, connecting to a real
  daemon socket that lacks it, is stamped correctly; and the `init.sh` wrapper
  stamps it into the payload for the legacy transport. The relay binary itself was
  not in the loop (the server test stands in for it), though it execs in place so
  the peer pid is the hook's.
- macOS: the relay is Linux-only and the python transport stamps on every
  platform, so both are covered in principle, but only Linux was run.
- The `nc` rung: covered by the same server path (peer is `nc`, which inherits the
  hook's environment), not exercised separately.

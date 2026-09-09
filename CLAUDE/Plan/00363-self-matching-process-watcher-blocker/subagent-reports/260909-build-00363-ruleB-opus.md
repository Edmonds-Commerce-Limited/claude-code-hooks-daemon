# Build report — Plan 00363, Rule B (wrapper-pid wait)

**Branch**: `agent-ab2da8fe312aa481b-9a2cd3ca` (worktree, branched off main at
`7d9b5821`, after v3.63.0 shipped Rules A and C).

## What shipped

### `utils/process_probe.py` — a third classifier

`classify_wrapper_pid_waits(command)` → one `WrapperPidWait` per site that
asks about a `$!` owned by a wrapper rather than by the job:

| Field            | Meaning                                                         |
| ---------------- | --------------------------------------------------------------- |
| `wrapper`        | `setsid`, `nohup sh -c`, `nohup bash -c`, `timeout`, `env`      |
| `detaching`      | the wrapper's parent exits AT ONCE, so the pid is already gone  |
| `reference`      | `$!`, or `$pid` when the pid was captured into a variable first |
| `site`           | the command text doing the waiting                              |
| `job`            | the backgrounded command, as written                            |
| `wait_construct` | the loop/`watch`/`timeout` the site sits inside, if any         |

It reports nothing unless the SAME invocation both backgrounds a wrapped job
and then asks about `$!`. That is the right scope rather than a gap: each Bash
tool call is its own `bash -c`, so a `$!` inherited from an earlier call names
nothing, and a backgrounded job nobody waits on has no bug. It also makes the
guard free on almost every command — no `&` word, no work.

Reuses the module's existing lexer, span grouping, `_basename` resolution and
wait-region machinery, so the command-name respellings Rule A already handles
(`/usr/bin/…`, `\cmd`, quoting, line continuations) are handled here too.

### The two hazards, and why the verdict splits

The spec's five wrappers do not fail the same way, and collapsing them would
have produced a deny message that says something false:

- **`setsid` ABANDONS the pid.** It forks when it is not already a
  process-group leader and its parent exits at once, so `$!` names a pid gone
  in milliseconds. The wait ends on its first pass and reports the job
  finished. **DENY.**
- **`nohup sh -c`, `nohup bash -c`, `timeout`, `env` MIGHT own the wrong pid,
  and the command text does not say which.** `timeout` keeps the pid to
  enforce its own deadline; `sh -c` execs a single simple command but forks
  for anything longer; `env` and a bare `nohup` exec in place. **ADVISORY**,
  and the message states the uncertainty rather than asserting a fork.

`setsid` wins wherever it appears in a chain, so `env FOO=1 setsid ./job &`
denies: abandoning a pid is the worse fault.

### Two allow decisions, each with a test naming why

- **`nohup ./job.bash & pid=$!` is ALLOWED.** `nohup` handed a COMMAND execs
  in place, so the pid it was given is the pid that runs. Only `nohup sh -c '…'` puts a shell in between — which is exactly why the spec names the
  `sh -c` spelling and not `nohup` alone.
- **`setsid -w ./job.bash & wait $!` is ALLOWED.** `-w` makes the wrapper wait
  for its child, so the pid lives exactly as long as the job, and the job
  still gets its own session. The incident report calls `setsid -w` "not the
  fix", but that is about reaching for it INSTEAD of backgrounding; with `&`
  the command is correct. Denying it would have printed "the parent exits at
  once" over a command where the parent does not.

### `handlers/pre_tool_use/self_matching_process_probe.py`

A fourth `Rule` on the existing handler, `R-WAIT-ON-WRAPPER-PID`, used for
both verdicts (deny when `detaching`, advisory otherwise). The message names
the incident's first waiter, then the four remedies in the report's order:
wait on the artefact (`until grep -q "MARKER" run.log`), do not poll at all
(`run_in_background` is harness-tracked), a pidfile the job writes itself
(`nohup sh -c './job.bash > run.log 2>&1 & echo $! > job.pid' &`), and
`pgrep -P <wrapper-pid>` to resolve the child — with the note that after
`setsid` the parent is already gone, so it must be done immediately.

Rules A and C are untouched; their unit and acceptance tests pass unchanged.
The one behavioural edit outside Rule B is the handler's cheap pre-filter,
which gained `wait` and `$!` — without it a `nohup sh -c … & wait $!` naming
no probe command would never have been looked at.

Three acceptance tests added, all `false &&`-guarded so the backgrounded list
exits at once and `wait` cannot hang: a `setsid` deny, a `timeout` advisory,
and the near-miss `false && ./probe-demo-job.bash & wait $!` which is allowed
silently.

### Detection details worth remembering

- `pid=$!` binds the job backgrounded BEFORE it; a later `&` rebinds `$!`
  without touching the variable. The reference test is anchored
  (`\$\{?name\}?(?!\w)`) so `$pidfile` is not read as `$pid`.
- A pipeline's `$!` is its LAST stage, which falls out of walking back from
  the `&` to whatever last put the shell in command position.
- `while [ -d /proc/$! ]` is a loop keyed on the pid with no command the
  module recognises, so loop conditions are scanned separately — and a
  condition whose probe was already reported is skipped, or the same site
  would be billed twice.

## Surfaces touched

- `src/claude_code_hooks_daemon/constants/rule_ids.py` — `WAIT_ON_WRAPPER_PID`
- `src/claude_code_hooks_daemon/utils/process_probe.py` — `WrapperPidWait`,
  `classify_wrapper_pid_waits` and their helpers
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/self_matching_process_probe.py`
  — the fourth rule, `get_claude_md()` and three acceptance tests
- `tests/unit/utils/test_process_probe.py`,
  `tests/unit/handlers/pre_tool_use/test_self_matching_process_probe.py`
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/01-wait-on-wrapper-pid.md`
- `docs/guides/HANDLER_REFERENCE.md` — the handler's section
- `CLAUDE.md` / `.claude/HOOKS-DAEMON.md` — regenerated

No config key was added, so no config-changes manifest entry is due.

## One environment trap, for whoever runs the harness next

`test_playbook_harness.py` first failed on the new probe with "expected deny,
observed no decision at all". The handler was right; the dispatch was not
reaching it. `.claude/hooks/pre-tool-use` opens with a generated relay hot
path whose paths are baked absolute at deploy time
(`_rl_dir="/workspace/untracked"`), so a WORKTREE's hook calls relay to the
MAIN repository's daemon. Rule A denied there (v3.63.0 shipped it) and Rule B
did not (it exists only on this branch). Proved by stopping the worktree
daemon and watching the wrapper still return a Rule A deny.

Run the suite with the relay BINARY pointed at a path that does not exist, so
the wrapper falls through to `init.sh` and the project-scoped socket:

```bash
HOOKS_DAEMON_RELAY_BINARY=/nonexistent/hooks-relay ./scripts/qa/llm_qa.py all
```

Override the binary, not `HOOKS_DAEMON_EVENTS_DIR` — that one fixes the
harness and then breaks
`test_relay_guard_fail_open.py::test_nc_rung_round_trip_completes_promptly`,
which builds its own events directory under a temp root and dials the path
`init.sh` computes.

## State handed back

`PLAN.md` Task 3.1 and the Rule B success criterion are ticked; Status stays
**In Progress** and nothing is archived — the main thread merges, runs the
acceptance tests live and closes the plan.

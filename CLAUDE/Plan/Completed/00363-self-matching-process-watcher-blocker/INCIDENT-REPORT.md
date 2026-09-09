# Incident report: a background waiter that could never fire

Imported from a client-project report (`untracked/hooks-daemon-pgrep-self-match.md`),
with the reporting project's identifiers replaced. The goal it states: a PreToolUse
handler that blocks the shapes of "wait for a process" that cost a session ten idle
hours.

## What happened

A plan needed a long provisioning run (five to ten minutes). The agent started it
detached and asked Bash to wait for it in the background so it could keep working
and be notified on exit. Two consecutive waiters were written. Both were wrong, in
different ways, and the second one never returned.

### Waiter 1 — waited on the wrong pid

```bash
setsid nohup shellscripts/provision.bash target-host -- provisioner … > run.log 2>&1 &
echo "started pid $!"          # 269550
```

```bash
until ! kill -0 269550 2>/dev/null; do sleep 15; done; echo "converge finished"
```

`$!` was the pid of the `setsid` wrapper. `setsid` forks when it is not already a
process group leader, and the parent exits immediately, so pid 269550 died in
milliseconds while the real run continued as 269551. The waiter reported "converge
finished" while the provisioner was in its fourth minute. The agent noticed only
because the log ended mid-task, and checked with `pgrep`.

### Waiter 2 — the pattern matched the waiter itself

Having learnt that the pid was unreliable, the agent switched to a name match:

```bash
until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done; echo "run 02 finished"
```

`pgrep -f` matches against the full command line of every process. The waiter's
own command line is a `bash -c '… pgrep -f "provision.bash target-host" …'`, which
contains the literal string `provision.bash target-host`. So the waiter always
found at least one match: itself. The loop was unconditional. The run it was
waiting for finished at 22:23; the waiter was still sleeping at 08:44 the next
morning when the owner asked what was going on.

The agent also checked progress by hand twice during the night with the same
`pgrep -f`, saw "still running", and believed it. The same bug produced a false
positive in the check that was supposed to catch the bug.

## Why this is a class, not a typo

Every one of these is the same defect: **a liveness probe whose success condition
is satisfied by the probe itself, or by a process that is not the one being waited
on.**

| Shape                                                                        | Why it lies                                                          |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `pgrep -f "<pattern>"` inside a loop or `bash -c`                            | the enclosing shell's argv contains `<pattern>`                      |
| `pkill -f "<pattern>"`                                                       | same; on a good day it kills the caller, on a bad day something else |
| `ps aux \| grep "<pattern>"` without the `[p]attern` trick or `grep -v grep` | the grep matches itself                                              |
| `kill -0 $!` after `setsid …&` or `nohup sh -c '…' &`                        | `$!` is a short-lived wrapper, not the job                           |
| `while pgrep …; do sleep; done` with no upper bound                          | an always-true condition becomes an infinite sleep                   |

The cost profile is what makes it worth a hard block: the failure is **silent and
looks exactly like success** ("still running"). No error, no timeout, no log line.
It consumed a whole idle night and every human-visible signal said the agent was
patiently waiting.

## What a handler should catch

PreToolUse on `Bash`. Deny, do not advise — an advisory in a background waiter is
read by nobody.

### Rule A — self-matching process search (the one that fired here)

Deny a command when a `pgrep -f`, `pgrep -af`, `pkill -f` or `ps … | grep` appears
**and** the pattern argument is a literal that would appear in the command's own
text. In practice: the pattern is a quoted or bare string, not a variable
expansion, and the invocation is not already guarded.

Not flagged:

- `pgrep -f "$pattern"` where the pattern comes from a variable set at runtime
  (still fragile, but the string is not in argv of the caller).
- `pgrep -f -- "[p]rovision.bash"` — the bracket trick, the pattern cannot match
  its own text.
- `ps aux | grep "[p]attern"` and `ps aux | grep pattern | grep -v grep`.
- `pgrep -x name` / `pgrep name` without `-f` — matches the process name only,
  never argv.
- A `pgrep -f` whose result is written to a file and not consumed as a condition
  (rare; allow).

Message shape:

```
BLOCKED [R-PGREP-SELF-MATCH]: `pgrep -f "<literal>"` matches this command's own argv

The shell running this command has "<literal>" on its command line, so pgrep always
finds at least one process: itself. As a loop condition this never becomes false;
as a liveness check it always says "running".

Fix: pgrep -f '[p]rovision.bash' (bracket the first char), or pgrep -x <name>,
or record the real pid (see R-WAIT-ON-WRAPPER-PID) and use kill -0 / wait on it.
```

### Rule B — waiting on a wrapper's `$!`

Deny `kill -0 $!`, `wait $!`, or a loop keyed on `$!` when the backgrounded command
in the same Bash invocation begins with `setsid`, `nohup sh -c`, `nohup bash -c`,
`timeout`, or `env`, i.e. a wrapper that re-forks or execs. Ask for one of:

- `setsid -w` is not the fix (it waits, which defeats backgrounding). Use a
  **pidfile written by the job itself** (`… & echo $! > job.pid` inside the same
  `sh -c`), or
- `pgrep -P <wrapper-pid>` once to resolve the child, or
- wait on the **artefact**, not the process:
  `until grep -q "PLAY RECAP" run.log; do sleep; done`, which is what Claude
  Code's own `run_in_background` guidance recommends.

This is the weaker rule; it will have false positives where a wrapper does not
fork. Advise rather than deny if that turns out to be noisy, but the `setsid` case
is unambiguous and should deny.

### Rule C — unbounded liveness loop (belt and braces)

Advise (not deny) on `until`/`while` loops whose body is only `sleep` and whose
condition is a process probe, when no iteration cap or `timeout` wraps them. The
Bash tool already caps a foreground call at ten minutes; a `run_in_background`
call has no cap, and that is where the night went. Suggest
`timeout 3600 bash -c '…'` or a counter.

## Suggested tests for the handler

Deny:

- `until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done`
- `while pgrep -af 'provisioner playbooks/' ; do sleep 5; done`
- `pkill -f "my-long-job"`
- `ps aux | grep "provisioner" | wc -l`
- `setsid nohup ./job.bash > j.log 2>&1 & sleep 1; until ! kill -0 $! ; do sleep 5; done`

Allow:

- `pgrep -f '[p]rovision.bash'`
- `pgrep -x provisioner`
- `ps aux | grep '[p]rovision' `
- `ps aux | grep provision | grep -v grep`
- `./job.bash > j.log 2>&1 & pid=$!; until ! kill -0 "$pid"; do sleep 5; done` (no wrapper)
- `until grep -q "PLAY RECAP" run.log; do sleep 10; done`

## Timeline (UTC, one evening to the next morning)

| Time         | Event                                                                                                      |
| ------------ | ---------------------------------------------------------------------------------------------------------- |
| 22:12        | Run 01 started via `setsid nohup … &`; waiter 1 armed on `$!`                                              |
| 22:1x        | Waiter 1 fires immediately (wrong pid); agent notices the truncated log, finds the real pid, re-arms on it |
| 22:16        | Run 01 fails in an upstream optional stage (genuine defect, fixed upstream)                                |
| 22:18        | Run 02 started; waiter 2 armed with `pgrep -f "provision.bash target-host"`                                |
| 22:23        | Run 02 finishes green. Nobody is told                                                                      |
| 22:3x, 23:xx | Agent checks by hand with the same `pgrep -f`, sees "still running", stops with a reason                   |
| 08:44        | Owner: "status? you have been stuck for nearly 12 hours?"                                                  |
| 08:44        | `pgrep -af` shows only the waiter's own `bash -c`; log mtime 22:23; waiter killed                          |
| 08:46–08:55  | Remaining proofs run and pass; both plans closed                                                           |

## What the agent should have done instead

Wait on the artefact. The run writes a terminal marker on exit and the wrapper
writes a final log line; either is a terminal marker that cannot match the waiter.
The Bash tool's own guidance says exactly this for one-shot notifications:
`until grep -q "Ready in" dev.log; do sleep 0.5; done`. The agent read that
guidance in the same session and reached for the process table anyway, because
"is the process alive" felt more direct than "did the log end". It is not more
direct; it is a second thing that can lie.

# Operator Signals

Canonical home for the operator-signal channel (Plan 00417): a host-side way
to warn a running Claude Code session that the machine it lives on is about
to reboot or shut down, delivered through the ccy PTY supervisor.

## Why this exists

Interactive sessions run in a container on a machine the operator, or an
automated patch cycle, sometimes reboots. Nothing told the agent before this
existed: work in flight was cut off mid-step, uncommitted changes were lost,
and the next session had to re-derive where things stood. The supervisor
already has the machinery to solve this — it knows when Claude is idle with
an empty input box, and it already consumes session-keyed signal files for
`/goal` (`*.goal-intent`, see
[CcySupervisor.md](../development/CcySupervisor.md)) and `/model`
(`*.model-switch-intent`). This is a third family for host-originated
operator signals, reusing that same delivery mechanism.

## The signal set

A closed set of three `kind`s — nothing else is accepted:

| Kind               | Payload             | Meaning                                                                                                                                                        |
| ------------------ | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `reboot-warning`   | `minutes` (int > 0) | The machine reboots in N minutes. Commit and push uncommitted work, journal state, finish the current step, and start nothing new — a session restore follows. |
| `shutdown-warning` | `minutes` (int > 0) | As above, but **no session restore follows** — also leave a handoff entry for whoever picks the work up next.                                                  |
| `reboot-cancelled` | none                | The previously warned reboot was cancelled; resume normal work.                                                                                                |

## The no-free-text rule, and why

**This is the one signal family reachable from OUTSIDE the container.** The
goal signal and the model-switch signal are both written by something already
running inside a session (a PostToolUse handler, or a Bash-tool CLI call with
`CLAUDE_CODE_SESSION_ID` set); this one is written by host-side tooling that
may have no session context at all. A channel a host process can write into a
running agent's context is a prompt-injection surface by default, so it is
built closed rather than merely validated:

- The payload is **at most a positive integer** (minutes). No free text, no
  reason field, nothing else.
- The **wording the agent sees is owned by the supervisor, in code, under
  test** (`_render_operator_message` in `.claude/ccy/claude-supervise.py`,
  covered by `tests/unit/supervise/test_operator_signal.py`). A signal's
  `kind` only ever *selects* one of the three pre-written sentences above;
  `minutes` is the only value ever interpolated into it. Nothing read from
  the signal file is ever rendered as text.
- Both the daemon-side writer
  (`claude_code_hooks_daemon.utils.operator_signal.write_operator_signal`)
  and the supervisor's reader (`load_operator_signal`) validate the shape
  independently — the writer so a CLI caller fails fast, the reader because a
  signal file reachable from outside the container is a real forgery/corruption
  surface the writer's own discipline cannot guarantee against.

The practical consequence: at absolute worst, a forged or corrupted signal
file can make one of the three fixed sentences above appear early, late, or
not at all — never arbitrary text. If a future need seems to call for prose,
that is a signal to add a new `kind`, not a text field.

## Delivery semantics

Same contract as the goal signal: a session-keyed
`<session>.operator-signal` JSON file dropped into the shared context-sidecar
directory, injected as a real user-role chat line only when the session is
**idle with an empty input box**, **unlinked (consumed) on injection** so it
can never re-fire, and **TTL-bounded** so a stale, never-consumed file cannot
fire late (reaped like every other signal family;
`_DEFAULT_OPERATOR_SIGNAL_TTL_SECONDS`). It will also not paste over a
still-unconfirmed line the supervisor itself typed earlier in the session.

Precedence: consumed at the supervisor's idle choke point ahead of the goal
and model-switch/model-restore families (a host-initiated reboot warning is
more time-critical than either), but still strictly subordinate to
compact/continue/escape — none of those may ever be interrupted by an
informational warning. (Plan 00466 N47 review 2 removed the DROP ANCHOR and
coupled-effort corrections entirely; the supervisor injects no effort of any
kind, so neither is in this precedence chain any more.)

**The status-line countdown is independent of the chat line.** The moment a
valid signal is observed, a transient WARNING-level notice is posted on the
same status-line message channel the Ctrl+Z/Ctrl+C guards use
(`write_status_message`), with a real countdown to the deadline
(`ts + minutes * 60` from the signal's own write time, not recomputed from
"now" on every tick — recomputing from "now" would push the deadline forward
every tick and never converge). This happens regardless of whether the chat
line can be typed yet, because writing a status file cannot disturb what a
human is typing, mirroring the audit-trail banner's rationale.

## The CLI

```
hooks-daemon signal <kind> [--minutes N] [--all-sessions] [--project-root PATH]
```

- `<kind>` — one of `reboot-warning`, `shutdown-warning`, `reboot-cancelled`.
- `--minutes N` — required for the two `*-warning` kinds, refused for
  `reboot-cancelled`.
- Without `--all-sessions`, the signal is session-keyed exactly like
  `inject-goal`: the target session id is resolved from
  `CLAUDE_CODE_SESSION_ID` (set when run from a Claude Code Bash tool), and
  the command refuses with a clear message when it is unset.
- `--all-sessions` is for the host-side caller this feature is *for* — it
  need not run inside any session at all. It reaches every session of THIS
  project by writing one signal per live `<session>.json` context sidecar
  found in the project's own shared, bind-mounted context-sidecar directory
  (`discover_session_ids`), and no session outside that project-scoped
  directory.

Deciding *when* to raise a signal, actually performing the reboot, and
restoring sessions afterwards are all host-side responsibilities outside this
command's scope — it only ever writes the signal file.

### Runs without a venv (Plan 00457, #55)

`--all-sessions` is the host-reachable form above, and the host is not
guaranteed to have a working venv for this project — a container-only
deployment builds its venv inside the container, so its interpreter cannot
run on the host at all, and every other `hooks-daemon` verb refuses with
exit 5 in that state. `signal` is handled before venv resolution instead
(`_run_venv_free_verb` in `bin/hooks-daemon`, the same mechanism `repair`
uses for the missing-venv case itself, Plan 00456/#53):

- `bin/hooks-daemon signal ...` first checks for a system `python3` on
  `PATH`, gated at **Python >= 3.8** (the floor `typing.Final`, used in
  `utils/operator_signal.py`, needs). Older or missing gets a clear message
  and exit 5, not a raw `ImportError`.
- It then execs `daemon/signal_standalone.py` directly by file path under
  that interpreter — never `-m`, never `PYTHONPATH`. That module is
  standard-library-only and loads its few dependencies
  (`utils/operator_signal.py`, `utils/temp_names.py`,
  `daemon/install_layout.py` — NOT the much larger `daemon/paths.py`,
  which would otherwise raise the floor for reasons unrelated to signalling)
  by file path too, so importing it never pulls in `pydantic` or anything
  else `claude_code_hooks_daemon/__init__.py` would otherwise initialise.
  It resolves the untracked/sidecar directory itself
  (`install_layout.get_untracked_dir`) rather than through
  `ProjectContext`, and so needs `--project-root` explicitly — there is no
  venv-backed CWD walk-up to fall back on.
- When a venv DOES resolve for the project, nothing about `signal` changes:
  it goes through the normal `cmd_signal` path in `daemon/cli.py`, which
  shares the same `validate_signal_request`/`run_signal_cli` the
  venv-free entry point calls — one implementation, two ways to reach it.

**Known caveat**: the venv-free dispatch above depends on
`resolve_venv_python` correctly reporting "no venv resolves". Today it
accepts a `venv-*/bin/python` fallback candidate on its executable bit
alone, so a venv that is *present* but cannot actually run on this host
(built for a different architecture/libc inside a container, say) may be
reported "resolved" instead of falling through to the venv-free path here
— surfacing as a raw exec failure rather than this section's clean
dispatch. Tracked as
[00466 N1](../Plan/00466-niggles-ledger-sixteen/NIGGLES.md), being fixed on
another branch; this affects `repair` identically, since both share
`_run_venv_free_verb`'s reliance on the same resolver.

## Out of scope (Phase 1)

Whether a session should be able to answer "not yet" — for example, mid-way
through a long run — by writing a file host-side tooling reads before it
reboots, was raised by the originating issue but deliberately deferred: it
would need to be a fixed token, never text, consistent with the no-free-text
rule above, and needs an owner ruling on the exact contract before it is
built.

# Plan 00245 — Technical Decisions

Extracted from `PLAN.md` (plan-doc-size remedy 1) so the plan stays lean while
the reasoning behind each choice stays available on demand.

### Decision 1: set the premise rather than relax the guard

**Context**: `init.sh`'s repo-detection guard is what broke the tests in CI.

**Options Considered**:

1. Relax the guard in `init.sh` — it would stop protecting real client installs
   from a misconfigured self-install.
2. Mark the tests as requiring a self-installed tree (skip in CI) — buys a green
   tick and removes the coverage; the bodge.
3. Have each test establish the premise explicitly.

**Decision**: Option 3. The guard is correct and worth keeping; the defect was a
test depending on ambient untracked state. Setting `HOOKS_DAEMON_ROOT_DIR` is
exactly what the untracked `.env` does in a real self-install session, so the
tests now assert against the same conditions a real session has.

**Date**: 2026-08-17

### Decision 2: no source scanner for Task 2.2 — CI is the guard

**Context**: Task 2.2 asked for a guard catching a NEW test that sources the
real `init.sh` without establishing the premise. Enumerating the landscape
first: 30 test files mention `init.sh`, but only five actually run it. Two of
those five (`test_socket_timeout_daemon_alive.py`,
`test_emit_hook_error_jqless.py`) copy it into a sandbox and write their own
`.env`, so they were correctly absent from the CI failure set.

**Options Considered**:

1. **A source scanner** over test files that touch the real `init.sh`. Rejected:
   the discriminator is not "mentions `init.sh`" (a false-positive machine — most
   of the 30 only name it in a docstring or a path list) but "hands the REAL path
   to a subprocess that executes it, rather than a copy". Separating those needs
   dataflow analysis, which is disproportionate. A weaker text rule ("must
   mention `HOOKS_DAEMON_ROOT_DIR` somewhere") is satisfied by a bare mention and
   so proves nothing.
2. **Require an import of a shared premise helper**, making the check crisp. Rejected:
   it forces an abstraction at three sites, and `CLAUDE.md`'s own ratio is "three
   similar lines of code is better than a wrong abstraction… six identical blocks
   means you need a proper pattern".
3. **An autouse `conftest.py` fixture** exporting `HOOKS_DAEMON_ROOT_DIR` for the
   whole session. Rejected as actively harmful: it would make the tests pass for a
   reason invisible at the test site — relocating the ambient dependency rather
   than removing it, which is the very defect this plan exists to fix. It also
   would not reach tests that build their environment from scratch, which is what
   `_build_clean_env` does.
4. **CI is the guard.** A fresh checkout with no untracked `.env` is exactly what
   the runner provides, and it already caught this — 25 consecutive times.

**Decision**: Option 4, plus the contract test from Task 2.1. The blind guard
here was never a missing scanner: CI detected the defect on every single push and
no decision depended on the result. Adding a third partial guard while the second
stays unread would be treating the symptom. Phase 4 is therefore the real
remedy, and Task 2.1 pins the contract so the two ways through the guard cannot
be silently narrowed to the untracked one.

**Date**: 2026-08-17

### Decision 3: install `uv` in CI rather than skip the bootstrap tests

**Context**: `ensure_venv` skips its whole body when `CI=true`, which GitHub
Actions always exports. That made four `test_ensure_venv` tests fail on the
runner and — worse — made the file's own gate test pass for the wrong reason: the
skip it asserts was already happening before it set anything. Fixing the premise
means the tests really build venvs, and `create_venv_at_path` needs `uv`, which
the runner does not have.

**Options Considered**:

1. `skipif(os.environ.get("CI"))` on the four tests. A green tick that removes
   the coverage — the same bodge Decision 1 rejected, and it would leave the
   gate's `CI=true` half unmeasured on every interpreter.
2. Assert the skip in CI and the creation locally, branching per environment. The
   test then verifies whichever behaviour the environment happens to select, so
   neither is verified everywhere and a regression hides in the branch not taken.
3. Strip the gate vars in the harness and install `uv` in CI, so each test states
   which side of the gate it exercises.

**Decision**: Option 3. This is the bootstrap path behind two field incidents
(the v3.9.x `ModuleNotFoundError` class and the v3.10.0 stdout-capture SEV-1), so
leaving it unexercised on all three interpreters is precisely the blindness this
plan exists to remove. Measured cost: ~15s for the file including four real venv
builds. Accepted trade-off: those builds now do network I/O on the runner, so a
PyPI outage can redden CI — which is a truthful red (the bootstrap genuinely
cannot run) rather than a false green.

**Date**: 2026-08-17

### Decision 4: construct the interpreter pair instead of reading the ambient one

**Context**: two failures in this cluster shared a shape — a test asserting a
property about a PAIR of interpreters while taking one of them from whatever the
environment provided. `test_fingerprint_parity` compared `/usr/bin/python3`
against `sys.executable` under a guard reading
`sysconfig.get_config_var("base_prefix")`, which is always `None`, so the guard
was permanently true; it passed locally only because the dogfood venv's base
genuinely is `/usr`. `test_venv_include_resolution` compared an in-process
fingerprint against a resolver that ran its own glob-and-sort discovery.

**Decision**: build the pair the assertion is about. The parity test now creates
a venv from the running interpreter and compares the two, so it verifies the
stated property on any box; the resolver test pins `HOOKS_DAEMON_PYTHON` (the
resolver's documented first precedence) so both sides describe one interpreter.
The runner's own shape — two unrelated interpreters sharing a major.minor — is
now asserted as correct behaviour in its own test rather than being the thing
that broke the file.

Each fix carries a non-vacuity check, because both original tests would have
passed against a broken implementation: the parity test asserts the constructed
interpreter really is a venv (`sys.prefix != sys.base_prefix`, the check the
broken guard was reaching for), and the resolver test asserts the answer tracks a
NAMED interpreter, so removing the pin fails locally instead of only in CI.

**Date**: 2026-08-17

### Decision 5: declare an accepted finding rather than defeat the code or the guard

**Context**: ruff 0.16 promoted `DTZ` and `BLE` into its default rule set, so
`.claude/ccy/claude-supervise.py` started failing the client-owned-asset guard
with no change to the asset. Two findings (`DTZ005`, `DTZ006`) had
behaviour-preserving fixes. The third (`BLE001`) flags a per-tick
`except Exception` that is a documented safety net: it logs the full traceback
and emits a NOOP so one tick's failure cannot kill the worker.

**Options Considered**:

1. Narrow the `except` to named exceptions. Defeats the safety net — its entire
   purpose is containing the UNEXPECTED — to satisfy a linter.
2. Pin the guard to a fixed rule set. Silences the guard's real signal: a client
   runs whatever ruff they have, so "clean under a CURRENT default set" is the
   property worth checking, and freezing it makes the check answer a question no
   client is asking.
3. Stop checking the asset. Reintroduces the Plan 00217 blindness wholesale.
4. Let an asset DECLARE the rules it accepts, each with a reason.

**Decision**: Option 4 for `BLE001`, Option "fix it" for both DTZ findings —
fixing is strictly better where behaviour is preserved, because it removes a
line from every client's lint config rather than justifying it. The declaration
lives beside the asset in the manifest, the guard honours it per FILE as well as
per rule, and a new test pins the client document's ignore snippet to the same
list so the two cannot drift.

Two guards come with it, because a declared exception is a promise that decays:
one fails if a declared rule no longer fires (the exclusion outlived its cause),
and it selects the declared codes EXPLICITLY rather than reading a default-rule
run — otherwise an older ruff calls a live exception stale and a newer one is
right by accident.

**Date**: 2026-08-17

### Decision 6: the ambient environment is the recurring defect, not the tests

**Context**: worth stating once, because all six clusters in Phase 3 turned out
to be the same shape rather than six unrelated bugs. In each, a test depended on
something the ENVIRONMENT supplied rather than something it established:

| Cluster                         | Ambient thing depended on                  |
| ------------------------------- | ------------------------------------------ |
| `test_ensure_venv`              | `CI` unset                                 |
| `test_fingerprint_parity`       | `sys.executable` being a venv of `/usr`    |
| `test_venv_include_resolution`  | discovery choosing the running interpreter |
| `test_server_modes/_validation` | `hasattr`-based protocol checks (pre-3.12) |
| `test_git_sync_rewrite_...`     | a global git `user.email`                  |
| `test_client_owned_asset_lint`  | the installed ruff's default rule set      |

Every one passes on a developer machine and fails on a fresh runner, which is
why 25 consecutive pushes were red while local runs were green.

**Decision**: fix each by making the test STATE its premise, never by relaxing
the assertion or skipping in CI. The premise is stated at the point of use where
possible; where it cannot be seen from the assertion — the interpreter pin, the
git identity — a guard fails locally if it is removed, so the next person does
not have to rediscover this from a red CI they cannot reproduce.

This also caught one of my own: a scratch `untracked/venv-py312-verify/` silently
hijacked `resolve_venv_python`, which globs `untracked/venv-*`, so several runs I
labelled 3.11 were 3.12. Renamed out of that namespace. The same class of defect,
committed while fixing it.

**Date**: 2026-08-17


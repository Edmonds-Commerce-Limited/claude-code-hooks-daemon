# Client-Mode Testing (Standard Practice)

**Status**: MANDATORY for changes that touch paths, interpreters, wrappers, or
deployed assets
**Audience**: AI agents and human developers

## The problem this exists to prevent

This repository dogfoods itself in **self-install mode**. A real client project
is laid out differently, and the two disagree in exactly the places bugs hide:

|                               | Self-install (this repo)             | Client install                                   |
| ----------------------------- | ------------------------------------ | ------------------------------------------------ |
| Source                        | `/workspace/src/`                    | `.claude/hooks-daemon/src/`                      |
| Venv                          | `untracked/venv-{slug}-py{MM}-{fp}/` | `.claude/hooks-daemon/untracked/venv-…/`         |
| Socket / PID / log            | `untracked/daemon-{host}.*`          | `.claude/hooks-daemon/untracked/daemon-{host}.*` |
| `scripts/lib/resolve_venv.sh` | repo root `scripts/lib/`             | `.claude/hooks-daemon/scripts/lib/`              |
| Skill wrappers                | **not deployed**                     | `.claude/skills/hooks-daemon/scripts/`           |

**A change can pass every self-install test and still be broken for every
actual user.** Anything that resolves a path, an interpreter, a wrapper, or a
deployed asset must be verified in both modes.

Plan 00192 is the worked example: the daemon shipped 9 unrunnable client-facing
lines naming `$PYTHON` — a variable no agent shell ever sets. <!-- python-var-guidance-exempt: names the banned pattern to warn against it -->
No self-install test could see it, because self-install has no deployed wrapper
to disagree with.

## The fixture

`scripts/dummy-client-repo.sh` provisions a genuine client-mode install at
`untracked/dummy-client-repo/`.

```bash
scripts/dummy-client-repo.sh create     # build fresh (destroys any existing)
scripts/dummy-client-repo.sh status     # layout + daemon state
scripts/dummy-client-repo.sh cli ARGS   # run the daemon CLI inside it
scripts/dummy-client-repo.sh python     # print its resolved interpreter
scripts/dummy-client-repo.sh destroy    # stop daemon, remove worktree + dir
```

### Design rules (do not weaken these)

1. **It drives the production installer.** `create` runs
   `scripts/install_version.sh` end-to-end. It never synthesises install state.
   The v3.10.0 SEV-1 shipped precisely because a gate faked state instead of
   running the real chain — faking it here would rebuild that blind spot.
2. **It is isolated by `HOSTNAME`.** The fixture daemon uses hostname
   `dummy-client-repo`, so its socket/PID/log never collide with the dogfood
   daemon. Verify the dogfood daemon still runs after provisioning.
3. **It fails fast.** If the install leaves no RUNNING daemon, `create` aborts
   rather than handing back a fixture that masks a broken install path.
4. **It lives in `untracked/`** and is disposable. Rebuild it rather than
   repairing it.

### Which code the fixture actually runs (important)

`create` mixes two sources, and the difference will bite you:

| Component                    | Comes from                      | Sees uncommitted work? |
| ---------------------------- | ------------------------------- | ---------------------- |
| `scripts/install_version.sh` | your **main checkout**          | **yes**                |
| Everything under `src/`      | a detached **worktree at HEAD** | **no**                 |

So an uncommitted installer change takes effect immediately, while an
uncommitted `src/` change does **not** — the venv is built from the worktree.

**Commit `src/` changes before provisioning**, or the fixture will silently
exercise the previous version of your Python code and you will conclude a fix
does not work when it was never installed.

### CWD matters — for the CLI, not for the wrapper

The daemon CLI derives socket/PID/log paths from the **current working
directory's** project root. Invoking the CLI module directly from the repo
root therefore resolves the *self-install* paths and misreports the fixture
daemon as down — or worse, acts on the wrong project's daemon while reporting
success.

**`bin/hooks-daemon` is exempt (Plan 00194).** The wrapper derives its own
project root from its location and passes `--project-root`, so it manages *its*
project's daemon from any directory:

```bash
W=untracked/dummy-client-repo/.claude/hooks-daemon/bin/hooks-daemon
HOSTNAME=dummy-client-repo "$W" status     # the FIXTURE daemon, run from anywhere
```

Two things the wrapper does **not** do for you:

- **Hostname isolation is a separate axis.** The fixture runs under
  `HOSTNAME=dummy-client-repo`; without it you get the right project but the
  wrong socket suffix, and a truthful "NOT RUNNING".
- **A raw `daemon.cli` invocation is still CWD-bound.** Any script calling the
  module directly must pass `--project-root` itself — that omission is what
  orphaned a fixture daemon during teardown (Plan 00193 Task 6.7).

`dummy-client-repo.sh cli` handles both and remains the easiest correct option.

## When this is required

Verify in client mode — not just self-install — whenever a change touches:

- Path resolution, venv/interpreter resolution, or `resolve_venv.sh`
- Anything the installer deploys (skills, wrappers, `mkplan.bash`, hooks)
- Guidance strings that name a command an agent is told to run
- `docs_generator` / `playbook_generator` output
- Install, upgrade, or bootstrap logic

## Definition of Done addition

Add to the existing lifecycle checklists (@CLAUDE/CodeLifecycle/Features.md,
@CLAUDE/CodeLifecycle/Bugs.md, @CLAUDE/CodeLifecycle/General.md):

- [ ] If the change touches paths/interpreters/wrappers/deployed assets:
  rebuilt `scripts/dummy-client-repo.sh create` and verified the behaviour
  in **client mode**, not only self-install.
- [ ] Confirmed the dogfood daemon still reports RUNNING afterwards.

## Related

- @CLAUDE/SELF_INSTALL.md — why this repo's layout is unusual
- `tests/acceptance/test_install_sh_end_to_end.py` — the H-1 release gate that
  drives the same production install chain in a temp dir

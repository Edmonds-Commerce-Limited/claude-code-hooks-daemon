# Worktree

**Read first:** [CLAUDE/core/Worktree.core.md](core/Worktree.core.md) — the daemon's core
guidance for this subject, and the baseline everything below extends.

That file is DAEMON-owned: it is refreshed on every daemon upgrade and
overwritten wholesale, so never edit it and never copy its content here. This
file holds only what is specific to this repository — the daemon's own
self-install source checkout — so nothing below repeats what the core states.

## Provisioning a Worktree in This Repo

This repository IS the daemon's source checkout (self-install mode — see
[SELF_INSTALL.md](SELF_INSTALL.md)), so the core document's Critical Rule 3
("Daemon Installation Per Worktree") means something concrete here: building
this project's own fingerprint-keyed Python venv, editable-installed against
the worktree's own `src/`, rather than installing a separately-packaged
dependency.

**Always use `./scripts/setup_worktree.sh`** rather than hand-rolling a venv
or following the core document's generic two-step (`git worktree add`, then
separately reinstall). This script does both steps together:

```bash
# Create a parent worktree from main (worktree + venv + editable install together):
./scripts/setup_worktree.sh worktree-plan-00042

# Create a child worktree from a parent (same, based on the parent branch):
./scripts/setup_worktree.sh worktree-child-plan-00042-handler-a worktree-plan-00042
```

What it does:

1. Validates the branch name (must start with `worktree-`)
2. Creates the git worktree under `untracked/worktrees/`
3. Creates the fingerprint-keyed venv (`untracked/venv-{slug}-py{MM}-{fingerprint}/`
   — see the "Venv layout" section in [SELF_INSTALL.md](SELF_INSTALL.md)) via
   `ensure_venv`
4. Syncs the dev extras (pytest, ruff, mypy...) into that venv from `uv.lock`
   (`uv sync --frozen --all-extras`) and proves `import pytest` works —
   `ensure_venv` alone builds the runtime venv a client install needs, which
   cannot run QA
5. Verifies the editable install points at the worktree's own `src/`
6. Creates the daemon's `untracked/` directory
7. Writes `.claude/hooks-daemon.env` (see below)
8. Prints an agent prompt template

## The Worktree's Own Daemon Answers Its Own Hooks

Two things have to be true for a worktree's `.claude/hooks/*` to reach the
daemon running in THAT worktree, and both are handled for you.

**`.claude/hooks-daemon.env` must exist in the worktree.** It is gitignored,
so `git worktree add` never brings it across, and `init.sh` only enters
self-install mode when it is present. Without it `HOOKS_DAEMON_ROOT_DIR` falls
back to `.claude/hooks-daemon`, no daemon is found there, and every wrapper
answers with its "Hooks daemon not installed" fallback. `setup_worktree.sh`
writes it. The file's content is checkout-agnostic
(`HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"`, expanded by `init.sh` at source
time), so a worktree created another way can be fixed by re-running the setup
script — never by copying the file from another checkout, which
`worktree_file_copy` blocks and which would carry that checkout's edits.

**The relay hot path is scoped to the checkout it was generated for.** The
generated guard in each `.claude/hooks/<event>` bakes absolute literals on
purpose — it is a zero-spawn hot path — so a worktree inherits the MAIN
checkout's socket path with the tracked file. The guard therefore also tests
`${BASH_SOURCE[0]}` against the hooks directory it was generated for: outside
that checkout it declines the relay and falls through to `init.sh`, which
computes this worktree's own project-scoped socket. No environment override is
needed, and `HOOKS_DAEMON_RELAY_BINARY` is not a workaround for anything.

The cost is one legacy-transport round trip per hook in a worktree, and the
same applies when a hook is invoked by a RELATIVE path even in the main
checkout (Claude Code itself always invokes them absolutely, via
`$CLAUDE_PROJECT_DIR`). A slower answer from the right daemon is the trade
being made.

Verify with a probe rather than by inspection — the wrong-daemon failure is
silent, and its answer looks exactly like the right one:

```bash
printf '{"tool_name":"Bash","tool_input":{"command":"true"},"hook_event_name":"PreToolUse","session_id":"probe"}' \
  | bash .claude/hooks/pre-tool-use
./bin/hooks-daemon logs -n 5   # the probe's session_id appears in THIS worktree's log
```

A not-installed answer names the checkout it is answering for, so an answer
about another checkout is visible in the response itself.

**Never hand-build the venv** (e.g. `python3 -m venv untracked/venv`): that
produces the retired pre-v3.7.0 layout, and the fingerprint-aware venv
resolver refuses it — every `bin/hooks-daemon` call then exits telling you to
reinstall.

`./scripts/validate_worktrees.sh` runs this project's QA suite sequentially
across all (or one named) worktree, checking the venv and editable install
first:

```bash
./scripts/validate_worktrees.sh                     # all worktrees
./scripts/validate_worktrees.sh worktree-plan-00042 # one worktree
```

## Running This Project's QA Suite Inside a Worktree

Wherever the core document says "run this project's test/QA suite", the
concrete command in this repository is:

```bash
./scripts/qa/llm_qa.py all
```

## Concurrent QA Limitation (Critical)

The core document's "Concurrent Verification Across Worktrees" section is a
general warning; this project has two concrete, observed failure modes when
QA runs collide because two runs share a worktree (rather than each running
in its own isolated worktree):

1. **Daemon socket collisions** — `test_daemon_smoke.py` starts and stops
   daemons that compete for socket paths, producing `FileNotFoundError` or
   `AssertionError: Daemon still running after stop`.
2. **MyPy cache corruption** — concurrent mypy processes writing to a shared
   `.mypy_cache` produce spurious type-checker failures (e.g. `Library stubs not installed for "jsonschema"`).

Use `./scripts/validate_worktrees.sh` to run QA sequentially, or make sure
every concurrent run has its own worktree (own venv, daemon socket, and test
isolation) — that combination is safe.

## Repo-Specific Pitfall: Skipping `setup_worktree.sh`

```bash
# No venv is created, so nothing can import the package
git worktree add untracked/worktrees/worktree-plan-00042 -b worktree-plan-00042
cd untracked/worktrees/worktree-plan-00042
pytest tests/  # ModuleNotFoundError: No module named 'claude_code_hooks_daemon'
```

Fix: always create worktrees with `./scripts/setup_worktree.sh`, which builds
the worktree and its venv together.

The worse variant is a worktree whose `untracked/venv` is a SYMLINK to the
main checkout's venv: the package then imports from `/workspace/src`, so the
worktree's tests silently exercise main's code and a correct fix fails its
own tests. `tests/conftest.py` refuses to start such a session, naming the
imported path, the expected path and this remedy (Plan 00358). A harness
worktree (`Agent(isolation: "worktree")`) arrives with no venv at all; run
`./scripts/setup_worktree.sh` there rather than linking one.

## See Also (This Repo's Own Docs)

- Agent team workflow, lessons from the Wave 1 proof-of-concept, and
  copy-paste agent prompts: [CLAUDE/AgentTeam.md](AgentTeam.md)
- Self-install mode and the venv fingerprint layout:
  [CLAUDE/SELF_INSTALL.md](SELF_INSTALL.md)
- Plan workflow: [CLAUDE/PlanWorkflow.md](PlanWorkflow.md)
- Code lifecycle: [CLAUDE/CodeLifecycle/General.md](CodeLifecycle/General.md)
- Worktree setup script: `scripts/setup_worktree.sh`
- Worktree QA validation script: `scripts/validate_worktrees.sh`

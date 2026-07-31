# Hooks-daemon: `$PYTHON` in generated agent guidance is undefined in the agent shell

**Upstream:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon
**Installed version:** 3.49.0
**Reporter context:** client-a infra repo, ccy (Podman) container, project root `/workspace`.
**Date filed to `untracked/`:** 2026-07-31

---

## TL;DR / verified facts

- The daemon is installed and healthy in its **own uv-built Python 3.13 venv**; system `python3` (here `/opt/ansible-venv/bin/python3`) genuinely cannot import it (`include-system-site-packages = false`).

- **Live interpreter:**
  `/workspace/.claude/hooks-daemon/untracked/venv-workspace_claude_hooks-daemon-py313-693d94f8/bin/python`
  (the fingerprint hash changes on upgrade — don't hardcode it; four venvs coexist under `untracked/`).

- **Working invocation from an agent shell** (run from the MAIN checkout; from a git worktree, run from `/workspace` and pass files by absolute path — see the worktree symptom below):

  ```bash
  HOOKS_DAEMON_SKIP_BOOTSTRAP=1 bash /workspace/.claude/skills/hooks-daemon/scripts/daemon-cli.sh <subcommand> [args]
  ```

  Verified: `status` → `Daemon: RUNNING`; `plan-qa --lint <PLAN.md>` → correct findings/exit codes.

- **Every documented `$PYTHON -m …` line fails** because `$PYTHON` is undefined in the agent's shell (details below).

---

## Summary

Every piece of generated agent guidance instructs the agent to run the CLI as `$PYTHON -m claude_code_hooks_daemon.daemon.cli <subcommand>`. `$PYTHON` is never defined in the environment an agent actually runs commands in, so **every documented CLI invocation fails as written**. The pattern appears in 29 source files and lands 12 times in the generated `CLAUDE.md` block that is resident in the agent's context every session.

## Repro

1. Install the daemon into a project; let it generate its `CLAUDE.md` block.
2. As the agent, run a line copied verbatim from that generated guidance:

```console
$ $PYTHON -m claude_code_hooks_daemon.daemon.cli status
/bin/bash: line 10: -m: command not found
```

Exit code 127.

The failure is especially unhelpful: `$PYTHON` expands to the empty string, so bash reports the *next* token (`-m`) as the missing command. The error message mentions neither Python, nor the venv, nor the daemon — there is no thread for the agent to pull.

## Root cause

`$PYTHON` is only ever defined inside the process scope of the three skill wrapper scripts (`daemon-cli.sh`, `health-check.sh`, `init-handlers.sh`) that source `skills/hooks-daemon/scripts/_resolve-venv.sh`:

```bash
#   - SETS:     PYTHON — path to the venv's bin/python.
if PYTHON=$(resolve_venv_python "$DAEMON_DIR"); then
    export PYTHON
```

It is **not** exported into the agent's shell, and — contrary to what one might assume — it is **not** exported into the hook execution environment either. `.claude/init.sh` resolves the interpreter into a differently-named variable, `PYTHON_CMD`, and deliberately does not export it (`init.sh:502-503`):

```bash
# Note: PYTHON_CMD is intentionally NOT exported - only used internally
# by start_daemon() and validate_venv(). Hot path uses system python3.
```

That decision is correct and should stand — the hot path should stay on stdlib `python3`. The bug is purely that the **documentation is written from inside the wrapper scripts' scope** and handed to a reader who is not in that scope.

Because the venv is intentionally isolated (`include-system-site-packages = false`), the obvious guesses also fail:

```console
$ python3 -c "import claude_code_hooks_daemon"
ModuleNotFoundError: No module named 'claude_code_hooks_daemon'
```

There is also no fallback: `pyproject.toml` declares no `[project.scripts]`, so no console entry point is installed, and nothing named `plan-qa` / `hooks-daemon` / `ccyd` exists on `PATH`.

## Where it lands (this install)

Unrunnable lines in the deployed `/workspace/CLAUDE.md` (all inside the auto-generated `<hooksdaemon>` block, 12 occurrences): the daemon-CLI section (`status`/`restart`/`logs`), `plan-qa --check-staged`, `plan-qa --lint <file>`, `harvest-background`, `format-markdown`, `validate-project-handlers`, `restart`, `plan-qa --sweep`, `init-project-handlers`, `deploy-plan-workflow`. Also `/workspace/.claude/HOOKS-DAEMON.md:3` (`generate-docs`). Upstream the pattern spans 29 source files; `daemon/cli_acceptance_tests.py:13` hardcodes `_CLI_PREFIX = "$PYTHON -m claude_code_hooks_daemon.daemon.cli"`, so the convention is baked into the acceptance-test surface too.

## Related symptom — the shipped wrapper is not git-worktree-aware

The project ships a working wrapper (`skills/hooks-daemon/scripts/daemon-cli.sh`) that resolves the venv correctly **when run from the main checkout**. But run from inside a git *worktree* it fails with a second, differently-misleading error:

```console
$ HOOKS_DAEMON_SKIP_BOOTSTRAP=1 bash .claude/skills/hooks-daemon/scripts/daemon-cli.sh plan-qa --lint <file>
❌ _resolve-venv.sh: canonical library missing at
   <worktree>/.claude/hooks-daemon/scripts/lib/resolve_venv.sh
   Reinstall the daemon so scripts/lib/resolve_venv.sh is present.
exit=5
```

`_resolve-venv.sh` anchors the daemon dir to the *current* project root rather than the main checkout that actually holds `.claude/hooks-daemon/`. Git worktrees are a common agent workflow, so an agent working in one hits this on top of the `$PYTHON` issue. Workaround: run the wrapper from the main checkout and pass the target file by absolute path.

## Impact

Agents cannot self-serve any of the workflows the handlers explicitly tell them to run — `plan-qa --lint`, `plan-qa --sweep`, `plan-qa --check-staged`, `status`, `restart`, `logs`, `validate-project-handlers`, `deploy-plan-workflow`, `harvest-background`, `format-markdown`.

The failure mode drives actively harmful recovery behaviour. Having seen `ModuleNotFoundError`, an agent reasonably concludes the package "is not installed" and attempts to fix that: `pip install claude-code-hooks-daemon` (wrong environment, and blocked by PEP 668 on modern distros), editing the container Dockerfile, or creating a new venv — all of which damage a working installation whose venv was never broken. (This report exists because exactly that path was started before being caught.)

Two of the affected messages make this worse by appearing exactly when the agent is already confused:

- `daemon_location_guard` exists to redirect an agent that `cd`s into the daemon directory, and its remedy is three `$PYTHON` commands that all fail.
- `project_handler_load_checker` fires on degraded protection and tells the agent to diagnose via `$PYTHON ... validate-project-handlers` — so a real, security-relevant degradation cannot be investigated by following the printed instructions.

The project already ships a working wrapper (`skills/hooks-daemon/scripts/daemon-cli.sh`) and a Skill-tool path (`SKILL.md:208,213`). The generated guidance never mentions either, so the two documented interfaces disagree and the more prominent one is the broken one.

## Suggested fixes

Any one resolves it; (1) is the smallest and (3) the most robust.

1. **Point the generated docs at the shipped wrapper instead of `$PYTHON`.** Replace the `$PYTHON -m claude_code_hooks_daemon.daemon.cli` prefix with `bash "$CLAUDE_PROJECT_DIR"/.claude/skills/hooks-daemon/scripts/daemon-cli.sh` (already resolves the venv via `_resolve-venv.sh`). Single change to the shared prefix constant (`cli_acceptance_tests.py:13` already centralises `_CLI_PREFIX`) plus handler message strings. Consider documenting `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` so the line works in network-isolated containers (the self-bootstrap stanza aborts loudly on network failure by design). Also fix the worktree-anchoring in `_resolve-venv.sh` so the wrapper works from a worktree.

2. **Emit the resolved absolute interpreter path at generation time.** The docs generator and handlers run *inside* the daemon, where `sys.executable` is exactly right. Interpolating it makes every documented line copy-pasteable with no shell-variable dependency. Cheapest correct fix for the handler messages specifically. (Docs regenerate on upgrade, so a venv fingerprint change is handled.)

3. **Ship a console entry point.** Add to `pyproject.toml`:

   ```toml
   [project.scripts]
   hooks-daemon = "claude_code_hooks_daemon.daemon.cli:main"
   ```

   and symlink it onto `PATH` (or document `<venv>/bin/hooks-daemon`). Docs then read `hooks-daemon plan-qa --lint <file>` — stable across venv rebuilds and far more readable.

If `$PYTHON` is kept, at minimum have the generated block define it first rather than assuming the reader inherited it from a wrapper's scope.

## Incidental

`.claude/HOOKS-DAEMON.md` in this project was generated at v3.19.0 while the installed daemon is v3.49.0; its regeneration instruction is itself one of the unrunnable `$PYTHON` lines, so the doc cannot be refreshed by following its own header — a self-demonstration of the bug.

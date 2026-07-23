# Hooks Daemon Upgrade — Socket Name Mix-up (v3.47.0 → v3.48.0)

> **Resolution (Plan 00187)**: This field report was the source for Plan 00187.
> Recommendation #3 (detect + report the split-brain) is implemented upstream:
> the management CLI now mirrors `init.sh`'s socket-discovery-file fallback, so
> `status`/`health` find the live daemon and print an explicit split-brain drift
> warning instead of a bare `NOT RUNNING`. Recommendations #1/#2 (regenerating a
> stale client-authored `hooks-daemon.env`) are intentionally out of scope —
> the upstream daemon must not rewrite client files; the durable fix is a CLI
> robust to the drift that tells the operator exactly what to correct. Retained
> here as a supporting doc; see `PLAN.md` and `JOURNAL/`.

## Summary

After upgrading the Claude Code Hooks Daemon from **v3.47.0 to v3.48.0**, every
management/health command (`status`, `health`, `restart`) reported
`Daemon: NOT RUNNING`, while the hooks themselves kept firing normally.

The daemon was actually running the whole time. The failure was a **socket-name
disagreement** between two parts of the same installation:

- the **bash hook forwarders** bound/looked-up `hooks-daemon-pda.sock`
- the **Python management CLI** computed the canonical
  `hooks-daemon-aee977c2.sock`

Root cause was a stale, tracked override in `.claude/hooks-daemon.env` that
pinned a non-canonical socket name (`-pda`). Correcting that value to the
canonical hash-based name resolved it.

## Environment

| Item          | Value                                                                              |
| ------------- | ---------------------------------------------------------------------------------- |
| Project       | `/srv/example-app/product-data-api`                                |
| Host          | `host-c`                                                                  |
| From → To     | daemon `v3.47.0` → `v3.48.0`                                                       |
| Python / venv | 3.13.11, `untracked/venv-srv_example-app_prod-f2c9-py313-956ed987` |
| Runtime dir   | `/run/user/1000/`                                                                  |
| project_hash  | `aee977c2` (`md5(abs project path)[:8]`)                                           |

## Symptoms

1. `upgrade.sh` completed successfully and reported the daemon started.
2. `health-check.sh` immediately reported `Daemon: NOT RUNNING`.
3. `restart` printed `Daemon started successfully (PID: …)` referencing
   `/run/user/1000/hooks-daemon-aee977c2.sock`, but a follow-up `status`
   again reported `NOT RUNNING` and that socket file did not exist.
4. Meanwhile, PreToolUse/PostToolUse hooks (pipe_blocker, lsp_enforcement,
   etc.) fired correctly against every command — proof a daemon *was* serving.
5. A live process was always present but under a **different** name each check;
   a new PID kept appearing after kills.

## Investigation timeline

1. **Confirmed a live daemon existed.** `pgrep` showed a running
   `…daemon.cli … start` process; hooks were actively firing.

2. **Found two socket naming schemes in `/run/user/1000/`:**

   - `hooks-daemon-aee977c2.sock` — only a stale `.start.lock`, no socket
     (what the tooling looked for).
   - `hooks-daemon-pda.sock` + `hooks-daemon-pda.pid` — a **live, bound**
     socket (what the daemon was actually serving on).

3. **Found a socket-discovery file** at
   `.claude/hooks-daemon/untracked/daemon-host-c.socket-path`
   whose contents pointed bash hook forwarders at `…-pda.sock`.

4. **Read `paths.py` (v3.48.0)** and probed it directly:

   - `get_project_hash(project)` → `aee977c2`
   - `get_project_name(project)` → `product-data-api` (never `pda`)
   - `get_socket_path(project)` with env unset →
     `/run/user/1000/hooks-daemon-aee977c2.sock`

   So Python never produces `-pda`. The name had to come from elsewhere.

5. **Located the source of `-pda`:** `.claude/hooks-daemon.env` (git-tracked)
   contained an explicit override:

   ```sh
   export CLAUDE_HOOKS_SOCKET_PATH="/run/user/1000/hooks-daemon-pda.sock"
   export CLAUDE_HOOKS_PID_PATH="/run/user/1000/hooks-daemon-pda.pid"
   ```

6. **Confirmed the split-brain mechanism:**

   - `init.sh` (hook forwarders) sources `hooks-daemon.env` → binds/looks-up
     `-pda`. Works.
   - The management CLI (`status`/`health`/`restart`, invoked without sourcing
     that env) falls through to `get_socket_path()` → `-aee977c2`. Reports the
     `-aee977c2` daemon as absent because nothing runs there.
   - `cli.py` documents the precedence: *"CLI flag > auto-discovery (env vars
     honored by `get_socket_path`)"*, and `CLAUDE_HOOKS_SOCKET_PATH` is one of
     the honored vars — so whichever side sets/doesn't-set the env wins.

## Root cause

`.claude/hooks-daemon.env` was created for an **older daemon** to work around the
AF_UNIX 108-byte socket-path limit. Its own comment stated:

> Python daemon has auto-fallback to `/run/user/{uid}/` but bash init.sh does NOT.
> Both must agree on the same path, so we set it explicitly here.

At that time the hand-picked short name `-pda` (initials of `product-data-api`)
made both sides agree. In v3.48.0 the Python side derives the relocated name
**deterministically** from `project_hash` (`hooks-daemon-aee977c2.sock`), and
`init.sh` now has its own discovery-file fallback. The hardcoded `-pda` value no
longer matches what the Python management CLI computes, so the two halves of the
install diverged.

### Why the override could not simply be deleted

Empirically verified against v3.48.0:

- `get_socket_path()` **honors `CLAUDE_HOOKS_SOCKET_PATH` verbatim** — it does
  *not* apply the AF_UNIX length-guard/relocation to an env-provided path. A
  too-long env value is returned unchanged.
- `init.sh` **always** exports a socket path to the daemon it spawns
  (`CLAUDE_HOOKS_SOCKET_PATH="$SOCKET_PATH" … cli … start`).
- On a first boot with no discovery file yet, `SOCKET_PATH` defaults to the
  full-length path
  (`…/.claude/hooks-daemon/untracked/daemon-host-c.sock`, 108 chars),
  which exceeds the AF_UNIX limit → bind would fail.

So the env override is still needed to hand bash a **valid short path** — it just
had the **wrong** short path.

## Fix applied

Corrected `.claude/hooks-daemon.env` to the canonical hash-based path (the exact
value `get_socket_path()` computes when the env is unset), and documented the
invariant:

```sh
export CLAUDE_HOOKS_SOCKET_PATH="/run/user/1000/hooks-daemon-aee977c2.sock"
export CLAUDE_HOOKS_PID_PATH="/run/user/1000/hooks-daemon-aee977c2.pid"
```

Then:

1. Killed the stale `-pda` daemon.
2. Removed stale artifacts: `hooks-daemon-pda.{sock,pid,sock.start.lock}`, the
   stray `hooks-daemon-aee977c2.sock.start.lock`, and the discovery file
   `daemon-host-c.socket-path`.
3. Restarted via the CLI.

## Verification

- **Bare CLI `status` (no env sourced):** `Daemon: RUNNING`, PID 26257, socket
  `hooks-daemon-aee977c2.sock (exists)`.
- **Official `health-check.sh`:** `RUNNING`, config validation PASSED,
  **84 handlers loaded**, daemon logs show it listening on the `-aee977c2` socket.
- Only `-aee977c2` runtime files remain in `/run/user/1000/`; `-pda` no longer
  regenerates.
- Discovery file now contains `/run/user/1000/hooks-daemon-aee977c2.sock`.

## Recommendations for maintainers

1. **Deterministic env, not hardcoded names.** The AF_UNIX workaround should
   derive the same short path on both sides. Options:
   - Have the installer/upgrader (re)generate `hooks-daemon.env` from
     `paths.get_socket_path()` so the override can never drift from the Python
     scheme, **or**
   - Make `get_socket_path()` apply the length-guard/relocation to
     env-provided paths too, so bash can pass the long default and the daemon
     self-relocates consistently (then the override becomes unnecessary).
2. **Upgrade should reconcile a stale `hooks-daemon.env`.** The v3.47→v3.48
   upgrade changed the relocated-socket naming but left an existing override
   pointing at the old name, silently breaking all management/health tooling
   while hooks kept working — a confusing failure mode.
3. **Health check could detect the split-brain.** If a live daemon is found on a
   discovery-file/env socket that differs from `get_socket_path()`, report the
   mismatch explicitly instead of a bare `NOT RUNNING`.
4. **Path portability caveat.** The corrected value hardcodes `uid=1000` and the
   `aee977c2` hash (derived from this project's absolute path). If the repo is
   cloned to a different path or run as a different uid, the hash/uid change and
   the override would need regenerating — reinforcing recommendation 1.

## Files touched

- `.claude/hooks-daemon.env` — socket/PID override corrected `-pda` → `-aee977c2`
  (git-tracked; fix benefits the whole team).

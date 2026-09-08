# LXC Support for the ccy Supervisor — Handoff Note

**Status**: TODO (not yet implemented). Pass this to whoever owns the LXC `ccy`
tooling when ready. Podman `ccy` support is already done (fedora-desktop
`entrypoint.sh`, commit `e9ed32c`).

## What already works (shared, launcher-agnostic)

The supervisor is deliberately decoupled so LXC needs almost nothing new:

- **Artifact**: `.claude/ccy/claude-supervise.py` — tracked in the project,
  **stdlib-only**, `#!/usr/bin/env python3`, executable. No venv, no
  `claude_code_hooks_daemon` import. Runs under any system `python3`.
- **Config**: `.claude/ccy/ccy.env` — tracked; exports
  `CCY_CLAUDE_WRAPPER="${CCY_CLAUDE_WRAPPER:-/workspace/.claude/ccy/claude-supervise.py --}"`.

Both are ordinary tracked files, so they are present in any checkout — podman OR
LXC — with no image/rebuild step.

## The only LXC-specific work: teach the `ccy()` alias the contract

The podman entrypoint implements a tiny contract that the LXC thin `ccy()` alias
must also implement:

> **Source `.claude/ccy/ccy.env`, then prepend `$CCY_CLAUDE_WRAPPER` to the
> `claude` invocation.**

### Current LXC alias (as provided by the user)

```bash
ccy () {
    source ~/.nvm/nvm.sh
    export CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1
    export ENABLE_LSP_TOOL=1
    export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
    export CLAUDE_CODE_DISABLE_MOUSE=1
    export CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1
    export IS_SANDBOX=1
    umask 0002
    _claude_parse_token_arg "$@"
    _claude_select_token "$_CLAUDE_TOKEN_NAME" || return 1
    claude update && claude --dangerously-skip-permissions "${_CLAUDE_REMAINING_ARGS[@]}"
}
```

### Required change (illustrative)

Insert the contract just before the final `claude` launch:

```bash
    # --- ccy supervisor contract (mirror of the podman entrypoint) ---
    # Source the project's per-project ccy env, if present. This runs INSIDE the
    # LXC container (the sandbox where claude --dangerously-skip-permissions
    # already runs), so it is the same in-sandbox trust model as podman ccy —
    # never source a project file on the host.
    _ccy_env="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/ccy/ccy.env"
    if [ -f "$_ccy_env" ]; then
        # shellcheck source=/dev/null
        . "$_ccy_env"
    fi

    claude update || return 1
    if [ -n "${CCY_CLAUDE_WRAPPER:-}" ]; then
        # word-split the wrapper (e.g. "/workspace/.claude/ccy/claude-supervise.py --")
        # shellcheck disable=SC2086
        exec $CCY_CLAUDE_WRAPPER claude --dangerously-skip-permissions "${_CLAUDE_REMAINING_ARGS[@]}"
    fi
    exec claude --dangerously-skip-permissions "${_CLAUDE_REMAINING_ARGS[@]}"
```

Notes:

- Use `${CLAUDE_PROJECT_DIR:-$PWD}` — the LXC path is whatever the project dir is,
  not necessarily `/workspace` (that is the podman-container mount point). The
  `ccy.env` default wrapper path currently hardcodes `/workspace/...`; for LXC the
  project may be elsewhere, so either (a) run `ccy` from the project root and the
  supervisor path must resolve there, or (b) make the `ccy.env` wrapper path relative
  / `$CLAUDE_PROJECT_DIR`-based. **Decide this when implementing** — see Open
  Questions.
- `exec` replaces the shell so the supervisor becomes the session's process, exactly
  as the podman entrypoint does.

## Prerequisites to verify in the LXC image

1. **`python3` is installed** in the LXC container (the supervisor is stdlib-only,
   so any 3.x works — no pip installs needed). Confirm with `python3 --version`.
2. The project is checked out so `.claude/ccy/claude-supervise.py` (executable) and
   `.claude/ccy/ccy.env` are present.
3. `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1` is already set by the alias — good; the
   supervisor's terminal handling assumes the in-band renderer (same as podman).

## Open questions (resolve at implementation time)

1. **Where is the `ccy()` alias defined?** (lxc-bash tooling? a shell rc deployed by
   Ansible?) That is the file to edit so the change is tracked in IaC, not
   hand-edited per container.
2. **Supervisor path in `ccy.env`**: `/workspace/...` is the podman mount path. For
   LXC, either standardise the project mount to `/workspace`, or switch the `ccy.env`
   default to a `$CLAUDE_PROJECT_DIR`-relative path so one `ccy.env` serves both
   launchers.
3. **`claude update` semantics**: the LXC alias runs `claude update` every launch;
   keep that before the `exec` wrap (as above) so the supervisor wraps the updated
   binary.

## Why this is safe / low-risk

- Default-off unless `ccy.env` sets `CCY_CLAUDE_WRAPPER` (the `${VAR:-...}` default is
  only applied if the project ships a `ccy.env` that exports it).
- v0 supervisor is transparent, dry-run — it injects nothing; it only wraps the PTY.
- Disable at any time by commenting the `export` line in `.claude/ccy/ccy.env`.

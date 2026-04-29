# Report 1 — Prevention: Keep the Exec Bit Set in the First Place

## Summary

The exec bit gets lost because *several different actors* (git, IDEs, archive tools, deploy systems, the user's own `cp`) are willing to silently strip it, and the daemon currently relies on a single line of defence — `chmod +x` at install time. Prevention should be layered: bake `100755` into the source of truth (git index + `.gitattributes`), block the most common stripping vector (`core.fileMode=false`) at install, and re-assert the bit at every place a hook wrapper is touched (install, upgrade, daemon start, `init.sh` source). The cheapest highest-leverage piece is a `.gitattributes` rule shipped in the daemon repo's own `.claude/` payload — it's one line, lives with the files, and survives clone, checkout, and merge.

Note: `git_force_executable()` is already implemented at `scripts/install/hooks_deploy.sh:230` (commit 8a3f1ba), so plan 00091's Phase 1 is effectively done. The remaining gap is everything *outside* the install moment.

## Ideas

### 1. Ship `.gitattributes` in `.claude/` payload

**Mechanism.** Add `/workspace/.claude/.gitattributes` (and have the installer copy it into client `.claude/` directories alongside the wrappers):

```
hooks/*  text eol=lf
init.sh  text eol=lf
```

`.gitattributes` cannot set the exec bit directly, but pinning `eol=lf` stops Windows/CRLF clones from rewriting blobs (which is what triggers index-mode resets in cross-platform clones). Pair with the existing `git update-index --chmod=+x` in `hooks_deploy.sh:259`.

**Pros.** Travels with the repo. Zero per-client config. Survives `git archive` / GitHub source tarballs (which honour index mode).
**Cons.** Doesn't help `core.fileMode=false` alone — must pair with idea 2. Doesn't help non-git transfers (rsync, scp).
**Blast radius.** One-time daemon repo change; picked up by every client on next upgrade because installer copies `.claude/` payload.
**Cost.** S.

### 2. Refuse to install when `core.fileMode=false`, with a one-keystroke fix

**Mechanism.** In `git_force_executable()` (`scripts/install/hooks_deploy.sh:288-295`), upgrade the current `print_warning` to a hard error inside `install.py` (not upgrade — upgrades must never block). Print:

```
ERROR: git core.fileMode=false will silently break hook permissions.
       Run: git config core.fileMode true
       Then re-run install.
```

Add `--allow-filemode-false` opt-out for SMB / Windows-bind-mount users.

**Pros.** Eliminates the #1 cause of exec-bit loss at source. Forcing the user's hand once is cheaper than chasing silent breakage forever.
**Cons.** Hostile first-install UX. Legit `fileMode=false` users (WSL / SMB) need the opt-out.
**Blast radius.** One-time daemon repo change.
**Cost.** S.

### 3. Re-assert exec bit every time `init.sh` is sourced (sibling-heal)

**Mechanism.** Add a once-per-process guarded block near the top of `.claude/init.sh`:

```bash
if [ -z "${HOOKS_DAEMON_PERMS_HEALED:-}" ] && [ -d "$(dirname "${BASH_SOURCE[0]}")/hooks" ]; then
    chmod +x "$(dirname "${BASH_SOURCE[0]}")/hooks/"* 2>/dev/null || true
    export HOOKS_DAEMON_PERMS_HEALED=1
fi
```

**Pros.** Self-healing without daemon involvement. Works even if the daemon is down. Fires on the next event after damage.
**Cons.** Chicken/egg — the wrapper currently executing already had +x; this only helps *siblings*. Adds ~5ms to first hook of each session.
**Blast radius.** One-time daemon repo change, propagated via installer.
**Cost.** S.

### 4. Daemon-startup re-permission

**Mechanism.** On daemon boot (`src/claude_code_hooks_daemon/daemon/server.py` startup path), call `set_hook_permissions(project_root)` from `hooks_deploy.sh:154` unconditionally. Already idempotent and cheap (~5ms for 12 files).

**Pros.** Catches damage from any source (IDE save, rsync, manual `cp`) within one daemon restart. Fully decoupled from git.
**Cons.** If the SessionStart wrapper itself lost +x, the daemon never gets invoked, so this doesn't bootstrap. Useful as belt-and-braces, not primary defence.
**Blast radius.** One-time daemon repo change.
**Cost.** S.

### 5. Installer-managed `.git/hooks/pre-commit`

**Mechanism.** Installer appends to (or creates) `.git/hooks/pre-commit`: `git update-index --chmod=+x .claude/hooks/* .claude/init.sh` before every commit.

**Pros.** Catches the case where an IDE rewrites a wrapper at 0644 and the user `git commit -a`'s it.
**Cons.** Conflicts with husky/lefthook/pre-commit framework users — the #1 reason teams refuse installer-managed `.git/hooks/`. Most projects ban it.
**Blast radius.** Every client repo. Touches user-owned territory.
**Cost.** M.

### 6. Ship wrappers as wheel resources, extract with `os.chmod(0o755)`

**Mechanism.** Move wrappers into the Python package as `importlib.resources` data. Installer extracts to `.claude/hooks/` with explicit `chmod`. Wheel `RECORD` preserves mode.

**Pros.** Eliminates git from mode tracking entirely. Authoritative source becomes the wheel.
**Cons.** Breaks self-install dogfooding (this repo's own wrappers ARE the source). Big architectural change.
**Blast radius.** Major refactor — installer, deploy, self-install paths.
**Cost.** L.

## Top Pick

**Idea 2 (refuse install on `core.fileMode=false`)** combined with **Idea 1 (`.gitattributes`)**. The existing `git update-index --chmod=+x` (already shipped) only helps if mode survives the *next* checkout — which `core.fileMode=false` actively prevents. Hardening install is the only place where we can interrupt the user before they enter the failure mode, and `.gitattributes` makes the contract travel with the files for free. Both are S-cost, both are one-time daemon repo changes, both propagate to every client on next upgrade with zero per-client work. Idea 3 (init.sh self-heal) is the obvious complement but belongs in agent 3's detection-and-heal report.

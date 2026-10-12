# Provision a Checkout

Build the daemon for a checkout of a project that already uses it, at exactly
the version the project names, or bring an existing clone to that version.

## When

A fresh clone carries the tracked hooks, `.claude/init.sh`, `.claude/settings.json`
and `.claude/hooks-daemon.yaml`, but not the daemon: `.claude/hooks-daemon/` is
gitignored and per-checkout. Until it is built, every safety handler is off.

The same command syncs a clone that is already there but at another version than
the project names: a pull changed `daemon.expected_version`, and the gitignored
clone did not follow.

This is not `install` (add the daemon to a project that does not use it) and not
`upgrade` (move the project itself to a new version, which also migrates config
and rewrites tracked files).

## Run

```claude-code
/hooks-daemon provision
```

It runs the project's own tracked `.claude/provision.sh`, which:

1. Resolves the expected version from `daemon.expected_version` in
   `.claude/hooks-daemon.yaml`, else from the `.claude/HOOKS-DAEMON.md` header.
   Unknown or not `X.Y.Z`: it stops and says so. It never guesses and never
   installs `main`.
2. Fetches that one tag into `.claude/hooks-daemon/` from the repository the
   installer trusts. The URL is fixed in the script; no environment variable or
   config value can change it.
3. Builds the venv through the clone's own venv build path and lock.
4. Starts the daemon, as a hook would.

It changes no tracked file, and needs no session restart: the hooks are already
registered in the tracked `.claude/settings.json` and reach the daemon on the
next tool call.

## Syncing a clone that is already there

A clone already at the expected version is left alone ("already at vX.Y.Z").
Otherwise, for a newer or an older expected version:

1. It refuses, changing nothing, when the clone is not a git checkout, its
   `origin` is not the fixed URL, or it has tracked changes or files outside
   `untracked/` (gitignored files do not count).
2. It fetches exactly that tag (depth 1) from the fixed URL, and checks that
   the tag's `version.py` names the version before checking it out.
3. It runs the target release's own pre-deploy gate, the one `upgrade` runs. If
   the gate wants its reading list confirmed it prints the listing, puts the
   clone back and stops; read it, then re-run with
   `--skip-reading-confirmation=<digest>` (the digest it printed). A target that
   predates the gate has none to run.
4. It rebuilds the venv with the clone's own `scripts/venv_bootstrap.sh repair`
   and restarts the daemon with the clone's own `bin/hooks-daemon restart`.
5. A failure after the checkout puts the previous commit and its venv back,
   restarts the old daemon, and says so.

A sync writes no tracked file, runs no config migration and regenerates no docs.

## When it refuses

| It says                                                                | What to do                                                                           |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| the version is unknown                                                 | Set `daemon.expected_version`, commit it, run provision again                        |
| `daemon.expected_version` is not X.Y.Z                                 | Correct it (for example `3.68.0`: no `v`, no branch name)                            |
| the clone has local changes                                            | Commit, move or discard them yourself, run provision again                           |
| the clone's `origin` is not the fixed URL, or it is not a git checkout | Move `.claude/hooks-daemon/` aside and provision a fresh clone                       |
| the pre-deploy gate asks for reading                                   | Read the listing, re-run with the `--skip-reading-confirmation=<digest>`             |
| a clone exists but has no venv here                                    | `.claude/hooks-daemon/bin/hooks-daemon repair` keeps the clone, then provision again |
| the directory holds something else                                     | Inspect it; move it aside if disposable; run provision again                         |
| the tag cannot be fetched                                              | Check the version is a release and the machine can reach GitHub                      |
| the venv cannot be built                                               | Fix the named condition, then `.claude/hooks-daemon/bin/hooks-daemon repair`         |

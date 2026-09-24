# Callout: a missing venv now builds itself, and `repair` works without one

**Plan**: 00456
**Audience**: operators

A daemon clone with no venv for the current project path is common on a
host/container bind mount, where the second view shares the clone but not its
venv. That clone now heals itself. The first hook checks five conditions: `uv`,
`pyproject.toml`, `uv.lock`, a compatible Python, and a writable `untracked/`.
When they hold, the hook starts ONE background build of this path's venv under
the venv build lock, returns at once with the build's log, and the next hook
after it finishes starts the daemon. When a condition fails, nothing is
changed and the message names each failed condition with its fix. A failed
build is reported with its log and is not retried until its inputs change
(including an in-place `uv self update`). A background build is bounded by
`HOOKS_DAEMON_VENV_BUILD_TIMEOUT` (default 900 seconds), after which it is
stopped and reported failed, and while it runs the message names its pid.
`HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` or `CI=true` switches the automatic build
off, and the message names which. An explicit `repair` still builds.

`bin/hooks-daemon repair` now works in that state. It used to exit 5 like
every other verb. It now builds the missing venv in the foreground and then
runs the normal repair. In a client install, `repair` also now targets the
venv, lock and `uv sync` of the daemon directory rather than the project root.
Before this, it built a venv the resolver refused. `repair` also finds `uv` in
`~/.local/bin` (where uv's installer puts it) when that is not on PATH, and it
waits for a background build already running rather than giving up after two
minutes.

The skill's `install` no longer escalates to `--force` by itself. A clone with
no working venv is repaired in place, and nothing is deleted. An explicit
`install --force` keeps every environment's `untracked/venv-*` across the
re-clone, in a directory git ignores. If the run is killed outright, the next
`install` puts them back. Switching between the host and container views of one project no
longer deletes the other view's venv.

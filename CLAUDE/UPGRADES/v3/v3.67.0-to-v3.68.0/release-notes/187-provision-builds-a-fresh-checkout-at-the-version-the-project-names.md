# Callout: `provision` builds a fresh checkout's daemon at the version the project names

**Plan**: 00477
**Audience**: operators

A fresh clone of a project that uses the daemon has the tracked hooks and config but not the daemon, which lives in the gitignored `.claude/hooks-daemon/`. The new `bash .claude/provision.sh` (or `/hooks-daemon provision`) builds it: it resolves the version the project expects, fetches exactly that tag from the repository the installer trusts (never `main`), builds the venv through the existing build path and lock, and starts the daemon. It writes no tracked file and needs no session restart, because the hooks are already registered in the tracked `settings.json`. It refuses, and says why, when the version is unknown or not `X.Y.Z`, when a clone is already present (pointing at `upgrade`, or at `hooks-daemon repair` when the clone has no venv for this path), and inside the daemon's own repository.

The version comes from the new `daemon.expected_version` key in `.claude/hooks-daemon.yaml`, which `install` and `upgrade` now record, falling back to the `.claude/HOOKS-DAEMON.md` header for a project that predates it. `.claude/provision.sh` is a new tracked file deployed beside `init.sh`; commit it. Hooks do not run it: a person or an agent does, deliberately. The hooks' loud "needs provisioning" message is described under "A fresh clone without a daemon now says so loudly and names `provision`" below.

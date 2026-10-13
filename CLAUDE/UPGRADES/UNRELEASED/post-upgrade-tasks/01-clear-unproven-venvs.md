# Task: Investigate and clear any UNPROVEN venvs the new advisory lists

**Type**: other
**Severity**: recommended
**Applies to**: all
**Idempotent**: yes

## Why

Removal of a stale venv needs proof: a readable `lock_hash` that differs from the current source's, on this checkout view's slug. The upgrade cleanup, daemon start, restart and `provision` now remove every venv proven stale. A venv the code cannot prove stale (missing or unreadable `.daemon-metadata.json`, or another checkout view's slug) is never removed automatically, and until now nothing mentioned it either, so it stayed on disk unexplained. The new SessionStart advisory `unproven_venv_advisor`, and `list-venvs`, name each one with the facts needed to judge it. Deciding that one is safe to remove is the upgrading agent's job.

## How to detect if this applies to you

List the venvs and look for the `UNPROVEN` marker. Sample:

```bash
.claude/hooks-daemon/bin/hooks-daemon list-venvs
```

In a daemon repository checkout use `./bin/hooks-daemon list-venvs`. Nothing is listed under `UNPROVEN venv(s)` and the marker column shows none: this task does not apply, and the SessionStart advisory stays silent.

## How to handle

For each listed venv read the evidence the command prints:

- **IN USE** lines name a process using the venv. Do not remove it; stop the process first, or leave the venv.
- **belongs to: another view** means the slug is another checkout view's (a host and a container sharing one checkout). Confirm that view is not in use, for example no daemon or shell is running from it, before removing.
- **interpreter, version, last modified** tell you whether it is an old leftover (an interpreter that no longer exists, a modification time long before the current daemon was built) or something recent.
- A venv with no readable metadata but a recent modification time may be mid-build by another process: wait and list again.

Once you have confirmed a venv is unused and safe, remove that one venv with the command printed under it:

```bash
.claude/hooks-daemon/bin/hooks-daemon prune-venvs --unproven <path> --force
```

The command refuses a venv that is the running daemon's or the resolver's choice, one a live process uses, a proven-stale one and any path that is not a venv here. When you cannot tell whether a venv is safe, ask the user rather than removing it.

## How to confirm

`list-venvs` shows no `UNPROVEN` marker, or only venvs you decided to keep and can say why. A new session start no longer shows the advisory for the ones you removed.

## Rollback / if this goes wrong

A removed venv is rebuilt by the next hook or `hooks-daemon repair` for the view that needed it, so removing one that was in use costs a rebuild, not data.

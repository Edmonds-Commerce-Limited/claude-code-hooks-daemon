# What was measured before the merge existed (Plan 00176)

The evidence the plan was filed on, extracted from `PLAN.md` to keep that
document lean and current. Everything here describes the state BEFORE Tasks 2.0,
2.0b and 2.3 shipped; it is kept because the reasoning — particularly about
where a recoverable copy really lived — is what shaped the design, and
re-deriving it would cost more than storing it.

## Three routes, all of them a verbatim copy

The installer and upgrader deployed the daemon's own `.claude/settings.json`
into client projects by verbatim copy, never a merge. On a fresh install the
client's existing file was backed up then overwritten
(`scripts/install_version.sh`); on **every upgrade** it was overwritten again
(`scripts/upgrade_version.sh`, Step 9 "Redeploying settings.json"). The
config-preservation machinery that survives client customisations
(`scripts/install/config_preserve.sh` → `preserve_config_for_upgrade`) operates
**only on `hooks-daemon.yaml`** — `settings.json` got no merge at all.

The consequence: any customisation a client made to `.claude/settings.json` —
their own `statusLine` command, an extra hook they registered, a `permissions`
block, a deliberately-chosen `refreshInterval`, or any additional key — was
silently clobbered on every upgrade and reset to the daemon's values. This is
the footgun surfaced while shipping Plan 00175's `refreshInterval: 1` default:
that default rolls out *because* we overwrite, but the same mechanism meant a
client could never keep a value of their own.

## The third route, found by Plan 00250

`install.py`, on **every** invocation. `create_settings_json` and
`create_daemon_config` both opened with `if <file>.exists() and not force:` —
which is **not** an early return. The body renamed the existing file to `.bak`
and then wrote the default template unconditionally:

```python
if <file>.exists() and not force:
    backup_file = ...
    <file>.rename(backup_file)
# ... default template written here regardless
```

So `force` only decided whether a **backup was taken**. There was no invocation
that preserved an existing config. Confirmed on a GitHub runner, which printed
`✅ Backed up existing hooks-daemon.yaml…` / `✅ Created .claude/hooks-daemon.yaml`
from a plain `install.py --self-install` with no flag. The
`/hooks-daemon install` skill documents `--force` only as "Force reinstall over
existing", which reads as though omitting it is safe.

Measured against this repository, that dropped `plansDirectory` (whose absence
trips `R-MARKDOWN-PLAN-SYNC`), a `permissions.deny` block guarding `/tmp`,
`/var/tmp` and `/dev/shm`, `enableArtifact: false`, and the statusLine
`refreshInterval` — then replaced 1188 lines of `hooks-daemon.yaml` carrying 128
enabled handlers. **And the replacement did not work**: the daemon refused to
start on that config with
`Unknown field 'min_confidence_score' at: handlers.session_start.min_confidence_score`,
because the template still configured `yolo_container_detection`, a handler with
no module left in `src/`. Worked example and evidence in
[Plan 00250's RESEARCH-ci-install.md](../00250-ci-runs-the-blocking-acceptance-gates/RESEARCH-ci-install.md).

## Where the backup actually was

The answer inverts what you would hope for. Of the three routes, the one that
repeats was the one with no backup:

| Route                                | Backup before overwrite   |
| ------------------------------------ | ------------------------- |
| `install_version.sh` (fresh)         | yes — `.bak-<timestamp>`  |
| `upgrade_version.sh` (every upgrade) | yes — the Step 3 snapshot |
| `install.py` without `--force`       | yes — `.bak`              |
| `install.py --force`                 | **no**                    |

**Correction (verified, and it changed the cheap mitigation).** The upgrade row
first read "**no** — bare `cp`", reasoning from the copy alone. The copy does
take no adjacent backup, but `upgrade_version.sh` creates a full state snapshot
at **Step 3**, long before Step 9, and `install/rollback.sh` captures
`settings.json` in it. `cleanup_old_snapshots "$DAEMON_DIR" 3` keeps the three
most recent, so the copy survives a *successful* upgrade.

So a recoverable copy did exist, and "back it up first" would have added a
second one. What was actually missing is different, and worse in a quieter way:

- **The snapshot is a rollback artefact, not a preservation mechanism.** It is
  restored only by `cleanup_on_failure`. On a *successful* upgrade the client's
  customisations were silently discarded and nothing put them back.
- **Nobody was told.** Step 9 printed `Redeployed settings.json` — a success
  message for an operation that may have just dropped their `statusLine`, their
  `permissions` block and their `plansDirectory`.
- **It expires.** Three more upgrades and the last copy is gone.
- **It is best-effort.** Snapshot creation failure only warns, and the upgrade
  proceeds anyway.

The cheap mitigation was therefore **not** an extra backup but a truthful
message: when the deployed file differs from the one already there, say so and
name the snapshot path. Small, independent of the merge design, and it converts
a silent loss into a recoverable one. That is what Task 2.0 shipped.

## The two installers already disagreed, and one of them was right

For `hooks-daemon.yaml`, `install_version.sh` KEEPS an existing config and
deploys the tracked `.yaml.example` only when there is none — exactly what this
plan wanted. `install.py` embedded its own template and replaced the config
every time, and that copy had drifted far enough to generate a config the daemon
refused to load. Fixed, with a round-trip test through the real validator. A
single source for the default config would have made it impossible.

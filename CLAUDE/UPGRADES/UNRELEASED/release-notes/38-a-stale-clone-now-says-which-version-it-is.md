# Callout: a stale clone now says which version it is

**Plan**: 00386
**Audience**: operators
**Reported as**: GitHub issue #38

`.claude/hooks-daemon/` is gitignored, so the clone is per-checkout and
disposable. Everything it deploys — `init.sh`, the hook forwarders,
`settings.json`, the skills, `hooks-daemon.yaml`, the `CLAUDE.md` block — is
TRACKED, and is the reviewed truth. Nothing compared the two.

In the reported case a leftover v3.15.1 clone met tracked assets deployed from
v3.60.0. The daemon refused to start and every hook event for the whole session
answered:

```
HOOKS DAEMON: Not currently running
Error: daemon_startup_failed - Failed to start hooks daemon.
```

Every safety handler was inactive, under `--dangerously-skip-permissions`, until
a human noticed. The message points at `logs` and `restart` — and a restart
changes neither version, so the advice loops while the reader never learns what
is actually wrong.

**Startup now names both versions and the exact command**, and states outright
that a restart cannot fix it rather than merely offering something better. Both
directions are covered: a clone BEHIND the tracked assets is upgraded, while a
clone AHEAD of them means the tracked assets are the stale half and are
regenerated instead. It is silent whenever the two agree, and whenever either
version cannot be read — a project that has never generated
`.claude/HOOKS-DAEMON.md` is normal, not broken, and is never accused on absent
evidence.

**`upgrade` now computes an honest range.** It took `from_version` from the
clone, so the reported case ran `check-truth-changes --from 3.15.1` and got 73
entries of already-reconciled history where the true answer was five. The
version the project's TRACKED assets were deployed from is what decides what the
project still owes, so that is what is used — but only when it is NEWER than the
clone, so the change can only shrink a range a stale clone inflated, never grow
one. When it substitutes, it says so, naming both versions.

**The session-start freshness advisory now says to commit.** It already reported
a generated doc whose embedded version had fallen behind the running daemon.
What it did not say is that the regenerated result must be COMMITTED — and for a
tracked artefact that is the load-bearing half, because the committed copy is
what the next install deploys from. Projects whose generated doc is gitignored
do not see the extra advice; trackedness is asked of git rather than assumed.

**No new file format was added.** The version was already machine-readable — the
`> Generated on YYYY-MM-DD (vX.Y.Z) by ...` header that `generate-docs` writes
into `.claude/HOOKS-DAEMON.md` on every upgrade. The issue concluded no marker
existed after grepping for `daemon_version`; it is simply spelled as prose.

**Nothing upgrades or restarts itself.** That was asked for and deliberately not
built: it would have the daemon mutate its own installed version from a signal
any commit can change, at the one moment the project is least protected. Every
message here names a command for a human to run.

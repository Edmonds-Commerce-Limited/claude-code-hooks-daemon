# Callout: a pulled `daemon.expected_version` upgrade now syncs the daemon clone in the background, and a failed sync is reported at every session start

**Plan**: 00477
**Audience**: operators

When someone else upgrades the project and commits, this checkout's pull changes `daemon.expected_version`, but the gitignored clone under `.claude/hooks-daemon/` stays at the old version. The SessionStart `version_check` drift notice used to name `bash .claude/provision.sh` and wait for a person to run it. For an UPGRADE it now starts that sync itself: `bash .claude/provision.sh --background`, detached, so it never runs inside the hook's time budget. The steps are provision's own: the tag is fetched from the fixed URL, its `version.py` is checked, the target release's pre-deploy gate runs, the venv is rebuilt through the clone's own build path, and the daemon is restarted. The running daemon keeps serving until the restart.

- The output goes to `.claude/hooks-daemon/untracked/background-sync/v<version>.log`. The outcome is recorded in `v<version>.state` beside it. That file is also the marker that the target was attempted, so each target version is synced in the background at most once. A lock stops two syncs from overlapping.
- A failure leaves the previous version in place, as a manual provision does: a refused clone, an unfetchable tag, a failed venv build, or a target whose pre-deploy gate wants its reading list confirmed. Every later session start then shows `BACKGROUND SYNC TO vX.Y.Z FAILED` (or `STOPPED`) to the human and the agent, with the reason, the log, `bash .claude/provision.sh` to run by hand, and the state file to delete to have it retried in the background.
- A DOWNGRADE is never synced in the background. Nor is a fresh checkout provisioned, or a project without the tracked `.claude/provision.sh` synced. The notice for those still names the command, and a person or agent runs it. The daemon's own repository never syncs.
- Only the version check started by an installed daemon at this version or later starts the sync. The first move onto this release is therefore still a manual `bash .claude/provision.sh` (or the upgrade itself), as before.

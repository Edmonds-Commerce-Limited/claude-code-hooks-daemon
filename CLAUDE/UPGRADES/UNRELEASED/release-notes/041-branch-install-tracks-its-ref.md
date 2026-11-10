# Callout: a branch install knows the ref it tracks, notices when it moves, and has a one-step way back

**Plan**: 00594
**Audience**: client projects

A guarded branch install now records the exact tracked ref (slashes kept), the full commit and the release installed before it in the venv's `.daemon-metadata.json`; a release install clears them. At session start a branch install makes one cached, time-bounded listing of that branch on the remote and, when the tip differs from the installed commit, says `tracked ref <ref> moved <old7>..<new7>; re-run the upgrade to follow it` with the command to run. A full-sha pin never moves and makes no network call; a listing that fails or times out says "not checked", never "current". A release install makes no such call. `upgrade.sh --release` (or the hooks-daemon skill with `args=upgrade --release`) returns to the release recorded before the branch install, or the latest release when none was recorded, with no `HOOKS_DAEMON_UNSAFE_*` variables. Following a moved ref still goes through the same guarded upgrade; the stop, checkout, build and start handover order is owned by Plan 00535.

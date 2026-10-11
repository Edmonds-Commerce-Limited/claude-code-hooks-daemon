# Callout: Stop re-entry with an unreadable transcript is allowed, and fewer inline-code advisories

**Plan**: 00474
**Audience**: everyone

Three guard changes from the niggles ledger. A Stop on a re-entry whose transcript cannot be read (no path, a missing file, a directory or a permission error) is now allowed by auto-continue, instead of being treated as a fresh stop and blocked again; this keeps the daemon to one block per chain and below Claude Code's 8-continuation cap (N411). A readable transcript with no block marker is still treated as a fresh stop.

The sub-agent full-QA guard no longer raises the unrecognised-interpreter inline-code advisory for `ps -e`, `file -e`/`-c`/`-r`, or `docker run -e`/`podman run -e` (and `exec`, `create`) when the flag comes before the image. Words after the image are still judged, so `docker run IMG sh -c '...'` is still flagged (N419).

The conflict-marker commit gate stays fail-closed when it cannot place the repository, and its deny now names the forms it accepts for reaching the project root: `cd "$(git rev-parse --show-toplevel)"`, `cd "$PWD"` and `cd "$(pwd)"` (N402). Nothing to do on upgrade.

# Callout: the venv resolver probes this path's venv first and no longer warns about a sibling view's

**Plan**: 00598
**Audience**: client projects

When one checkout is visible at two paths (for example a container bind mount of the host checkout), each path builds its own venv under `untracked/`, and both carry the same `lock_hash`. The resolver's scan ranked them equal, so the other path's venv could be probed first and, when another Python built it, print `resolve_venv: candidate ... interpreter drift ... -- skipping` on every interpreter-cache miss before choosing the right venv (GitHub #199). Two changes, in `scripts/lib/resolve_venv.sh` and its mirror in `daemon/paths.py`:

- **Own-slug first.** Among candidates of equal rank, the venv whose slug names THIS project path is probed first.
- **A sibling view's failure is not reported.** A candidate slugged for a different path that fails the usable probe is skipped silently; it belongs to that view. A failing venv slugged for this path, or a legacy un-slugged one, still warns as before.

The venv chosen is unchanged; only the spurious warning and the probe order differ.

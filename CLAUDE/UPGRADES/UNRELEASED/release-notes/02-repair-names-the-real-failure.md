# Callout: `repair` no longer blames a missing `uv` for a lock failure

**Plan**: 00364
**Audience**: operators

`hooks-daemon repair` used to answer every `FileNotFoundError` with "'uv' not
found. Install with: curl ...", including one raised by the venv build lock
rather than by `uv` itself. The lock's `mkdir` backend was the likely source:
it checks a held lock's age with a `stat` that fails if the holder releases
between the two syscalls, which is precisely what happens when two daemons —
or a daemon and a repair — contend. That gap now reads as "the lock just
became free" and the lock is retaken, still bounded by the same wait, and the
"install uv" message is scoped to the `uv` spawn that can actually mean it.
Everything else reports the path it could not find.

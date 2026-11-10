# Callout: a guarded unreleased-ref install no longer dies on a large pyproject.toml

**Plan**: 00594
**Audience**: client projects

An install of an unreleased ref (`HOOKS_DAEMON_UNSAFE_TRACK_REF` with `HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE`) could stop with exit 141 straight after "Fetching tracked ref ...", before anything was checked out. The version reader stopped at the version line while git was still writing the rest of `pyproject.toml`, and the resulting SIGPIPE ended the script. It only happened when the ref's `pyproject.toml` was larger than one pipe write. The installer now reads the whole file before parsing it. If such an install failed for you, run it again: the daemon was never changed.

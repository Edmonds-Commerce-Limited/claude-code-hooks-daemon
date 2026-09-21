# Callout: the worktree socket-path pre-flight now works without a venv

**Plan**: 00431
**Audience**: operators

`scripts/setup_worktree.sh` refuses to create a worktree whose prospective
daemon socket path would exceed the AF_UNIX cap, because exceeding it is silent:
the daemon still starts, relocates its runtime files to `/tmp`, and the
acceptance gates then report "no live socket found under `untracked/`" with a
restart instruction that cannot fix it.

That check resolved a virtualenv Python in order to call the daemon's own
measurement helpers, and stood down when it could not — so it never ran in a
worktree created from INSIDE another worktree, which has no venv yet and is
exactly where the path gets long enough to matter. The guard was inert in the
case that motivated it and healthy everywhere else, reporting `✓ Socket path fits` on every short path anyone tested it against.

It now measures under the system `python3`, loading `daemon/paths.py` by file
rather than importing it by package path (`paths.py` is stdlib-only; the package
`__init__` pulls in pydantic). The AF_UNIX limit still comes from
`_UNIX_SOCKET_PATH_LIMIT` — the fix deliberately does not put a second copy of
that number into bash. Failing open survives for the cases that deserve it, a
missing `python3` or a missing `paths.py`, and each now says which one happened
instead of naming the venv.

# Callout: `hooks-daemon status` names the live commit after a branch install moves

**Plan**: 00594
**Audience**: client projects

When a guarded branch install moved to a newer commit whose `pyproject.toml` and `uv.lock` were unchanged, the existing venv was reused but kept the install stamp of the older commit, so `hooks-daemon status` and the version check reported a commit that was no longer live. Every venv reuse now rewrites the stamp with the version being installed, without rebuilding, and a stamp that cannot be written fails the install the same way a failed build does.

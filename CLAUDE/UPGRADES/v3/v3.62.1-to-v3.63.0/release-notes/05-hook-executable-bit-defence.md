# Callout: hooks that lose their executable bit are detected and repaired

**Plan**: 00102
**Audience**: operators

A hook script whose executable bit was dropped (a checkout on a filesystem
that ignores file modes, a copy that lost permissions) used to fail silently
and take its protection with it. A multi-tier defence now reports the
condition at session start via `git_filemode_checker`, and the existing
auto-fixer repairs git hooks in place.

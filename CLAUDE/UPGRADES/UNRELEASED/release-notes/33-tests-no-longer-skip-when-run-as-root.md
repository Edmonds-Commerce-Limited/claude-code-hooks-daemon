# Callout: tests no longer skip when run as root

**Plan**: 00466 (N56)
**Audience**: contributors

Every test in this repository now proves its behaviour as root instead of
skipping. Four tests used to guard a permission-bypass assertion with
`os.geteuid() == 0`, so they never ran on this container or the dogfood
server, where the process is root. Each is rewritten to fault the operation a
different way — an injected `PermissionError` at the specific write call, a
stubbed shell `cp`, or a monkeypatched `os.access` — since root bypasses the
file mode bits those tests used to rely on.

`tests/integration/test_no_root_conditioned_skips.py` replaces Plan 00351's
narrower "does the root-skip's condition match its reason" check with a
blanket static scan: it fails on any `skipif`/`xfail` decorator or
hand-written `if <root check>: skip/xfail/return` anywhere under `tests/`
that gates on `os.geteuid()`/`os.getuid()`, whatever the condition or the
reason say. `CLAUDE/QA.md` records the rule alongside the other testing
requirements.

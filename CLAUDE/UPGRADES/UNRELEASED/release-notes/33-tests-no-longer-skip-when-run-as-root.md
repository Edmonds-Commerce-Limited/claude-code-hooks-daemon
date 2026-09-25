# Callout: tests no longer skip when run as root

**Plan**: 00466 (N56)
**Audience**: contributors

Every test in this repository now proves its behaviour as root instead of
skipping. Three tests used to guard a permission-bypass assertion with
`os.geteuid() == 0`, so they never ran on this container or the dogfood
server, where the process is root. Each is rewritten to fault the operation a
different way — an injected `PermissionError` at the specific write call, a
stubbed shell `cp`, or a monkeypatched `os.access` — since root bypasses the
file mode bits those tests used to rely on. A fourth test (an OSError path
gated behind `chmod(0o000)`, not a skip) and a fifth (a skip keyed on
`/run/user/{uid}` existing, which depends on the host rather than on root)
are fixed the same way.

`tests/integration/test_no_root_conditioned_skips.py` replaces Plan 00351's
narrower "does the root-skip's condition match its reason" check with a
blanket static scan of every `.py` file under `tests/` (not just
`test_*.py`/`conftest.py`, and excluding `tests/fixtures/`, which holds
deliberately-invalid Python for other handlers' own error-path tests). It
fails on a `skipif`/`xfail`/`unittest.skipIf` decorator or a hand-written
`if <root check>: skip/xfail/skipTest/return` whose condition resolves —
following a module constant or a zero-arg helper's `return`, and covering
`not geteuid()`, `geteuid() in (0,)`, a `pwd`/`getpass` identity check, and a
string condition — to something that tests root, **and independently** on
any skip-like call whose stated *reason* names root, whatever its condition
actually tests (Plan 00351's own shape). `CLAUDE/QA.md` records the rule
alongside the other testing requirements.

# Callout: tests no longer skip when run as root

**Plan**: 00466 (N56)
**Audience**: contributors

Every test in this repository now proves its behaviour as root instead of
skipping. Three tests used to guard a permission-bypass assertion with
`os.geteuid() == 0`, so they never ran on this container or the dogfood
server, where the process is root. Each is rewritten to fault the operation a
different way — an injected `PermissionError` at the specific write call, a
stubbed shell `cp`, or a monkeypatched `os.access` — since root bypasses the
file mode bits those tests used to rely on. Two more tests were vacuous as
root without ever skipping: an OSError path gated behind `chmod(0o000)` now
monkeypatches the specific read call instead, and a skip keyed on
`/run/user/{uid}` existing (host-dependent, not root-dependent) is now
deterministic. A `set_hook_permissions` failure path that root's own chmod
success had left untested behaviourally is now proven with a stubbed
`chmod`.

`tests/integration/test_no_root_conditioned_skips.py` replaces Plan 00351's
narrower "does the root-skip's condition match its reason" check with a
blanket static scan of EVERY `.py` file under `tests/` — not just
`test_*.py`/`conftest.py`, and with no exclusion list; a `fixtures/`
directory is scanned exactly like the rest of the tree. It classifies by
data flow, not by name: a condition tainted by `geteuid`/`getuid`/
`getegid`/`getgid`/`getresuid`/`getresgid`, `getpass.getuser`, a `pwd`/`grp`
lookup, an env check of `USER`/`LOGNAME`/`HOME`/`SUDO_*`, `Path.home()`/
`os.path.expanduser("~")`, `os.access(...)`, or `<expr>.stat().st_uid` is
flagged through an alias, a local variable, a module constant, or one level
of same-module helper (a `def` or a zero-arg lambda, including a
parameterised helper called with literal arguments). It fails on a
`skipif`/`xfail`/`unittest.skipIf`/`skipUnless` decorator, an `IfExp`
marker, a hand-written `if <root check>: skip/xfail/skipTest/return`, or a
conftest collection hook whose control flow depends on one — **and
independently** on any skip-like call whose stated *reason* names root,
whatever its condition actually tests (Plan 00351's own shape). A reference
this scan cannot resolve (a cross-module import, a class attribute) whose
own name suggests process identity is reported rather than silently passed.
`CLAUDE/QA.md` records the rule alongside the other testing requirements.

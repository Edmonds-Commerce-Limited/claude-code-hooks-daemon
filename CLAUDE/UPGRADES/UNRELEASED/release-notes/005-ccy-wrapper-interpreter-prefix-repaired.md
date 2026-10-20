# Callout: an interpreter-prefixed ccy wrapper broken by 3.69.0 and 3.70.0 is repaired

**Plan**: 00540
**Audience**: operators

3.69.0 and 3.70.0 broke a ccy wrapper written with a Python interpreter in front of the supervisor (`python3 .claude/ccy/claude-supervise.py`): the upgrade pointed it at the `claude-supervise` launcher, which is a `sh` script, so Python failed on it with a SyntaxError and every ccy launch died. The next upgrade now rewrites the interpreter word to `sh` (`sh .claude/ccy/claude-supervise`), both for a wrapper not yet migrated and for one already broken that way, and it tells you when the word it dropped pinned a specific Python so you can set `CCY_PYTHON` to keep the pin. `ccy_supervisor_integrity` now also warns at session start about a Python interpreter in front of the launcher. (reported as issue #126)

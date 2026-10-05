# Callout: an unsupported Python no longer stops Claude Code opening

**Plan**: 00483
**Audience**: client projects

On a system `python3` older than 3.11 (RHEL-family 9 ships 3.9) the ccy supervisor crashed at import and Claude Code could not start, and the daemon reported only "Not installed". The supervisor now starts through a shell launcher, `.claude/ccy/claude-supervise`, that picks Python 3.11 or later (`CCY_PYTHON`, then `python3.14` down to `python3.11`, then `python3`) and otherwise prints a loud warning and starts `claude` unsupervised, and the daemon names the unsupported Python, the version it needs and to upgrade instead of "Not installed". Supported Python is 3.11 or later (see `CLAUDE/LLM-INSTALL.md`); an upgrade repoints an existing `ccy.env` at the launcher and `ccy_supervisor_integrity` warns about one that still runs `claude-supervise.py` directly.

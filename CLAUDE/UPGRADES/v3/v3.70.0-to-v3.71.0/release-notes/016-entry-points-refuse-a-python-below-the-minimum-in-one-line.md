# Callout: a Python below the minimum gets one clear line, not a traceback

**Plan**: 00546
**Audience**: everyone

The minimum Python (`requires-python`, currently 3.11) is now declared once, in `src/claude_code_hooks_daemon/python_floor.py`, and checked before anything else at every entry point an arbitrary interpreter can start: `daemon/paths.py`, `daemon/signal_standalone.py` and `install.py` run as scripts, any `python -m claude_code_hooks_daemon...`, and `bin/hooks-daemon signal` (which runs the guard under the system `python3` before executing the signal script). An older interpreter now prints one line naming the version it found and the version required, and exits non-zero. Before this, `paths.py` raised `AttributeError`/`TypeError` on 3.8/3.9, `install.py` a `ModuleNotFoundError` for `tomllib`, and `signal_standalone.py` accepted 3.8 and then crashed on `dataclass(slots=True)`. The `bin/hooks-daemon signal` wrapper previously accepted any `python3` from 3.8 and now requires the declared minimum.

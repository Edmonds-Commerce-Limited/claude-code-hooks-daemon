"""runpy entry point for `python -m claude_code_hooks_daemon.supervise`.

Kept as a pure shim (no logic, no re-exports) so that `runpy` executing this
module as `__main__` never also has to import the package `__init__.py`
re-exporting the same `main` symbol from here -- that double-import path is
what previously triggered `RuntimeWarning: '...supervise.__main__' found in
sys.modules after import of package '...supervise', but prior to execution`
on every launch. All logic lives in `cli.py`.
"""

from claude_code_hooks_daemon.supervise.cli import main

if __name__ == "__main__":  # pragma: no cover - exercised via subprocess, not in-process import
    raise SystemExit(main())

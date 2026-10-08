"""paths.py's log_and_continue must work with no package on the path.

``resolve_venv.sh`` runs ``python3 paths.py ...`` by file path during
fresh-clone bootstrap, when no venv exists and ``src/`` is not on
``sys.path``. The N296 audit recognises the sanctioned helper by call name, so
paths.py defines a lazy ``log_and_continue`` that loads
``utils/deliberate_swallow.py`` (and its stdlib-only ``escape_hatch``
dependency) by file path on first use.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.utils import deliberate_swallow

_PATHS_PY = Path(paths.__file__).resolve()
_TIMEOUT_SECONDS = 60

_STANDALONE_PROBE = textwrap.dedent("""
    import importlib.util, logging, sys

    spec = importlib.util.spec_from_file_location("standalone_paths", sys.argv[1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    log = logging.getLogger("probe")
    log.addHandler(_Capture())
    module.log_and_continue(log, OSError("boom"), reason="the probe tolerates boom")
    assert records == ["the probe tolerates boom: boom"], records

    rejected = False
    try:
        module.log_and_continue(log, OSError("boom"), reason="")
    except ValueError:
        rejected = True
    assert rejected, "an empty reason was accepted"

    package_importable = True
    try:
        import claude_code_hooks_daemon
    except ModuleNotFoundError:
        package_importable = False
    assert not package_importable, "the package was importable, the probe proves nothing"
    print("OK")
    """)


class TestStandaloneByFilePath:
    """With ``-S`` and no PYTHONPATH the package is invisible."""

    def test_log_and_continue_works_with_no_package_on_the_path(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
        result = subprocess.run(
            [sys.executable, "-S", "-c", _STANDALONE_PROBE, str(_PATHS_PY)],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OK"


class TestSharedModuleWhenPackageImportable:
    """One module object, not a second copy, when the package is importable."""

    def test_delegates_to_the_already_imported_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def _spy(
            logger: logging.Logger, exc: BaseException, *, reason: str, level: int = 0
        ) -> None:
            calls.append(reason)

        monkeypatch.setattr(deliberate_swallow, "log_and_continue", _spy)
        paths.log_and_continue(logging.getLogger("probe"), OSError("x"), reason="the spy sees this")
        assert calls == ["the spy sees this"]

    def test_rejects_a_placeholder_reason(self) -> None:
        with pytest.raises(ValueError):
            paths.log_and_continue(logging.getLogger("probe"), OSError("x"), reason="")

"""Regression tests for the `python -m claude_code_hooks_daemon.supervise` shim.

Guards against the runpy double-import bug: `runpy` executing this package as
`__main__` used to also trigger a `sys.modules['...supervise.__main__']`
collision (via `__init__.py` importing `main` from `.__main__`), producing a
`RuntimeWarning` on every single supervised launch. `main` now lives in
`cli.py`; `__main__.py` is a pure shim that only imports and calls it.
"""

import subprocess  # nosec B404 - trusted, args-list only, no shell
import sys

_SUBPROCESS_TIMEOUT_SECONDS = 10


class TestMainModuleShim:
    """`python -m claude_code_hooks_daemon.supervise` must run clean."""

    def test_module_is_importable_and_reexports_main(self) -> None:
        """In-process import exercises the shim's own `from ... import main` line."""
        from claude_code_hooks_daemon.supervise import __main__ as shim_module

        assert shim_module.main is not None

    def test_module_invocation_has_no_runtime_warning(self) -> None:
        result = subprocess.run(  # nosec B603 - fixed argv list, no shell
            [
                sys.executable,
                "-m",
                "claude_code_hooks_daemon.supervise",
                "--",
                "echo",
                "SUPERVISED_OK",
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )

        assert result.returncode == 0
        assert "SUPERVISED_OK" in result.stdout
        assert "RuntimeWarning" not in result.stderr

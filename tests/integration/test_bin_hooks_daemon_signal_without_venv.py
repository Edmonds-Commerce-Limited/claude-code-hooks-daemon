"""``bin/hooks-daemon signal`` works when there is no venv to run it with (Plan 00457, #55).

The wrapper resolves the venv before it looks at a single argument, so every
verb exits 5 when no venv resolves for this path (Plan 00456, #53, fixed this
for ``repair`` first -- see ``test_bin_hooks_daemon_repair_without_venv.py``).
``signal`` -- the operator-signal channel's host-reachable caller (Plan
00417) -- is the second verb this applies to, and for a different reason: its
caller need not be inside any Claude Code session at all, so for a project
whose only venv was built inside a container (wrong slug, wrong interpreter),
this host-side tool was refused on the exact deployment it exists for.

Unlike ``repair``, ``signal`` never builds a venv. Its arm execs
``daemon/signal_standalone.py`` -- standard-library-only, loaded by file path
rather than package import (see that module's own docstring) -- directly
under a system ``python3``, gated on Python >= 3.8 first so an old
interpreter gets a clear message instead of an ``ImportError`` from inside
``operator_signal.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import Sandbox

#: bin/hooks-daemon's "no venv resolves" exit status.
_NO_VENV_EXIT = 5


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _sidecar_dir(sandbox: Sandbox) -> Path:
    sidecar_dir = sandbox.clone / "untracked" / "context-sidecar"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    return sidecar_dir


class TestSignalWithNoVenv:
    def test_writes_a_signal_and_builds_no_venv(self, sandbox: Sandbox) -> None:
        sidecar_dir = _sidecar_dir(sandbox)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert (sidecar_dir / "sess-a.operator-signal").exists()
        assert sandbox.uv_calls() == [], "signal must never build a venv"
        assert not sandbox.resolves(), "signal leaves this clone with no venv, exactly as before"

    def test_a_warning_kind_without_minutes_is_still_refused(self, sandbox: Sandbox) -> None:
        """Validation is unchanged: reused from operator_signal.py, not
        re-implemented for the venv-free path."""
        result = sandbox.wrapper(
            "signal", "reboot-warning", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == 1, result.stdout + result.stderr
        assert "--minutes" in result.stderr

    def test_help_needs_no_venv(self, sandbox: Sandbox) -> None:
        result = sandbox.wrapper("signal", "--help")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "signal" in result.stdout.lower()
        assert sandbox.uv_calls() == []

    def test_a_missing_entry_point_is_named(self, sandbox: Sandbox) -> None:
        entry_point = (
            sandbox.clone / "src" / "claude_code_hooks_daemon" / "daemon" / "signal_standalone.py"
        )
        entry_point.unlink()

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == _NO_VENV_EXIT
        assert "signal_standalone.py" in result.stderr
        assert sandbox.uv_calls() == []

    def test_refuses_a_python3_older_than_the_floor(self, sandbox: Sandbox) -> None:
        """The wrapper's own gate, ahead of ever invoking the entry point --
        distinct from (and a backstop alongside) signal_standalone.py's own
        internal `_check_python_version`."""
        old_python3 = sandbox.root / "tools" / "python3"
        old_python3.unlink()
        old_python3.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
        old_python3.chmod(0o755)

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == _NO_VENV_EXIT
        assert "3.8" in result.stderr
        assert sandbox.uv_calls() == []


class TestTheVerbIsFoundPastGlobalOptions:
    """Mirrors ``TestTheVerbIsFoundPastGlobalOptions`` in the repair test file
    (Review S3): the intercept looks for the subcommand, not just ``$1``.
    """

    def test_signal_after_a_global_option_still_dispatches(self, sandbox: Sandbox) -> None:
        sidecar_dir = _sidecar_dir(sandbox)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")

        result = sandbox.wrapper(
            "--project-root",
            str(sandbox.project),
            "signal",
            "reboot-cancelled",
            "--all-sessions",
            "--project-root",
            str(sandbox.project),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert (sidecar_dir / "sess-a.operator-signal").exists()

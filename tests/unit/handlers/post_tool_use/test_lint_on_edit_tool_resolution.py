"""Guard: lint tools installed in the project venv must actually be found.

DOGFOODING BUG. ``lint_on_edit`` builds its extended Python command as the bare
string ``ruff check {file}`` and hands it to ``subprocess.run`` without a shell,
so the executable is resolved against ``PATH`` only. In this repository — and in
any Python project that keeps its tooling in a virtualenv, which is the normal
case — ``ruff`` is installed in the venv's ``bin/`` and is NOT on ``PATH``. The
handler therefore raised ``FileNotFoundError`` on every single ``.py`` edit and
degraded to an advisory reading:

    ⚠️ Python lint tool not found (ruff) - install to enable lint checking

Two failures in one:

1. The lint-on-edit guard was silently inert in the daemon's own repo, and in
   every client repo with a venv. A guard that reports "not available" instead
   of running is indistinguishable from a guard that passed.
2. The advice was wrong. It told the user to install software that was already
   installed, so following it could not fix anything.

The strategy module already had the answer in the line above: the DEFAULT Python
command is built as ``f"{sys.executable} -m py_compile ..."``, deliberately
using the running interpreter "works in any environment". Only the extended
command was left resolving against PATH.

WHY RESOLUTION, NOT ``python -m ruff``: rewriting the command to
``{sys.executable} -m ruff check`` would find ruff here but would be actively
harmful in a client whose daemon venv lacks it — ``python -m ruff`` exits
NON-ZERO ("No module named ruff") rather than raising ``FileNotFoundError``, and
a non-zero extended lint result is a DENY. That converts "tool absent" from a
harmless advisory into a hard block on the user's file edit, with a baffling
reason. Resolving the executable to an absolute path keeps the two cases
distinct: found -> run it; genuinely absent -> advise, never block.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import (
    LintOnEditHandler,
)
from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy

# The interpreter running the daemon lives in the project venv's bin/ directory,
# which is where that venv's console scripts (ruff, black, mypy) also live.
_VENV_BIN: Final[Path] = Path(sys.executable).parent


class TestLintToolResolution:
    """The handler resolves a bare tool name before deciding it is missing."""

    def test_resolves_tool_installed_in_the_daemon_venv(self) -> None:
        """A tool in the venv bin/ resolves, even when absent from PATH.

        This is the exact condition that made the handler inert: ruff present in
        ``<venv>/bin/ruff``, nothing named ruff anywhere on PATH.
        """
        handler = LintOnEditHandler()

        resolved = handler._resolve_executable("ruff")

        assert resolved is not None, (
            "ruff did not resolve. It is installed in the project venv at "
            f"{_VENV_BIN / 'ruff'}; a resolver that misses it leaves the "
            f"lint-on-edit guard inert for every venv-based project."
        )
        assert Path(resolved).is_file(), f"Resolved to {resolved!r}, which is not a file."

    def test_absolute_paths_pass_through_unchanged(self) -> None:
        """An already-absolute command (e.g. sys.executable) is not rewritten."""
        handler = LintOnEditHandler()

        assert handler._resolve_executable(sys.executable) == sys.executable

    def test_genuinely_missing_tool_returns_none(self) -> None:
        """Absence is still reported as absence — NOT silently resolved.

        Control. A resolver that returned some path for every input would make
        the first test pass while breaking the graceful-degradation path, so the
        handler would try to execute nonsense instead of advising.
        """
        handler = LintOnEditHandler()

        assert handler._resolve_executable("definitely-not-a-real-linter-xyzzy") is None

    def test_python_extended_command_still_names_ruff(self) -> None:
        """The strategy keeps a bare tool name; resolution is the handler's job.

        Guards against "fixing" this by hardcoding an absolute venv path into
        the strategy constant, which would break every OTHER environment.
        """
        command = PythonLintStrategy().extended_lint_command

        assert command is not None
        assert command.startswith("ruff "), (
            f"Expected the extended command to invoke ruff by name, got {command!r}. "
            f"The strategy must stay environment-independent."
        )


class TestMissingToolIsAdvisoryNotBlocking:
    """A missing linter must never deny the user's edit."""

    def test_missing_tool_allows_and_explains(self) -> None:
        """An unresolvable tool yields ALLOW with actionable context."""
        from claude_code_hooks_daemon.core import Decision

        handler = LintOnEditHandler()

        result = handler._run_lint_command(
            "definitely-not-a-real-linter-xyzzy check {file}",
            "/tmp/example.py",
            "Python",
        )

        assert result is not None, "A missing tool must report, not pass silently."
        assert result.decision == Decision.ALLOW, (
            "A missing linter must never DENY. Blocking a user's edit because a "
            "tool is not installed is the failure mode this guard exists to "
            "prevent — see the module docstring on `python -m ruff`."
        )

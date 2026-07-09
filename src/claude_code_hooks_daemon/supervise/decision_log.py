"""Typed, append-only decision log for the PTY supervisor.

Every line is timestamped and written immediately (no buffering) so a crash
or forced kill of the supervised session never loses prior observations.
Write failures are never swallowed -- FAIL FAST so a broken log path is
surfaced immediately rather than silently discarding supervisor context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from claude_code_hooks_daemon.core.project_context import ProjectContext

if TYPE_CHECKING:
    from pathlib import Path

_LOG_SUBDIRECTORY = "supervise"
_LOG_FILENAME = "decision.log"


class DecisionLog:
    """Append-only, timestamped log file for supervisor decisions/observations."""

    def __init__(self, path: Path | None = None) -> None:
        """Create (or attach to) a decision log file.

        Args:
            path: Explicit log file path. When omitted, defaults to
                ``ProjectContext.daemon_untracked_dir() / "supervise" / "decision.log"``.

        Raises:
            OSError: If the parent directory cannot be created.
            RuntimeError: If no explicit path is given and ProjectContext has
                not been initialized.
        """
        self._path = path if path is not None else self._default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _default_path() -> Path:
        return ProjectContext.daemon_untracked_dir() / _LOG_SUBDIRECTORY / _LOG_FILENAME

    @property
    def path(self) -> Path:
        """Absolute path to the underlying log file."""
        return self._path

    def write(self, message: str) -> None:
        """Append a single timestamped line to the log.

        Args:
            message: The message to record.

        Raises:
            OSError: If the file cannot be written (never swallowed).
        """
        timestamp = datetime.now(UTC).isoformat()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")

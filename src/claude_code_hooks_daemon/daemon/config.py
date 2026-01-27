"""Daemon configuration management."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DaemonConfig:
    """Configuration for the hooks daemon server.

    Attributes:
        socket_path: Path to Unix domain socket for IPC
        idle_timeout_seconds: Seconds of inactivity before auto-shutdown
        pid_file_path: Path to PID file for daemon lifecycle tracking
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """

    socket_path: Path
    idle_timeout_seconds: int = 600  # 10 minutes default
    pid_file_path: Path | None = None
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Validate configuration after initialisation."""
        if self.idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds must be positive")

        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError(f"Invalid log_level: {self.log_level}")

        # Convert string paths to Path objects if needed
        if isinstance(self.socket_path, str):
            self.socket_path = Path(self.socket_path)

        if isinstance(self.pid_file_path, str):
            self.pid_file_path = Path(self.pid_file_path)

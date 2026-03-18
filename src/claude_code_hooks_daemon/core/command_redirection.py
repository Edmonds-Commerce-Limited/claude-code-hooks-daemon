"""Command redirection utility for blocking handlers.

When a blocking handler denies a command but knows the corrected version,
this utility executes the corrected command, saves output to a file, and
returns context lines so Claude gets both the educational deny message
AND the result in one turn.

Usage in handlers:
    from claude_code_hooks_daemon.core.command_redirection import (
        execute_and_save, format_redirection_context,
    )

    result = execute_and_save(
        command=["gh", "issue", "view", "123", "--comments"],
        output_dir=redirection_dir,
        label="gh_issue_view",
    )
    context = format_redirection_context(result)
    return HookResult(decision=Decision.DENY, reason="...", context=context)

SECURITY:
- Commands are computed by handlers (not user input) — safe by construction
- Uses subprocess.run with list args (no shell=True)
- Output written to daemon untracked directory (not /tmp)
- Files auto-cleaned after 1 hour
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404 - subprocess used for handler-computed commands only
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Subdirectory name within daemon untracked dir for redirection output
COMMAND_REDIRECTION_SUBDIR: str = "command-redirection"

# Default timeout for redirected commands (seconds)
DEFAULT_TIMEOUT_SECONDS: int = 30

# Max age for output files before cleanup (seconds) — 1 hour
_CLEANUP_MAX_AGE_SECONDS: int = 3600


@dataclass(frozen=True)
class CommandRedirectionResult:
    """Result of executing a redirected command.

    Attributes:
        exit_code: Process exit code (0 = success)
        output_path: Path to file containing command output
        command: The command string that was executed
    """

    exit_code: int
    output_path: Path
    command: str

    @property
    def success(self) -> bool:
        """Whether the command exited successfully."""
        return self.exit_code == 0


def execute_and_save(
    command: list[str],
    output_dir: Path,
    label: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: Path | None = None,
) -> CommandRedirectionResult:
    """Execute a command and save its output to a file.

    Runs the command via subprocess (no shell), captures stdout+stderr,
    and writes a structured output file with header and content.

    Args:
        command: Command as list of args (e.g. ["gh", "issue", "view", "123"])
        output_dir: Directory to write output file into
        label: Handler label for filename (e.g. "gh_issue_view")
        timeout_seconds: Max execution time before killing the process
        cwd: Working directory for command execution. CRITICAL: the daemon
            process runs from "/" (daemonization calls os.chdir("/")), so
            commands with relative paths will fail without this parameter.
            Use ProjectContext.project_root() for project-relative commands.

    Returns:
        CommandRedirectionResult with exit code, output path, and command string

    SECURITY: B603/B607 — commands are handler-computed, not user input.
    Only trusted system tools (gh, npm, etc.) are used.
    """
    command_str = " ".join(command)

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old files on each execution
    cleanup_old_files(output_dir, max_age_seconds=_CLEANUP_MAX_AGE_SECONDS)

    # Generate unique filename with timestamp
    timestamp = int(time.time())
    output_path = output_dir / f"{label}_{timestamp}.txt"

    try:
        # SECURITY: B603/B607 — command list computed by handler, not user input.
        # Only trusted system tools are invoked (gh, npm, etc.).
        proc = subprocess.run(  # nosec B603 B607
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            cwd=str(cwd) if cwd else None,
        )

        exit_code = proc.returncode
        stdout = proc.stdout.decode(errors="replace")
        stderr = proc.stderr.decode(errors="replace")

        # Write structured output file
        lines = [
            f"Command: {command_str}",
            f"Exit code: {exit_code}",
            "---",
        ]
        if stdout.strip():
            lines.append(stdout)
        if stderr.strip():
            lines.append(f"[stderr]\n{stderr}")

        output_path.write_text("\n".join(lines), encoding="utf-8")

    except subprocess.TimeoutExpired:
        exit_code = 124  # Standard timeout exit code
        output_path.write_text(
            f"Command: {command_str}\n"
            f"Exit code: {exit_code}\n"
            "---\n"
            f"Command timed out after {timeout_seconds} seconds.\n",
            encoding="utf-8",
        )
        logger.warning("Command redirection timed out: %s", command_str)

    except FileNotFoundError as e:
        exit_code = 127  # Standard "command not found" exit code
        output_path.write_text(
            f"Command: {command_str}\n"
            f"Exit code: {exit_code}\n"
            "---\n"
            f"Command not found: {e}\n",
            encoding="utf-8",
        )
        logger.error("Command redirection failed — command not found: %s", command_str)

    except OSError as e:
        exit_code = 1
        output_path.write_text(
            f"Command: {command_str}\n"
            f"Exit code: {exit_code}\n"
            "---\n"
            f"Command execution failed: {type(e).__name__}: {e}\n",
            encoding="utf-8",
        )
        logger.error("Command redirection failed: %s — %s", command_str, e)

    return CommandRedirectionResult(
        exit_code=exit_code,
        output_path=output_path,
        command=command_str,
    )


def format_redirection_context(result: CommandRedirectionResult) -> list[str]:
    """Format redirection result as context lines for HookResult.

    These lines appear in additionalContext (system-reminder) so Claude
    sees both the educational deny message AND the command result.

    Args:
        result: The redirection execution result

    Returns:
        List of context strings for HookResult.context
    """
    return [
        "COMMAND REDIRECTED: Corrected command was executed automatically.",
        f"Exit code: {result.exit_code}",
        f"Output saved to: {result.output_path}",
        "Read the output file to get the result.",
    ]


def cleanup_old_files(output_dir: Path, max_age_seconds: int = _CLEANUP_MAX_AGE_SECONDS) -> None:
    """Remove output files older than max_age_seconds.

    Only removes .txt files (command output files) to avoid
    accidentally deleting other files in the directory.

    Args:
        output_dir: Directory containing output files
        max_age_seconds: Maximum file age in seconds before removal
    """
    if not output_dir.exists():
        return

    cutoff = time.time() - max_age_seconds
    for file_path in output_dir.iterdir():
        if file_path.suffix != ".txt":
            continue
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                logger.debug("Cleaned up old redirection output: %s", file_path.name)
        except FileNotFoundError:
            logger.debug("File already removed during cleanup: %s", file_path.name)
        except PermissionError:
            # Non-critical cleanup — one stuck file must not abort cleanup of others
            logger.debug("Permission denied removing old output: %s", file_path.name)

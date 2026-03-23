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
import threading
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

# Constant shell wrapper script for async (non-blocking) command execution.
# $0 = output file path, $@ = command + args.
# SECURITY: No interpolation — all values passed as positional arguments.
# The script appends command output and exit code to the output file.
_ASYNC_WRAPPER_SCRIPT: str = (
    '{ "$@"; } >> "$0" 2>&1; ' 'printf "\\n---\\nExit code: %d\\n" $? >> "$0"'
)


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
    pid: int | None = None

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


def _reap_background_process(proc: subprocess.Popen[bytes]) -> None:
    """Wait for background process to complete, preventing zombie accumulation.

    Called from a daemon thread — blocks until process exits, then reaps it.
    Without this, detached Popen processes become zombies when they exit
    because no one calls wait() on them.
    """
    try:
        proc.wait()
    except Exception:  # nosec B110 — reaper thread must not crash the daemon
        pass


def launch_and_save(
    command: list[str],
    output_dir: Path,
    label: str,
    cwd: Path | None = None,
) -> CommandRedirectionResult:
    """Launch a command in background and save output to a file.

    Unlike execute_and_save(), this returns IMMEDIATELY after spawning
    the process. The command runs detached (start_new_session=True) and
    a bash wrapper appends output + exit code to the file asynchronously.

    Use this for potentially slow commands (pytest, npm test, etc.) where
    synchronous execution would cause the hook to time out and fail open.

    Args:
        command: Command as list of args (e.g. ["pytest", "tests/"])
        output_dir: Directory to write output file into
        label: Handler label for filename (e.g. "pipe_blocker")
        cwd: Working directory for command execution. CRITICAL: the daemon
            process runs from "/" (daemonization calls os.chdir("/")), so
            commands with relative paths will fail without this parameter.
            Use ProjectContext.project_root() for project-relative commands.

    Returns:
        CommandRedirectionResult with pid set, exit_code=-1 (unknown),
        and output_path pointing to the file being written.

    SECURITY: B603/B607 — commands are handler-computed, not user input.
    The wrapper script is a constant; command args are passed positionally
    via $@ (never interpolated into the script string).
    """
    command_str = " ".join(command)

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old files on each execution
    cleanup_old_files(output_dir, max_age_seconds=_CLEANUP_MAX_AGE_SECONDS)

    # Generate unique filename with timestamp
    timestamp = int(time.time())
    output_path = output_dir / f"{label}_{timestamp}.txt"

    # Write header — bash wrapper will APPEND output after this
    output_path.write_text(
        f"Command: {command_str}\n" "---\n",
        encoding="utf-8",
    )

    try:
        # SECURITY: B603/B607 — _ASYNC_WRAPPER_SCRIPT is a constant string.
        # Command args passed as positional parameters ($@), never interpolated.
        # Output path passed as $0, also never interpolated into the script.
        # Only trusted system tools are invoked (pytest, npm, etc.).
        proc = subprocess.Popen(  # nosec B603 B607
            ["bash", "-c", _ASYNC_WRAPPER_SCRIPT, str(output_path)] + command,
            cwd=str(cwd) if cwd else None,
            start_new_session=True,  # Detach from parent process group
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = proc.pid

        # Spawn reaper thread to prevent zombie process accumulation.
        # Daemon thread — won't block daemon shutdown.
        reaper = threading.Thread(
            target=_reap_background_process,
            args=(proc,),
            daemon=True,
        )
        reaper.start()

    except FileNotFoundError:
        # bash not found (extremely unlikely on any real system)
        output_path.write_text(
            f"Command: {command_str}\n"
            "Exit code: 127\n"
            "---\n"
            "Failed to launch: bash not found\n",
            encoding="utf-8",
        )
        logger.error("launch_and_save failed — bash not found")
        return CommandRedirectionResult(
            exit_code=127,
            output_path=output_path,
            command=command_str,
        )

    except OSError as e:
        output_path.write_text(
            f"Command: {command_str}\n"
            "Exit code: 1\n"
            "---\n"
            f"Failed to launch: {type(e).__name__}: {e}\n",
            encoding="utf-8",
        )
        logger.error("launch_and_save failed: %s — %s", command_str, e)
        return CommandRedirectionResult(
            exit_code=1,
            output_path=output_path,
            command=command_str,
        )

    return CommandRedirectionResult(
        exit_code=-1,  # Unknown — process still running
        output_path=output_path,
        command=command_str,
        pid=pid,
    )


def format_redirection_context(result: CommandRedirectionResult) -> list[str]:
    """Format redirection result as context lines for HookResult.

    These lines appear in additionalContext (system-reminder) so Claude
    sees both the educational deny message AND the command result.

    For synchronous results (pid is None): shows exit code and file path.
    For async results (pid is set): shows PID, file path, and status check command.

    Args:
        result: The redirection execution result

    Returns:
        List of context strings for HookResult.context
    """
    if result.pid is not None:
        return [
            f"COMMAND REDIRECTED: Base command launched in background (PID {result.pid}).",
            f"Output file: {result.output_path}",
            f"DO NOT re-run the command. Let PID {result.pid} finish, then Read the output file.",
            f"Check status: kill -0 {result.pid} 2>/dev/null && echo running || echo done",
        ]
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

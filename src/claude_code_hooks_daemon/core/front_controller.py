"""Front controller for efficient hook dispatch (legacy compatibility).

This module provides the FrontController class for backward compatibility
with existing handler implementations. New code should use the HandlerChain
and EventRouter classes instead.
"""

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.router import inject_config_key_footer
from claude_code_hooks_daemon.core.utils import get_workspace_root
from claude_code_hooks_daemon.utils.retention import prune_directory
from claude_code_hooks_daemon.utils.secret_redaction import (
    get_active_secret_terms,
    redact_structure,
)

# hook-errors.log rotates to a timestamped backup when it exceeds this size.
_HOOK_ERROR_LOG_MAX_BYTES = 1_000_000
# Plan 00181: those rotation backups (hook-errors.log.<ts>) previously
# accumulated forever. Bound them by count and age after each rotation.
_HOOK_ERROR_LOG_BACKUP_GLOB = "hook-errors.log.*"
_HOOK_ERROR_LOG_MAX_BACKUPS = 5
_HOOK_ERROR_LOG_MAX_BACKUP_AGE_SECONDS = 14 * 86400


class FrontController:
    """Front controller that dispatches to handlers based on priority.

    This class maintains backward compatibility with the original handler
    interface that uses raw dict inputs. For new implementations, consider
    using HandlerChain and EventRouter instead.

    Implements efficient pattern-based dispatch to avoid spawning multiple processes.
    Supports both terminal (stop on match) and non-terminal (fall-through) handlers.
    """

    __slots__ = ("event_name", "handlers", "project_root")

    def __init__(self, event_name: str, project_root: Path | None = None) -> None:
        """Initialise front controller.

        Args:
            event_name: Hook event type (PreToolUse, PostToolUse, etc.)
            project_root: Project root to write hook-errors.log under, on a
                handler crash. Pass this explicitly for any controller built
                for a project root other than the real one the daemon source
                lives in (e.g. a test daemon rooted at a tmp directory) --
                otherwise a crash logs into the SOURCE TREE's own
                untracked/hook-errors.log via get_workspace_root()'s
                __file__-anchored fallback, regardless of this controller's
                intended project. Omit it to preserve that historical
                fallback for callers that never opted in.
        """
        self.event_name = event_name
        self.handlers: list[Handler] = []
        self.project_root = project_root

    def register(self, handler: Handler) -> None:
        """Register a handler instance.

        Args:
            handler: Handler to register
        """
        self.handlers.append(handler)
        # Keep handlers sorted by priority (lower = runs first)
        self.handlers.sort(key=lambda h: h.priority)

    def dispatch(self, hook_input: dict[str, Any]) -> HookResult:
        """Dispatch to matching handlers, supporting terminal and non-terminal execution.

        Terminal handlers (terminal=True):
            - Execute and STOP dispatch immediately
            - Return their result as-is

        Non-terminal handlers (terminal=False):
            - Execute but allow subsequent handlers to run
            - Accumulate their context into final result
            - Decision from non-terminal is ignored (always treated as "allow")

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult from last executed handler, or HookResult("allow") if no match.
            Catches any exceptions during handler execution and returns error details.
        """
        current_handler: Handler | None = None
        final_handler: Handler | None = None
        accumulated_context: list[str] = []
        handlers_matched: list[str] = []
        final_result: HookResult | None = None

        try:
            for handler in self.handlers:
                current_handler = handler

                if handler.matches(hook_input):
                    handlers_matched.append(handler.name)

                    result = handler.handle(hook_input)

                    # Track handler
                    result.add_handler(handler.name)

                    if handler.terminal:
                        # Terminal handler - stop dispatch and return result
                        # Merge accumulated context from non-terminal handlers
                        if accumulated_context:
                            result.context = accumulated_context + result.context

                        # Add all matched handlers
                        for h in handlers_matched[:-1]:
                            result.add_handler(h)

                        self._inject_config_key_footer(result, handler)
                        return result
                    else:
                        # Non-terminal handler - accumulate context and continue
                        accumulated_context.extend(result.context)
                        final_result = result
                        # Track the handler that PRODUCED final_result so the footer
                        # points at the correct config_key even if a later handler
                        # does not match (mirrors router.py handlers_executed[-1]).
                        final_handler = handler

            # No terminal handler matched - return last non-terminal result or default allow
            if final_result:
                # Merge accumulated context
                if accumulated_context:
                    final_result.context = accumulated_context
                self._inject_config_key_footer(final_result, final_handler)
                return final_result
            else:
                # No handlers matched at all
                return HookResult.allow()

        except Exception as e:
            # Handler crashed - log to file and return error details
            handler_name = current_handler.name if current_handler else "unknown"
            log_error_to_file(
                self.event_name, e, hook_input, handler_name, project_root=self.project_root
            )

            error_msg = f"Hook handler error in {handler_name}: {type(e).__name__}: {e}"

            # Return error as context (allows operation but shows error)
            return HookResult.error(
                error_type="handler_exception",
                error_details=error_msg,
                include_debug_info=True,
            )

    def _inject_config_key_footer(self, result: HookResult, handler: Handler | None) -> None:
        """Append config path footer to DENY/ASK results.

        Resolves the event config key from this controller's event_name and
        delegates the actual formatting/appending to the shared
        ``inject_config_key_footer`` helper (single source of truth shared with
        EventRouter), so the two cannot drift.

        Args:
            result: HookResult to potentially modify
            handler: Handler that produced the result (for config_key lookup)
        """
        # Convert event_name (e.g. "PreToolUse") to config key (e.g. "pre_tool_use")
        try:
            event_type = EventType.from_string(self.event_name)
            event_config_key = event_type.name.lower()
        except ValueError:
            # Unknown event type - skip injection rather than crash
            return

        inject_config_key_footer(result, event_config_key, handler)

    def run(self) -> None:
        """Main entry point - read stdin, dispatch, write output."""
        try:
            hook_input = json.load(sys.stdin)
        except json.JSONDecodeError:
            # Fail open if input invalid
            print("{}")
            sys.exit(0)

        # Dispatch to matching handler with error handling
        try:
            result = self.dispatch(hook_input)
        except Exception as e:
            # Handler crashed - log to file and return error details
            log_error_to_file(self.event_name, e, hook_input, project_root=self.project_root)

            error_msg = f"Hook handler error: {type(e).__name__}: {e}"
            stack_trace = traceback.format_exc()

            # Log full error to stderr for debugging
            print(f"\n{'=' * 60}", file=sys.stderr)
            print(f"HOOK ERROR in {self.event_name}", file=sys.stderr)
            print(f"{'=' * 60}", file=sys.stderr)
            print(stack_trace, file=sys.stderr)
            print(f"{'=' * 60}\n", file=sys.stderr)

            # Return error as context (allows operation but shows error)
            result = HookResult.error(
                error_type="handler_exception",
                error_details=error_msg,
            )

        # Output JSON
        stop_hook_active = bool(
            hook_input.get("stop_hook_active") or hook_input.get("stopHookActive")
        )
        output = result.to_json(
            self.event_name,
            stop_hook_active=stop_hook_active,
            terminal_columns=hook_input.get("terminal_columns"),
        )
        json.dump(output, sys.stdout)
        sys.exit(0)


def log_error_to_file(
    event_name: str,
    exception: Exception,
    hook_input: dict[str, Any],
    handler_name: str | None = None,
    project_root: Path | None = None,
) -> None:
    """Log hook errors to persistent file for debugging.

    Creates/appends to untracked/hook-errors.log with timestamped error entries.
    Rotates log if it exceeds 1MB to prevent bloat.

    Args:
        event_name: Hook event type (PreToolUse, PostToolUse, etc.)
        exception: The exception that was raised
        hook_input: The hook input dict that caused the error
        handler_name: Optional name of handler that crashed
        project_root: Project root to log under. When None, falls back to
            get_workspace_root() -- which is __file__-anchored to the daemon's
            OWN source tree, not to any particular caller's project. Pass this
            explicitly whenever the log must land under a project root other
            than the source tree itself (e.g. a test daemon rooted at a tmp
            directory), or it silently writes into the source tree's log
            instead.
    """
    try:
        workspace_root = project_root if project_root is not None else get_workspace_root()
        log_dir = workspace_root / "untracked"
        log_file = log_dir / "hook-errors.log"

        # Create untracked directory if needed
        log_dir.mkdir(exist_ok=True)

        # Rotate log if too large (>1MB)
        if log_file.exists() and log_file.stat().st_size > _HOOK_ERROR_LOG_MAX_BYTES:
            backup = log_dir / f"hook-errors.log.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            log_file.rename(backup)
            # Plan 00181: bound the accumulated rotation backups (previously they
            # grew forever, one per 1MB rollover).
            prune_directory(
                log_dir,
                pattern=_HOOK_ERROR_LOG_BACKUP_GLOB,
                max_count=_HOOK_ERROR_LOG_MAX_BACKUPS,
                max_age_seconds=_HOOK_ERROR_LOG_MAX_BACKUP_AGE_SECONDS,
                now=datetime.now().timestamp(),
            )

        # Format error entry
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80

        with log_file.open("a") as f:
            f.write(f"\n{separator}\n")
            f.write(f"HOOK ERROR - {timestamp}\n")
            f.write(f"{separator}\n")
            f.write(f"Event: {event_name}\n")
            if handler_name:
                f.write(f"Handler: {handler_name}\n")
            f.write(f"Exception: {type(exception).__name__}: {exception}\n")
            # Plan 00201: redacted BEFORE serialisation — a handler crashing
            # while processing a secret-laden payload must not leak that
            # secret into this persistent, gitignored-but-locally-readable log.
            secret_terms = get_active_secret_terms()
            logged_input = (
                redact_structure(hook_input, secret_terms) if secret_terms else hook_input
            )
            f.write(f"\nHook Input:\n{json.dumps(logged_input, indent=2)}\n")
            f.write("\nStack Trace:\n")
            f.write(traceback.format_exc())
            f.write(f"\n{separator}\n\n")

    except Exception as log_error:
        # If logging fails, write to stderr but don't crash
        print(f"WARNING: Failed to log error to file: {log_error}", file=sys.stderr)

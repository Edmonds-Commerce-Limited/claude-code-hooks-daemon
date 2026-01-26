"""Front controller for efficient hook dispatch (legacy compatibility).

This module provides the FrontController class for backward compatibility
with existing handler implementations. New code should use the HandlerChain
and EventRouter classes instead.
"""

import json
import sys
import traceback
from datetime import datetime
from typing import Any

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.utils import get_workspace_root


class FrontController:
    """Front controller that dispatches to handlers based on priority.

    This class maintains backward compatibility with the original handler
    interface that uses raw dict inputs. For new implementations, consider
    using HandlerChain and EventRouter instead.

    Implements efficient pattern-based dispatch to avoid spawning multiple processes.
    Supports both terminal (stop on match) and non-terminal (fall-through) handlers.
    """

    __slots__ = ("event_name", "handlers")

    def __init__(self, event_name: str) -> None:
        """Initialise front controller.

        Args:
            event_name: Hook event type (PreToolUse, PostToolUse, etc.)
        """
        self.event_name = event_name
        self.handlers: list[Handler] = []

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

                        return result
                    else:
                        # Non-terminal handler - accumulate context and continue
                        accumulated_context.extend(result.context)
                        final_result = result

            # No terminal handler matched - return last non-terminal result or default allow
            if final_result:
                # Merge accumulated context
                if accumulated_context:
                    final_result.context = accumulated_context
                return final_result
            else:
                # No handlers matched at all
                return HookResult.allow()

        except Exception as e:
            # Handler crashed - log to file and return error details
            handler_name = current_handler.name if current_handler else "unknown"
            log_error_to_file(self.event_name, e, hook_input, handler_name)

            error_msg = f"Hook handler error in {handler_name}: {type(e).__name__}: {e}"

            # Return error as context (allows operation but shows error)
            return HookResult.error(
                error_type="handler_exception",
                error_details=error_msg,
                include_debug_info=True,
            )

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
            log_error_to_file(self.event_name, e, hook_input)

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
        output = result.to_json(self.event_name)
        json.dump(output, sys.stdout)
        sys.exit(0)


def log_error_to_file(
    event_name: str,
    exception: Exception,
    hook_input: dict[str, Any],
    handler_name: str | None = None,
) -> None:
    """Log hook errors to persistent file for debugging.

    Creates/appends to untracked/hook-errors.log with timestamped error entries.
    Rotates log if it exceeds 1MB to prevent bloat.

    Args:
        event_name: Hook event type (PreToolUse, PostToolUse, etc.)
        exception: The exception that was raised
        hook_input: The hook input dict that caused the error
        handler_name: Optional name of handler that crashed
    """
    try:
        workspace_root = get_workspace_root()
        log_dir = workspace_root / "untracked"
        log_file = log_dir / "hook-errors.log"

        # Create untracked directory if needed
        log_dir.mkdir(exist_ok=True)

        # Rotate log if too large (>1MB)
        if log_file.exists() and log_file.stat().st_size > 1_000_000:
            backup = log_dir / f"hook-errors.log.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            log_file.rename(backup)

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
            f.write(f"\nHook Input:\n{json.dumps(hook_input, indent=2)}\n")
            f.write("\nStack Trace:\n")
            f.write(traceback.format_exc())
            f.write(f"\n{separator}\n\n")

    except Exception as log_error:
        # If logging fails, write to stderr but don't crash
        print(f"WARNING: Failed to log error to file: {log_error}", file=sys.stderr)

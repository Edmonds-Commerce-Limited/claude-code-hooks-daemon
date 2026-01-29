"""DaemonController for managing the hooks daemon lifecycle.

This module provides the DaemonController class that manages the
event router, handler registration, and request processing.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import HookEvent
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import DaemonConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DaemonStats:
    """Statistics for daemon operation.

    Attributes:
        start_time: When daemon started
        requests_processed: Total requests processed
        requests_by_event: Requests grouped by event type
        total_processing_time_ms: Cumulative processing time
        errors: Total errors encountered
        last_request_time: Time of last request
    """

    start_time: datetime = field(default_factory=datetime.now)
    requests_processed: int = 0
    requests_by_event: dict[str, int] = field(default_factory=dict)
    total_processing_time_ms: float = 0.0
    errors: int = 0
    last_request_time: datetime | None = None

    def record_request(self, event_type: str, processing_time_ms: float) -> None:
        """Record a processed request.

        Args:
            event_type: Event type that was processed
            processing_time_ms: Processing time in milliseconds
        """
        self.requests_processed += 1
        self.requests_by_event[event_type] = self.requests_by_event.get(event_type, 0) + 1
        self.total_processing_time_ms += processing_time_ms
        self.last_request_time = datetime.now()

    def record_error(self) -> None:
        """Record an error."""
        self.errors += 1

    @property
    def uptime_seconds(self) -> float:
        """Get daemon uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def avg_processing_time_ms(self) -> float:
        """Get average processing time in milliseconds."""
        if self.requests_processed == 0:
            return 0.0
        return self.total_processing_time_ms / self.requests_processed

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary.

        Returns:
            Dictionary representation of stats
        """
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": round(self.uptime_seconds, 2),
            "requests_processed": self.requests_processed,
            "requests_by_event": self.requests_by_event,
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "errors": self.errors,
            "last_request_time": (
                self.last_request_time.isoformat() if self.last_request_time else None
            ),
        }


class DaemonController:
    """Controller for the hooks daemon.

    Manages the event router, handler registration, and request processing.
    Provides a single entry point for processing hook events.
    """

    __slots__ = ("_config", "_initialised", "_registry", "_router", "_stats")

    def __init__(self, config: "DaemonConfig | None" = None) -> None:
        """Initialise daemon controller.

        Args:
            config: Optional daemon configuration
        """
        self._router = EventRouter()
        self._registry = HandlerRegistry()
        self._config = config
        self._stats = DaemonStats()
        self._initialised = False

    def initialise(
        self,
        handler_config: dict[str, dict[str, dict[str, Any]]] | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        """Initialise the controller with handlers.

        Discovers and registers all handlers with the event router.

        Args:
            handler_config: Optional handler configuration from hooks-daemon.yaml
            workspace_root: Optional workspace root path
        """
        if self._initialised:
            logger.warning("DaemonController already initialised")
            return

        logger.info("Initialising DaemonController")

        # Discover and register handlers
        self._registry.discover()
        count = self._registry.register_all(
            self._router, config=handler_config, workspace_root=workspace_root
        )

        logger.info("DaemonController initialised with %d handlers", count)
        self._initialised = True

    def process_event(self, event: HookEvent) -> ChainExecutionResult:
        """Process a hook event.

        Routes the event to the appropriate handler chain.

        Args:
            event: Hook event to process

        Returns:
            Chain execution result
        """
        if not self._initialised:
            self.initialise()

        start_time = time.perf_counter()
        try:
            # Convert HookInput to dict for handlers (use Python field names, not camelCase aliases)
            hook_input_dict = event.hook_input.model_dump(by_alias=False)
            result = self._router.route(event.event_type, hook_input_dict)
            processing_time = (time.perf_counter() - start_time) * 1000
            self._stats.record_request(event.event_type.value, processing_time)
            return result
        except Exception as e:
            processing_time = (time.perf_counter() - start_time) * 1000
            self._stats.record_request(event.event_type.value, processing_time)
            self._stats.record_error()
            logger.exception("Error processing event")

            # Return error result
            error_result = HookResult.error(
                error_type="internal_error",
                error_details=f"{type(e).__name__}: {e}",
            )
            return ChainExecutionResult(
                result=error_result,
                execution_time_ms=processing_time,
            )

    def process_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Process a raw request from the socket server.

        Parses the request, routes to handler chain, and formats response.

        Args:
            request_data: Raw request dictionary

        Returns:
            Response dictionary per PRD 3.2.2 format
        """
        try:
            event = HookEvent.model_validate(request_data)
        except Exception as e:
            logger.warning("Invalid request data: %s", e)
            error_result = HookResult.error(
                error_type="invalid_request",
                error_details=str(e),
            )
            return error_result.to_response_dict("Unknown", 0.0)

        result = self.process_event(event)

        return result.result.to_response_dict(
            event.event_type.value,
            result.execution_time_ms,
        )

    def get_stats(self) -> DaemonStats:
        """Get daemon statistics.

        Returns:
            Current daemon statistics
        """
        return self._stats

    def get_health(self) -> dict[str, Any]:
        """Get health check information.

        Returns:
            Health status dictionary
        """
        return {
            "status": "healthy",
            "initialised": self._initialised,
            "stats": self._stats.to_dict(),
            "handlers": self._router.get_handler_count(),
        }

    def get_handlers(self) -> dict[str, list[dict[str, Any]]]:
        """Get all registered handlers with details.

        Returns:
            Dictionary mapping event type to handler details
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for event_type, handlers in self._router.get_all_handlers().items():
            result[event_type] = [
                {
                    "name": h.name,
                    "class": h.__class__.__name__,
                    "priority": h.priority,
                    "terminal": h.terminal,
                }
                for h in handlers
            ]
        return result

    def get_router(self) -> EventRouter:
        """Get the event router.

        Returns:
            Event router instance
        """
        return self._router

    def get_registry(self) -> HandlerRegistry:
        """Get the handler registry.

        Returns:
            Handler registry instance
        """
        return self._registry

    @property
    def is_initialised(self) -> bool:
        """Check if controller is initialised."""
        return self._initialised


# Global controller instance
_controller: DaemonController | None = None


def get_controller() -> DaemonController:
    """Get the global daemon controller.

    Creates the controller on first access.

    Returns:
        Global DaemonController instance
    """
    global _controller
    if _controller is None:
        _controller = DaemonController()
    return _controller


def reset_controller() -> None:
    """Reset the global controller (for testing)."""
    global _controller
    _controller = None

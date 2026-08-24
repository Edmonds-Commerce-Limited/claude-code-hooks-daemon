"""Project handler loader for convention-based discovery.

This module provides the ProjectHandlerLoader class that discovers and loads
project-level handlers from a convention-based directory structure, mirroring
the built-in handler event-type subdirectories.

Directory structure:
    project-handlers/
        pre_tool_use/
            vendor_reminder.py
            test_vendor_reminder.py  (skipped)
            _helpers.py              (skipped)
        post_tool_use/
            build_checker.py
        session_start/
            branch_enforcer.py
"""

import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command, daemon_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectHandlerLoadFailure:
    """A single project handler that failed to load, with actionable detail.

    Captured at discovery time so the running daemon can persist and loudly
    surface protection regressions (Plan 00143) instead of dropping them into
    a log line nobody reads.

    Attributes:
        filename: The handler file's basename (e.g. ``vendor_reminder.py``).
        event_dir: The event-type subdirectory it was found in (e.g.
            ``pre_tool_use``) — tells the user which protection is now off.
        reason: Human-readable load-failure reason (the RuntimeError message),
            which for the v2.30.0 abstract-method class names the missing
            method and the version that introduced it.
    """

    filename: str
    event_dir: str
    reason: str


@dataclass(frozen=True)
class ProjectHandlerDiscovery:
    """Result of failure-aware project handler discovery.

    Attributes:
        handlers: Successfully loaded ``(EventType, Handler)`` pairs.
        failures: Structured records for every handler that failed to load.
    """

    handlers: list[tuple[EventType, Handler]] = field(default_factory=list)
    failures: list[ProjectHandlerLoadFailure] = field(default_factory=list)


# Maps abstract method names to the daemon version that made them abstract.
# Used to emit version-specific error messages when project handlers are found
# to be missing required methods after an upgrade.
_ABSTRACT_METHOD_VERSIONS: dict[str, str] = {
    "get_acceptance_tests": "2.5.0",
    "get_claude_md": "2.30.0",
}

# NOTE: `get_default_enabled()` was added to the Handler base in v3.24.0
# (Plan 00133) as a CONCRETE method (default True), deliberately NOT abstract —
# so it does not appear above. Project handlers need not implement it; they
# inherit the opt-out default and override only to declare themselves opt-in.


#: Path from the daemon root to the versioned upgrade-guide tree.
_UPGRADE_GUIDES_SUBPATH: tuple[str, ...] = ("CLAUDE", "UPGRADES")

#: Separator between a semver string's components.
_VERSION_SEPARATOR: str = "."


def _upgrade_guides_hint(missing: list[tuple[str, str]]) -> str:
    """Return an upgrade-guide path that resolves from the reader's cwd.

    The guides ship inside the daemon's own tree. In a CLIENT install that is
    ``.claude/hooks-daemon/CLAUDE/UPGRADES/``, NOT ``CLAUDE/UPGRADES/`` — a bare
    relative path sent readers to a directory their project does not have.

    The major-version subdirectory is derived from the version that introduced
    the missing method, so the hint stays correct as new abstract methods land
    in later majors rather than being pinned to ``v2/``.

    Args:
        missing: ``(method_name, introduced_version)`` pairs from
            :func:`_get_missing_abstract_method_versions`.

    Returns:
        An absolute path when :class:`ProjectContext` is initialised, else the
        client-install-relative path — never a bare ``CLAUDE/UPGRADES``, which
        is the spelling that misled readers.
    """
    base = daemon_path(*_UPGRADE_GUIDES_SUBPATH)
    majors = {version.split(_VERSION_SEPARATOR)[0] for _, version in missing if version}
    if len(majors) == 1:
        return f"{base}/v{majors.pop()}"
    return base


def _get_missing_abstract_method_versions(cls: type) -> list[tuple[str, str]]:
    """Return (method_name, introduced_version) for abstract methods not implemented in cls.

    Uses cls.__abstractmethods__ (a frozenset maintained by Python's ABCMeta)
    to find which methods are still abstract, then cross-references the version
    registry to produce actionable upgrade guidance.

    Args:
        cls: A class that may be abstract (Handler subclass with missing methods)

    Returns:
        List of (method_name, version_string) tuples for unimplemented methods
        that appear in _ABSTRACT_METHOD_VERSIONS. Empty list if all are implemented.
    """
    abstract_methods: frozenset[str] = getattr(cls, "__abstractmethods__", frozenset())
    return [
        (method_name, version)
        for method_name, version in _ABSTRACT_METHOD_VERSIONS.items()
        if method_name in abstract_methods
    ]


class ProjectHandlerLoader:
    """Load project-level handlers from convention-based directory structure.

    Discovers handlers by scanning event-type subdirectories (pre_tool_use/,
    post_tool_use/, etc.) and dynamically loading Python files that contain
    Handler subclasses.

    Files starting with '_' or 'test_' are skipped. Only concrete Handler
    subclasses are loaded.
    """

    @staticmethod
    def load_handler_from_file(file_path: Path) -> Handler:
        """Load a single handler from a Python file.

        Uses importlib.util.spec_from_file_location to dynamically load
        the module and find concrete Handler subclasses.

        Args:
            file_path: Absolute path to a Python file containing a Handler subclass

        Returns:
            Handler instance

        Raises:
            RuntimeError: If handler fails to load (import error, no concrete
                subclass found, multiple subclasses, or instantiation failure)
        """
        if not file_path.exists():
            raise RuntimeError(f"Project handler file not found: {file_path}")

        module_name = f"project_handler_{file_path.stem}_{id(file_path)}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Failed to create module spec for project handler: {file_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except RuntimeError:
            # Re-raise our own RuntimeErrors
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to import project handler {file_path.name}: {e}") from e

        # Find concrete Handler subclasses in the module
        handler_classes: list[type[Handler]] = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Handler)
                and attr is not Handler
                and not attr.__name__.startswith("_")
                and not inspect.isabstract(attr)
            ):
                handler_classes.append(attr)

        if len(handler_classes) > 1:
            class_names = [cls.__name__ for cls in handler_classes]
            raise RuntimeError(
                f"Multiple Handler subclasses found in {file_path.name}: {', '.join(class_names)}. "
                f"Each project handler file should contain exactly one Handler subclass."
            )

        if not handler_classes:
            # Before giving a generic error, check if there are abstract Handler
            # subclasses — this happens when an upgrade added a new abstract method
            # that the user's handler doesn't implement yet.
            # DEFINED here, not merely imported. A handler subclasses its
            # event's base, and that base is an abstract Handler subclass
            # sitting in the module namespace — without this check the error
            # below would tell the client their handler is missing `handle`,
            # `matches` and everything else, naming a daemon-internal class
            # they cannot edit instead of their own.
            abstract_handler_classes: list[type] = [
                getattr(module, attr_name)
                for attr_name in dir(module)
                if isinstance(getattr(module, attr_name, None), type)
                and issubclass(getattr(module, attr_name), Handler)
                and getattr(module, attr_name) is not Handler
                and not getattr(module, attr_name).__name__.startswith("_")
                and getattr(module, attr_name).__module__ == module.__name__
                and inspect.isabstract(getattr(module, attr_name))
            ]

            if abstract_handler_classes:
                missing: list[tuple[str, str]] = []
                for cls in abstract_handler_classes:
                    missing.extend(_get_missing_abstract_method_versions(cls))

                if missing:
                    method_list = ", ".join(
                        f"{name} (introduced in v{version})" for name, version in missing
                    )
                    class_names = [cls.__name__ for cls in abstract_handler_classes]
                    stubs = "\n".join(
                        f"    def {name}(self) -> ...:\n        ..." for name, _ in missing
                    )
                    raise RuntimeError(
                        f"Project handler {file_path.name} class(es) "
                        f"{', '.join(class_names)} are missing required method(s): "
                        f"{method_list}. "
                        f"Add the following stub(s) to fix:\n{stubs}\n"
                        f"See {_upgrade_guides_hint(missing)} for migration guides."
                    )

            raise RuntimeError(
                f"No Handler subclass found in project handler file: {file_path.name}. "
                f"File must contain a concrete Handler subclass."
            )

        handler_class = handler_classes[0]

        # Instantiate the handler
        try:
            handler = handler_class()
        except Exception as e:
            raise RuntimeError(
                f"Failed to instantiate project handler from {file_path.name}: {e}"
            ) from e

        # Validate priority is not None (Plan 00070: defence in depth)
        if handler.priority is None:
            logger.warning(
                "Project handler '%s' from %s has None priority — applying default (%d). "
                "Set an explicit priority in __init__().",
                handler.name,
                file_path.name,
                Priority.DEFAULT,
            )
            handler.priority = Priority.DEFAULT

        # Validate acceptance tests (warn but don't fail)
        try:
            acceptance_tests = handler.get_acceptance_tests()
            if not acceptance_tests:
                logger.warning(
                    "Project handler '%s' from %s does not define acceptance tests",
                    handler.name,
                    file_path.name,
                )
        except Exception as e:
            logger.warning(
                "Project handler '%s' from %s failed to return acceptance tests: %s",
                handler.name,
                file_path.name,
                e,
            )

        logger.info(
            "Loaded project handler '%s' from %s (priority=%d, terminal=%s)",
            handler.name,
            file_path.name,
            handler.priority,
            handler.terminal,
        )
        return handler

    @staticmethod
    def discover_handlers(
        project_handlers_path: Path,
    ) -> list[tuple[EventType, Handler]]:
        """Discover project handlers from convention-based directory structure.

        Backward-compatible thin wrapper over
        :meth:`discover_handlers_with_failures` that returns only the
        successfully loaded handlers. Existing callers that do not need the
        failure detail keep working unchanged.

        Args:
            project_handlers_path: Path to the project handlers root directory

        Returns:
            List of (EventType, Handler) tuples for successfully loaded handlers.
            Handlers that failed to load are omitted (warning logged for each).
        """
        return ProjectHandlerLoader.discover_handlers_with_failures(project_handlers_path).handlers

    @staticmethod
    def discover_handlers_with_failures(
        project_handlers_path: Path,
    ) -> ProjectHandlerDiscovery:
        """Discover project handlers, returning both successes AND failures.

        Scans event-type subdirectories (pre_tool_use/, post_tool_use/, etc.)
        for Python files containing Handler subclasses. Skips files starting
        with '_' or 'test_'.

        Broken handlers (import errors, missing abstract methods, instantiation
        failures) are skipped with a warning rather than crashing the daemon.
        This ensures an upstream upgrade that introduces a new abstract method
        does not prevent the daemon from starting — working handlers remain
        active while the broken ones are reported for the user to fix.

        Unlike :meth:`discover_handlers`, the failures are returned as
        structured :class:`ProjectHandlerLoadFailure` records (Plan 00143) so
        the daemon can persist them and surface a loud session-start alert
        rather than relying on a transient log line.

        Args:
            project_handlers_path: Path to the project handlers root directory

        Returns:
            A :class:`ProjectHandlerDiscovery` with the loaded handlers and the
            structured load failures.
        """
        if not project_handlers_path.exists() or not project_handlers_path.is_dir():
            logger.debug("Project handlers directory does not exist: %s", project_handlers_path)
            return ProjectHandlerDiscovery()

        results: list[tuple[EventType, Handler]] = []
        failures: list[ProjectHandlerLoadFailure] = []

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = project_handlers_path / dir_name
            if not event_dir.is_dir():
                continue

            for py_file in sorted(event_dir.glob("*.py")):
                # Skip files starting with '_' (includes __init__.py)
                if py_file.name.startswith("_"):
                    continue

                # Skip test files
                if py_file.name.startswith("test_"):
                    continue

                try:
                    handler = ProjectHandlerLoader.load_handler_from_file(py_file)
                    results.append((event_type, handler))
                except RuntimeError as e:
                    logger.warning(
                        "Skipping project handler %s: %s",
                        py_file.name,
                        e,
                    )
                    failures.append(
                        ProjectHandlerLoadFailure(
                            filename=py_file.name,
                            event_dir=dir_name,
                            reason=str(e),
                        )
                    )

        if failures:
            logger.warning(
                "%d project handler(s) failed to load and were skipped: %s. "
                "Daemon started with %d working project handler(s). "
                "Run: %s",
                len(failures),
                ", ".join(f.filename for f in failures),
                len(results),
                daemon_cli_command("validate-project-handlers"),
            )

        logger.info(
            "Discovered %d project handlers from %s",
            len(results),
            project_handlers_path,
        )
        return ProjectHandlerDiscovery(handlers=results, failures=failures)

"""This project's own project handlers must not collide on priority.

`DaemonController._load_project_handlers` warns — every single daemon start —
when a project handler's priority is already taken on that event, and then
registers it anyway. The warning is correct and the consequence is real: two
handlers at the same priority have an arbitrary relative order, so which of
two DENY reasons an agent sees is decided by registration order rather than by
design.

`plan_done_requires_holding_area` shipped at priority 20, which the safety
band already gives to `git_message_backtick` and `lock_file_edit_blocker`, so
the warning fired on every start and was routinely read as noise (Plan 00364
Task 5.2).

The check here reproduces the controller's own rule rather than restating a
number: library handlers are registered through `register_all()` — the same
entry point the live daemon uses — against THIS project's real config, then
each project handler is offered to the router in turn and asked whether its
priority is already present on that event. `DaemonController.initialise()` is
deliberately not used, for the reason `test_acceptance_contract.py` records:
it also rewrites the tracked `CLAUDE.md` as a side effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Real config, so every handler can be constructed and registered."""
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_repo_root() / ".claude" / "hooks-daemon.yaml")


def _router_with_library_handlers() -> EventRouter:
    config = Config.model_validate(
        ConfigLoader.load(_repo_root() / ".claude" / "hooks-daemon.yaml")
    )
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(
        router,
        config=_build_handler_config_mapping(config),
        workspace_root=_repo_root(),
        project_languages=config.daemon.languages,
        project_exclude_paths=config.daemon.exclude_paths,
        plan_workflow=config.plan_workflow,
        documentation=config.documentation,
    )
    return router


def _collisions() -> dict[str, tuple[int, list[str]]]:
    """``handler name -> (priority, the handlers already holding it)``."""
    router = _router_with_library_handlers()
    discovered = ProjectHandlerLoader.discover_handlers(
        _repo_root() / ".claude" / "project-handlers"
    )
    collisions: dict[str, tuple[int, list[str]]] = {}
    for event_type, handler in discovered:
        chain = router.get_chain(event_type)
        clashing = [h.name for h in chain.handlers if h.priority == handler.priority]
        if clashing:
            collisions[handler.name] = (handler.priority, clashing)
        # Register as the controller does, so a second project handler at the
        # same priority as the first is caught too.
        router.register(event_type, handler)
    return collisions


class TestNoProjectHandlerCollidesOnPriority:
    def test_the_project_handlers_were_discovered(self) -> None:
        """Vacuity guard: an empty discovery would pass the check below."""
        discovered = ProjectHandlerLoader.discover_handlers(
            _repo_root() / ".claude" / "project-handlers"
        )
        assert discovered, "no project handlers discovered — the check proves nothing"

    def test_none_of_them_takes_a_priority_already_in_use(self) -> None:
        collisions = _collisions()
        assert not collisions, (
            "a project handler shares its priority with an already-registered "
            "handler on the same event, so the daemon logs a collision warning "
            "on every start and their relative order is arbitrary: "
            + "; ".join(
                f"{name} (priority {priority}) clashes with {', '.join(clashing)}"
                for name, (priority, clashing) in sorted(collisions.items())
            )
        )

"""The coordinator's full QA gate survives orchestrator-only mode being ARMED.

Plan 00463 makes full QA the coordinator's gate: ``subagent_full_qa_blocker``
denies a sub-agent's full-suite run, so the main thread is the only role left
that can run it. Plan 00418's orchestrator-only mode restricts the main thread.
If that mode, once armed, denied the main thread's ``llm_qa.py all``, the two
would deadlock and nobody could run full QA.

A unit test of the orchestrator handler alone cannot rule that out, because a
deny can come from anywhere in the chain. So this drives the REAL PreToolUse
chain: every library handler registered through ``register_all()`` against
this project's real config (the entry point the live daemon uses), plus every
discovered project handler, with the orchestrator handler switched to blocking
the same way flipping ``BLOCKING_ENABLED`` would switch it.
``DaemonController.initialise()`` is not used, for the reason
``test_acceptance_contract.py`` records: it rewrites the tracked ``CLAUDE.md``.

Two controls make the ALLOW meaningful. The same chain DENIES a main-thread
``Edit``, which proves the mode really is armed. It also DENIES a sub-agent's
``llm_qa.py all``, which proves the full-QA guard really is live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, cast

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID
from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

_ORCHESTRATOR = "orchestrator-simulate"
_ORCHESTRATOR_RULE = "R-ORCHESTRATOR-MAIN-THREAD-WRITE"
_FULL_GATE = "./scripts/qa/llm_qa.py all"
_SESSION_ID = "00000000-0000-0000-0000-000000000000"
_SUBAGENT_ID = "aplan463-impl-84165102c3e9edf0"


class _ArmableHandler(Protocol):
    """The orchestrator handler's class: it takes a ``blocking`` override."""

    def __call__(self, *, blocking: bool) -> Handler: ...


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Real config, so every handler can be constructed and registered."""
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_repo_root() / ".claude" / "hooks-daemon.yaml")


@pytest.fixture(scope="module")
def armed_router() -> EventRouter:
    """The live PreToolUse chain, with orchestrator-only mode BLOCKING."""
    root = _repo_root()
    config = Config.model_validate(ConfigLoader.load(root / ".claude" / "hooks-daemon.yaml"))
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(
        router,
        config=_build_handler_config_mapping(config),
        workspace_root=root,
        project_languages=config.daemon.languages,
        project_exclude_paths=config.daemon.exclude_paths,
        plan_workflow=config.plan_workflow,
        documentation=config.documentation,
    )
    armed = False
    for event_type, handler in ProjectHandlerLoader.discover_handlers(
        root / ".claude" / "project-handlers"
    ):
        if handler.name == _ORCHESTRATOR:
            # The constructor's own override of BLOCKING_ENABLED, on the class
            # the loader actually loaded.
            handler = cast("_ArmableHandler", type(handler))(blocking=True)
            armed = True
        router.register(event_type, handler)
    assert armed, f"{_ORCHESTRATOR} was not discovered; this test would prove nothing"
    return router


def _event(tool_name: str, tool_input: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": _SESSION_ID,
        "cwd": str(_repo_root()),
        "tool_name": tool_name,
        "tool_input": tool_input,
        **extra,
    }


def _route(router: EventRouter, hook_input: dict[str, Any]) -> ChainExecutionResult:
    return router.route(EventType.PRE_TOOL_USE, hook_input, collect_all=True)


def _verdict(result: ChainExecutionResult, handler_name: str) -> Decision | None:
    for verdict in result.decisions:
        if verdict.handler == handler_name:
            return verdict.decision
    return None


class TestTheCoordinatorsFullGateUnderAnArmedOrchestrator:
    def test_the_main_threads_full_gate_is_allowed_by_the_whole_chain(
        self, armed_router: EventRouter
    ) -> None:
        result = _route(armed_router, _event("Bash", {"command": _FULL_GATE}))
        assert result.result.decision == Decision.ALLOW, result.result.reason
        assert _verdict(result, _ORCHESTRATOR) == Decision.ALLOW

    def test_the_orchestrator_does_not_record_the_full_gate_as_a_would_be_denial(
        self, armed_router: EventRouter
    ) -> None:
        result = _route(armed_router, _event("Bash", {"command": _FULL_GATE}))
        assert "would have been denied" not in " ".join(result.result.context)


class TestTheControlsProveTheChainIsArmed:
    def test_a_main_thread_edit_is_denied_by_the_orchestrator(
        self, armed_router: EventRouter
    ) -> None:
        target = str(_repo_root() / "README.md")
        result = _route(
            armed_router,
            _event("Edit", {"file_path": target, "old_string": "a", "new_string": "b"}),
        )
        assert _verdict(result, _ORCHESTRATOR) == Decision.DENY
        assert _ORCHESTRATOR_RULE in (result.result.reason or "")

    def test_a_subagents_full_gate_is_denied_by_the_full_qa_guard(
        self, armed_router: EventRouter
    ) -> None:
        result = _route(
            armed_router, _event("Bash", {"command": _FULL_GATE}, agent_id=_SUBAGENT_ID)
        )
        assert result.result.decision == Decision.DENY
        guard = HandlerID.SUBAGENT_FULL_QA_BLOCKER.display_name
        assert _verdict(result, guard) == Decision.DENY


class TestTheLiveDeclarationThroughTheRegistry:
    """Review finding 12: this repository's YAML, configured by the registry.

    A restated copy of the patterns stays green while the YAML the daemon
    loads drifts, so these go through ``register_all()`` on the real config.
    """

    _GUARD = HandlerID.SUBAGENT_FULL_QA_BLOCKER.display_name

    @pytest.mark.parametrize(
        "command",
        [_FULL_GATE, "pytest", "./scripts/qa/run_all.sh", "pytest --cov src"],
    )
    def test_a_subagents_full_run_is_denied(self, armed_router: EventRouter, command: str) -> None:
        result = _route(armed_router, _event("Bash", {"command": command}, agent_id=_SUBAGENT_ID))
        assert _verdict(result, self._GUARD) == Decision.DENY, command

    @pytest.mark.parametrize(
        "command",
        [
            "./scripts/qa/llm_qa.py changed",
            "./scripts/qa/llm_qa.py --read-only all",
            "pytest tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py",
        ],
    )
    def test_a_subagents_targeted_run_is_allowed(
        self, armed_router: EventRouter, command: str
    ) -> None:
        result = _route(armed_router, _event("Bash", {"command": command}, agent_id=_SUBAGENT_ID))
        assert _verdict(result, self._GUARD) is None, command

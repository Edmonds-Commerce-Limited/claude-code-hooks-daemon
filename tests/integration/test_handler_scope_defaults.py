"""Which handlers ship scoped to MAIN, and why each one (Plan 00423 Task 3.1).

The agreed split is "content guards ALL, nudge handlers MAIN". ALL is already
the default for everything, so the whole decision is the short list below — and
it is a SAFETY decision, because a wrong answer switches a guard off for a
class of session, and a handler that stops firing looks exactly like one with
nothing to report.

Each entry is justified individually rather than by category, because "nudge
handler" is a description and not a property the code can check:

- `auto-continue-stop` owns the goal-ledger nudge. This is issue #40's reported
  harm verbatim: a finished subagent told to continue every In Progress plan in
  the COORDINATOR's ledger, none of which was its assignment.
- `cron-stop-enforcer` verifies the session's declared crons and names the
  `CronCreate` to run. Session crons belong to the coordinator's session, and
  the incident behind #40 was a subagent DELETING one on its own initiative —
  so instructing a subagent to manage them is the same category of mistake.
- `teammate-reap-advisor` names the unreaped teammates a stop is waiting on.
  Only the coordinator has teammates.

One handler ships scoped to SUB, and it is the only one that gains anything
from it:

- `subagent-cron-delete-blocker` (Plan 00423 Task 3.2) denies `CronDelete`
  inside a subagent. `PreToolUse` fires for both roles, so SUB is doing real
  work here — it is the whole role test, which is why that handler never reads
  `agent_id` itself.

Everything else stays ALL, including the SubagentStop handlers. Scoping
`cron-subagent-stop-enforcer` to SUB would be true but redundant — its event
only ever fires for subagents — and a redundant restriction is a claim to
maintain for no behaviour gained. That is the line: SUB is for a handler on an
event BOTH roles reach.

An INTEGRATION test, not a unit one: the question is what the real registry
builds from this repository's real config, which is the only place a shipped
default is observable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler_scope import AGENT_ID_EVENTS, HandlerScope
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

#: The handlers that must SHIP scoped to MAIN. An exact set, so adding one is a
#: deliberate edit here with a justification above it.
_EXPECTED_MAIN: frozenset[str] = frozenset(
    {"auto-continue-stop", "cron-stop-enforcer", "teammate-reap-advisor"}
)

#: The handlers that must SHIP scoped to SUB. Exact, for the same reason.
_EXPECTED_SUB: frozenset[str] = frozenset({"subagent-cron-delete-blocker"})

_EXPECTED_SCOPED: frozenset[str] = _EXPECTED_MAIN | _EXPECTED_SUB


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Real config, so every handler can be constructed and registered."""
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_repo_root() / ".claude" / "hooks-daemon.yaml")


@pytest.fixture(scope="module")
def router() -> EventRouter:
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


def _registered(router: EventRouter) -> list[tuple[EventType, object]]:
    return [
        (event, handler)
        for event in EventType
        for handler in router.get_chain(event).handlers
    ]


class TestTheFixtureActuallyLoadsHandlers:
    """Guard the guard: an empty router would pass every assertion below."""

    def test_a_realistic_number_of_handlers_is_registered(self, router: EventRouter) -> None:
        assert len(_registered(router)) > 100

    def test_each_expected_scoped_handler_is_actually_registered(
        self, router: EventRouter
    ) -> None:
        names = {handler.name for _, handler in _registered(router)}
        assert _EXPECTED_SCOPED <= names, _EXPECTED_SCOPED - names


class TestTheShippedDefaults:
    def test_exactly_the_listed_handlers_are_scoped_to_main(self, router: EventRouter) -> None:
        actual = {h.name for _, h in _registered(router) if h.scope is HandlerScope.MAIN}
        assert actual == set(_EXPECTED_MAIN)

    def test_exactly_the_listed_handlers_are_scoped_to_sub(self, router: EventRouter) -> None:
        actual = {h.name for _, h in _registered(router) if h.scope is HandlerScope.SUB}
        assert actual == set(_EXPECTED_SUB)

    def test_every_other_handler_is_all(self, router: EventRouter) -> None:
        for _, handler in _registered(router):
            if handler.name in _EXPECTED_SCOPED:
                continue
            assert handler.scope is HandlerScope.ALL, handler.name


class TestNoScopeContradictsItsEvent:
    """A restricting scope on an event with no `agent_id` cannot mean anything.

    The config validator refuses an AUTHOR who writes one. This applies the
    same rule to what the library itself ships, which no config validator ever
    sees — a shipped default is not config.
    """

    def test_a_restricting_scope_only_appears_on_a_scopeable_event(
        self, router: EventRouter
    ) -> None:
        for event, handler in _registered(router):
            if handler.scope is HandlerScope.ALL:
                continue
            assert event.value in AGENT_ID_EVENTS, (
                f"{handler.name} is `{handler.scope}` on `{event.value}`, "
                "which never carries agent_id"
            )

"""End-to-end coverage gap fix (Plan 00290 dogfood field report, commit
9d353fd3 EMERGENCY suspension): the three stacked defects that broke the
relay dogfood live all shipped because no test ever drove a REALISTIC
per-event-socket payload — as Claude Code actually sends it, without
hand-adding fields the TRANSPORT is responsible for injecting — through a
real daemon instance with strict input validation on (this project's own
shipped default, ``.claude/hooks-daemon.yaml``: ``daemon.strict_mode: true``,
``input_validation.enabled: true``).

For every WIRED, RELAY-ELIGIBLE event this asserts a realistic payload gets a
valid, non-error verdict via the per-event socket path (EOF framing,
DESIGN-socket-relay.md §2) — the exact path the relay binary drives, minus
the relay binary itself (a Python socket client stands in for it, which is
sufficient: the relay is a pure byte pump and contributes no behaviour of
its own beyond moving bytes).

For every event EXCLUDED from relay eligibility (raw_stdout: StatusLine,
WorktreeCreate; requires_client_translation: Stop, SubagentStop) this
asserts the generated forwarder carries NO guard block at all — that
exclusion is covered by unit tests directly against
``generate_forwarder_content``
(``tests/unit/install/test_relay_guard_eligibility_completeness.py``), and is
re-asserted here so this suite is a complete cross-check on its own.

Payload shapes are drawn from the repo's REAL schemas:
- The 11 core events: the exact ``required`` fields (and const
  ``hook_event_name``) from ``core/input_schemas.py`` — the single source of
  truth the daemon itself validates against.
- StatusLine: deliberately OMITS ``hook_event_name`` — Claude Code's real
  status-line payload never carries it (CLAUDE/Architecture/StatusLine.md;
  the wrapper/daemon is responsible for injecting it, which is exactly
  defect 2). This is the one payload in this file that is intentionally NOT
  schema-complete on the wire, to prove the daemon's own enrichment step
  (``_handle_event_client``) closes the gap.
- Every Plan 00170 catalogued event (no bespoke schema — the daemon's own
  ``_permissive_input_schema`` requires only a matching ``hook_event_name``):
  the minimal conformant payload, which is the actual real schema surface
  those events have today.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    DaemonConfig,
    InputValidationConfig,
    LogLevel,
    TransportConfig,
)
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta, wired_event_metas
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
from claude_code_hooks_daemon.daemon.server import HooksDaemon
from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"

# ---------------------------------------------------------------------------
# Realistic minimal payloads, keyed by json_key (the wire event name family;
# StatusLine's wire value diverges — handled via EventID.STATUS_LINE below).
# ---------------------------------------------------------------------------

_CORE_SCHEMA_PAYLOADS: dict[str, dict[str, Any]] = {
    "PreToolUse": {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    },
    "PostToolUse": {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "tool_response": {"stdout": "hi\n", "stderr": ""},
    },
    "PermissionRequest": {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "permission_suggestions": [{"type": "once"}],
    },
    "Notification": {
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
    },
    "SessionStart": {
        "hook_event_name": "SessionStart",
        "session_id": "sess-e2e-001",
    },
    "SessionEnd": {
        "hook_event_name": "SessionEnd",
        "session_id": "sess-e2e-001",
    },
    "PreCompact": {
        "hook_event_name": "PreCompact",
    },
    "UserPromptSubmit": {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "hello",
    },
}


def _payload_for(meta: EventIDMeta) -> dict[str, Any]:
    """The realistic minimal payload for a relay-eligible wired event.

    StatusLine is the one deliberate exception (see module docstring): its
    real payload never carries ``hook_event_name``. Every other event either
    has a bespoke schema (core 11) or the daemon's own permissive schema
    (Plan 00170 catalogued events), and both cases genuinely carry
    ``hook_event_name`` on the wire — Claude Code sends it natively.
    """
    if meta is EventID.STATUS_LINE:
        return {
            "model": {"display_name": "Claude Sonnet 4.5", "id": "claude-sonnet-4-5-20250929"},
            "context_window": {"used_percentage": 25.0},
            "workspace": {"current_dir": str(_REPO_ROOT), "project_dir": str(_REPO_ROOT)},
        }
    if meta.json_key in _CORE_SCHEMA_PAYLOADS:
        return dict(_CORE_SCHEMA_PAYLOADS[meta.json_key])
    # Plan 00170 catalogued event: the daemon's own permissive schema
    # requires only a matching hook_event_name (core/input_schemas.py
    # _permissive_input_schema) — the minimal conformant payload IS the
    # real schema surface for these events today.
    return {"hook_event_name": meta.json_key}


_RELAY_ELIGIBLE_METAS = tuple(m for m in wired_event_metas() if m.relay_eligible)
_RELAY_INELIGIBLE_METAS = tuple(m for m in wired_event_metas() if not m.relay_eligible)


class _EchoHandler(Handler):
    """Records the last dispatched hook_input and always allows."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER, terminal=True
        )
        self.last_hook_input: dict[str, Any] | None = None

    def matches(self, hook_input: dict) -> bool:
        return True

    def handle(self, hook_input: dict) -> HookResult:
        self.last_hook_input = hook_input
        return HookResult(decision=Decision.ALLOW, context=["echoed"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        return []


@pytest.fixture
def isolated_untracked_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def echo_handler() -> _EchoHandler:
    return _EchoHandler()


@pytest.fixture
def front_controller(echo_handler: _EchoHandler) -> FrontController:
    controller = FrontController(event_name="PreToolUse")
    controller.register(echo_handler)
    return controller


def _make_strict_config(untracked_dir: Path) -> DaemonConfig:
    """Mirrors this project's own shipped strict-validation posture
    (`.claude/hooks-daemon.yaml`: `daemon.strict_mode: true`,
    `input_validation.enabled: true`) — the exact posture the live dogfood
    session ran under when this defect was found."""
    return DaemonConfig(
        socket_path=untracked_dir / "daemon.sock",
        pid_file_path=untracked_dir / "daemon.pid",
        idle_timeout_seconds=600,
        log_level=LogLevel.DEBUG,
        transport=TransportConfig(relay_enabled=True),
        strict_mode=True,
        input_validation=InputValidationConfig(enabled=True),
    )


async def _connect_and_send_eof(socket_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """EOF-delimited round trip — the exact framing the relay binary drives
    (DESIGN-socket-relay.md §2): write the raw payload, half-close, read to
    EOF. A plain Python socket client stands in for the relay binary itself,
    which is sufficient since the relay is a pure byte pump with no
    behaviour of its own beyond moving these exact bytes."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(payload).encode())
    writer.write_eof()
    await writer.drain()
    raw_response = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    return dict(json.loads(raw_response.decode()))


@pytest.fixture
async def running_daemon(
    isolated_untracked_dir: Path, front_controller: FrontController
) -> AsyncIterator[tuple[HooksDaemon, Path]]:
    config = _make_strict_config(isolated_untracked_dir)
    daemon = HooksDaemon(config=config, controller=front_controller)
    server_task = asyncio.create_task(daemon.start())
    await asyncio.sleep(0.1)
    yield daemon, isolated_untracked_dir
    await daemon.shutdown()
    await server_task


class TestRealisticPayloadsGetValidVerdicts:
    @pytest.mark.anyio
    @pytest.mark.parametrize("meta", _RELAY_ELIGIBLE_METAS, ids=lambda m: m.bash_key)
    async def test_relay_eligible_event_real_payload_gets_valid_verdict(
        self,
        running_daemon: tuple[HooksDaemon, Path],
        echo_handler: _EchoHandler,
        meta: EventIDMeta,
    ) -> None:
        _daemon, untracked_dir = running_daemon
        events_dir = get_event_socket_dir_from_untracked(untracked_dir)
        socket_path = events_dir / f"{meta.bash_key}.sock"
        assert socket_path.is_socket(), f"{meta.bash_key}: per-event socket not bound"

        payload = _payload_for(meta)
        response = await _connect_and_send_eof(socket_path, payload)

        assert response.get("error") != "input_validation_failed", (
            f"{meta.bash_key}: strict-mode validation rejected a realistic "
            f"payload: {response!r}"
        )
        assert (
            echo_handler.last_hook_input is not None
        ), f"{meta.bash_key}: handler never ran — request never dispatched"
        assert echo_handler.last_hook_input.get("hook_event_name") == meta.wire_key.value, (
            f"{meta.bash_key}: dispatched hook_input carries the wrong "
            f"hook_event_name: {echo_handler.last_hook_input!r}"
        )


class TestExcludedEventsCarryNoGuard:
    """Cross-check against tests/unit/install/test_relay_guard_eligibility_completeness.py:
    every relay-ineligible event's REAL deployed forwarder must never gain a
    guard block, at any config."""

    @pytest.mark.parametrize("meta", _RELAY_INELIGIBLE_METAS, ids=lambda m: m.bash_key)
    def test_real_deployed_forwarder_has_no_guard_when_relay_enabled(
        self, meta: EventIDMeta
    ) -> None:
        source_path = _HOOKS_DIR / meta.bash_key
        assert source_path.is_file(), f"{meta.bash_key}: no deployed forwarder found"
        source = source_path.read_text()
        transport = TransportConfig(relay_enabled=True)

        result = generate_forwarder_content(
            source, meta.bash_key, transport, Path("/proj/untracked")
        )

        assert "relay hot path" not in result, (
            f"{meta.bash_key} is relay-ineligible but the generated forwarder "
            "carries a relay guard block"
        )
        assert result == source


class TestHookEventNameEnrichmentAcrossEverySocket:
    """Defect 2 direct end-to-end reproduction (Plan 00290 field report): the
    daemon binds a per-event socket for EVERY wired event unconditionally,
    regardless of relay eligibility (DESIGN-socket-relay.md §1.1 — an unused
    listener costs nothing). This drives a payload with ``hook_event_name``
    stripped through every one of those real sockets and asserts the
    daemon's enrichment (``_handle_event_client``) restores it correctly —
    the live failure shape (``'hook_event_name' is a required property``)
    reproduced directly against the exact socket that hit it in production,
    not just the dedicated unit test."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("meta", wired_event_metas(), ids=lambda m: m.bash_key)
    async def test_payload_stripped_of_hook_event_name_is_enriched_on_every_socket(
        self,
        running_daemon: tuple[HooksDaemon, Path],
        echo_handler: _EchoHandler,
        meta: EventIDMeta,
    ) -> None:
        _daemon, untracked_dir = running_daemon
        events_dir = get_event_socket_dir_from_untracked(untracked_dir)
        socket_path = events_dir / f"{meta.bash_key}.sock"
        assert socket_path.is_socket(), f"{meta.bash_key}: per-event socket not bound"

        payload = _payload_for(meta)
        payload.pop("hook_event_name", None)

        response = await _connect_and_send_eof(socket_path, payload)

        assert response.get("error") != "input_validation_failed", (
            f"{meta.bash_key}: a payload missing hook_event_name was rejected "
            f"instead of enriched: {response!r}"
        )
        assert echo_handler.last_hook_input is not None
        assert echo_handler.last_hook_input.get("hook_event_name") == meta.wire_key.value

"""Every SAFETY pre_tool_use handler must stay near-linear on hostile input (Plan 00466 N25).

N25's Task 2 fixed ONE super-linear handler (``destructive_git``, via
``strip_inert_spans``) that the guard-defects security review 2 measured at
99s/98s on 200 KB inputs — see
``tests/unit/utils/test_shell_segmentation_performance.py``. Task 3 is the
harness that would have caught it generically: every handler tagged
``HandlerTag.SAFETY`` under ``pre_tool_use`` (the handlers a hostile,
adversarial CALLER can reach with a large ``Bash``/``Write`` payload) is
driven with several hostile input shapes — long runs of quotes, backslashes,
wildcards, and deep nesting — and timed.

Scope: ``pre_tool_use`` only. SAFETY handlers on other events (session_start,
stop, subagent_stop, pre_compact) do not process attacker-supplied bulk text
the same way — their inputs are daemon/session state, not a payload a client
chooses the size and shape of — so a hostile-input sweep does not apply to
them the way it does here.

Handlers are discovered via ``iter_builtin_handler_classes()`` (the same
enumeration ``register_all`` uses — Plan 00330), not a hardcoded list: a new
SAFETY handler is automatically swept without anyone remembering to add it
here.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.registry import iter_builtin_handler_classes

# Generous relative to a genuinely linear scan of ~100 KB (milliseconds), but
# far below what even a modestly quadratic handler would take on an input
# this size, and well below the 30s client socket timeout (Plan 00466 N25).
_MAX_SECONDS = 5.0

# Large enough to make an O(n^2) handler's blowup obvious (Task 2's repros
# hit 99s/98s at 200 KB); not so large that a genuinely linear handler's
# legitimate per-character work approaches the bound.
_HOSTILE_SIZE = 100_000

# Nesting is bounded well under it: depth here is levels, not characters, and
# unlike the other three shapes a naive recursive-descent matcher could raise
# ``RecursionError`` long before it would time out -- a real finding, but a
# different failure mode than the superlinearity this harness targets.
_NESTING_DEPTH = 5_000


def _many_quotes(size: int) -> str:
    """Many small quoted tokens -- the shape that actually caused Task 2's bug.

    A single giant quoted blob only stresses a handler's per-CHARACTER
    scanning; a per-MATCH quadratic bug (like the one Task 2 fixed) only
    shows up with many separate matches, so this repeats a short quoted
    token rather than emitting one long one.
    """
    return "'q' " * (size // 4)


def _many_backslashes(size: int) -> str:
    """Many small backslash-escaped tokens -- confuses naive escape tracking."""
    return "\\x " * (size // 3)


def _many_wildcards(size: int) -> str:
    """Many small glob tokens -- confuses naive glob/expansion scanning."""
    return "*.txt " * (size // 6)


def _deep_nesting(depth: int) -> str:
    """Deeply nested command substitution -- confuses naive depth tracking."""
    return "$(" * depth + "true" + ")" * depth


def _hostile_bash_command(shape: str) -> str:
    body = {
        "quotes": _many_quotes(_HOSTILE_SIZE),
        "backslashes": _many_backslashes(_HOSTILE_SIZE),
        "wildcards": _many_wildcards(_HOSTILE_SIZE),
        "nesting": _deep_nesting(_NESTING_DEPTH),
    }[shape]
    return f"git commit -m 'x' && echo {body}"


def _hostile_write_content(shape: str) -> str:
    body = {
        "quotes": _many_quotes(_HOSTILE_SIZE),
        "backslashes": _many_backslashes(_HOSTILE_SIZE),
        "wildcards": _many_wildcards(_HOSTILE_SIZE),
        "nesting": _deep_nesting(_NESTING_DEPTH),
    }[shape]
    return f"# hostile content\n{body}\n"


_SHAPES = ("quotes", "backslashes", "wildcards", "nesting")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so every SAFETY handler can be constructed.

    Mirrors ``tests/unit/test_rule_parity.py``: a handler that raises on
    construction without it would silently drop out of the sweep below,
    which would make this test pass on a smaller-than-real handler set
    without telling us.
    """
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _safety_pre_tool_use_handlers() -> list[type[Handler]]:
    """Every ``HandlerTag.SAFETY`` handler class registered for ``pre_tool_use``."""
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")
    classes: list[type[Handler]] = []
    for ref in iter_builtin_handler_classes():
        if ref.event_dir != "pre_tool_use":
            continue
        instance = ref.handler_cls()
        if HandlerTag.SAFETY in instance.tags:
            classes.append(ref.handler_cls)
    return classes


def _timed_dispatch(handler: Handler, hook_input: dict) -> float:
    """Time ``matches()`` (and ``handle()`` when it matches); return elapsed seconds."""
    start = time.perf_counter()
    if handler.matches(hook_input):
        handler.handle(hook_input)
    return time.perf_counter() - start


class TestNoVacuousDiscovery:
    """A discovery that finds nothing would make every sweep below pass by omission."""

    def test_discovers_at_least_the_known_safety_handlers(self) -> None:
        names = {cls.__name__ for cls in _safety_pre_tool_use_handlers()}
        # A floor, not an exhaustive list -- new SAFETY handlers are swept
        # automatically; this just guards against discovery going vacuous.
        assert len(names) >= 15, f"expected >=15 SAFETY pre_tool_use handlers, found: {names}"


class TestBashCommandShapesStayLinear:
    """Every SAFETY handler, driven with a hostile Bash ``command``."""

    @pytest.mark.parametrize("shape", _SHAPES)
    def test_every_safety_handler_stays_under_bound(self, shape: str) -> None:
        command = _hostile_bash_command(shape)
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        slow: list[str] = []
        for handler_cls in _safety_pre_tool_use_handlers():
            handler = handler_cls()
            elapsed = _timed_dispatch(handler, hook_input)
            if elapsed >= _MAX_SECONDS:
                slow.append(f"{handler_cls.__name__} took {elapsed:.2f}s on shape={shape!r}")
        assert not slow, "superlinear SAFETY handler(s) found:\n" + "\n".join(slow)


class TestWriteContentShapesStayLinear:
    """Every SAFETY handler, driven with hostile ``Write`` file content."""

    @pytest.mark.parametrize("shape", _SHAPES)
    def test_every_safety_handler_stays_under_bound(self, shape: str, tmp_path: Path) -> None:
        content = _hostile_write_content(shape)
        file_path = str(tmp_path / "hostile.md")
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }
        slow: list[str] = []
        for handler_cls in _safety_pre_tool_use_handlers():
            handler = handler_cls()
            elapsed = _timed_dispatch(handler, hook_input)
            if elapsed >= _MAX_SECONDS:
                slow.append(f"{handler_cls.__name__} took {elapsed:.2f}s on shape={shape!r}")
        assert not slow, "superlinear SAFETY handler(s) found:\n" + "\n".join(slow)

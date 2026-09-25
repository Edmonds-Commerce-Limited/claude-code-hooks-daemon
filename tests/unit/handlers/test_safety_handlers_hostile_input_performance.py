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

Plan 00466 N24 follow-up (guard-defects review 3): the large-scale (100 KB)
shapes above miss a DIFFERENT pathology — COMBINATORIAL blowup on a SHORT
input, where the state space grows with a repetition count or nesting depth
rather than with byte count. Review 3 measured `echo {a,b}` x20 (110 bytes)
at 36s on one guard. ``TestCombinatorialSmallInputShapesStayLinear`` below
covers that class: brace expansion, nested braces, ``/**/``/``**/*`` globs,
bracket classes, and deep ``eval``/``bash -c`` nesting, all under 300 bytes.

Scope: ``pre_tool_use`` only. SAFETY handlers on other events (session_start,
stop, subagent_stop, pre_compact) do not process attacker-supplied bulk text
the same way — their inputs are daemon/session state, not a payload a client
chooses the size and shape of — so a hostile-input sweep does not apply to
them the way it does here.

Handlers are discovered via ``iter_builtin_handler_classes()`` (the same
enumeration ``register_all`` uses — Plan 00330), not a hardcoded list: a new
SAFETY handler is automatically swept without anyone remembering to add it
here. The combinatorial-shape tests ALSO sweep this project's own
``.claude/project-handlers/`` (e.g. ``enforce_llm_qa``) best-effort, via the
same ``ProjectHandlerLoader`` the daemon itself uses — a project handler is
just as reachable by a hostile payload as a built-in one, and this repo's
own project handlers are real, in-scope code, not a fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, cpu_seconds, scaling_ratio

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.handlers.registry import (
    HandlerRegistry,
    iter_builtin_handler_classes,
)

# Generous relative to a genuinely linear scan of ~100 KB (milliseconds), but
# far below what even a modestly quadratic handler would take on an input
# this size, and well below the 30s client socket timeout (Plan 00466 N25).
# One bound for every handler: it is measured in the handler thread's own CPU
# time (see `_timed_dispatch`), so a loaded host does not inflate it.
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


def _dispatch(handler: Handler, hook_input: dict) -> None:
    """Run ``matches()``, and ``handle()`` when it matches."""
    if handler.matches(hook_input):
        handler.handle(hook_input)


def _timed_dispatch(handler: Handler, hook_input: dict) -> float:
    """CPU seconds this thread spends in :func:`_dispatch`.

    Thread CPU time, not wall clock: the review 2 gate saw
    ``SecretFileGuardHandler`` at 5.2s-10.9s wall on a host running other
    gates, when its own work was a fraction of that.
    """
    return cpu_seconds(lambda: _dispatch(handler, hook_input))


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


# ---------------------------------------------------------------------------
# Combinatorial small-input shapes (Plan 00466 N24 follow-up, guard-defects
# review 3). Distinct failure mode from the large-scale shapes above: state
# space grows with a repetition COUNT or nesting DEPTH, not with byte count,
# so these stay under 300 bytes on purpose -- a large size would not make a
# genuinely combinatorial bug any easier to find, only slower to run.
# ---------------------------------------------------------------------------

# Generous for a genuinely linear (or even mildly superlinear) scan of a
# <300 byte input, which is milliseconds; nowhere near review 3's 36s on a
# 110-byte payload. Tighter than `_MAX_SECONDS` because there is no
# legitimate reason ANY per-character cost should approach a whole second on
# input this short.
_SMALL_MAX_SECONDS = 2.0


def _brace_expansion_body(count: int) -> str:
    """Adjacent brace groups -- naive full cartesian expansion is ``2**count``.

    Review 3: ``echo {a,b}`` x20 (110 bytes) took 36s on a guard that
    expanded rather than merely scanning past the syntax.
    """
    return "{a,b}" * count


def _nested_braces_body(depth: int = 20) -> str:
    """Deeply NESTED (not adjacent) brace groups -- a different combinatorial shape."""
    return "{" * depth + "a" + "}" * depth


def _double_star_glob_body(count: int = 30) -> str:
    """Repeated ``/**/`` filesystem-walk tokens."""
    return "/**/" * count


def _star_star_slash_star_body(count: int = 30) -> str:
    """Repeated ``**/*`` recursive-glob tokens."""
    return "**/*" * count


def _bracket_classes_body(count: int = 40) -> str:
    """Repeated bracket character classes -- can feed a catastrophic regex."""
    return "[a-z]" * count


def _deep_bash_c_nesting_body(depth: int = 20) -> str:
    """Deeply nested ``bash -c '...'`` -- distinct from ``$(...)`` substitution nesting."""
    return "bash -c '" * depth + "true" + "'" * depth


def _deep_eval_nesting_body(depth: int = 20) -> str:
    """Repeated ``eval`` prefixes."""
    return "eval " * depth + "true"


#: Shape name -> the hostile BODY text (shared between the Bash-command and
#: Write-path variants below, so the two never drift apart).
_SMALL_COMBINATORIAL_BODIES: dict[str, str] = {
    "brace_x16": _brace_expansion_body(16),
    "brace_x20": _brace_expansion_body(20),
    "brace_x24": _brace_expansion_body(24),
    "nested_braces": _nested_braces_body(),
    "double_star_glob": _double_star_glob_body(),
    "star_star_slash_star": _star_star_slash_star_body(),
    "bracket_classes": _bracket_classes_body(),
    "deep_bash_c_nesting": _deep_bash_c_nesting_body(),
    "deep_eval_nesting": _deep_eval_nesting_body(),
}

#: Shape name -> command-head prefix needed for the body to parse as a
#: harmless Bash command. Empty for the two shapes whose body is ALREADY a
#: complete invocation (``bash -c '...'`` / ``eval ...``) -- prefixing those
#: with ``echo`` would stop them nesting at all.
_SMALL_COMMAND_PREFIX: dict[str, str] = {
    "brace_x16": "echo ",
    "brace_x20": "echo ",
    "brace_x24": "echo ",
    "nested_braces": "echo ",
    "double_star_glob": "ls ",
    "star_star_slash_star": "ls ",
    "bracket_classes": "echo ",
    "deep_bash_c_nesting": "",
    "deep_eval_nesting": "",
}

_SMALL_SHAPE_NAMES = tuple(sorted(_SMALL_COMBINATORIAL_BODIES))


def _hostile_small_bash_command(shape_name: str) -> str:
    return _SMALL_COMMAND_PREFIX[shape_name] + _SMALL_COMBINATORIAL_BODIES[shape_name]


def _hostile_small_write_path(shape_name: str, tmp_path: Path) -> str:
    return str(tmp_path / f"hostile-{_SMALL_COMBINATORIAL_BODIES[shape_name]}")


def _project_pre_tool_use_handlers() -> list[Handler]:
    """Every discoverable ``pre_tool_use`` project-level handler, best-effort.

    Team-lead ask: "Include project-handlers (enforce_llm_qa) if the harness
    can load them." Project handlers are auto-discovered from THIS
    repository's own ``.claude/project-handlers/`` (self-install/dogfood
    mode) via the same ``ProjectHandlerLoader`` the daemon itself uses at
    startup. A hostile payload reaches a project handler exactly as easily
    as a built-in one, so it belongs in the sweep -- but best-effort: a
    client checkout with no project handlers (or a discovery failure) just
    yields an empty list rather than failing the whole sweep. The built-in
    SAFETY set is this harness's real backbone regardless.
    """
    from claude_code_hooks_daemon.core.event import EventType
    from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader

    project_handlers_path = _project_root() / ".claude" / "project-handlers"
    if not project_handlers_path.is_dir():
        return []
    discovery = ProjectHandlerLoader.discover_handlers_with_failures(project_handlers_path)
    return [
        handler
        for event_type, handler in discovery.handlers
        if event_type == EventType.PRE_TOOL_USE
    ]


def _all_swept_handlers() -> list[Handler]:
    """Fresh built-in SAFETY instances plus best-effort project-level handlers."""
    instances: list[Handler] = [cls() for cls in _safety_pre_tool_use_handlers()]
    instances.extend(_project_pre_tool_use_handlers())
    return instances


# ---------------------------------------------------------------------------
# GIL-starvation sweep across EVERY PreToolUse handler (Plan 00466 N40
# review 2 MA2). The SAFETY-only sweep above missed two shipped handlers
# entirely -- `lsp_enforcement` and `plan_number_helper` are not
# SAFETY-tagged -- whose hand-written regexes were quadratic on exactly the
# whitespace-run and quote-run shapes below: 73.5s and 37.5s, holding the
# GIL for the handler's ENTIRE run so nothing else in the daemon process
# could run meanwhile (not the chain deadline's own timed wait, not the
# asyncio loop, not the straggler watchdog).
#
# Both were quadratic, and a call only holds the GIL for seconds on 100 KB
# when its cost grows faster than its input. So this sweep asserts on GROWTH:
# each handler's CPU cost at N and at 8N (`tests/scaling.py`), which neither
# host load nor a slow CI machine moves, where a wall-clock gap bound did.
# ---------------------------------------------------------------------------


def _whitespace_run_command(size: int) -> str:
    """A harmless command followed by a long run of newlines.

    The exact shape that froze `enforce-lsp-usage` for 73.5s: `_BASH_GREP_PATTERN`
    had a `\\s` alternative directly beside `\\s*`, both able to claim the same
    whitespace run.
    """
    return "true" + "\n" * size


def _quote_run_command(size: int) -> str:
    """An `echo` followed by a long run of single quotes.

    The exact shape that froze `plan-number-helper` for 37.5s: the argument
    gap `[ \\t]+` sat directly beside a negated class that also accepts
    space/tab.
    """
    return "echo " + "'" * size


#: Shape name -> hostile Bash command of a given run length. Kept separate
#: from `_SHAPES` above: those shapes are wrapped inside a larger command
#: (`git commit -m 'x' && echo <body>`), which would place the run
#: mid-command rather than at the exact position that triggered both real
#: regressions.
_GIL_STARVATION_SHAPES: dict[str, Callable[[int], str]] = {
    "whitespace_run": _whitespace_run_command,
    "quote_run": _quote_run_command,
}

# Large enough that either old quadratic regex already costs far more than
# its fixed overhead at N (so its ratio shows the full ~64x); the 8N run of a
# still-broken handler then takes seconds, not minutes.
_GIL_SHAPE_SIZE = 4_000


def _all_pre_tool_use_handlers() -> list[Handler]:
    """Every built-in ``pre_tool_use`` handler, SAFETY-tagged or not, CONFIGURED.

    Unlike ``_safety_pre_tool_use_handlers()``, this applies NO tag filter --
    the GIL-starvation class of defect is not specific to SAFETY handlers,
    and both regressions this sweep exists to catch (`lsp_enforcement`,
    `plan_number_helper`) carry the ``workflow``/``blocking`` tags instead.

    Configured, not default-constructed: `plan_number_helper` does nothing at
    all until `register_all()` injects the plan directory from the project's
    config, so a bare ``handler_cls()`` swept its quadratic regex vacuously.
    Each handler is built the way daemon startup builds it, from this
    project's own config (read-only -- a ``DaemonController`` would also
    regenerate ``CLAUDE.md``). A handler that config disables is still swept,
    default-constructed.
    """
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")
    config = Config.model_validate(
        ConfigLoader.load(_project_root() / ".claude" / "hooks-daemon.yaml")
    )
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(
        router,
        config=_build_handler_config_mapping(config),
        workspace_root=_project_root(),
        project_languages=config.daemon.languages,
        project_exclude_paths=config.daemon.exclude_paths,
        plan_workflow=config.plan_workflow,
        documentation=config.documentation,
    )
    handlers: list[Handler] = list(router.get_chain(EventType.PRE_TOOL_USE).handlers)
    configured = {type(handler) for handler in handlers}
    handlers.extend(
        ref.handler_cls()
        for ref in iter_builtin_handler_classes()
        if ref.event_dir == "pre_tool_use" and ref.handler_cls not in configured
    )
    return handlers


def _bash_input(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# 8x this is ~32 KB of path, deep enough that a quadratic per-segment cost
# dominates at N already, and shallow enough that sweeping every handler at
# 8N stays quick.
_DEEP_PATH_SEGMENTS = 1_000


def _deep_write_path(segments: int) -> str:
    """A ``src/`` file under the project root, ``segments`` directories deep:
    the shape of review 1's B2 ``file_path`` (90 KB at 22,500 segments)."""
    return str(_project_root() / ("src/" + "pkg/" * segments + "module.py"))


def _write_input(file_path: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": "x = 1\n"}}


class TestGilStarvationAcrossEveryPreToolUseHandler:
    """No PreToolUse handler's cost may grow superlinearly on the whitespace-run
    and quote-run shapes: that growth is what let one call hold the GIL for
    tens of seconds."""

    @pytest.mark.parametrize("shape_name", sorted(_GIL_STARVATION_SHAPES))
    def test_no_handler_grows_superlinearly(self, shape_name: str) -> None:
        build = _GIL_STARVATION_SHAPES[shape_name]
        large_text = build(SIZE_FACTOR * _GIL_SHAPE_SIZE)
        superlinear: list[str] = []
        for handler in _all_pre_tool_use_handlers():
            ratio = scaling_ratio(
                lambda size, h=handler: _dispatch(h, _bash_input(build(size))),
                _GIL_SHAPE_SIZE,
                large_text,
            )
            if ratio > SUPERLINEAR_RATIO:
                superlinear.append(
                    f"{type(handler).__name__} cost grew {ratio:.0f}x for "
                    f"{SIZE_FACTOR}x input on shape={shape_name!r}"
                )
        assert not superlinear, "superlinear PreToolUse handler(s) found:\n" + "\n".join(
            superlinear
        )

    def test_no_handler_grows_superlinearly_on_a_deep_write_path(self) -> None:
        """Review 2 nit 4: a 90 KB-deep Write ``file_path`` still took 9.4s.

        Most of it was `tdd_enforcement` building the mirrored test path one
        ``Path / segment`` at a time -- each step copies every segment before
        it, so quadratic in the depth.
        """
        segments = _DEEP_PATH_SEGMENTS
        large_path = _deep_write_path(SIZE_FACTOR * segments)
        superlinear: list[str] = []
        for handler in _all_pre_tool_use_handlers():
            ratio = scaling_ratio(
                lambda size, h=handler: _dispatch(h, _write_input(_deep_write_path(size))),
                segments,
                large_path,
            )
            if ratio > SUPERLINEAR_RATIO:
                superlinear.append(
                    f"{type(handler).__name__} cost grew {ratio:.0f}x for "
                    f"{SIZE_FACTOR}x path depth"
                )
        assert not superlinear, "superlinear PreToolUse handler(s) found:\n" + "\n".join(
            superlinear
        )

    def test_the_ratio_separates_linear_from_quadratic_work(self) -> None:
        """The measure itself: a linear scan stays under the threshold and a
        quadratic one clears it, on the same inputs the sweep uses."""
        build = _GIL_STARVATION_SHAPES["quote_run"]
        large_text = build(SIZE_FACTOR * _GIL_SHAPE_SIZE)

        def quadratic(size: int) -> None:
            text = build(size)
            for i in range(0, len(text), 8):
                text.count("'", i)

        linear = scaling_ratio(lambda size: build(size).count("'"), _GIL_SHAPE_SIZE, large_text)
        assert linear <= SUPERLINEAR_RATIO
        assert scaling_ratio(quadratic, _GIL_SHAPE_SIZE, large_text) > SUPERLINEAR_RATIO


class TestCombinatorialSmallInputShapesStayLinear:
    """Every swept handler, driven with SHORT combinatorial hostile shapes.

    Plan 00466 N24 follow-up (guard-defects review 3). Distinct from the
    classes above: the input here is always under 300 bytes, so ANY handler
    exceeding the bound is combinatorial (state space keyed by a repetition
    count or nesting depth), never a legitimately large-input cost.
    """

    @pytest.mark.parametrize("shape_name", _SMALL_SHAPE_NAMES)
    def test_bash_command(self, shape_name: str) -> None:
        command = _hostile_small_bash_command(shape_name)
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        slow: list[str] = []
        for handler in _all_swept_handlers():
            elapsed = _timed_dispatch(handler, hook_input)
            if elapsed >= _SMALL_MAX_SECONDS:
                slow.append(f"{handler.name} took {elapsed:.2f}s on shape={shape_name!r}")
        assert not slow, "combinatorial-blowup handler(s) found:\n" + "\n".join(slow)

    @pytest.mark.parametrize("shape_name", _SMALL_SHAPE_NAMES)
    def test_write_file_path(self, shape_name: str, tmp_path: Path) -> None:
        file_path = _hostile_small_write_path(shape_name, tmp_path)
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": "clean body\n"},
        }
        slow: list[str] = []
        for handler in _all_swept_handlers():
            elapsed = _timed_dispatch(handler, hook_input)
            if elapsed >= _SMALL_MAX_SECONDS:
                slow.append(f"{handler.name} took {elapsed:.2f}s on shape={shape_name!r}")
        assert not slow, "combinatorial-blowup handler(s) found:\n" + "\n".join(slow)

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

import logging
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, counted_ratio, scaling_ratio

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.handlers.registry import (
    HandlerRegistry,
    iter_builtin_handler_classes,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.path_predicates import (
    _reset_unreadable_warning_burst,
    path_exists,
)

# Large enough to make an O(n^2) handler's blowup obvious (Task 2's repros
# hit 99s/98s at 200 KB); not so large that a genuinely linear handler's
# legitimate per-character work approaches the bound.
_HOSTILE_SIZE = 100_000

# Nesting is bounded well under it: depth here is levels, not characters, and
# unlike the other three shapes a naive recursive-descent matcher could raise
# ``RecursionError`` long before it would time out -- a real finding, but a
# different failure mode than the superlinearity this harness targets.
_NESTING_DEPTH = 5_000

# A scan deadline no host is slow enough to cross: the sweep's subject is how a
# handler's cost grows, and a deadline that fires at one size and not the other
# would turn the same-path check into a measurement of host speed (N281).
_HOST_INDEPENDENT_DEADLINE_SECONDS = 120.0


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


#: Shape name -> body builder, called with a size (characters for the three
#: byte-count shapes, nesting depth for ``nesting``). Plan 00466 N24 review 3
#: mi4: kept as callables (not fixed-size strings) so every shape can be
#: driven at an arbitrary N -- required to measure GROWTH via
#: ``scaling_ratio`` instead of asserting an absolute CPU-time bound.
_SHAPE_BUILDERS: dict[str, Callable[[int], str]] = {
    "quotes": _many_quotes,
    "backslashes": _many_backslashes,
    "wildcards": _many_wildcards,
    "nesting": _deep_nesting,
}

#: Shape name -> the largest size this shape is driven at. Unchanged from the
#: sizes the old absolute-bound version used (``_HOSTILE_SIZE``/
#: ``_NESTING_DEPTH``), so the upper end of the sweep is exactly as
#: hostile as before; the small end for the ratio is derived from it
#: (``large // SIZE_FACTOR``), never larger.
_SHAPE_LARGE_SIZE: dict[str, int] = {
    "quotes": _HOSTILE_SIZE,
    "backslashes": _HOSTILE_SIZE,
    "wildcards": _HOSTILE_SIZE,
    "nesting": _NESTING_DEPTH,
}


def _hostile_bash_command_at(shape: str, size: int) -> str:
    body = _SHAPE_BUILDERS[shape](size)
    return f"git commit -m 'x' && echo {body}"


def _hostile_write_content_at(shape: str, size: int) -> str:
    body = _SHAPE_BUILDERS[shape](size)
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


@pytest.fixture(autouse=True)
def _host_independent_scan_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the secret guard's scan deadline out of the sweep (N281): crossing
    it is a fail-closed deny, which is the guard working, but whether a given
    size crosses depends on host speed. Cost growth is still measured by the
    ratio checks; the deadline's own verdict is pinned in
    ``TestSweepVerdictIsHostIndependent``."""
    monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", _HOST_INDEPENDENT_DEADLINE_SECONDS)


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


class _WarningRecorder(logging.Handler):
    """Notes whether anything was logged at WARNING or above."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.seen = False

    def emit(self, record: logging.LogRecord) -> None:
        self.seen = True


def _regime(handler: Handler, hook_input: dict) -> tuple[bool, str | None, bool]:
    """The path ``handler`` takes on ``hook_input``: whether it matched, what
    it decided, and whether it logged a warning or worse on the way (a cap it
    gave up at, a path the OS refused)."""
    # The unreadable-path warning is rate-limited per calling site, so whether
    # it fires depends on how many earlier calls used up the burst -- on call
    # order and on how many probes the checkout root length makes fail. Each
    # regime is measured from a fresh burst so it reflects only ``hook_input``.
    _reset_unreadable_warning_burst()
    recorder = _WarningRecorder()
    root = logging.getLogger()
    root.addHandler(recorder)
    try:
        matched = handler.matches(hook_input)
        decision = str(handler.handle(hook_input).decision) if matched else None
    finally:
        root.removeHandler(recorder)
    return matched, decision, recorder.seen


def _growth_finding(
    handler: Handler, input_at: Callable[[int], dict], small_n: int, large_text: str
) -> str | None:
    """Why ``handler`` fails the sweep between ``small_n`` and ``SIZE_FACTOR``
    times it, or ``None``.

    The two sizes must take the same path through the handler before their
    costs say anything about growth (00466 N252): an input under a cap
    against one past it compares two code paths, and the gate failed on
    exactly that.
    """
    large_n = SIZE_FACTOR * small_n
    small_regime = _regime(handler, input_at(small_n))
    large_regime = _regime(handler, input_at(large_n))
    if small_regime != large_regime:
        return (
            f"takes another path at {large_n} than at {small_n} "
            f"(matched, decision, logged a warning): {large_regime} vs {small_regime}"
        )
    ratio = scaling_ratio(lambda size: _dispatch(handler, input_at(size)), small_n, large_text)
    if ratio > SUPERLINEAR_RATIO:
        return f"cost grew {ratio:.0f}x for {SIZE_FACTOR}x input"
    return None


class TestNoVacuousDiscovery:
    """A discovery that finds nothing would make every sweep below pass by omission."""

    def test_discovers_at_least_the_known_safety_handlers(self) -> None:
        names = {cls.__name__ for cls in _safety_pre_tool_use_handlers()}
        # A floor, not an exhaustive list -- new SAFETY handlers are swept
        # automatically; this just guards against discovery going vacuous.
        assert len(names) >= 15, f"expected >=15 SAFETY pre_tool_use handlers, found: {names}"


class TestSweepVerdictIsHostIndependent:
    """Ledger 00474 N281: the sweep compares the path a handler takes at two
    sizes, and the secret guard's 5s scan deadline made that path depend on
    host speed. A wildcard command of 100,000 characters scans in about 1.7s
    on a development host, so a runner three times slower crossed the deadline
    and the guard (correctly, fail-closed) denied the large input while
    allowing the small one."""

    def test_sweep_runs_under_a_deadline_no_host_crosses(self) -> None:
        assert sfm.SCAN_DEADLINE_SECONDS >= _HOST_INDEPENDENT_DEADLINE_SECONDS

    @pytest.mark.parametrize("size", [12_500, 100_000])
    def test_an_expired_scan_deadline_denies_a_wildcard_command(
        self, size: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard's verdict when time runs out is a deny, at every size --
        never an allow -- so the divergence N281 saw is the sweep's, not a
        fail-open in the guard."""
        monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", -1.0)
        matched, decision, _warned = _regime(
            SecretFileGuardHandler(), _bash_input(_hostile_bash_command_at("wildcards", size))
        )
        assert matched is True
        assert decision == "deny"

    def test_the_could_not_finish_reason_names_the_scan_not_a_guard_bug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", -1.0)
        handler = SecretFileGuardHandler()
        result = handler.handle(_bash_input(_hostile_bash_command_at("wildcards", 12_500)))
        assert result.reason is not None
        assert RuleID.SECRET_SCAN_INCOMPLETE in result.reason
        assert RuleID.SECRET_EVALUATION_ERROR not in result.reason


class TestBashCommandShapesStayLinear:
    """Every SAFETY handler's cost, driven with a hostile Bash ``command``,
    may not grow superlinearly between size N and ``SIZE_FACTOR`` x N.

    Plan 00466 N24 review 3 mi4: replaces the old absolute-CPU-time bound
    (a handler that merely ran close to it on a loaded host would fail
    despite being linear) with the same growth-ratio measure
    ``TestGilStarvationAcrossEveryPreToolUseHandler`` already uses below.
    """

    @pytest.mark.parametrize("shape", _SHAPES)
    def test_every_safety_handler_stays_linear(self, shape: str) -> None:
        large_size = _SHAPE_LARGE_SIZE[shape]
        small_n = large_size // SIZE_FACTOR
        large_text = _hostile_bash_command_at(shape, large_size)
        superlinear: list[str] = []
        for handler_cls in _safety_pre_tool_use_handlers():

            def input_at(size: int, s: str = shape) -> dict:
                return _bash_input(_hostile_bash_command_at(s, size))

            finding = _growth_finding(handler_cls(), input_at, small_n, large_text)
            if finding is not None:
                superlinear.append(f"{handler_cls.__name__} {finding} on shape={shape!r}")
        assert not superlinear, "superlinear SAFETY handler(s) found:\n" + "\n".join(superlinear)


class TestWriteContentShapesStayLinear:
    """Every SAFETY handler's cost, driven with hostile ``Write`` file
    content, may not grow superlinearly between size N and
    ``SIZE_FACTOR`` x N (see ``TestBashCommandShapesStayLinear``)."""

    @pytest.mark.parametrize("shape", _SHAPES)
    def test_every_safety_handler_stays_linear(self, shape: str, tmp_path: Path) -> None:
        large_size = _SHAPE_LARGE_SIZE[shape]
        small_n = large_size // SIZE_FACTOR
        file_path = str(tmp_path / "hostile.md")
        large_text = _hostile_write_content_at(shape, large_size)
        superlinear: list[str] = []
        for handler_cls in _safety_pre_tool_use_handlers():

            def input_at(size: int, s: str = shape) -> dict:
                return {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": file_path,
                        "content": _hostile_write_content_at(s, size),
                    },
                }

            finding = _growth_finding(handler_cls(), input_at, small_n, large_text)
            if finding is not None:
                superlinear.append(f"{handler_cls.__name__} {finding} on shape={shape!r}")
        assert not superlinear, "superlinear SAFETY handler(s) found:\n" + "\n".join(superlinear)


# ---------------------------------------------------------------------------
# Combinatorial small-input shapes (Plan 00466 N24 follow-up, guard-defects
# review 3). Distinct failure mode from the large-scale shapes above: state
# space grows with a repetition COUNT or nesting DEPTH, not with byte count,
# so these stay under 300 bytes on purpose -- a large size would not make a
# genuinely combinatorial bug any easier to find, only slower to run.
# ---------------------------------------------------------------------------


def _brace_expansion_body(count: int) -> str:
    """Adjacent brace groups -- naive full cartesian expansion is ``2**count``.

    Review 3: ``echo {a,b}`` x20 (110 bytes) took 36s on a guard that
    expanded rather than merely scanning past the syntax.
    """
    return "{a,b}" * count


def _nested_braces_body(depth: int) -> str:
    """Deeply NESTED (not adjacent) brace groups -- a different combinatorial shape."""
    return "{" * depth + "a" + "}" * depth


def _double_star_glob_body(count: int) -> str:
    """Repeated ``/**/`` filesystem-walk tokens."""
    return "/**/" * count


def _star_star_slash_star_body(count: int) -> str:
    """Repeated ``**/*`` recursive-glob tokens."""
    return "**/*" * count


def _bracket_classes_body(count: int) -> str:
    """Repeated bracket character classes -- can feed a catastrophic regex."""
    return "[a-z]" * count


def _deep_bash_c_nesting_body(depth: int) -> str:
    """Deeply nested ``bash -c '...'`` -- distinct from ``$(...)`` substitution nesting."""
    return "bash -c '" * depth + "true" + "'" * depth


def _deep_eval_nesting_body(depth: int) -> str:
    """Repeated ``eval`` prefixes."""
    return "eval " * depth + "true"


def _letter_sequences_body(count: int) -> str:
    """Adjacent ``{a..p}`` sequence groups: ``16**count`` spellings."""
    return "{a..p}" * count


def _digit_sequences_body(count: int) -> str:
    """Adjacent ``{0..9}`` sequence groups: ``10**count`` spellings."""
    return "{0..9}" * count


#: Shape name -> (body builder, SMALL size). Each sweep drives the small size
#: and ``SIZE_FACTOR`` times it, and both must sit in ONE regime (00466 N252):
#: a small input under a cap against a large one past it compares two code
#: paths, not growth. That pairing is what failed the gate: 2 ``eval``s parse,
#: 16 exceed the nested-shell depth cap (4), and ``secret_file_guard`` answers
#: the cap with a logged traceback costing ten times its whole parse. So:
#:
#: - the sequence shapes start past the 256-spelling cap and stay under the
#:   64-group depth cap and the 255-byte file name limit; ``brace_pairs``
#:   cannot do that in an 8x span, so it starts past both;
#: - ``deep_eval_nesting`` starts past the nested-shell depth cap;
#: - the rest reach no cap at either size.
#:
#: ``_assert_one_regime`` checks each pairing handler by handler.
_SMALL_COMBINATORIAL_SHAPES: dict[str, tuple[Callable[[int], str], int]] = {
    "brace_pairs": (_brace_expansion_body, 65),
    "letter_sequences": (_letter_sequences_body, 3),
    "digit_sequences": (_digit_sequences_body, 3),
    "nested_braces": (_nested_braces_body, 2),
    "double_star_glob": (_double_star_glob_body, 3),
    "star_star_slash_star": (_star_star_slash_star_body, 3),
    "bracket_classes": (_bracket_classes_body, 5),
    "deep_bash_c_nesting": (_deep_bash_c_nesting_body, 2),
    "deep_eval_nesting": (_deep_eval_nesting_body, 5),
}

#: Shape name -> command-head prefix needed for the body to parse as a
#: harmless Bash command. Empty for the two shapes whose body is ALREADY a
#: complete invocation (``bash -c '...'`` / ``eval ...``) -- prefixing those
#: with ``echo`` would stop them nesting at all.
_SMALL_COMMAND_PREFIX: dict[str, str] = {
    "brace_pairs": "echo ",
    "letter_sequences": "echo ",
    "digit_sequences": "echo ",
    "nested_braces": "echo ",
    "double_star_glob": "ls ",
    "star_star_slash_star": "ls ",
    "bracket_classes": "echo ",
    "deep_bash_c_nesting": "",
    "deep_eval_nesting": "",
}

_SMALL_SHAPE_NAMES = tuple(sorted(_SMALL_COMBINATORIAL_SHAPES))


def _hostile_small_bash_command_at(shape_name: str, size: int) -> str:
    build, _small_size = _SMALL_COMBINATORIAL_SHAPES[shape_name]
    return _SMALL_COMMAND_PREFIX[shape_name] + build(size)


def _hostile_small_write_path_at(shape_name: str, size: int, tmp_path: Path) -> str:
    build, _small_size = _SMALL_COMBINATORIAL_SHAPES[shape_name]
    return str(tmp_path / f"hostile-{build(size)}")


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


# Past PATH_MAX already at N, so both sizes take one path through every
# handler: under it a ``stat`` of the path fails ENOENT, past it ENAMETOOLONG,
# and ``block-unread-overwrite`` allowed one and denied the other (00466
# N252). Deep enough that a quadratic per-segment cost dominates at N, and
# 8x (~33 KB) stays quick to sweep.
_DEEP_PATH_SEGMENTS = os.pathconf("/", "PC_PATH_MAX") // len("pkg/") + 1


#: File suffixes the deep-path sweep writes. Handlers dispatch on the suffix,
#: so each one reaches different code: a ``.py``-only sweep never reached
#: ``markdown_organization``'s per-ancestor plugin probe (Plan 00466 N106).
_DEEP_PATH_SUFFIXES = (".py", ".md", ".sh", ".ts", ".json")


def _deep_write_path(segments: int, suffix: str = ".py") -> str:
    """A ``src/`` file under the project root, ``segments`` directories deep:
    the shape of review 1's B2 ``file_path`` (90 KB at 22,500 segments)."""
    return str(_project_root() / ("src/" + "pkg/" * segments + "module" + suffix))


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
            finding = _growth_finding(
                handler, lambda size: _bash_input(build(size)), _GIL_SHAPE_SIZE, large_text
            )
            if finding is not None:
                superlinear.append(f"{type(handler).__name__} {finding} on shape={shape_name!r}")
        assert not superlinear, "superlinear PreToolUse handler(s) found:\n" + "\n".join(
            superlinear
        )

    @pytest.mark.parametrize("suffix", _DEEP_PATH_SUFFIXES)
    def test_no_handler_grows_superlinearly_on_a_deep_write_path(self, suffix: str) -> None:
        """Review 2 nit 4: a 90 KB-deep Write ``file_path`` still took 9.4s.

        Most of it was `tdd_enforcement` building the mirrored test path one
        ``Path / segment`` at a time -- each step copies every segment before
        it, so quadratic in the depth.
        """
        segments = _DEEP_PATH_SEGMENTS
        large_path = _deep_write_path(SIZE_FACTOR * segments, suffix)
        superlinear: list[str] = []
        for handler in _all_pre_tool_use_handlers():
            finding = _growth_finding(
                handler,
                lambda size: _write_input(_deep_write_path(size, suffix)),
                segments,
                large_path,
            )
            if finding is not None:
                superlinear.append(f"{type(handler).__name__} {finding} in path depth on {suffix}")
        assert not superlinear, "superlinear PreToolUse handler(s) found:\n" + "\n".join(
            superlinear
        )

    def test_the_ratio_separates_linear_from_quadratic_work(self) -> None:
        """The measure itself: a linear operation count stays under the
        threshold and a quadratic one clears it, on the same growth shape the
        sweep uses.

        Plan 00466 N24 review 3 MA5: this used to drive ``scaling_ratio``
        (elapsed CPU time) on a C-level ``str.count`` linear reference, whose
        cost sits close to the timing floor and so was sensitive to
        scheduler noise under a loaded gate -- flaky, not a hole in the
        ratio sweep itself (review 3 separately proved the sweep catches a
        REAL quadratic regression, ``probe_n24r3_red_ratio.out``). Using
        ``counted_ratio`` on an explicit operation count removes the clock
        from this self-test entirely, so it is deterministic on any host.
        """
        build = _GIL_STARVATION_SHAPES["quote_run"]

        def linear_ops(size: int) -> int:
            return len(build(size))  # one comparison per character

        def quadratic_ops(size: int) -> int:
            n = len(build(size))
            return sum(n - i for i in range(0, n, 8))  # each scan-start rescans the rest

        linear = counted_ratio(linear_ops, _GIL_SHAPE_SIZE)
        assert linear <= SUPERLINEAR_RATIO
        assert counted_ratio(quadratic_ops, _GIL_SHAPE_SIZE) > SUPERLINEAR_RATIO

    def test_sizes_on_either_side_of_a_cap_are_rejected_before_timing(self) -> None:
        """The pairing that failed the gate (00466 N252): 2 ``eval``s parse,
        16 exceed the nested-shell depth cap, and the guard answers the cap
        with a logged deny. The sweep must name that, not time it."""
        guard = SecretFileGuardHandler()

        def input_at(size: int) -> dict:
            return _bash_input(_deep_eval_nesting_body(size))

        finding = _growth_finding(guard, input_at, 2, _deep_eval_nesting_body(16))
        assert finding is not None
        assert finding.startswith("takes another path at 16 than at 2")


class TestRegimeIsIndependentOfEarlierWarnings:
    """The warning component of a regime must not depend on call order."""

    def test_a_rate_limited_warning_is_still_seen_after_an_earlier_burst(self) -> None:
        unreadable = "x" * (os.pathconf("/", "PC_NAME_MAX") + 1)

        class _Prober(Handler):
            def __init__(self) -> None:
                super().__init__(
                    handler_id=HandlerID.DESTRUCTIVE_GIT,
                    priority=Priority.DESTRUCTIVE_GIT,
                )

            def matches(self, hook_input: dict) -> bool:
                return True

            def handle(self, hook_input: dict) -> HookResult:
                for _ in range(20):
                    path_exists(unreadable, unreadable_means=False)
                return HookResult(decision=Decision.ALLOW)

            def get_claude_md(self) -> str | None:
                return None

            def get_acceptance_tests(self) -> list[AcceptanceTest]:
                return []

        handler = _Prober()
        first = _regime(handler, {})
        second = _regime(handler, {})
        assert first == second == (True, "allow", True)


class TestCombinatorialSmallInputShapesStayLinear:
    """Every swept handler, driven with SHORT combinatorial hostile shapes.

    Plan 00466 N24 follow-up (guard-defects review 3). Distinct from the
    classes above: every input is a few hundred bytes to a few KB, so growth
    here is ONLY explained by the repetition count or nesting depth, never a
    legitimately large-input cost.

    Plan 00466 N24 review 3 mi4: growth-ratio measure (N vs ``SIZE_FACTOR``
    x N), like ``TestBashCommandShapesStayLinear`` above, instead of an
    absolute CPU-time bound, with both sizes in one regime (see
    ``_SMALL_COMBINATORIAL_SHAPES``).
    """

    @pytest.mark.parametrize("shape_name", _SMALL_SHAPE_NAMES)
    def test_bash_command(self, shape_name: str) -> None:
        _build, small_n = _SMALL_COMBINATORIAL_SHAPES[shape_name]
        large_text = _hostile_small_bash_command_at(shape_name, SIZE_FACTOR * small_n)
        superlinear: list[str] = []
        for handler in _all_swept_handlers():
            finding = _growth_finding(
                handler,
                lambda size: _bash_input(_hostile_small_bash_command_at(shape_name, size)),
                small_n,
                large_text,
            )
            if finding is not None:
                superlinear.append(f"{handler.name} {finding} on shape={shape_name!r}")
        assert not superlinear, "combinatorial-blowup handler(s) found:\n" + "\n".join(superlinear)

    @pytest.mark.parametrize("shape_name", _SMALL_SHAPE_NAMES)
    def test_write_file_path(self, shape_name: str, tmp_path: Path) -> None:
        _build, small_n = _SMALL_COMBINATORIAL_SHAPES[shape_name]
        large_path = _hostile_small_write_path_at(shape_name, SIZE_FACTOR * small_n, tmp_path)
        superlinear: list[str] = []
        for handler in _all_swept_handlers():
            finding = _growth_finding(
                handler,
                lambda size: {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": _hostile_small_write_path_at(shape_name, size, tmp_path),
                        "content": "clean body\n",
                    },
                },
                small_n,
                large_path,
            )
            if finding is not None:
                superlinear.append(f"{handler.name} {finding} on shape={shape_name!r}")
        assert not superlinear, "combinatorial-blowup handler(s) found:\n" + "\n".join(superlinear)

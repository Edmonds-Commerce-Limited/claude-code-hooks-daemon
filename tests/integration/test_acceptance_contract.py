"""CI-time contract test for `get_acceptance_tests()` (Plan 00319 Task 4.6).

A static check was tried during the v3.60.0 release and rejected: matching a
declared pattern against handler SOURCE produced 87 candidates that were
overwhelmingly false positives, because the deny text a handler actually
emits is assembled at runtime (`Rule` fields, the `RuleFormatter` header,
handler-appended literals) -- none of which a source-text regex can see. The
only reliable oracle is EXECUTING the handler, which is exactly what the
release acceptance gate already does in `tests/acceptance/test_playbook_
harness.py` -- but only against a LIVE daemon, so only during a release, and
only for the tests that happen to declare a `tool_payload`. Four handlers
(`quarantine_artefact_read_guard`, `sensitive_content`, `sed_blocker`,
`write_clobber_guard`) shipped stale patterns anyway, each found one at a
time, each costing a FAIL-FAST cycle.

This file closes both gaps at once, IN-PROCESS (no live daemon, no socket):

1. **Coverage** (``test_every_blocking_test_declares_a_way_to_drive_it``):
   every BLOCKING acceptance test must declare `tool_payload`, `hook_input`
   or `harness_cannot_produce` -- there is no fourth option, and the
   assertion is unconditional (no ratchet allowlist). Plan 00319 Task 4.6
   closed the only two tests that were missing one
   (`SubagentReportSizeBlockerHandler`, via the new `hook_input` field --
   `tool_payload` cannot describe a `SubagentStop`, which carries no tool
   call at all).

2. **Contract** (``test_every_blocking_test_with_a_declared_input_produces_
   its_declared_verdict``): for every test that DOES declare an input, drive
   the REAL handler instance with it and assert the decision AND every
   declared pattern match what the handler really produces.

Both need a FULLY instantiated, FULLY CONFIGURED production handler set --
several acceptance payloads produce their declared verdict only against a
handler's CONFIGURED state (`sensitive_content`'s `public_patterns`,
`flaggable_content_channel_guard`'s glob, `plan_number_helper`'s
`plan_workflow` directory), not its bare dataclass default. Library handlers
are therefore registered through `HandlerRegistry.register_all()` -- the
SAME entry point the live daemon uses at startup -- driven by THIS project's
real `.claude/hooks-daemon.yaml`, plus the project's own
`.claude/project-handlers/` handlers.

`DaemonController.initialise()` is deliberately NOT used here even though it
wraps `register_all()`: it also runs the ClaudeMdInjector, which rewrites the
tracked project `CLAUDE.md` as a side effect of "starting the daemon" --
exactly wrong for a test run, which must never mutate tracked source.

The contract half also replicates the SAME fixture discipline
`tests/acceptance/test_playbook_harness.py` already established: a
PostToolUse event claims a tool call ALREADY HAPPENED, so a Write/Edit
target must exist on disk with the post-write content BEFORE dispatch (or
`lint_on_edit._is_lintable`'s `Path(file_path).exists()` never sees it), and
a declared `setup_commands`/`cleanup_commands` pair is translated to a plain
filesystem operation via the SAME `vet_probe_commands` used there -- never a
shell, and bounded to `untracked/scratch/`.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.daemon.playbook_harness import (
    ExecutableProbe,
    FixtureAction,
    SkippedProbe,
    plan_probe,
)
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

logger = logging.getLogger(__name__)

#: Where a fixture action is allowed to act, relative to the checkout --
#: the same bound `tests/acceptance/test_playbook_harness.py` applies.
_PROBE_SCRATCH = ("untracked", "scratch")


def _repo_root() -> Path:
    """Project root, derived from this file's location (not hardcoded)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext against the REAL repo so every handler can

    be constructed and every payload's repo-relative path resolves. A
    handler that raises on construction would silently drop out of
    discovery, which is precisely the escape this file exists to prevent.
    """
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_repo_root() / ".claude" / "hooks-daemon.yaml")


def _real_config() -> Config:
    """This project's OWN validated configuration -- read-only, no side

    effects (unlike building a `DaemonController`, which also regenerates
    `CLAUDE.md`).
    """
    config_path = _repo_root() / ".claude" / "hooks-daemon.yaml"
    config_dict = ConfigLoader.load(config_path)
    return Config.model_validate(config_dict)


def _project_handler_instances() -> dict[str, Any]:
    project_handlers_path = _repo_root() / ".claude" / "project-handlers"
    return {
        handler.__class__.__name__: handler
        for _event_type, handler in ProjectHandlerLoader.discover_handlers(project_handlers_path)
    }


def _collect_all_blocking_tests() -> list[dict[str, Any]]:
    """Every BLOCKING acceptance test declared by the REAL production handler

    set. Mirrors what `hooks-daemon generate-playbook` assembles (library +
    project handlers). `include_disabled=True` so a handler disabled by
    default in the shipped config template still has to satisfy the
    requirement -- same rationale as
    `test_acceptance_negative_case_requirement.py`. CLI-feature entries carry
    no `handler_name`/`test_type` in the BLOCKING sense used here and are
    excluded by the `source != "cli"` filter.
    """
    registry = HandlerRegistry()
    registry.discover()
    project_handlers = list(_project_handler_instances().values())
    generator = PlaybookGenerator(config={}, registry=registry, project_handlers=project_handlers)
    tests = generator.generate_json(include_disabled=True)
    return [t for t in tests if t.get("test_type") == "blocking" and t.get("source") != "cli"]


def _handler_instances() -> dict[tuple[str, str], Any]:
    """``(source, handler_name) -> a REAL, config-injected handler instance``.

    Library handlers are registered through `register_all()` -- see the
    module docstring for why `DaemonController.initialise()` is not used.
    One instance per handler class, shared across that handler's own
    multiple acceptance tests -- the same sharing a real router gives a
    handler across events in a live session, so state genuinely leaking
    between two of a handler's own tests here is a real defect (the exact
    shape Finding F10 fixed), not a test artefact to paper over.
    """
    instances: dict[tuple[str, str], Any] = {}
    config = _real_config()
    handler_config = _build_handler_config_mapping(config)

    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(
        router,
        config=handler_config,
        workspace_root=_repo_root(),
        project_languages=config.daemon.languages,
        project_exclude_paths=config.daemon.exclude_paths,
        plan_workflow=config.plan_workflow,
        documentation=config.documentation,
    )
    for event_type in EventType:
        for handler in router.get_chain(event_type).handlers:
            instances[("library", handler.__class__.__name__)] = handler

    # A handler DISABLED in this project's real config never reaches the
    # router above, but its acceptance tests still need SOME instance to
    # drive -- fall back to a bare one, matching PlaybookGenerator's own
    # `include_disabled=True` posture. Logged, not silently dropped: the
    # caller reports "no live handler instance found" for anything that
    # still comes up missing.
    for name in registry.list_handlers():
        key = ("library", name)
        if key in instances:
            continue
        handler_class = registry.get_handler_class(name)
        if handler_class is None:
            continue
        try:
            instances[key] = handler_class()
        except Exception:
            logger.warning("Could not construct handler %s for the contract test", name)

    for name, handler in _project_handler_instances().items():
        instances[("project", name)] = handler
    return instances


def _identifier(test: dict[str, Any]) -> str:
    """``source:event_type/handler_name::title`` -- mirrors the key shape

    `find_deny_capable_handlers_without_allow_case` already uses, for a
    reader's mental model, extended with the test title since multiple
    tests share one handler here.
    """
    return f"{test['source']}:{test['event_type']}/{test['handler_name']}::{test['title']}"


def _is_removable_probe_target(target: Path) -> bool:
    """Only ever touch a path this probe is entitled to own.

    Mirrors `tests/acceptance/test_playbook_harness.py`'s same-named guard:
    bounded to gitignored scratch inside the repo and the system temp
    directory, never trusted to the playbook's own declared path.
    """
    scratch = _repo_root().joinpath(*_PROBE_SCRATCH)
    temp_root = Path(tempfile.gettempdir())
    return target.is_relative_to(scratch) or target.is_relative_to(temp_root)


def _perform_fixture_actions(actions: list[FixtureAction]) -> None:
    """Establish (or clear) a probe's fixtures as plain filesystem calls.

    No shell. `vet_probe_commands` (inside `plan_probe`) has already
    translated each declared setup/cleanup command into one of three
    operations and proved its path resolves inside `untracked/scratch/`.
    Mirrors `tests/acceptance/test_playbook_harness.py`'s `_perform`.
    """
    for action in actions:
        if not _is_removable_probe_target(action.path):
            raise AssertionError(f"vetting let through an out-of-bounds path: {action.path}")
        if action.kind == "mkdir":
            action.path.mkdir(parents=True, exist_ok=True)
        elif action.kind == "remove":
            if action.path.is_dir():
                shutil.rmtree(action.path, ignore_errors=True)
            elif action.path.exists():
                action.path.unlink()
        elif action.kind == "write":
            action.path.parent.mkdir(parents=True, exist_ok=True)
            action.path.write_text(action.content, encoding="utf-8")
        else:
            raise AssertionError(f"unknown fixture action kind: {action.kind!r}")


def _drive_executable_probe(probe: ExecutableProbe, instance: Any, *, source: str) -> list[str]:
    """Dispatch ONE `ExecutableProbe` against `instance` directly, in-process.

    Mirrors `tests/acceptance/test_playbook_harness.py`'s `_run_probe`, with
    the daemon-socket half replaced by a direct handler call: same fixture
    discipline (PostToolUse claims a write already happened, so the target
    must exist first; setup/cleanup run as plain filesystem ops).
    """
    failures: list[str] = []
    identifier = f"{source}:{probe.event_type}/{probe.handler_name}::{probe.title}"
    created: Path | None = None
    target = Path(probe.file_path) if probe.file_path else None

    _perform_fixture_actions(probe.setup_actions)
    try:
        if target is not None and _is_removable_probe_target(target):
            if probe.requires_existing_file:
                target.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    probe.tool_input.get("content") or probe.tool_input.get("new_string") or ""
                )
                target.write_text(str(content), encoding="utf-8")
                created = target
            elif probe.requires_absent_file and target.exists():
                target.unlink()

        # `cwd` matters for a Bash payload: get_bash_write_targets declines
        # (fail-safe) to resolve a RELATIVE redirect target with no cwd, so
        # a heredoc-authored fixture is invisible to lint_on_edit without
        # it. Matches `playbook_harness.build_event`'s own shape.
        hook_input = {
            "tool_name": probe.tool_name,
            "tool_input": probe.tool_input,
            "cwd": str(probe.project_root),
        }

        if not instance.matches(hook_input):
            # The third lesson from tests/unit/daemon/test_playbook_harness.py:
            # a handler that correctly declines to match returns NO verdict at
            # all. That satisfies an ALLOW expectation (nothing was denied) but
            # is a real failure for a DENY expectation -- the payload never
            # reaches the handler's deny path at all.
            if probe.expected_decision == "deny":
                failures.append(
                    f"{identifier}: expected_decision=DENY but matches() "
                    "returned False for its own declared input"
                )
            return failures

        result = instance.handle(hook_input)
        actual_decision = str(getattr(result.decision, "value", result.decision)).lower()
        if actual_decision != probe.expected_decision:
            failures.append(
                f"{identifier}: expected decision {probe.expected_decision!r}, "
                f"got {actual_decision!r}"
            )
            return failures

        reason = result.reason or ""
        for pattern in probe.expected_message_patterns:
            if not re.search(pattern, reason):
                failures.append(
                    f"{identifier}: pattern {pattern!r} not found in reason: {reason[:300]!r}"
                )
        return failures
    finally:
        if created is not None and created.exists():
            created.unlink()
        _perform_fixture_actions(probe.cleanup_actions)


def _drive_hook_input_test(test: dict[str, Any], instance: Any) -> list[str]:
    """Dispatch a raw `hook_input`-declared test (no tool call to plan).

    `plan_probe` cannot classify these -- its `DISPATCHABLE_EVENTS` check is
    about tool CALLS, and a `hook_input` test exists precisely because its
    event carries none. Driven directly: `hook_input` is already the exact
    dict `handler.handle()` expects.
    """
    failures: list[str] = []
    identifier = _identifier(test)
    hook_input = test["hook_input"]
    expected_decision = str(test.get("expected_decision") or "").lower()

    if not instance.matches(hook_input):
        if expected_decision == "deny":
            failures.append(
                f"{identifier}: expected_decision=DENY but matches() "
                "returned False for its own declared input"
            )
        return failures

    result = instance.handle(hook_input)
    actual_decision = str(getattr(result.decision, "value", result.decision)).lower()
    if actual_decision != expected_decision:
        failures.append(
            f"{identifier}: expected decision {expected_decision!r}, got {actual_decision!r}"
        )
        return failures

    reason = result.reason or ""
    for pattern in test.get("expected_message_patterns") or []:
        if not re.search(pattern, reason):
            failures.append(
                f"{identifier}: pattern {pattern!r} not found in reason: {reason[:300]!r}"
            )
    return failures


class TestEveryBlockingTestDeclaresAWayToDriveIt:
    """The coverage half: no BLOCKING test may ship as blind coverage.

    Unconditional, unlike the negative-case ratchet in
    `test_acceptance_test_coverage.py` -- Plan 00319 Task 4.6 closed the
    only two tests that were missing a declared input
    (`SubagentReportSizeBlockerHandler`), so there is nothing left to grace
    into an allowlist. A future BLOCKING test that omits `tool_payload`,
    `hook_input` AND `harness_cannot_produce` fails here on the SAME commit
    that adds it.
    """

    def test_every_blocking_test_declares_a_way_to_drive_it(self) -> None:
        tests = _collect_all_blocking_tests()
        assert tests, "no BLOCKING acceptance tests discovered -- discovery is broken"

        missing = sorted(
            _identifier(test)
            for test in tests
            if not test.get("tool_payload")
            and not test.get("hook_input")
            and not test.get("harness_cannot_produce")
        )
        assert not missing, (
            "The following BLOCKING acceptance test(s) declare no way to "
            "drive them (no tool_payload, no hook_input, no "
            "harness_cannot_produce), so the contract test below cannot "
            "verify their declared patterns are real. Add a tool_payload "
            "(a real tool call), a hook_input (any other event shape), or "
            "harness_cannot_produce (with a reason) if genuinely "
            "unreachable:\n" + "\n".join(missing)
        )


class TestEveryDeclaredInputProducesItsDeclaredVerdict:
    """The contract half: a declared input must really produce what it claims.

    This is the oracle that catches a stale pattern -- one left behind by a
    header change, a rewording, or a Rule that moved -- WITHOUT running the
    daemon: the handler is instantiated (with THIS project's real
    configuration) and called directly, in-process.
    """

    def test_every_blocking_test_with_a_declared_input_produces_its_declared_verdict(
        self,
    ) -> None:
        tests = _collect_all_blocking_tests()
        instances = _handler_instances()
        project_root = _repo_root()

        failures: list[str] = []
        driven = 0
        for test in tests:
            if test.get("hook_input"):
                instance = instances.get((test["source"], test["handler_name"]))
                if instance is None:
                    failures.append(f"{_identifier(test)}: no live handler instance found")
                    continue
                driven += 1
                failures.extend(_drive_hook_input_test(test, instance))
                continue

            if not test.get("tool_payload"):
                continue  # harness_cannot_produce, or reported by the coverage test above

            probe = plan_probe(test, project_root)
            if isinstance(probe, SkippedProbe):
                # A required tool is missing on this machine (a language
                # linter this container does not have) -- nothing to drive.
                continue

            instance = instances.get((test["source"], test["handler_name"]))
            if instance is None:
                failures.append(f"{_identifier(test)}: no live handler instance found")
                continue

            driven += 1
            failures.extend(_drive_executable_probe(probe, instance, source=test["source"]))

        assert driven > 0, "no test was actually driven -- the harness is checking nothing"
        assert not failures, "Acceptance-test contract violated:\n\n" + "\n\n".join(failures)

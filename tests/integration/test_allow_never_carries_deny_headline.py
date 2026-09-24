"""Class-wide guard (Plan 00466 N8): no handler's ALLOW result may carry a
DENY headline ("BLOCKED [...]").

`reference_repo_freshness._verdict()` returned `Decision.ALLOW` for a
`block_once` repeat (and for `advise` mode) with a `context` built by
`RuleFormatter.verbose()` -- the SAME "BLOCKED [rule_id]: ..." rendering used
for a call that was actually stopped. An agent reading that context has no
way to tell its own call went through from one that did not.

This file drives every declared BLOCKING acceptance test TWICE against the
SAME handler instance, reproducing the shape a real `block_once` handler
sees in a live session: first call denies (proving the test's own DENY
contract, already checked by `test_acceptance_contract.py`), then the SAME
recording step `DaemonController.dispatch()` performs after every route
(`data_layer.history.record(handler_id=..., decision="deny", ...)`,
`daemon/controller.py`) is replicated by hand -- calling `handle()` twice
in isolation never populates a handler's block-once state for the handlers
(e.g. `lsp_enforcement`) that read it from the SHARED `HandlerHistory` data
layer rather than from an in-instance dict, so without this step their
repeat call denies again instead of exercising the ALLOW path this test
exists to check. Second call -- if the handler's own mode allows a repeat
through -- must never carry the deny headline in its `reason` or `context`.
`test_acceptance_contract.py`'s own machinery is reused rather than
duplicated (`_handler_instances`, `_collect_all_blocking_tests`, fixture
helpers) -- this file only adds the double-dispatch, the history record,
and the headline assertion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import get_data_layer, reset_data_layer
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.playbook_harness import (
    ExecutableProbe,
    SkippedProbe,
    plan_probe,
)
from tests.integration.test_acceptance_contract import (
    _collect_all_blocking_tests,
    _handler_instances,
    _identifier,
    _is_removable_probe_target,
    _perform_fixture_actions,
    _repo_root,
)

#: The exact signature `RuleFormatter.verbose()`/`terse()` open every
#: first-fire and repeat-fire DENY message with -- see `core/rule.py`.
_DENY_HEADLINE_SIGNATURE = "BLOCKED ["


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext against the REAL repo (same rationale as

    `test_acceptance_contract`'s own fixture of the same name -- every
    handler needs it to construct, and every declared path needs it to
    resolve). Duplicated rather than imported: an autouse fixture is
    resolved from the module a test lives in, not from an imported name.
    """
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_repo_root() / ".claude" / "hooks-daemon.yaml")


@pytest.fixture(autouse=True)
def _fresh_data_layer() -> None:
    """A clean `HandlerHistory` per test.

    Without this, an earlier probe's recorded DENY for the same handler_id
    could make a LATER probe's first call read a non-zero block count and
    ALLOW immediately -- never reaching the repeat this test means to check.
    """
    reset_data_layer()


def _rendered(result: Any) -> str:
    """Every string an agent would actually read from `result`."""
    return "\n".join([result.reason or "", *result.context])


def _dispatch_hook_input(instance: Any, hook_input: dict[str, Any]) -> Any | None:
    """One `handle()` call, or `None` if the handler declines to match."""
    if not instance.matches(hook_input):
        return None
    return instance.handle(hook_input)


def _dispatch_probe(probe: ExecutableProbe, instance: Any) -> Any | None:
    """One `handle()` call for a tool-payload probe, fixtures included.

    Mirrors `test_acceptance_contract._drive_executable_probe`'s fixture
    discipline, but returns the raw result instead of a list of failures --
    this file needs to inspect `reason`/`context`, not just the decision.
    """
    target = Path(probe.file_path) if probe.file_path else None
    created: Path | None = None

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

        hook_input = {
            "tool_name": probe.tool_name,
            "tool_input": probe.tool_input,
            "cwd": str(probe.project_root),
        }
        return _dispatch_hook_input(instance, hook_input)
    finally:
        if created is not None and created.exists():
            created.unlink()
        _perform_fixture_actions(probe.cleanup_actions)


def _record_deny_like_the_real_controller(instance: Any, test: dict[str, Any], result: Any) -> None:
    """Replicate `DaemonController.dispatch()`'s history-recording step.

    `daemon/controller.py` records every matched handler's OWN verdict into
    the shared `HandlerHistory` AFTER routing, outside `handle()` itself --
    so a handler whose block-once state lives there (not in an in-instance
    dict) never sees a repeat go through without this step. `tool_name` and
    `session_id` are read the same way `controller.py` reads them: from the
    hook input actually dispatched.
    """
    hook_input = test.get("hook_input") or {}
    tool_name = hook_input.get("tool_name") or (test.get("tool_payload") or {}).get("tool_name", "")
    get_data_layer().history.record(
        handler_id=instance.name,
        event_type=test.get("event_type") or "PreToolUse",
        decision=result.decision.value,
        tool_name=str(tool_name),
        reason=result.reason,
        session_id=hook_input.get("session_id"),
    )


class TestAllowResultsNeverCarryADenyHeadline:
    """Every handler, driven with its own declared BLOCKING payloads."""

    def test_the_repeat_of_a_denied_call_never_carries_the_deny_headline(self) -> None:
        tests = _collect_all_blocking_tests()
        instances = _handler_instances()
        project_root = _repo_root()

        failures: list[str] = []
        repeats_seen = 0

        for test in tests:
            instance = instances.get((test["source"], test["handler_name"]))
            if instance is None:
                continue

            reset_data_layer()

            if test.get("hook_input"):
                hook_input = test["hook_input"]
                first = _dispatch_hook_input(instance, hook_input)
                if first is None or first.decision != Decision.DENY:
                    continue
                _record_deny_like_the_real_controller(instance, test, first)
                second = _dispatch_hook_input(instance, hook_input)
            elif test.get("tool_payload"):
                probe = plan_probe(test, project_root)
                if isinstance(probe, SkippedProbe):
                    continue
                first = _dispatch_probe(probe, instance)
                if first is None or first.decision != Decision.DENY:
                    continue
                _record_deny_like_the_real_controller(instance, test, first)
                second = _dispatch_probe(probe, instance)
            else:
                continue

            if second is None:
                continue

            repeats_seen += 1
            if second.decision == Decision.ALLOW:
                rendered = _rendered(second)
                if _DENY_HEADLINE_SIGNATURE in rendered:
                    failures.append(
                        f"{_identifier(test)}: the repeat call was ALLOWed but its "
                        f"reason/context still opens with the deny headline: "
                        f"{rendered[:300]!r}"
                    )

        assert repeats_seen > 0, (
            "no handler's repeat call was ever driven -- the double-dispatch "
            "harness is checking nothing"
        )
        assert not failures, (
            "An ALLOW result carried a DENY headline (Plan 00466 N8 defect "
            "class):\n\n" + "\n\n".join(failures)
        )

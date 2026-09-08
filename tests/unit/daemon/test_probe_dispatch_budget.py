"""A probe dispatch must outlast anything a handler may legitimately do.

The playbook harness dispatched each probe with
`Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC` — 15s, a constant named for restart
verification — while `lint_on_edit` gives a single lint 15s and
`validate_eslint_on_write` gives one 30s. Two consequences, both observed in CI
once Plan 00250 gave the runner a daemon:

- The handler's own fail-open is unreachable. `lint_on_edit` catches
  `TimeoutExpired` and ALLOWs, but it can only do that AFTER its 15s elapse, by
  which point the harness has already killed the hook.
- One slow lint ends the whole gate. The harness raises `TimeoutExpired` out of
  `_run_probe`, so 201 probes report as a crash rather than one failure — which
  is how a Kotlin probe on a runner with a JVM masked the Rust probe next to it.

The budget is therefore DERIVED from the handler budgets rather than pinned, so
raising a lint timeout cannot silently restore the collision.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.playbook_harness import (
    PROBE_DISPATCH_TIMEOUT_SECONDS,
)

_ACCEPTANCE_HARNESS = (
    Path(__file__).resolve().parents[3] / "tests" / "acceptance" / "test_playbook_harness.py"
)

#: Every budget a handler may spend before answering a probe.
_HANDLER_BUDGETS = {
    "lint_on_edit": Timeout.LINT_CHECK,
    "validate_eslint_on_write": Timeout.ESLINT_CHECK,
}


class TestTheBudgetOutlastsTheHandlers:
    def test_it_exceeds_every_handler_budget(self) -> None:
        for name, budget in _HANDLER_BUDGETS.items():
            assert PROBE_DISPATCH_TIMEOUT_SECONDS > budget, (
                f"{name} may spend {budget}s before answering, so a dispatch "
                f"budget of {PROBE_DISPATCH_TIMEOUT_SECONDS}s kills the hook "
                f"before the handler's fail-open can return"
            )

    def test_it_leaves_room_for_the_handler_to_report_after_timing_out(self) -> None:
        """Exceeding the budget by a hair would still lose the fail-open."""
        assert PROBE_DISPATCH_TIMEOUT_SECONDS >= 2 * max(_HANDLER_BUDGETS.values())

    def test_it_is_derived_from_the_handler_budgets(self) -> None:
        """Pinning a number is what let the two drift into agreement."""
        assert PROBE_DISPATCH_TIMEOUT_SECONDS % max(_HANDLER_BUDGETS.values()) == 0


class TestTheAcceptanceHarnessUsesIt:
    """The constant is worthless if the dispatch does not pass it."""

    def test_the_dispatch_passes_the_shared_budget(self) -> None:
        source = _ACCEPTANCE_HARNESS.read_text(encoding="utf-8")
        assert "timeout=PROBE_DISPATCH_TIMEOUT_SECONDS" in source

    def test_the_dispatch_no_longer_borrows_the_restart_constant(self) -> None:
        source = _ACCEPTANCE_HARNESS.read_text(encoding="utf-8")
        assert "DAEMON_RESTART_VERIFY_TIMEOUT_SEC" not in source, (
            "that constant is the ceiling for verifying a daemon RESTART; "
            "borrowing it for a hook dispatch is how the two budgets came to "
            "be the same number by accident"
        )

    def test_the_harness_file_is_where_this_test_thinks_it_is(self) -> None:
        """Vacuity: a moved file would make both checks above pass on ''."""
        assert _ACCEPTANCE_HARNESS.is_file()

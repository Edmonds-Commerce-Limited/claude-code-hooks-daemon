"""The pytest-side sink: refuse a whole-suite-sized run with no lock held.

Plan 00463 round 9's design decision: a Bash-text denylist (the sub-agent
full-QA blocker handler) can never enumerate every way to start a whole-suite
test run -- any interpreter, launcher or rewritten script can do it. So the
guarantee moves to the SINK, the one place every route ends up: this pytest
plugin. It runs in `pytest_collection_modifyitems`, after collection and
before any test executes, so a refusal costs nothing but wall time already
spent collecting.

Generic on purpose: this module is a pytest plugin, not code that assumes it
is testing THIS repository. `_total_test_file_count` counts under whatever
`pytest.Config.rootpath` resolves to for the run, so the SAME plugin, loaded
by a tiny fixture suite's own `conftest.py`, enforces the SAME rule at a
proportionally small scale -- which is what lets a test exercise this
mechanism without running 1,000+ real files (see
`tests/unit/qa/test_full_qa_gate.py`).

xdist: only the CONTROLLER process runs this check. A worker's own
sub-selection is never whole-suite-sized by construction (the controller
already split it), so re-checking there would only ever say "allow", and the
controller's own collection has already run and would have refused, before
any worker is spawned, had the whole selection failed the check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.qa.full_qa_lock import full_qa_lock_is_held

#: M1's own direction (review 9): "a measured fraction such as 25% of the
#: test files is one option". Chosen at that value because it sits well above
#: what a bounded per-file selection can reach by accident --
#: `run_changed_tests.py`'s own `MAX_IMPORT_SELECTION` caps one file's reach at
#: 40 test files, three orders of magnitude below 25% of this repository's
#: ~1,124-file suite -- while staying well under "effectively the whole
#: suite" (review 9's own M1 reproduction selected 94%).
WHOLE_SUITE_FRACTION = 0.25


def _is_xdist_worker(config: pytest.Config) -> bool:
    """True only inside an xdist worker; see the module docstring."""
    return hasattr(config, "workerinput")


def _test_root(config: pytest.Config) -> Path:
    """Where to count from: `<rootpath>/tests` if it exists, else rootpath."""
    candidate = config.rootpath / "tests"
    return candidate if candidate.is_dir() else config.rootpath


def _total_test_file_count(config: pytest.Config) -> int:
    return sum(1 for _ in _test_root(config).rglob("test_*.py"))


def whole_suite_refusal_message(selected: int, total: int) -> str:
    fraction = selected / total if total else 0.0
    return (
        "REFUSED: this pytest run selects "
        f"{selected} of {total} test files ({fraction:.0%}), which is "
        f"whole-suite-sized (over {WHOLE_SUITE_FRACTION:.0%}). A whole-suite "
        "run must hold the host-wide full-QA lock (Plan 00463) -- acquire it "
        "via `scripts/qa/run_tests.sh`, `llm_qa.py all`, or `llm_qa.py "
        "changed` rather than invoking pytest directly. This is the SINK-side "
        "guarantee: whatever launched this pytest process, it does not hold "
        "the lock, so it is refused before running any test. See "
        "CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate/PLAN.md."
    )


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    del session  # part of pytest's hookspec signature; unused here.
    if _is_xdist_worker(config):
        return
    total = _total_test_file_count(config)
    if total == 0:
        return
    selected_files = {item.path for item in items if hasattr(item, "path")}
    if not selected_files:
        return
    fraction = len(selected_files) / total
    if fraction <= WHOLE_SUITE_FRACTION:
        return
    if full_qa_lock_is_held(config.rootpath):
        return
    pytest.exit(whole_suite_refusal_message(len(selected_files), total), returncode=1)

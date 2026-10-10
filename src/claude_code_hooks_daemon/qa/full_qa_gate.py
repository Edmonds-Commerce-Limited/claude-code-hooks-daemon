"""The pytest-side sink: refuse a whole-suite-sized run with no lock held.

Plan 00463 round 9's design decision: a Bash-text denylist (the sub-agent
full-QA blocker handler) can never enumerate every way to start a whole-suite
test run -- any interpreter, launcher or rewritten script can do it. So the
guarantee moves to the SINK, the one place every route ends up: this pytest
plugin. It runs in `pytest_collection_modifyitems`, after collection and
before any test executes, so a refusal costs nothing but wall time already
spent collecting.

Generic on purpose: this module is a pytest plugin, not code that assumes it
is testing THIS repository. `_total_test_file_count` counts under the
directory of the conftest.py that IMPORTED this hook (`_gate_anchor`), never
`pytest.Config.rootpath` -- `--rootdir` repoints the latter at any directory
the caller names, including an empty one, without moving where conftest.py
is discovered from (review 10 B1). The SAME plugin, loaded by a tiny fixture
suite's own `conftest.py`, enforces the SAME rule at a proportionally small
scale -- which is what lets a test exercise this mechanism without running
1,000+ real files (see `tests/unit/qa/test_full_qa_gate.py`).

xdist (N392): `_is_xdist_worker` exempts worker processes, and the xdist
CONTROLLER's own `pytest_collection` short-circuits, so
`pytest_collection_modifyitems` never judged a `-n N` run at all. The
controller is judged instead in `pytest_xdist_node_collection_finished`,
which xdist calls with the node ids a worker collected (the whole selection).
xdist is not installed in this repository's own environment (`-n 2` gives
rc=4), so the hook is exercised by a simulated controller in
`tests/unit/qa/test_full_qa_gate.py`, not by a real xdist run; the hook name
and signature are xdist's documented ones.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Protocol

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


#: This module's own directory (`src/claude_code_hooks_daemon/qa/`). Round
#: 10 M1: `addopts` force-loads this module itself as a plugin (through
#: `claude_code_hooks_daemon_full_qa_gate_loader`), so that `--noconftest`
#: (which drops the conftest-import route entirely) cannot silently remove
#: the sink. When a project's own conftest.py ALSO imports and re-exports
#: `pytest_collection_modifyitems` (the normal, non---noconftest case), BOTH
#: routes register a plugin object carrying this exact function, and
#: `_gate_anchor` below must not pick whichever one the pluginmanager's
#: iteration order happens to put first -- this module's own directory
#: holds no project test files at all, so anchoring here by accident turns
#: every run, however small, into an "unable to judge" refusal.
_OWN_DIR: Final[Path] = Path(__file__).resolve().parent


def _gate_anchor(config: pytest.Config) -> Path | None:
    """The directory of the conftest.py that registered this very hook.

    Review 10 B1: counting from `config.rootpath` is counting from a value
    the CALLER controls -- `pytest --rootdir=<empty dir>` (with or without
    `-c /dev/null`) repoints it at a directory with nothing under it, so the
    old `_total_test_file_count` silently counted zero and the caller's own
    `total == 0` early-return let the run straight through with no refusal,
    fail-OPEN on a security path. `--rootdir` never moves where conftest.py
    files are discovered from (that follows the test paths given on the
    command line), so the directory holding the conftest module that
    IMPORTED this hook is an anchor the caller cannot move by any pytest
    flag examined here. Found by identity: `config.pluginmanager` registers
    each conftest.py as a plugin object, and only the one that re-exports
    this exact function carries it as an attribute equal to it.

    Round 10 M1: double registration (the `-p` route above AND a project's
    own conftest import both active at once) is made a no-op here rather
    than at registration time -- pytest does not raise for this shape (the
    two plugin objects are registered under distinct names), it just calls
    the hook twice, and both a plugin's own directory and a conftest's are
    valid identity matches. The conftest-registered anchor always wins over
    this module's own directory when both are present, since it is the one
    that actually sits inside the project's real test tree; this module's
    own directory is used only when it is the sole match (e.g. under
    `--noconftest`, where the conftest route is not registered at all).
    """
    candidates: list[Path] = []
    for plugin in config.pluginmanager.get_plugins():
        if getattr(plugin, "pytest_collection_modifyitems", None) is pytest_collection_modifyitems:
            plugin_file = getattr(plugin, "__file__", None)
            if plugin_file:
                candidates.append(Path(plugin_file).resolve().parent)
    if not candidates:
        return None
    non_self = [candidate for candidate in candidates if candidate != _OWN_DIR]
    return non_self[0] if non_self else candidates[0]


def _test_root(config: pytest.Config) -> Path | None:
    """Where to count from: the gate's own anchor, never `config.rootpath`.

    `None` when no conftest.py that loaded this hook can be found -- this is
    itself unable to judge, not zero, and the caller must refuse rather than
    read it as an empty suite.
    """
    return _gate_anchor(config)


def _invocation_tests_dir(config: pytest.Config) -> Path | None:
    """`tests/` under the directory pytest was launched from, if there is one.

    Used when only the force-loaded plugin registered the hook (no conftest.py
    of the suite was collected, e.g. `pytest .claude/project-handlers`), so
    the plugin's own source directory holds no test files to count. The
    launch directory is not moved by `--rootdir`, `-c` or any other pytest
    flag, so it keeps the count fail-closed.
    """
    candidate = Path(config.invocation_params.dir) / "tests"
    return candidate if candidate.is_dir() else None


def _total_test_file_count(config: pytest.Config) -> int | None:
    root = _test_root(config)
    if root is None:
        return None
    count = sum(1 for _ in root.rglob("test_*.py"))
    if count == 0 and root == _OWN_DIR:
        fallback = _invocation_tests_dir(config)
        if fallback is not None:
            return sum(1 for _ in fallback.rglob("test_*.py"))
    return count


def whole_suite_refusal_message(selected: int, total: int) -> str:
    fraction = selected / total if total else 0.0
    return (
        "REFUSED: this pytest run selects "
        f"{selected} of {total} test files ({fraction:.0%}), which is "
        f"whole-suite-sized (over {WHOLE_SUITE_FRACTION:.0%}). A whole-suite "
        "run must hold the host-wide full-QA lock (Plan 00463) -- acquire it "
        "via `scripts/qa/run_tests.sh` or `llm_qa.py all` rather than "
        "invoking pytest directly. This is the SINK-side guarantee: "
        "whatever launched this pytest process, it does not hold the lock, "
        "so it is refused before running any test. See "
        "CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate/PLAN.md."
    )


#: Review 10 B1: `_total_test_file_count` returning `None` or `0` means the
#: gate could not establish how big the real suite is -- from `--rootdir`
#: pointed at an empty directory, `-c`/`--config-file` naming a config with
#: no anchor, or any other way the count comes back unusable. A whole-suite
#: run under exactly those conditions is indistinguishable from a genuinely
#: tiny fixture suite by this count alone, so an unusable count REFUSES
#: rather than reads as "nothing to protect" -- the fail-OPEN this closes.
_UNABLE_TO_JUDGE_MESSAGE: Final[str] = (
    "REFUSED: this pytest run's whole-suite-sized check could not establish "
    "how many test files the real suite holds (the conftest.py that loaded "
    "this plugin could not be found, or it reports zero test files under "
    "its own directory) -- most likely `--rootdir`, `-c` or "
    "`--config-file` pointed collection away from the real suite. An "
    "unusable count is refused, not read as an empty suite. A whole-suite "
    "run must hold the host-wide full-QA lock (Plan 00463) -- acquire it "
    "via `scripts/qa/run_tests.sh` or `llm_qa.py all` rather than invoking "
    "pytest directly. See CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate/PLAN.md."
)


def _refuse_if_whole_suite_without_lock(config: pytest.Config, selected: int) -> None:
    """Exit the run when `selected` test files is whole-suite-sized and no lock is held."""
    total = _total_test_file_count(config)
    if not total:
        pytest.exit(_UNABLE_TO_JUDGE_MESSAGE, returncode=1)
    if not selected:
        return
    if selected / total <= WHOLE_SUITE_FRACTION:
        return
    if full_qa_lock_is_held(config.rootpath):
        return
    pytest.exit(whole_suite_refusal_message(selected, total), returncode=1)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    del session  # part of pytest's hookspec signature; unused here.
    if _is_xdist_worker(config):
        return
    selected_files = {item.path for item in items if hasattr(item, "path")}
    _refuse_if_whole_suite_without_lock(config, len(selected_files))


class _HasConfig(Protocol):
    """The one attribute of an xdist node the gate reads."""

    config: pytest.Config


@pytest.hookimpl(optionalhook=True)  # the hook exists only when xdist is installed
def pytest_xdist_node_collection_finished(node: _HasConfig, ids: list[str]) -> None:
    """The xdist controller's only view of the selection (N392).

    The controller never collects, so `pytest_collection_modifyitems` cannot
    judge a `-n N` run there, and workers are exempt from it. xdist calls this
    hook on the controller with the node ids a worker collected -- the whole
    selection -- so the same rule is applied to the files those ids name. The
    controller process is the one that holds the lock descriptor, so the lock
    proof is made here, not in a worker.
    """
    files = {node_id.split("::", 1)[0] for node_id in ids}
    _refuse_if_whole_suite_without_lock(node.config, len(files))

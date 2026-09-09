"""Shared fixtures for the plan QA suites.

The subprocess counter lives here rather than in one test module because two
suites need the same measurement: the unit test that pins
:meth:`GitFacts.staged_changes` to one spawn, and the commit-gate regression
that pins the whole check run to one (Plan 00364 Task 2.1).
"""

from collections.abc import Iterator, Mapping
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from _pytest.monkeypatch import MonkeyPatch

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa import gitfacts as gitfacts_module


@pytest.fixture
def git_diff_spawns(monkeypatch: MonkeyPatch) -> Iterator[list[tuple[str, ...]]]:
    """Every ``git diff`` argv :mod:`plan_qa.gitfacts` spawns during the test.

    Wraps the real runner rather than replacing it, so the facts under test
    are still the ones a real repository produces -- a stub would pin the
    call count while proving nothing about the answer.
    """
    spawned: list[tuple[str, ...]] = []
    real_run_git = gitfacts_module.run_git

    def recording(
        cwd: Path,
        *args: str,
        timeout: float = Timeout.GIT_CONTEXT,
        env: Mapping[str, str] | None = None,
    ) -> CompletedProcess[str]:
        if args and args[0] == "diff":
            spawned.append(args)
        return real_run_git(cwd, *args, timeout=timeout, env=env)

    monkeypatch.setattr(gitfacts_module, "run_git", recording)
    yield spawned

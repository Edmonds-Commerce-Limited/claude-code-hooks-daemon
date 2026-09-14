"""SessionStart sweep over the governed reference repos (Plan 00401 Task 3.1).

This is the surface that does the network work, and the reason the PreToolUse
backstop never has to: by the time any read happens, every governed repo has
been fetched, safely pulled where that was provable, and recorded.

The test that matters most here is
``test_the_cache_is_written_even_when_everything_is_clean``. It is tempting to
skip the write when there is nothing to report, and that would be a real defect:
the cache is what tells PreToolUse "this was checked", so a clean sweep that
wrote nothing would leave every subsequent read reading as NOT VERIFIED — the
handler would enforce hardest precisely when the repos were perfect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import ReferenceReposConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.reference_repo_sweep import (
    ReferenceRepoSweepHandler,
)
from claude_code_hooks_daemon.reference_repos.cache import cached_states
from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.reference_repos.refresh import RefreshOutcome

_STARTUP: dict[str, Any] = {"hook_event_name": "SessionStart", "source": "startup"}


def _resumed(tmp_path: Path) -> dict[str, Any]:
    """A resume is detected from TRANSCRIPT SIZE, not a `source` field.

    Discovered by this test failing against a `source: "resume"` fixture I had
    assumed would work — `is_resume_session` reads the transcript's byte count,
    so a resume has to be built rather than declared.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("x" * 500, encoding="utf-8")
    return {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}


def _make_checkout(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


def _state(path: Path, *, behind: int = 0, branch: str = "main") -> RepoState:
    return RepoState(
        path=path,
        checkability=Checkability.CHECKABLE,
        branch=branch,
        default_branch="main",
        upstream="origin/main",
        behind=behind,
        ahead=0,
        dirty=False,
    )


@pytest.fixture
def handler(tmp_path: Path) -> ReferenceRepoSweepHandler:
    instance = ReferenceRepoSweepHandler()
    instance.project_root_reader = lambda: tmp_path
    instance._reference_repos = ReferenceReposConfig()
    instance.refresher = lambda path, *, allow_pull: RefreshOutcome(
        state=_state(path), fetched=True, pulled=False, detail="ok"
    )
    return instance


class TestWhenItRuns:
    def test_it_runs_on_a_new_session(self, handler: ReferenceRepoSweepHandler) -> None:
        assert handler.matches(_STARTUP) is True

    def test_it_skips_a_resumed_session(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        """A resume should not re-fetch every repo; the cache from startup stands."""
        assert handler.matches(_resumed(tmp_path)) is False

    def test_it_does_nothing_when_disabled(self, handler: ReferenceRepoSweepHandler) -> None:
        handler._reference_repos = ReferenceReposConfig(enabled=False)

        assert handler.matches(_STARTUP) is False

    def test_it_does_nothing_when_config_was_never_injected(
        self, handler: ReferenceRepoSweepHandler
    ) -> None:
        """Absent config means off, never a crash at session start."""
        handler._reference_repos = None

        assert handler.matches(_STARTUP) is False


class TestReporting:
    def test_it_is_silent_when_the_project_governs_no_repos(
        self, handler: ReferenceRepoSweepHandler
    ) -> None:
        """The ordinary state of a project that never adopted the convention."""
        result = handler.handle(_STARTUP)

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_it_is_silent_when_every_repo_is_current(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        _make_checkout(tmp_path / "untracked" / "repos" / "alpha")

        result = handler.handle(_STARTUP)

        assert result.context == []

    def test_it_reports_a_repo_it_could_not_make_fresh(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        _make_checkout(tmp_path / "untracked" / "repos" / "alpha")
        handler.refresher = lambda path, *, allow_pull: RefreshOutcome(
            state=_state(path, behind=3), fetched=True, pulled=False, detail="dirty"
        )

        result = handler.handle(_STARTUP)

        body = "\n".join(result.context)
        assert "alpha" in body
        assert "3" in body

    def test_it_never_blocks(self, tmp_path: Path, handler: ReferenceRepoSweepHandler) -> None:
        """Advisory by design — a session must never fail to start over this."""
        _make_checkout(tmp_path / "untracked" / "repos" / "alpha")
        handler.refresher = lambda path, *, allow_pull: RefreshOutcome(
            state=_state(path, behind=99), fetched=False, pulled=False, detail="offline"
        )

        assert handler.handle(_STARTUP).decision == Decision.ALLOW

    def test_the_report_is_bounded(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        """One advisory among several must not push the others out of view."""
        for index in range(30):
            _make_checkout(tmp_path / "untracked" / "repos" / f"r{index}")
        handler.refresher = lambda path, *, allow_pull: RefreshOutcome(
            state=_state(path, behind=1), fetched=True, pulled=False, detail="behind"
        )

        result = handler.handle(_STARTUP)

        assert any("more" in line for line in result.context)


class TestTheCache:
    def test_the_cache_is_written_even_when_everything_is_clean(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        """The whole point: a clean sweep must still record that it HAPPENED.

        Skipping the write when there is nothing to report would leave every
        later read as NOT VERIFIED, so the backstop would enforce hardest
        exactly when the repos were perfect.
        """
        repo = _make_checkout(tmp_path / "untracked" / "repos" / "alpha")

        handler.handle(_STARTUP)

        cached = cached_states(tmp_path)
        assert cached is not None
        assert repo in cached

    def test_the_cached_reading_is_the_state_AFTER_the_refresh(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        """A cache holding the pre-pull state would report freshly-pulled repos as stale."""
        repo = _make_checkout(tmp_path / "untracked" / "repos" / "alpha")
        handler.refresher = lambda path, *, allow_pull: RefreshOutcome(
            state=_state(path, behind=0), fetched=True, pulled=True, detail="fast-forwarded"
        )

        handler.handle(_STARTUP)

        cached = cached_states(tmp_path)
        assert cached is not None
        assert cached[repo].behind == 0

    def test_an_empty_sweep_still_writes_a_cache(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        """Verified-and-empty must be distinguishable from never-checked."""
        handler.handle(_STARTUP)

        assert cached_states(tmp_path) == {}


class TestAutoPull:
    def test_auto_pull_on_is_passed_through(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        _make_checkout(tmp_path / "untracked" / "repos" / "alpha")
        seen: list[bool] = []

        def _refresh(path: Path, *, allow_pull: bool) -> RefreshOutcome:
            seen.append(allow_pull)
            return RefreshOutcome(state=_state(path), fetched=True, pulled=False, detail="ok")

        handler.refresher = _refresh
        handler.handle(_STARTUP)

        assert seen == [True]

    def test_auto_pull_off_is_passed_through(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        """Report-only mode must actually reach the code that would mutate."""
        _make_checkout(tmp_path / "untracked" / "repos" / "alpha")
        handler._reference_repos = ReferenceReposConfig(auto_pull=False)
        seen: list[bool] = []

        def _refresh(path: Path, *, allow_pull: bool) -> RefreshOutcome:
            seen.append(allow_pull)
            return RefreshOutcome(state=_state(path), fetched=True, pulled=False, detail="ok")

        handler.refresher = _refresh
        handler.handle(_STARTUP)

        assert seen == [False]


class TestConfiguredScope:
    def test_a_custom_root_is_swept(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        repo = _make_checkout(tmp_path / "vendor" / "upstream")
        handler._reference_repos = ReferenceReposConfig(roots=["vendor"])

        handler.handle(_STARTUP)

        cached = cached_states(tmp_path)
        assert cached is not None
        assert repo in cached

    def test_an_excluded_repo_is_not_swept(
        self, tmp_path: Path, handler: ReferenceRepoSweepHandler
    ) -> None:
        _make_checkout(tmp_path / "untracked" / "repos" / "alpha")
        _make_checkout(tmp_path / "untracked" / "repos" / "scratch")
        handler._reference_repos = ReferenceReposConfig(exclude=["**/scratch"])

        handler.handle(_STARTUP)

        cached = cached_states(tmp_path)
        assert cached is not None
        assert {path.name for path in cached} == {"alpha"}


class TestHandlerContract:
    def test_it_documents_itself_for_the_generated_guidance(
        self, handler: ReferenceRepoSweepHandler
    ) -> None:
        """get_claude_md coverage is a release gate in this project."""
        guidance = handler.get_claude_md()

        assert guidance
        assert "reference" in guidance.lower()

    def test_it_declares_an_acceptance_test(self, handler: ReferenceRepoSweepHandler) -> None:
        assert handler.get_acceptance_tests()

"""The one discover -> refresh -> record pipeline (Plan 00401, review finding 7).

Two callers ran these three steps: the SessionStart sweep handler and the
`reference-repos` CLI. Two copies of a pipeline is not merely untidy here — it
is how the two surfaces come to disagree about what was checked, and they
already had. The CLI's JSON encoder gained `fetch_failed` and `verified` while
the handler's copy of the same walk knew nothing about either, so a repo whose
fetch had failed read as a confident all-clear on one surface and not the other.

So the pipeline lives here, and both callers spend it rather than reproducing
it. The tests below pin the parts a caller would otherwise get subtly wrong:
that the cache is written even when nothing is wrong, that `auto_pull` reaches
the refresher, and that the refresher is resolved at CALL time so a test
replacing the only network-touching function in the package actually replaces
the one this module uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import ReferenceReposConfig
from claude_code_hooks_daemon.reference_repos import refresh as refresh_module
from claude_code_hooks_daemon.reference_repos.cache import cached_states
from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.reference_repos.refresh import RefreshOutcome
from claude_code_hooks_daemon.reference_repos.sweep import governed_roots, sweep_reference_repos


def _checkout(root: Path, name: str) -> Path:
    path = root / "untracked" / "repos" / name
    (path / ".git").mkdir(parents=True)
    return path


def _state(path: Path, *, behind: int = 0) -> RepoState:
    return RepoState(
        path=path,
        checkability=Checkability.CHECKABLE,
        branch="main",
        default_branch="main",
        upstream="origin/main",
        behind=behind,
        ahead=0,
        dirty=False,
    )


def _outcome(path: Path, *, allow_pull: bool = True) -> RefreshOutcome:
    return RefreshOutcome(state=_state(path), fetched=True, pulled=allow_pull, detail="ok")


class TestGovernedRoots:
    def test_a_relative_root_is_resolved_against_the_project(self, tmp_path: Path) -> None:
        assert governed_roots(tmp_path, ["untracked/repos"]) == [tmp_path / "untracked" / "repos"]

    def test_several_roots_keep_their_configured_order(self, tmp_path: Path) -> None:
        roots = governed_roots(tmp_path, ["a", "b"])

        assert roots == [tmp_path / "a", tmp_path / "b"]

    def test_no_roots_produces_no_paths(self, tmp_path: Path) -> None:
        assert governed_roots(tmp_path, []) == []


class TestTheSweep:
    def test_every_governed_checkout_gets_an_outcome(self, tmp_path: Path) -> None:
        _checkout(tmp_path, "alpha")
        _checkout(tmp_path, "beta")

        outcomes = sweep_reference_repos(
            tmp_path, ReferenceReposConfig(), refresher=lambda path, *, allow_pull: _outcome(path)
        )

        assert [outcome.state.path.name for outcome in outcomes] == ["alpha", "beta"]

    def test_the_outcomes_come_back_in_a_stable_order(self, tmp_path: Path) -> None:
        """Walk order churns between runs; a report that churns gets skimmed."""
        for name in ("zulu", "alpha", "mike"):
            _checkout(tmp_path, name)

        outcomes = sweep_reference_repos(
            tmp_path, ReferenceReposConfig(), refresher=lambda path, *, allow_pull: _outcome(path)
        )

        assert [outcome.state.path.name for outcome in outcomes] == ["alpha", "mike", "zulu"]

    def test_the_cache_is_written_even_when_nothing_is_wrong(self, tmp_path: Path) -> None:
        """The cache records that a check HAPPENED, not that something is wrong.

        Skipping the write on a clean sweep would leave every later read as NOT
        VERIFIED — enforcing hardest precisely when the repos were perfect.
        """
        repo = _checkout(tmp_path, "alpha")

        sweep_reference_repos(
            tmp_path, ReferenceReposConfig(), refresher=lambda path, *, allow_pull: _outcome(path)
        )

        assert cached_states(tmp_path) == {repo: _state(repo)}

    def test_a_project_governing_nothing_still_records_that_it_checked(
        self, tmp_path: Path
    ) -> None:
        """`{}` and `None` are different answers to the handler that reads this."""
        sweep_reference_repos(
            tmp_path, ReferenceReposConfig(), refresher=lambda path, *, allow_pull: _outcome(path)
        )

        assert cached_states(tmp_path) == {}

    def test_excluded_checkouts_are_never_refreshed(self, tmp_path: Path) -> None:
        _checkout(tmp_path, "alpha")
        _checkout(tmp_path, "vendored")

        outcomes = sweep_reference_repos(
            tmp_path,
            ReferenceReposConfig(exclude=["**/vendored"]),
            refresher=lambda path, *, allow_pull: _outcome(path),
        )

        assert [outcome.state.path.name for outcome in outcomes] == ["alpha"]

    def test_auto_pull_reaches_the_refresher(self, tmp_path: Path) -> None:
        """Report-only mode is a promise that nothing is touched; it must arrive."""
        _checkout(tmp_path, "alpha")
        seen: list[bool] = []

        def _record(path: Path, *, allow_pull: bool) -> RefreshOutcome:
            seen.append(allow_pull)
            return _outcome(path)

        sweep_reference_repos(tmp_path, ReferenceReposConfig(auto_pull=False), refresher=_record)

        assert seen == [False]

    def test_the_refresher_is_resolved_at_call_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bound as a default argument, a monkeypatched `refresh_repo` is missed.

        `refresh_repo` is the only function in this package that touches the
        network, so a test that replaces it and is quietly bypassed spends real
        fetches while reporting that it did not.
        """
        repo = _checkout(tmp_path, "alpha")
        monkeypatch.setattr(
            refresh_module,
            "refresh_repo",
            lambda path, *, allow_pull: RefreshOutcome(
                state=_state(path, behind=9), fetched=True, pulled=False, detail="patched"
            ),
        )

        outcomes = sweep_reference_repos(tmp_path, ReferenceReposConfig())

        assert outcomes == [
            RefreshOutcome(
                state=_state(repo, behind=9), fetched=True, pulled=False, detail="patched"
            )
        ]

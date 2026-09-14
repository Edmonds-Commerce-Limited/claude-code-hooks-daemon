"""The PreToolUse backstop over governed reference repos (Plan 00401 Phase 4).

The SessionStart sweep does the network work; this handler only ever READS the
cache the sweep wrote. Two tests carry the architecture:

``test_the_handler_never_performs_network_io``
    ``GIT_FETCH_SESSION`` and ``GIT_PULL_SESSION`` are 30s apiece against a 30s
    hook socket budget, so one fetch here could consume the entire budget for a
    single repo. A future change that "helpfully" adds a fetch is caught here
    and nowhere else.

``test_the_remediation_command_it_prints_is_itself_allowed``
    A handler that blocks the command it just told you to run is impossible to
    satisfy. The exemption is asserted against the string the renderer actually
    produces, not against a hand-written lookalike, so the two cannot drift.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import ReferenceReposConfig
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.pre_tool_use.reference_repo_freshness import (
    ReferenceRepoFreshnessHandler,
)
from claude_code_hooks_daemon.reference_repos.cache import write_cache
from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.reference_repos.report import (
    NOT_VERIFIED_HEADLINE,
    UNCONFIRMED_HEADLINE,
    remediation_command,
)

_SESSION = "session-alpha"
_OTHER_SESSION = "session-beta"


def _state(
    path: Path,
    *,
    behind: int = 0,
    branch: str = "main",
    checkability: Checkability = Checkability.CHECKABLE,
    dirty: bool = False,
    fetch_failed: bool = False,
) -> RepoState:
    return RepoState(
        path=path,
        checkability=checkability,
        branch=branch,
        default_branch="main",
        upstream="origin/main",
        behind=behind,
        ahead=0,
        dirty=dirty,
        fetch_failed=fetch_failed,
    )


def _repo(root: Path, name: str = "alpha") -> Path:
    path = root / "untracked" / "repos" / name
    (path / ".git").mkdir(parents=True)
    return path


def _fresh_cache(root: Path, name: str = "alpha") -> None:
    """An in-date cache recording one perfectly current governed repo.

    The point of several tests below: even with nothing whatsoever wrong, the
    handler used to deny reads of non-checkout paths under the root.
    """
    write_cache(root, [_state(root / "untracked" / "repos" / name)])


def _reason(result: Any) -> str:
    """The deny text, asserted present rather than assumed.

    `HookResult.reason` is `str | None`, so a bare `"x" in result.reason` is a
    type error on every assertion below. Asserting here rather than coercing
    keeps the failure honest: a DENY that carries no reason is itself a defect,
    and this reports it as one instead of comparing against the string "None".
    """
    reason = result.reason
    assert reason is not None, "a denial must carry a reason"
    return str(reason)


def _read(path: Path, session: str = _SESSION) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(path)},
        "session_id": session,
    }


def _bash(command: str, session: str = _SESSION) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session,
    }


@pytest.fixture
def handler(tmp_path: Path) -> ReferenceRepoFreshnessHandler:
    instance = ReferenceRepoFreshnessHandler()
    instance.project_root_reader = lambda: tmp_path
    instance._reference_repos = ReferenceReposConfig()
    return instance


class TestWhichCallsItEngages:
    def test_a_read_inside_a_governed_repo_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)

        assert handler.matches(_read(repo / "src" / "main.py")) is True

    def test_a_read_elsewhere_in_the_project_is_ignored(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The overwhelmingly common call must not pay for this handler."""
        assert handler.matches(_read(tmp_path / "src" / "main.py")) is False

    def test_a_grep_scoped_to_a_governed_repo_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"pattern": "x", "path": str(repo)},
            "session_id": _SESSION,
        }

        assert handler.matches(hook_input) is True

    def test_a_glob_scoped_to_a_governed_repo_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py", "path": str(repo)},
            "session_id": _SESSION,
        }

        assert handler.matches(hook_input) is True

    def test_a_bash_command_reading_a_governed_repo_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)

        assert handler.matches(_bash("cat untracked/repos/alpha/README.md")) is True

    def test_a_bash_command_running_from_inside_one_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`cd <repo> && rg x` reads the repo just as surely as `rg x <repo>`."""
        _repo(tmp_path)

        assert handler.matches(_bash("cd untracked/repos/alpha && rg pattern .")) is True

    def test_an_unrelated_bash_command_is_ignored(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)

        assert handler.matches(_bash("ls -la src/")) is False

    def test_it_does_nothing_when_disabled(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        handler._reference_repos = ReferenceReposConfig(enabled=False)

        assert handler.matches(_read(repo / "x.py")) is False

    def test_mode_off_disengages_entirely(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        handler._reference_repos = ReferenceReposConfig(mode="off")

        assert handler.matches(_read(repo / "x.py")) is False

    def test_an_uninjected_handler_carries_the_documented_defaults(self, tmp_path: Path) -> None:
        """Not None, and deliberately so.

        ``Config`` declares a ``default_factory`` for this block, so production
        never hands the registry an absent value. A None seed would exist only
        to be re-checked on every Read in the session — and a missed check would
        raise inside PreToolUse rather than degrade.
        """
        fresh = ReferenceRepoFreshnessHandler()
        fresh.project_root_reader = lambda: tmp_path
        repo = _repo(tmp_path)

        assert fresh._reference_repos == ReferenceReposConfig()
        assert fresh.matches(_read(repo / "x.py")) is True


class TestTheGitExemption:
    def test_the_remediation_command_it_prints_is_itself_allowed(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The invariant that keeps the handler satisfiable.

        Built from ``remediation_command`` rather than a hand-written string so
        that a change to the printed remedy cannot silently escape the exemption.
        """
        repo = _repo(tmp_path)
        state = _state(repo, behind=3)
        write_cache(tmp_path, [state])

        command = remediation_command(state)
        assert command is not None

        assert handler.matches(_bash(command)) is False

    def test_the_off_branch_remedy_is_allowed_too(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        state = _state(repo, branch="feature")
        write_cache(tmp_path, [state])

        command = remediation_command(state)
        assert command is not None

        assert handler.matches(_bash(command)) is False

    def test_an_absolute_path_to_git_is_still_git(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Respelling the command must not cost the exemption.

        This is the `git -C` lesson from test_blocking_handler_evasion pointed
        the other way: for this handler a respelling does not BYPASS anything,
        it strips the exemption and denies a legitimate remedy instead.
        """
        _repo(tmp_path)

        assert handler.matches(_bash("/usr/bin/git -C untracked/repos/alpha pull")) is False

    def test_any_git_invocation_against_a_governed_repo_passes(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Inspecting and fixing a repo is exactly the work this handler wants."""
        _repo(tmp_path)

        assert handler.matches(_bash("git -C untracked/repos/alpha status")) is False

    def test_navigating_in_and_then_running_git_is_exempt(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Task 4.3 says `-C <repo>` OR "run from inside it", and both must hold.

        Exempting only the `-C` form would mean a reader who does the obvious
        thing — cd in, then fix the repo — is blocked while doing exactly what
        the deny message asked for.
        """
        _repo(tmp_path)

        assert handler.matches(_bash("cd untracked/repos/alpha && git pull --ff-only")) is False

    def test_a_read_riding_behind_a_cd_and_a_git_still_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The exemption covers a git-only chain, not any chain containing git."""
        _repo(tmp_path)
        command = "cd untracked/repos/alpha && git pull --ff-only && cat README.md"

        assert handler.matches(_bash(command)) is True

    def test_a_non_git_command_in_the_same_chain_still_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """A git segment must not launder a read riding alongside it."""
        _repo(tmp_path)

        assert (
            handler.matches(
                _bash("git -C untracked/repos/alpha status && cat untracked/repos/alpha/x")
            )
            is True
        )


class TestVerdicts:
    def test_a_current_repo_is_allowed_silently(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_stale_repo_is_denied(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=4)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.DENY
        assert "4" in _reason(result)

    def test_the_deny_names_the_command_that_fixes_it(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=4)])

        result = handler.handle(_read(repo / "x.py"))

        assert "pull --ff-only" in _reason(result)

    def test_a_repo_on_the_wrong_branch_is_denied(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, branch="feature")])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.DENY

    def test_an_uncheckable_repo_is_never_denied(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The canary: an invalid origin BY DESIGN must never block a read."""
        repo = _repo(tmp_path, "php-qa-ci")
        write_cache(tmp_path, [_state(repo, checkability=Checkability.NO_REMOTE)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.ALLOW

    def test_a_dirty_repo_is_not_denied_for_being_dirty(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Local work is the user's business; only staleness gates a read."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, dirty=True)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.ALLOW


class TestBlockOnce:
    def test_the_second_read_of_the_same_repo_is_allowed(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Told once is the ruling: the block informs, it does not obstruct."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=4)])

        first = handler.handle(_read(repo / "x.py"))
        second = handler.handle(_read(repo / "y.py"))

        assert first.decision == Decision.DENY
        assert second.decision == Decision.ALLOW

    def test_the_allowed_retry_still_carries_the_warning(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Allowing silently would let the staleness vanish from view."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=4)])

        handler.handle(_read(repo / "x.py"))
        second = handler.handle(_read(repo / "y.py"))

        assert second.context

    def test_a_different_repo_still_blocks_once(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Per REPO, not per handler — each stale repo is its own surprise."""
        first_repo = _repo(tmp_path, "alpha")
        second_repo = _repo(tmp_path, "beta")
        write_cache(tmp_path, [_state(first_repo, behind=1), _state(second_repo, behind=2)])

        handler.handle(_read(first_repo / "x.py"))
        result = handler.handle(_read(second_repo / "x.py"))

        assert result.decision == Decision.DENY

    def test_a_different_session_still_blocks_once(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The daemon is shared across sessions (Plan 00127).

        One session consuming every other session's one-time block is the exact
        bug Plan 00277 fixed for lsp_enforcement.
        """
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=4)])

        handler.handle(_read(repo / "x.py", session=_SESSION))
        result = handler.handle(_read(repo / "x.py", session=_OTHER_SESSION))

        assert result.decision == Decision.DENY


class TestConfiguredModes:
    def test_block_mode_denies_every_time(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        handler._reference_repos = ReferenceReposConfig(mode="block")
        write_cache(tmp_path, [_state(repo, behind=4)])

        handler.handle(_read(repo / "x.py"))
        second = handler.handle(_read(repo / "y.py"))

        assert second.decision == Decision.DENY

    def test_advise_mode_never_denies(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        handler._reference_repos = ReferenceReposConfig(mode="advise")
        write_cache(tmp_path, [_state(repo, behind=4)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.ALLOW
        assert result.context

    def test_advise_mode_still_says_it_every_time(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        handler._reference_repos = ReferenceReposConfig(mode="advise")
        write_cache(tmp_path, [_state(repo, behind=4)])

        handler.handle(_read(repo / "x.py"))
        second = handler.handle(_read(repo / "y.py"))

        assert second.context


class TestNotVerified:
    def test_a_missing_cache_reads_as_not_verified(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """No reading is NOT the same as a clean reading."""
        repo = _repo(tmp_path)

        result = handler.handle(_read(repo / "x.py"))

        assert NOT_VERIFIED_HEADLINE in _reason(result)

    def test_not_verified_also_honours_block_once(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)

        first = handler.handle(_read(repo / "x.py"))
        second = handler.handle(_read(repo / "y.py"))

        assert first.decision == Decision.DENY
        assert second.decision == Decision.ALLOW

    def test_an_expired_cache_reads_as_not_verified(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo)], now=0.0)

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.DENY
        assert NOT_VERIFIED_HEADLINE in _reason(result)

    def test_a_repo_absent_from_a_valid_cache_reads_as_not_verified(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """A repo cloned mid-session was never swept, so nothing is known of it."""
        known = _repo(tmp_path, "alpha")
        unknown = _repo(tmp_path, "beta")
        write_cache(tmp_path, [_state(known)])

        result = handler.handle(_read(unknown / "x.py"))

        assert result.decision == Decision.DENY


class TestAnUnreadableAncestor:
    """A path the process cannot stat must not take PreToolUse down with it.

    `_subject`'s disk fallback walks down from the governed root asking whether
    each level carries a `.git`. A raw `Path.exists()` RAISES PermissionError
    when an ancestor is not traversable, and it raises inside the hook — where
    the caller is a tool call, not a test.
    """

    @staticmethod
    def _unstattable(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Make every stat under the governed root raise, as EACCES would.

        Simulated rather than produced with ``chmod``: the suite runs as root
        here, and root traverses a ``0o000`` directory regardless of its mode —
        so a permissions fixture would pass while proving nothing. The defect
        is that a RAW predicate propagates ``OSError``, and raising at the
        predicate is exactly that condition.
        """
        locked = root / "untracked" / "repos" / "locked"
        real = Path.exists

        def _raise(self: Path) -> bool:
            if self.is_relative_to(root / "untracked" / "repos"):
                raise PermissionError(13, "Permission denied", str(self))
            return real(self)

        monkeypatch.setattr(Path, "exists", _raise)
        return locked

    def test_matching_degrades_instead_of_raising(
        self,
        tmp_path: Path,
        handler: ReferenceRepoFreshnessHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        locked = self._unstattable(tmp_path, monkeypatch)

        assert handler.matches(_read(locked / "x.py")) is False

    def test_an_unstattable_path_is_not_treated_as_a_checkout(
        self,
        tmp_path: Path,
        handler: ReferenceRepoFreshnessHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """'I could not look' must not become 'this is a governed clone'.

        Saying yes would deny a read the agent could not perform anyway, with a
        `fix:` command that cannot clear it — the same unclearable block the
        invented-subject bug produced. The cache is consulted BEFORE the disk,
        so a repo that really was swept is still found either way.
        """
        locked = self._unstattable(tmp_path, monkeypatch)

        result = handler.handle(_read(locked / "x.py"))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_a_cached_repo_is_still_found_when_the_disk_cannot_be_read(
        self,
        tmp_path: Path,
        handler: ReferenceRepoFreshnessHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The cache answers first, so permissions cannot switch the gate off."""
        locked = tmp_path / "untracked" / "repos" / "locked"
        write_cache(tmp_path, [_state(locked, behind=2)])
        self._unstattable(tmp_path, monkeypatch)

        result = handler.handle(_read(locked / "x.py"))

        assert result.decision == Decision.DENY


class TestAnUnconfirmedReading:
    """The silent case: a sweep ran and confirmed nothing.

    An offline session fetches nothing, so ``behind`` reads 0 off the refs
    already on disk, nothing needs attention, and the sweep stays quiet by
    design. Before this, the read path was quiet too — so an agent could spend
    a whole session reasoning from clones no one had checked, with no signal
    anywhere. The gate says it once per repo, at the moment of the read.
    """

    def test_a_failed_fetch_is_reported_when_the_repo_is_read(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, fetch_failed=True)])

        result = handler.handle(_read(repo / "x.py"))

        assert UNCONFIRMED_HEADLINE in "\n".join(result.context)

    def test_it_never_denies_even_under_mode_block(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """There is no command that makes an unreachable remote reachable.

        Denying here would make a clone with a deliberately invalid origin — the
        canary this project keeps — permanently unreadable, and the only way out
        would be turning the whole system off.
        """
        handler._reference_repos = ReferenceReposConfig(mode="block")
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, fetch_failed=True)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.ALLOW

    def test_an_uncheckable_repo_is_reported_the_same_way(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """No remote to reach and a remote that did not answer are one fact here."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, checkability=Checkability.NO_REMOTE)])

        result = handler.handle(_read(repo / "x.py"))

        assert UNCONFIRMED_HEADLINE in "\n".join(result.context)

    def test_it_speaks_once_per_repo_per_session(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, fetch_failed=True)])

        first = handler.handle(_read(repo / "x.py"))
        second = handler.handle(_read(repo / "y.py"))

        assert first.context != []
        assert second.context == []

    def test_a_different_session_hears_it_too(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The daemon outlives any one session, so 'once' must not be daemon-wide."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, fetch_failed=True)])

        handler.handle(_read(repo / "x.py"))
        other = handler.handle(_read(repo / "x.py", session=_OTHER_SESSION))

        assert UNCONFIRMED_HEADLINE in "\n".join(other.context)

    def test_a_confirmed_current_repo_says_nothing(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        _fresh_cache(tmp_path)

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_a_stale_repo_still_gets_the_stale_verdict_not_a_note(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Behind AND unfetchable: the actionable half must not be buried."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=3, fetch_failed=True)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.DENY
        assert UNCONFIRMED_HEADLINE not in _reason(result)

    def test_the_note_does_not_spend_the_repos_one_block(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Otherwise an unreachable remote at 09:00 silences a real staleness at 09:05."""
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, fetch_failed=True)])
        handler.handle(_read(repo / "x.py"))

        write_cache(tmp_path, [_state(repo, behind=2)])
        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.DENY


class TestTheArchitecturalInvariant:
    def test_the_handler_never_performs_network_io(
        self,
        tmp_path: Path,
        handler: ReferenceRepoFreshnessHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PreToolUse reads the cache and nothing else.

        One fetch here can consume the whole 30s hook socket budget, so any
        future change that shells out is caught by this test and no other.
        """
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=4)])

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("PreToolUse must not spawn a subprocess")

        monkeypatch.setattr(subprocess, "run", _forbidden)
        monkeypatch.setattr(subprocess, "Popen", _forbidden)
        monkeypatch.setattr(subprocess, "check_output", _forbidden)

        assert handler.matches(_read(repo / "x.py")) is True
        assert handler.handle(_read(repo / "x.py")).decision == Decision.DENY


class TestCallsItMustNotJudge:
    def test_a_write_into_a_governed_repo_does_not_engage(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """This gate is about READING stale source.

        Whether a reference clone should be written to at all is a different
        question with a different answer, and answering it here would block a
        deliberate local edit with a message about freshness.
        """
        repo = _repo(tmp_path)
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(repo / "x.py"), "content": "x = 1"},
            "session_id": _SESSION,
        }

        assert handler.matches(hook_input) is False

    def test_a_read_with_no_path_at_all_is_ignored(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """A malformed payload must not crash every Read in the session."""
        _repo(tmp_path)
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {},
            "session_id": _SESSION,
        }

        assert handler.matches(hook_input) is False

    def test_empty_command_segments_are_skipped(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`cmd && ` and friends leave an empty segment behind."""
        _repo(tmp_path)

        assert handler.matches(_bash("cat untracked/repos/alpha/x.md && ")) is True


class TestWordsThatStillNameAPath:
    """Regression: three shapes slipped through entirely.

    Found by probing the parser rather than by a failing test — every existing
    case happened to use a bare unquoted path. `segment.split()` keeps quote
    characters attached to the word, so `Path("'untracked/repos/alpha/x.md'")`
    is not relative to any governed root, and the read was invisible.

    A false negative here is the worst failure this handler has: it is silent,
    and silence from this gate reads as "that repo is fine".
    """

    def test_a_single_quoted_path_is_seen(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The plainest possible shape — and it was missed completely."""
        _repo(tmp_path)

        assert handler.matches(_bash("cat 'untracked/repos/alpha/x.md'")) is True

    def test_a_double_quoted_path_is_seen(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)

        assert handler.matches(_bash('cat "untracked/repos/alpha/some file.md"')) is True

    def test_a_path_hidden_behind_a_flag_is_seen(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`--file=<path>` reads the repo; skipping every `-` word missed it."""
        _repo(tmp_path)

        assert handler.matches(_bash("rg --file=untracked/repos/alpha/patterns.txt .")) is True

    def test_a_bare_flag_is_still_not_a_path(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The reason `-` words were skipped in the first place still holds."""
        _repo(tmp_path)

        assert handler.matches(_bash("ls -la --color=auto src/")) is False


class TestTextIsNotACommand:
    """Regression: this handler blocked the commit that shipped its own docs.

    `_CHAIN_SEPARATORS` includes "\\n", so every LINE of a `git commit -F -`
    heredoc became its own "segment". A prose line mentioning
    `untracked/repos/php-qa-ci` therefore parsed as a command reading a governed
    repo, and the commit was denied. Nothing was being read at all.

    The shell never treats these spans as commands, and neither may this
    handler — `shell_segmentation` already has the strippers for exactly this.
    """

    def test_a_commit_message_body_naming_a_governed_repo_is_not_a_read(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)
        command = (
            "git commit -F - <<'MSGEOF'\n"
            "Document the convention\n"
            "\n"
            "The canary lives at untracked/repos/php-qa-ci and is never pulled.\n"
            "MSGEOF"
        )

        assert handler.matches(_bash(command)) is False

    def test_an_inline_git_message_naming_a_governed_repo_is_not_a_read(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)

        assert handler.matches(_bash("git commit -m 'note untracked/repos/alpha'")) is False

    def test_a_quoted_heredoc_body_is_never_scanned(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """A quoted delimiter makes the body literal text being WRITTEN."""
        _repo(tmp_path)
        command = "cat > notes.md <<'EOF'\nsee untracked/repos/alpha for details\nEOF"

        assert handler.matches(_bash(command)) is False

    def test_a_real_read_on_a_later_line_still_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Stripping inert spans must not blind the handler to actual commands."""
        _repo(tmp_path)
        command = (
            "git commit -m 'mentions untracked/repos/alpha'\ncat untracked/repos/alpha/README.md"
        )

        assert handler.matches(_bash(command)) is True


class TestOnlyRealCheckoutsAreGoverned:
    """Regression: a path under a root that is NOT a checkout was gated.

    The worst defect this handler had. Discovery only ever caches directories
    carrying a `.git` (discovery.py), so a subject invented for a non-checkout
    path can never appear in any cache — no sweep and no CLI run could clear it.
    The reader was handed a `fix:` command that was incapable of working, which
    under `mode: block` is a permanent dead end.

    Reported by review with a live reproduction: `ls untracked/repos` was denied
    in this repository with a fresh, in-date cache sitting on disk.
    """

    def test_listing_the_root_itself_is_not_a_read_of_any_repo(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)
        _fresh_cache(tmp_path)

        assert handler.matches(_bash("ls untracked/repos")) is False

    def test_a_loose_file_under_the_root_is_not_a_repo(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)
        notes = tmp_path / "untracked" / "repos" / "NOTES.md"
        notes.write_text("not a checkout", encoding="utf-8")
        _fresh_cache(tmp_path)

        assert handler.matches(_read(notes)) is False

    def test_a_plain_subdirectory_under_the_root_is_not_a_repo(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        _repo(tmp_path)
        scratch = tmp_path / "untracked" / "repos" / "scratch"
        scratch.mkdir()
        _fresh_cache(tmp_path)

        assert handler.matches(_read(scratch / "x.md")) is False

    def test_a_real_checkout_is_still_governed(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The narrowing must not blind the handler to actual repos."""
        repo = _repo(tmp_path)

        assert handler.matches(_read(repo / "src" / "x.py")) is True

    def test_a_clone_made_after_the_sweep_is_still_governed(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """It is on disk as a checkout but in no cache — the NOT VERIFIED case."""
        _repo(tmp_path, "alpha")
        fresh = _repo(tmp_path, "cloned-midsession")
        _fresh_cache(tmp_path)

        result = handler.handle(_read(fresh / "x.py"))

        assert result.decision == Decision.DENY
        assert NOT_VERIFIED_HEADLINE in _reason(result)


class TestCommandsThatCannotRead:
    """Regression: a governed path in ANY argument position counted as a read.

    Naming a repo is not reading it. Denying `rm -rf <repo>` with "run
    `git pull` first" is advice that makes no sense for the command being run.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf untracked/repos/alpha",
            "mkdir -p untracked/repos/alpha-new",
            "echo see untracked/repos/alpha for details",
            "gh repo clone o/x untracked/repos/alpha",
            "touch untracked/repos/alpha/marker",
        ],
    )
    def test_a_non_reading_command_does_not_engage(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler, command: str
    ) -> None:
        _repo(tmp_path)

        assert handler.matches(_bash(command)) is False

    def test_a_reading_command_on_the_same_path_still_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The counterweight: narrowing must not turn the gate off."""
        _repo(tmp_path)

        assert handler.matches(_bash("cat untracked/repos/alpha/x.md")) is True


class TestQuotedArgumentsAreTokenisedProperly:
    def test_a_path_with_a_space_is_extracted_whole(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`str.split()` cut this at the space and matched `.../alpha/some`.

        The old test asserted only that the command ENGAGED, which it did — via
        a truncated path that happened to still sit under the root. It passed
        for the wrong reason, so it is now asserted on the extracted path.
        """
        repo = _repo(tmp_path)

        touched = handler._touched_paths(
            _bash('cat "untracked/repos/alpha/some file.md"'), tmp_path
        )

        assert touched == [repo / "some file.md"]


class TestGitOnlyChainShapes:
    """Regression: three git-only shapes were intercepted.

    The deny message itself promises "`git` is NEVER intercepted", so any shape
    that slips through makes the handler's own explanation untrue.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git -C untracked/repos/alpha pull --ff-only",
            "/usr/bin/git -C untracked/repos/alpha pull",
            "cd untracked/repos/alpha && git pull --ff-only",
            "(cd untracked/repos/alpha && git pull)",
            "cd untracked/repos/alpha && git log | cat",
            "cd untracked/repos/alpha && git commit -F - <<'EOF'\nmsg\nEOF",
        ],
    )
    def test_a_git_only_chain_is_never_intercepted(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler, command: str
    ) -> None:
        _repo(tmp_path)

        assert handler.matches(_bash(command)) is False

    def test_navigating_in_and_then_reading_still_engages(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`cd <repo> && rg x` reads it without ever naming a governed path."""
        _repo(tmp_path)

        assert handler.matches(_bash("cd untracked/repos/alpha && rg pattern .")) is True


class TestMalformedInputDegrades:
    def test_an_unbalanced_quote_does_not_raise(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`shlex` refuses this; a PreToolUse hook must not.

        Half-typed commands reach hooks all the time. Raising here would cost
        the user their tool call over a quote they were still in the middle of.
        """
        _repo(tmp_path)

        assert handler.matches(_bash("cat 'untracked/repos/alpha/x.md")) is True

    def test_a_second_governed_root_is_skipped_when_the_path_is_not_under_it(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        repo = _repo(tmp_path)
        handler._reference_repos = ReferenceReposConfig(roots=["vendor", "untracked/repos"])

        assert handler.matches(_read(repo / "x.py")) is True


class TestSubjectResolution:
    def test_a_call_scoped_to_the_root_itself_names_no_repo(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """`rg pattern untracked/repos` attributes to no checkout, so it passes.

        This test previously asserted the OPPOSITE — that the root became its
        own subject — which pinned the defect rather than the behaviour: that
        subject could never be cached, so the deny it produced was unclearable.
        A search across the root is a real gap in coverage, but the answer to it
        is to judge the repos beneath, never to invent one that does not exist.
        """
        _repo(tmp_path)

        assert handler.handle(_bash("rg pattern untracked/repos")).decision == Decision.ALLOW

    def test_the_deepest_containing_repo_wins(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """A checkout nested under another must be judged on ITS own reading."""
        outer = _repo(tmp_path, "outer")
        inner = outer / "vendor" / "inner"
        (inner / ".git").mkdir(parents=True)
        write_cache(tmp_path, [_state(outer, behind=0), _state(inner, behind=7)])

        result = handler.handle(_read(inner / "x.py"))

        assert result.decision == Decision.DENY
        assert "7" in _reason(result)


class TestDirtyRepoWording:
    def test_a_dirty_stale_repo_is_told_there_is_no_mechanical_fix(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Every mechanical remedy would move a tree carrying someone's work.

        The plan forbids that outright, so the message must say so rather than
        print a command that would cost them the changes.
        """
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=3, dirty=True)])

        result = handler.handle(_read(repo / "x.py"))

        assert result.decision == Decision.DENY
        assert "uncommitted local changes" in _reason(result)
        assert "fix:" not in _reason(result)


class TestStateIsBounded:
    def test_block_once_state_does_not_grow_without_limit(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """The daemon outlives any one session, so the map needs a ceiling.

        Evicting the oldest costs at most one extra advisory in a session nobody
        has touched in a long time.
        """
        repo = _repo(tmp_path)
        write_cache(tmp_path, [_state(repo, behind=1)])

        for index in range(200):
            handler.handle(_read(repo / "x.py", session=f"session-{index}"))

        assert len(handler._reported) <= 64


class TestPathDisplay:
    def test_a_governed_repo_is_named_the_way_a_reader_recognises_it(
        self, tmp_path: Path, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Project-relative, and via the SHARED renderer.

        A repo called one thing when a read is blocked and another thing when
        the CLI reports it reads as two separate problems rather than one.
        """
        repo = _repo(tmp_path)

        result = handler.handle(_read(repo / "x.py"))

        assert "untracked/repos/alpha" in _reason(result)
        assert str(tmp_path) not in _reason(result)

    def test_a_root_outside_the_repository_cannot_be_configured(self) -> None:
        """Why the handler never has to render an absolute path.

        The config validator rejects a root that escapes the repository, so the
        absolute branch in `display_path` is reachable only from the CLI, which
        renders whatever readings it is handed.
        """
        with pytest.raises(ValidationError):
            ReferenceReposConfig(roots=["../elsewhere"])


class TestTheDefaultProjectRootReader:
    def test_it_resolves_from_the_project_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The injected reader is a test seam; the real one must work too."""
        monkeypatch.setattr(ProjectContext, "project_root", classmethod(lambda cls: tmp_path))

        assert ReferenceRepoFreshnessHandler().project_root_reader() == tmp_path


class TestHandlerContract:
    def test_it_documents_itself_for_the_generated_guidance(
        self, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        guidance = handler.get_claude_md()

        assert guidance
        assert "reference" in guidance.lower()

    def test_it_declares_an_acceptance_test(self, handler: ReferenceRepoFreshnessHandler) -> None:
        assert handler.get_acceptance_tests()

    def test_it_declares_both_rules_distinctly(
        self, handler: ReferenceRepoFreshnessHandler
    ) -> None:
        """Stale and NOT VERIFIED are different facts and get different IDs."""
        ids = {rule.rule_id for rule in handler.get_rules()}

        assert ids == {RuleID.REFERENCE_REPO_STALE, RuleID.REFERENCE_REPO_NOT_VERIFIED}

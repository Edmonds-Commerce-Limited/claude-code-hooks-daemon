"""A sub-agent writes only inside the worktree it was given (ledger 00474 N264).

Found when a landing agent's clean-tree check failed: three files in
``worktree-n466-n253`` held 253 added lines written in one second by a
sub-agent working in a SIBLING worktree. Nothing in the daemon stopped a
sub-agent writing outside the worktree it was dispatched into.

Real repositories and real ``git worktree add``: worktree membership is a
fact git wrote to disk, and a mocked path comparison would prove only that the
mock agrees with itself.
"""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.pre_tool_use import (
    subagent_worktree_write_guard as guard_module,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_worktree_write_guard import (
    SubagentWorktreeWriteGuardHandler,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "src").mkdir()
    (root / "src" / "mod.py").write_text("x = 1\n")
    _git(root, "add", "src/mod.py")
    _git(root, "commit", "-q", "-m", "init")
    return root.resolve()


def _worktree(repo: Path, where: Path, branch: str) -> Path:
    where.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", branch, str(where))
    return where.resolve()


@pytest.fixture
def wt_a(repo: Path, tmp_path: Path) -> Path:
    return _worktree(repo, tmp_path / "wt" / "a", "a")


@pytest.fixture
def wt_b(repo: Path, tmp_path: Path) -> Path:
    return _worktree(repo, tmp_path / "wt" / "b", "b")


def _event(
    target: Path | str,
    cwd: Path | str,
    tool: str = "Write",
    key: str = "file_path",
) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {key: str(target)},
        "cwd": str(cwd),
        "agent_id": "agent-1",
    }


@pytest.fixture
def handler() -> SubagentWorktreeWriteGuardHandler:
    return SubagentWorktreeWriteGuardHandler()


class TestScope:
    def test_scoped_to_subagents_so_the_coordinator_is_never_judged(
        self, handler: SubagentWorktreeWriteGuardHandler
    ) -> None:
        """The main thread merges and edits across worktrees legitimately. The
        role test is the chain's scope gate, not a second copy in here."""
        assert handler.scope is HandlerScope.SUB

    def test_on_by_default_and_terminal(self, handler: SubagentWorktreeWriteGuardHandler) -> None:
        assert handler.get_default_enabled() is True
        assert handler.terminal is True


class TestThroughTheChain:
    """The role test lives in the chain: same crossing write, two roles."""

    def test_denied_for_a_subagent_and_never_judged_on_the_main_thread(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        chain = HandlerChain()
        chain.add(handler)
        event = _event(wt_b / "src" / "mod.py", cwd=wt_a)
        assert chain.execute(dict(event)).result.decision is Decision.DENY
        main_thread = dict(event)
        del main_thread["agent_id"]
        assert chain.execute(main_thread).result.decision is Decision.ALLOW


class TestDenies:
    def test_a_write_into_a_sibling_worktree(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        event = _event(wt_b / "src" / "mod.py", cwd=wt_a)
        assert handler.matches(event) is True
        result = handler.handle(event)
        assert result.decision is Decision.DENY
        reason = result.reason or ""
        assert str(wt_a) in reason
        assert str(wt_b) in reason
        assert "coordinator" in reason.lower()
        assert RuleID.SUBAGENT_CROSS_WORKTREE_WRITE in reason

    def test_a_write_into_the_main_working_tree(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path
    ) -> None:
        event = _event(repo / "src" / "mod.py", cwd=wt_a)
        assert handler.matches(event) is True
        reason = handler.handle(event).reason or ""
        assert str(repo) in reason
        assert "main working tree" in reason

    def test_an_edit_of_a_file_that_does_not_exist_yet_in_a_sibling(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        event = _event(wt_b / "brand" / "new" / "file.py", cwd=wt_a, tool="Edit")
        assert handler.matches(event) is True

    def test_a_notebook_edit_names_notebook_path(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        event = _event(wt_b / "n.ipynb", cwd=wt_a, tool="NotebookEdit", key="notebook_path")
        assert handler.matches(event) is True

    def test_a_relative_target_is_read_against_the_cwd(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        relative = Path("..") / "b" / "src" / "mod.py"
        assert handler.matches(_event(relative, cwd=wt_a)) is True

    def test_a_symlink_into_a_sibling_is_followed(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        wt_a: Path,
        wt_b: Path,
        tmp_path: Path,
    ) -> None:
        link = wt_a / "shortcut"
        link.symlink_to(wt_b)
        assert handler.matches(_event(link / "src" / "mod.py", cwd=wt_a)) is True

    def test_a_subdirectory_cwd_is_still_the_same_worktree(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=wt_a / "src")) is True


class TestNestedWorktrees:
    """A worktree directory inside the main tree belongs to the WORKTREE, not
    to the main tree that happens to contain it."""

    def test_a_nested_worktrees_own_files_are_allowed(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path
    ) -> None:
        nested = _worktree(repo, repo / "untracked" / "worktrees" / "x", "x")
        assert handler.matches(_event(nested / "src" / "mod.py", cwd=nested)) is False

    def test_a_nested_worktree_writing_to_the_main_tree_is_denied(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path
    ) -> None:
        nested = _worktree(repo, repo / "untracked" / "worktrees" / "x", "x")
        event = _event(repo / "src" / "mod.py", cwd=nested)
        assert handler.matches(event) is True
        reason = handler.handle(event).reason or ""
        assert str(nested) in reason and "main working tree" in reason

    def test_two_nested_siblings_are_distinct(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path
    ) -> None:
        x = _worktree(repo, repo / "untracked" / "worktrees" / "x", "x")
        y = _worktree(repo, repo / ".claude" / "worktrees" / "y", "y")
        event = _event(y / "src" / "mod.py", cwd=x)
        assert handler.matches(event) is True
        reason = handler.handle(event).reason or ""
        assert str(x) in reason and str(y) in reason


class TestAllows:
    def test_a_write_inside_its_own_worktree(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        assert handler.matches(_event(wt_a / "src" / "mod.py", cwd=wt_a)) is False

    def test_a_new_file_inside_its_own_worktree(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        assert handler.matches(_event(wt_a / "new" / "deep" / "f.py", cwd=wt_a / "src")) is False

    def test_a_subagent_in_the_main_tree_is_not_judged(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path
    ) -> None:
        assert handler.matches(_as("one", _event(wt_a / "src" / "mod.py", cwd=repo))) is False
        assert handler.matches(_as("two", _event(repo / "src" / "mod.py", cwd=repo))) is False

    def test_a_write_outside_the_repository_is_out_of_scope(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere" / "f.txt"
        assert handler.matches(_event(outside, cwd=wt_a)) is False

    def test_a_different_repository_is_not_this_ones_worktree(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init", "-q", "-b", "main")
        assert handler.matches(_event(other / "f.py", cwd=wt_a)) is False

    def test_a_repository_nested_in_a_worktree_is_its_own_checkout(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        inner = wt_a / "vendored"
        inner.mkdir()
        _git(inner, "init", "-q", "-b", "main")
        assert handler.matches(_event(inner / "f.py", cwd=wt_a)) is False

    @pytest.mark.parametrize("tool", ["Read", "Bash", "Glob", "CronDelete"])
    def test_other_tools_never_match(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path, tool: str
    ) -> None:
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=wt_a, tool=tool)) is False

    def test_a_missing_target_never_matches(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        event = {"tool_name": "Write", "tool_input": {}, "cwd": str(wt_a)}
        assert handler.matches(event) is False

    def test_a_non_string_target_never_matches(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        event = {"tool_name": "Write", "tool_input": {"file_path": 7}, "cwd": str(wt_a)}
        assert handler.matches(event) is False


class TestUndecidableAllowsAndSaysSo:
    """Fail open, loudly in the debug log: a guard that cannot tell must not
    block a call it has no evidence against."""

    def test_no_cwd_allows(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        wt_b: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        event = _event(wt_b / "src" / "mod.py", cwd="")
        del event["cwd"]
        with caplog.at_level(logging.DEBUG):
            assert handler.matches(event) is False
        assert "no cwd" in caplog.text

    def test_a_cwd_in_no_repository_allows(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        wt_b: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with caplog.at_level(logging.DEBUG):
            assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=plain)) is False
        assert "not inside a git checkout" in caplog.text

    def test_an_unreadable_git_marker_on_the_target_side_allows(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        wt_a: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text("garbage\n")
        with caplog.at_level(logging.DEBUG):
            assert handler.matches(_event(broken / "f.py", cwd=wt_a)) is False
        assert "undecidable" in caplog.text

    def test_an_unreadable_git_marker_on_the_cwd_side_allows_in_matches_and_handle(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        wt_b: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text("garbage\n")
        event = _event(wt_b / "src" / "mod.py", cwd=broken)
        with caplog.at_level(logging.DEBUG):
            assert handler.matches(event) is False
            assert handler.handle(event).decision is Decision.ALLOW
        assert "undecidable" in caplog.text

    def test_a_nul_byte_target_allows(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        assert handler.matches(_event("/tmp/a\0b", cwd=wt_a)) is False

    def test_handle_on_an_event_that_no_longer_crosses_allows(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path
    ) -> None:
        result = handler.handle(_event(wt_a / "src" / "mod.py", cwd=wt_a))
        assert result.decision is Decision.ALLOW


def _as(agent_id: str, event: dict[str, Any]) -> dict[str, Any]:
    return {**event, "agent_id": agent_id}


class TestUnboundAgentsFallBackToTheCwd:
    """Ledger 00474 N282: with no binding, the payload ``cwd`` is the own-checkout
    signal, exactly as before. Nothing in a payload names the worktree a
    teammate was assigned, so the guard learns it from the first write."""

    def test_no_agent_id_is_judged_by_the_cwd_and_binds_nothing(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, wt_b: Path
    ) -> None:
        anonymous = _event(wt_b / "src" / "mod.py", cwd=repo)
        del anonymous["agent_id"]
        assert handler.matches(anonymous) is False
        # still nothing bound: a sibling write from the main tree is not stopped
        assert handler.matches(_event(wt_a / "src" / "mod.py", cwd=repo)) is False

    def test_an_unknown_agent_is_judged_by_the_cwd(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=wt_a)) is True

    def test_a_first_write_the_cwd_rule_denies_binds_nothing(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, wt_b: Path
    ) -> None:
        """A denied crossing must not become the agent's home: otherwise one
        retry from a different cwd would launder the crossing."""
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=wt_a)) is True
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=repo)) is False
        # that second call bound B, so A is now foreign
        assert handler.matches(_event(wt_a / "src" / "mod.py", cwd=repo)) is True

    def test_other_identity_fields_do_not_change_the_verdict(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        """Only ``agent_id`` is read, and only as a binding key."""
        event = _event(wt_b / "src" / "mod.py", cwd=wt_a)
        event["agent_type"] = "general-purpose"
        event["transcript_path"] = str(wt_b / "transcript.jsonl")
        assert handler.matches(event) is True


class TestFirstWriteBindsTheAgentToItsWorktree:
    """Ledger 00474 N282: ``agent_id`` is bound to the linked worktree of its
    first write and later writes are judged against that, not the shared cwd."""

    def test_a_bound_agent_may_write_home_whatever_the_cwd_says(
        self, handler: SubagentWorktreeWriteGuardHandler, wt_a: Path, wt_b: Path
    ) -> None:
        """Fixes the false deny: the coordinator ``cd``ed into A, the agent's
        worktree is B."""
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=wt_b)) is False
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=wt_a)) is False
        assert handler.matches(_event(wt_b / "new" / "f.py", cwd=wt_a, tool="Edit")) is False

    def test_a_bound_agent_is_denied_a_sibling_even_from_the_main_tree_cwd(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, wt_b: Path
    ) -> None:
        """Fixes the fail-open: the main-tree cwd is never judged, the binding is."""
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=repo)) is False
        event = _event(wt_a / "src" / "mod.py", cwd=repo)
        assert handler.matches(event) is True
        result = handler.handle(event)
        assert result.decision is Decision.DENY
        reason = result.reason or ""
        assert RuleID.SUBAGENT_CROSS_WORKTREE_WRITE in reason
        assert str(wt_b) in reason
        assert str(wt_a / "src" / "mod.py") in reason or str(wt_a) in reason
        assert "first write" in reason

    def test_a_bound_agent_is_denied_the_main_working_tree(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path
    ) -> None:
        assert handler.matches(_event(wt_a / "src" / "mod.py", cwd=repo)) is False
        event = _event(repo / "src" / "mod.py", cwd=repo)
        assert handler.matches(event) is True
        reason = handler.handle(event).reason or ""
        assert "main working tree" in reason and str(wt_a) in reason

    def test_a_first_write_into_the_main_tree_binds_nothing(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, wt_b: Path
    ) -> None:
        assert handler.matches(_event(repo / "src" / "mod.py", cwd=repo)) is False
        # still unbound: this write is the one that binds, to A
        assert handler.matches(_event(wt_a / "src" / "mod.py", cwd=repo)) is False
        assert handler.matches(_event(wt_b / "src" / "mod.py", cwd=repo)) is True

    def test_two_agents_bind_to_different_worktrees_independently(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, wt_b: Path
    ) -> None:
        assert handler.matches(_as("one", _event(wt_a / "f.py", cwd=repo))) is False
        assert handler.matches(_as("two", _event(wt_b / "f.py", cwd=repo))) is False
        assert handler.matches(_as("one", _event(wt_a / "g.py", cwd=wt_b))) is False
        assert handler.matches(_as("two", _event(wt_b / "g.py", cwd=wt_a))) is False
        assert handler.matches(_as("one", _event(wt_b / "g.py", cwd=repo))) is True
        assert handler.matches(_as("two", _event(wt_a / "g.py", cwd=repo))) is True

    def test_a_bound_agent_writing_outside_the_repository_is_out_of_scope(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, tmp_path: Path
    ) -> None:
        assert handler.matches(_event(wt_a / "f.py", cwd=repo)) is False
        assert handler.matches(_event(tmp_path / "elsewhere" / "f.txt", cwd=repo)) is False

    def test_a_bound_agent_writing_into_another_repository_is_out_of_scope(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init", "-q", "-b", "main")
        assert handler.matches(_event(wt_a / "f.py", cwd=repo)) is False
        assert handler.matches(_event(other / "f.py", cwd=repo)) is False

    def test_an_undecidable_cwd_does_not_stop_a_bound_agent_writing_home(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, tmp_path: Path
    ) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text("garbage\n")
        assert handler.matches(_event(wt_a / "f.py", cwd=repo)) is False
        assert handler.matches(_event(wt_a / "g.py", cwd=broken)) is False

    def test_an_undecidable_target_still_fails_open_for_a_bound_agent(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        repo: Path,
        wt_a: Path,
        tmp_path: Path,
    ) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text("garbage\n")
        assert handler.matches(_event(wt_a / "f.py", cwd=repo)) is False
        event = _event(broken / "f.py", cwd=repo)
        assert handler.matches(event) is False
        assert handler.handle(event).decision is Decision.ALLOW


class TestBindingsAreBounded:
    def test_the_oldest_binding_is_evicted_past_the_cap(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        repo: Path,
        wt_a: Path,
        wt_b: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(guard_module, "MAX_BINDINGS", 2)
        assert handler.matches(_as("one", _event(wt_a / "f.py", cwd=repo))) is False
        assert handler.matches(_as("two", _event(wt_b / "f.py", cwd=repo))) is False
        assert handler.matches(_as("three", _event(wt_a / "f.py", cwd=repo))) is False
        # "one" was evicted, so it is unbound again and falls back to the cwd rule
        assert handler.matches(_as("one", _event(wt_b / "f.py", cwd=repo))) is False
        # "three" is still bound to A
        assert handler.matches(_as("three", _event(wt_b / "f.py", cwd=repo))) is True

    def test_a_recently_used_binding_survives_eviction(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        repo: Path,
        wt_a: Path,
        wt_b: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(guard_module, "MAX_BINDINGS", 2)
        assert handler.matches(_as("one", _event(wt_a / "f.py", cwd=repo))) is False
        assert handler.matches(_as("two", _event(wt_b / "f.py", cwd=repo))) is False
        assert handler.matches(_as("one", _event(wt_a / "g.py", cwd=repo))) is False  # refresh
        assert handler.matches(_as("three", _event(wt_a / "f.py", cwd=repo))) is False
        assert handler.matches(_as("one", _event(wt_b / "f.py", cwd=repo))) is True

    def test_the_map_never_outgrows_the_cap(
        self,
        handler: SubagentWorktreeWriteGuardHandler,
        repo: Path,
        wt_a: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(guard_module, "MAX_BINDINGS", 5)
        for n in range(40):
            handler.matches(_as(f"agent-{n}", _event(wt_a / "f.py", cwd=repo)))
        assert handler.binding_count() == 5


class TestConcurrentCalls:
    def test_many_agents_binding_at_once_each_keep_their_own_worktree(
        self, handler: SubagentWorktreeWriteGuardHandler, repo: Path, wt_a: Path, wt_b: Path
    ) -> None:
        homes = {f"agent-{n}": (wt_a, wt_b) if n % 2 else (wt_b, wt_a) for n in range(60)}

        def run(agent_id: str) -> tuple[bool, bool]:
            home, other = homes[agent_id]
            first = handler.matches(_as(agent_id, _event(home / "f.py", cwd=repo)))
            foreign = handler.matches(_as(agent_id, _event(other / "f.py", cwd=repo)))
            return first, foreign

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(run, homes))
        assert results == [(False, True)] * len(homes)


class TestGuidanceAndAcceptance:
    def test_the_claude_md_guidance_states_the_standing_rule(
        self, handler: SubagentWorktreeWriteGuardHandler
    ) -> None:
        text = handler.get_claude_md() or ""
        assert "subagent_worktree_write_guard" in text
        assert "coordinator" in text.lower()

    def test_the_claude_md_guidance_states_the_first_write_binding(
        self, handler: SubagentWorktreeWriteGuardHandler
    ) -> None:
        text = (handler.get_claude_md() or "").lower()
        assert "first write" in text
        assert "agent_id" in text

    def test_every_acceptance_test_declares_why_the_harness_cannot_drive_it(
        self, handler: SubagentWorktreeWriteGuardHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert tests, "guard the guard: an empty list would pass the loop below"
        for test in tests:
            assert "synthetic" in (test.harness_cannot_produce or "").lower(), test.title

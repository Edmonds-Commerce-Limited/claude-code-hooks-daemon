"""Tests for HumanApprovalCheckHandler (Plan 00634 Task 2.2).

A coordinator seat's push, delete, world-writable chmod or merge into main
needs a cited questions-room line a declared human sent. The handler fails
closed once armed and stays silent for a session with no team seat.

Injection seams the handler exposes for these tests:

- ``_mode``: ``off`` | ``advise`` | ``block`` (option ``mode``)
- ``_coordinator_seats_only``: Q5 (option ``coordinator_seats_only``)
- ``_resolver``: anything with ``resolve(signals) -> SeatContext``; built
  lazily from ``_team_seat`` when None
- ``_verifier``: a :data:`Verifier`, default ``DEFAULT_VERIFIER``
- ``_records``: an :class:`ApprovalRecords`
"""

from __future__ import annotations

import builtins
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support import teamchat as fx

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use import human_approval_check as module
from claude_code_hooks_daemon.handlers.pre_tool_use.human_approval_check import (
    HumanApprovalCheckHandler,
    cite_from_command,
    classify_acts,
)
from claude_code_hooks_daemon.utils.human_approval import (
    DEFAULT_VERIFIER,
    ActClass,
    ApprovalCite,
    ApprovalRecords,
    Refusal,
    VerifiedLine,
    VerifyFailure,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    SeatContext,
    SessionSignals,
    parse_whoami,
)

RUNTIME = "/tmp/teamchat/run-a"
KIT = "/opt/teamchat-kit"
CWD = "/repo"
CITE_COMMENT = f"  # human-approval team=alpha id={fx.HUMAN_ID}"
PUSH = "git push origin feature"
CITED_PUSH = PUSH + CITE_COMMENT

COORDINATOR = parse_whoami(fx.COORDINATOR_ONLY)
WORKER = parse_whoami(fx.WORKER_ONLY)
ROLE_UNKNOWN = parse_whoami(fx.ROLE_NULL)
UNRESOLVED = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)

HUMAN_LINE = VerifiedLine(
    team="alpha", event_id=fx.HUMAN_ID, room="questions", declared_human=True, question="Q7"
)
_VERIFIED_WORD = re.compile(r"\bverified\b", re.IGNORECASE)


def bash(command: str, *, runtime: str = RUNTIME, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        HookInputField.TOOL_NAME: "Bash",
        HookInputField.TOOL_INPUT: {"command": command},
        HookInputField.CWD: CWD,
        HookInputField.TEAMCHAT_KIT: KIT,
        **extra,
    }
    if runtime:
        payload[HookInputField.TEAMCHAT_RUNTIME] = runtime
    return payload


def subagent(command: str) -> dict[str, Any]:
    return bash(command, agent_id="a1b2c3d4e5f6a7b8c")


class FakeResolver:
    def __init__(self, context: SeatContext | Exception) -> None:
        self._context = context
        self.calls: list[SessionSignals] = []

    def resolve(self, signals: SessionSignals, **_: Any) -> SeatContext:
        self.calls.append(signals)
        if isinstance(self._context, Exception):
            raise self._context
        return self._context


def human_verifier(_signals: SessionSignals, _cite: ApprovalCite) -> VerifiedLine:
    return HUMAN_LINE


def exploding_verifier(_signals: SessionSignals, _cite: ApprovalCite) -> VerifiedLine:
    raise RuntimeError("verifier crashed")


def _exploding_classify(_command: str, _cwd: Path) -> frozenset[ActClass]:
    raise RuntimeError("classifier crashed")


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture(autouse=True)
def _main_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every merge in these tests is in a readable main checkout on its default branch."""
    monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: True)


def make(
    context: SeatContext | Exception = COORDINATOR,
    *,
    mode: str = "block",
    coordinator_seats_only: bool = True,
    verifier: Any = DEFAULT_VERIFIER,
) -> tuple[HumanApprovalCheckHandler, FakeResolver]:
    handler = HumanApprovalCheckHandler()
    resolver = FakeResolver(context)
    handler._mode = mode
    handler._coordinator_seats_only = coordinator_seats_only
    handler._resolver = resolver
    handler._verifier = verifier
    handler._records = ApprovalRecords()
    return handler, resolver


# --- identity --------------------------------------------------------------------


class TestIdentity:
    def test_priority_follows_merge_to_main_approval(self) -> None:
        assert HumanApprovalCheckHandler().priority == 21

    def test_tags_are_workflow_blocking_terminal_and_not_git(self) -> None:
        tags = set(HumanApprovalCheckHandler().tags)
        assert {HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL} <= tags
        assert HandlerTag.GIT not in tags
        assert HandlerTag.SAFETY not in tags

    def test_declares_team_seat_for_injection(self) -> None:
        assert hasattr(HumanApprovalCheckHandler(), "_team_seat")


# --- act classification (pure) ------------------------------------------------------


class TestClassifyActs:
    @pytest.mark.parametrize(
        ("command", "act"),
        [
            ("git push origin feature", ActClass.PUSH),
            ("git push origin --delete feature", ActClass.DELETE),
            ("git branch -D feature", ActClass.DELETE),
            ("git worktree remove ../wt", ActClass.DELETE),
            ("chmod 777 shared", ActClass.PERMISSION),
            ("git merge feature", ActClass.MERGE_MAIN),
            ("gh pr merge 12 --merge", ActClass.MERGE_MAIN),
        ],
    )
    def test_each_act_class(self, command: str, act: ActClass) -> None:
        assert act in classify_acts(command, Path(CWD))

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m 'then git push origin main'",
            "cat > notes.md <<'EOF'\ngit push origin main\nEOF",
            "git status",
            "echo chmod 777 f",
        ],
    )
    def test_prose_and_harmless_name_no_act(self, command: str) -> None:
        assert classify_acts(command, Path(CWD)) == frozenset()

    @pytest.mark.parametrize(
        ("command", "act"),
        [
            ("git -C /srv/repo push origin feature", ActClass.PUSH),
            ("git --no-pager push origin feature", ActClass.PUSH),
            ("/usr/bin/git push origin feature", ActClass.PUSH),
            ("sudo git push origin feature", ActClass.PUSH),
            ("\\git push origin feature", ActClass.PUSH),
            ("cd /srv/repo && git push origin feature", ActClass.PUSH),
            ("git -C /srv/repo branch -D feature", ActClass.DELETE),
            ("/usr/bin/git worktree remove ../wt", ActClass.DELETE),
            ("sudo chmod 777 shared", ActClass.PERMISSION),
            ("git -C /srv/repo merge feature", ActClass.MERGE_MAIN),
        ],
    )
    def test_respelled_command_still_classifies(self, command: str, act: ActClass) -> None:
        """The evasion harness cannot arm a seat, so respellings are pinned here."""
        assert act in classify_acts(command, Path(CWD))

    def test_trailing_cite_comment_still_classifies_as_push(self) -> None:
        assert ActClass.PUSH in classify_acts(CITED_PUSH, Path(CWD))

    def test_unreadable_branch_with_a_merge_counts_as_merge_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: None)
        assert ActClass.MERGE_MAIN in classify_acts("git merge feature", Path(CWD))

    def test_linked_worktree_merge_is_not_merge_main(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: False)
        assert ActClass.MERGE_MAIN not in classify_acts("git merge feature", Path(CWD))

    @pytest.mark.parametrize("command", ["git send-pack origin x", "git http-push url x"])
    def test_plumbing_push_is_push(self, command: str) -> None:
        """Review finding 3: push plumbing is a push."""
        assert ActClass.PUSH in classify_acts(command, Path(CWD))

    @pytest.mark.parametrize(
        "command",
        [
            "gh -R o/r pr merge 5",
            "gh api -X PUT repos/o/r/pulls/5/merge",
            "gh api repos/o/r/merges -f base=main -f head=x",
        ],
    )
    def test_remote_merges_are_merge_main(
        self, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: False)
        assert ActClass.MERGE_MAIN in classify_acts(command, Path(CWD))

    @pytest.mark.parametrize(
        "command",
        [
            "git fetch . feature:main",
            "git fetch origin +feature:refs/heads/main",
            "git update-ref refs/heads/main abc123",
            "git branch -f main feature",
        ],
    )
    def test_moving_the_main_ref_from_anywhere_is_merge_main(
        self, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """These name the ref, so the checked-out branch and worktree do not matter."""
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: False)
        monkeypatch.setattr(module, "default_branch", lambda cwd: "main")
        assert ActClass.MERGE_MAIN in classify_acts(command, Path(CWD))

    @pytest.mark.parametrize(
        "command",
        [
            "git reset --hard feature",
            "git reset --hard",
            "git rebase feature",
            "git cherry-pick abc123",
            "git am < fix.patch",
        ],
    )
    def test_history_moves_on_main_are_merge_main(self, command: str) -> None:
        assert ActClass.MERGE_MAIN in classify_acts(command, Path(CWD))

    @pytest.mark.parametrize(
        "command",
        [
            "git reset --hard feature",
            "git rebase feature",
            "git cherry-pick abc123",
            "git fetch origin feature:feature",
            "git update-ref refs/heads/feature abc123",
            "git rebase --abort",
        ],
    )
    def test_history_moves_off_main_are_not_merge_main(
        self, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: False)
        monkeypatch.setattr(module, "default_branch", lambda cwd: "main")
        assert ActClass.MERGE_MAIN not in classify_acts(command, Path(CWD))

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout main && git merge feature",
            "git switch main && git reset --hard feature",
            "git checkout - && git merge feature",
            "git checkout $B && git merge feature",
            "git switch --detach && git cherry-pick abc",
        ],
    )
    def test_judged_against_the_branch_the_command_moves_to(
        self, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        """Issued from another branch; a switch to main, or one unreadable, counts."""
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: False)
        monkeypatch.setattr(module, "default_branch", lambda cwd: "main")
        assert ActClass.MERGE_MAIN in classify_acts(command, Path(CWD))

    def test_switch_away_from_main_then_merge_is_not_merge_main(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "default_branch", lambda cwd: "main")
        command = "git checkout feature && git merge other"
        assert ActClass.MERGE_MAIN not in classify_acts(command, Path(CWD))

    def test_pr_merge_is_merge_main_whatever_the_checkout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "merge_lands_on_main", lambda cwd, target: False)
        assert ActClass.MERGE_MAIN in classify_acts("gh pr merge 12", Path(CWD))


# --- the cite -----------------------------------------------------------------------


class TestCite:
    def test_trailing_comment_on_last_line(self) -> None:
        assert cite_from_command(CITED_PUSH) == ApprovalCite(team="alpha", event_id=fx.HUMAN_ID)

    @pytest.mark.parametrize(
        "command",
        [
            PUSH,
            PUSH + "  # human-approval team=alpha id=not-a-dollar-id",
            PUSH + "  # human-approval team= id=" + fx.HUMAN_ID,
            PUSH + CITE_COMMENT + " team=beta id=$second",
            PUSH + CITE_COMMENT + "\ngit status",
            "git commit -m '" + CITE_COMMENT.strip() + "' && " + PUSH,
        ],
    )
    def test_missing_malformed_or_doubled_is_none(self, command: str) -> None:
        assert cite_from_command(command) is None


# --- arming --------------------------------------------------------------------------


class TestArming:
    def test_no_runtime_is_silent_and_runs_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spawned: list[Any] = []
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
        handler = HumanApprovalCheckHandler()
        handler._mode = "block"
        assert handler.matches(bash(PUSH, runtime="")) is False
        assert spawned == []

    def test_no_runtime_never_asks_the_resolver(self) -> None:
        handler, resolver = make()
        assert handler.matches(bash(PUSH, runtime="")) is False
        assert resolver.calls == []

    def test_no_act_is_silent_for_an_armed_seat(self) -> None:
        handler, _ = make()
        assert handler.matches(bash("git status")) is False

    def test_classify_failure_counts_as_the_act_for_an_armed_seat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review finding 4: classifying runs AFTER arming, and fails closed there."""
        monkeypatch.setattr(module, "classify_acts", _exploding_classify)
        handler, _ = make(COORDINATOR)
        assert handler.matches(bash(PUSH)) is True
        result = handler.handle(bash(PUSH))
        assert result.decision == Decision.DENY

    @pytest.mark.parametrize("context", [WORKER, SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)])
    def test_classify_failure_is_silent_for_an_unarmed_seat(
        self, monkeypatch: pytest.MonkeyPatch, context: SeatContext
    ) -> None:
        monkeypatch.setattr(module, "classify_acts", _exploding_classify)
        handler, _ = make(context)
        assert handler.matches(bash(PUSH)) is False

    def test_classify_failure_is_silent_for_a_subagent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "classify_acts", _exploding_classify)
        handler, _ = make(COORDINATOR)
        assert handler.matches(subagent(PUSH)) is False

    def test_classify_failure_with_no_runtime_never_probes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "classify_acts", _exploding_classify)
        handler, resolver = make(COORDINATOR)
        assert handler.matches(bash(PUSH, runtime="")) is False
        assert resolver.calls == []

    def test_not_bash_is_silent(self) -> None:
        handler, _ = make()
        payload = bash(PUSH)
        payload[HookInputField.TOOL_NAME] = "Read"
        assert handler.matches(payload) is False

    def test_coordinator_is_armed(self) -> None:
        handler, _ = make(COORDINATOR)
        assert handler.matches(bash(PUSH)) is True

    def test_worker_seat_is_silent_with_q5_on(self) -> None:
        handler, _ = make(WORKER, coordinator_seats_only=True)
        assert handler.matches(bash(PUSH)) is False

    def test_worker_seat_is_armed_with_q5_off(self) -> None:
        handler, _ = make(WORKER, coordinator_seats_only=False)
        assert handler.matches(bash(PUSH)) is True

    @pytest.mark.parametrize("context", [ROLE_UNKNOWN, UNRESOLVED])
    def test_unknown_role_is_armed(self, context: SeatContext) -> None:
        handler, _ = make(context)
        assert handler.matches(bash(PUSH)) is True

    def test_absent_seat_is_silent(self) -> None:
        handler, _ = make(SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL))
        assert handler.matches(bash(PUSH)) is False

    def test_subagent_is_silent(self) -> None:
        handler, _ = make(COORDINATOR)
        assert handler.matches(subagent(PUSH)) is False

    def test_exception_before_arming_is_silent(self) -> None:
        handler, _ = make(RuntimeError("probe crashed"))
        assert handler.matches(bash(PUSH)) is False

    def test_mode_off_is_dormant(self) -> None:
        handler, resolver = make(mode="off")
        assert handler.is_dormant() is True
        assert handler.matches(bash(PUSH)) is False
        assert resolver.calls == []

    @pytest.mark.parametrize("mode", ["advise", "block"])
    def test_mode_on_is_not_dormant(self, mode: str) -> None:
        handler, _ = make(mode=mode)
        assert handler.is_dormant() is False


# --- the decision --------------------------------------------------------------------


def _text(result: Any) -> str:
    return " ".join([str(result.reason or ""), *[str(line) for line in result.context or []]])


class TestDecision:
    def test_no_cite_denies_in_block(self) -> None:
        handler, _ = make()
        result = handler.handle(bash(PUSH))
        assert result.decision == Decision.DENY
        assert "no well-formed cite" in _text(result)

    @pytest.mark.parametrize(
        "command",
        [
            PUSH + "  # human-approval team=alpha id=not-a-dollar-id",
            PUSH + CITE_COMMENT + " team=beta id=$second",
        ],
    )
    def test_malformed_or_doubled_cite_is_no_cite(self, command: str) -> None:
        handler, _ = make()
        result = handler.handle(bash(command))
        assert result.decision == Decision.DENY
        assert "no well-formed cite" in _text(result)

    def test_default_verifier_denies_in_block(self) -> None:
        handler, _ = make()
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.DENY
        assert "issue 369" in _text(result)
        assert not _VERIFIED_WORD.search(_text(result))

    def test_default_verifier_only_advises_in_advise(self) -> None:
        handler, _ = make(mode="advise")
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.ALLOW
        assert "issue 369" in _text(result)
        assert not _VERIFIED_WORD.search(_text(result))

    def test_refusal_names_the_act(self) -> None:
        handler, _ = make()
        assert "push" in _text(handler.handle(bash(CITED_PUSH)))

    def test_refusal_never_echoes_cite_text(self) -> None:
        marker = "$cite-text-marker-0042"
        handler, _ = make()
        result = handler.handle(bash(PUSH + f"  # human-approval team=alpha id={marker}"))
        assert marker not in _text(result)

    def test_human_approval_passes(self) -> None:
        handler, _ = make(verifier=human_verifier)
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.ALLOW
        assert result.reason in (None, "")

    def test_pass_never_relaxes_another_handler(self) -> None:
        """A pass is a plain ALLOW: no context, no reason, nothing a later step could read."""
        handler, _ = make(verifier=human_verifier)
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_peer_line_is_refused(self) -> None:
        def peer(_s: SessionSignals, _c: ApprovalCite) -> VerifiedLine:
            return VerifiedLine("alpha", fx.HUMAN_ID, "questions", False, "Q7")

        handler, _ = make(verifier=peer)
        assert handler.handle(bash(CITED_PUSH)).decision == Decision.DENY

    def test_verify_failure_is_refused(self) -> None:
        def refused(_s: SessionSignals, _c: ApprovalCite) -> VerifyFailure:
            return VerifyFailure(Refusal.VERIFY_REFUSED)

        handler, _ = make(verifier=refused)
        assert handler.handle(bash(CITED_PUSH)).decision == Decision.DENY

    def test_exception_after_arming_denies_in_block(self) -> None:
        handler, _ = make(verifier=exploding_verifier)
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.DENY
        assert "verifier crashed" not in _text(result)

    def test_exception_after_arming_advises_in_advise(self) -> None:
        handler, _ = make(mode="advise", verifier=exploding_verifier)
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_worker_seat_cite_is_not_coordinator_when_armed(self) -> None:
        handler, _ = make(WORKER, coordinator_seats_only=False, verifier=human_verifier)
        result = handler.handle(bash(CITED_PUSH))
        assert result.decision == Decision.DENY
        assert "not the coordinator" in _text(result)


# --- invariants --------------------------------------------------------------------


class TestInvariants:
    def test_nothing_under_the_run_dir_or_kit_is_opened(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        touched: list[str] = []

        def record(real: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                path = str(args[0]) if args else ""
                if path.startswith((RUNTIME, KIT)):
                    touched.append(path)
                return real(*args, **kwargs)

            return wrapper

        monkeypatch.setattr(builtins, "open", record(builtins.open))
        monkeypatch.setattr(os, "stat", record(os.stat))
        monkeypatch.setattr(os, "scandir", record(os.scandir))
        for verifier in (DEFAULT_VERIFIER, human_verifier):
            handler, _ = make(verifier=verifier)
            payload = bash(CITED_PUSH)
            if handler.matches(payload):
                handler.handle(payload)
        assert touched == []

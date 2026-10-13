"""``exempt_agent_types``: a dedicated QA-runner agent may run the full gate (Plan 00518).

The exemption keys on the agent's DEFINITION type. A payload's ``agent_type``
is the dispatch NAME for a named agent (measured, Task 0.1), so the handler
resolves it through the dispatch record first. Four ways it could fail without
looking broken are pinned: an empty ``agent_type`` must not match, a name that
equals a listed type must not buy the exemption, two exempt runs must not
overlap, and a dead holder must not block for ever.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_full_qa_blocker import (
    SubagentFullQaBlockerHandler,
)
from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock
from claude_code_hooks_daemon.utils.agent_dispatch_registry import record_dispatch

_PATTERNS: list[dict[str, Any]] = [{"id": "pytest", "command": "pytest", "bare_is_full": True}]
_LISTED = "qa-full-runner"
_UNNAMED_ID = "a57801934993f0485"  # measured unnamed shape: `a` + 16 hex
_NAMED_ID = "aprobe-named-518-0123456789abcdef"  # measured named shape


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


@pytest.fixture
def untracked(tmp_path: Path) -> Iterator[Path]:
    directory = tmp_path / "untracked"
    directory.mkdir()
    with patch.object(SubagentFullQaBlockerHandler, "_untracked_dir", return_value=directory):
        yield directory


def _handler(exempt: object = (_LISTED,)) -> SubagentFullQaBlockerHandler:
    handler = SubagentFullQaBlockerHandler()
    handler._full_qa_patterns = _PATTERNS
    handler._exempt_agent_types = list(exempt) if isinstance(exempt, tuple) else exempt
    return handler


def _payload(repo: Path, agent_type: Any = _LISTED, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "session_id": "s1",
        "agent_id": _UNNAMED_ID,
        "cwd": str(repo),
        **extra,
    }
    if agent_type is not None:
        payload["agent_type"] = agent_type
    return payload


class TestTheExemption:
    def test_unnamed_listed_type_is_allowed_with_an_advisory(
        self, repo: Path, untracked: Path
    ) -> None:
        result = _handler().handle(_payload(repo))
        assert result.decision == Decision.ALLOW
        advisory = "\n".join(result.context or [])
        assert "exempt_agent_types" in advisory
        assert _LISTED in advisory

    def test_named_dispatch_of_a_listed_type_is_allowed(self, repo: Path, untracked: Path) -> None:
        record_dispatch(untracked, "s1", "runner-1", _LISTED)
        result = _handler().handle(_payload(repo, agent_type="runner-1", agent_id=_NAMED_ID))
        assert result.decision == Decision.ALLOW

    def test_unlisted_type_is_denied(self, repo: Path, untracked: Path) -> None:
        assert _handler().handle(_payload(repo, agent_type="qa-runner")).decision == Decision.DENY

    @pytest.mark.parametrize("agent_type", [None, "", "   ", 7])
    def test_missing_or_empty_agent_type_is_denied(
        self, repo: Path, untracked: Path, agent_type: Any
    ) -> None:
        assert _handler().handle(_payload(repo, agent_type=agent_type)).decision == Decision.DENY

    @pytest.mark.parametrize(
        "near_miss", ["qa-full-runner2", "QA-full-runner", "qa-full", " qa-full-runner"]
    )
    def test_near_miss_name_is_denied(self, repo: Path, untracked: Path, near_miss: str) -> None:
        assert _handler().handle(_payload(repo, agent_type=near_miss)).decision == Decision.DENY

    def test_teammate_named_like_a_listed_type_is_denied(self, repo: Path, untracked: Path) -> None:
        record_dispatch(untracked, "s1", _LISTED, "general-purpose")
        result = _handler().handle(_payload(repo, agent_id=f"a{_LISTED}-0123456789abcdef"))
        assert result.decision == Decision.DENY

    def test_unnamed_listed_type_is_allowed_despite_a_stale_name_record(
        self, repo: Path, untracked: Path
    ) -> None:
        """The live repro: an earlier teammate NAMED like the type left a record."""
        record_dispatch(untracked, "s1", _LISTED, "general-purpose")
        assert _handler().handle(_payload(repo)).decision == Decision.ALLOW

    def test_named_shape_id_without_a_record_is_denied(self, repo: Path, untracked: Path) -> None:
        result = _handler().handle(_payload(repo, agent_id=_NAMED_ID))
        assert result.decision == Decision.DENY

    def test_no_list_denies_as_before(self, repo: Path, untracked: Path) -> None:
        assert _handler(exempt=None).handle(_payload(repo)).decision == Decision.DENY

    def test_non_list_option_denies_and_is_reported(self, repo: Path, untracked: Path) -> None:
        handler = _handler(exempt=_LISTED)
        assert handler.handle(_payload(repo)).decision == Decision.DENY
        assert any("exempt_agent_types" in line for line in handler.get_enforcement_status(repo))

    def test_non_string_entries_are_ignored(self, repo: Path, untracked: Path) -> None:
        handler = _handler(exempt=[7, None, _LISTED])
        assert handler.handle(_payload(repo)).decision == Decision.ALLOW

    def test_the_deny_for_an_unlisted_type_names_the_option(
        self, repo: Path, untracked: Path
    ) -> None:
        result = _handler().handle(_payload(repo, agent_type="qa-runner"))
        assert "exempt_agent_types" in (result.reason or "")


class TestOneExemptRunAtATime:
    def test_a_live_holder_denies_a_second_run(self, repo: Path, untracked: Path) -> None:
        with acquire_full_qa_lock(repo):
            result = _handler().handle(_payload(repo))
        assert result.decision == Decision.DENY
        assert "one at a time" in (result.reason or "")

    def test_a_released_lock_does_not_block(self, repo: Path, untracked: Path) -> None:
        with acquire_full_qa_lock(repo):
            pass
        assert _handler().handle(_payload(repo)).decision == Decision.ALLOW

    def test_a_dead_holder_does_not_block(self, repo: Path, untracked: Path) -> None:
        holder = subprocess.Popen(
            [
                "python3",
                "-c",
                "import fcntl,os,sys;fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT);"
                "fcntl.flock(fd,fcntl.LOCK_EX);print('held',flush=True);sys.stdin.read()",
                str(_lock_path(repo)),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        assert _handler().handle(_payload(repo)).decision == Decision.DENY
        holder.kill()
        holder.wait()
        assert _handler().handle(_payload(repo)).decision == Decision.ALLOW

    def test_the_lock_does_not_gate_a_denied_agent(self, repo: Path, untracked: Path) -> None:
        result = _handler().handle(_payload(repo, agent_type="qa-runner"))
        assert result.decision == Decision.DENY
        assert "one at a time" not in (result.reason or "")

    def test_an_unlocatable_lock_allows_and_says_so(self, tmp_path: Path, untracked: Path) -> None:
        result = _handler().handle(_payload(tmp_path / "not-a-repo"))
        assert result.decision == Decision.ALLOW
        assert "could not be checked" in "\n".join(result.context or [])

    def test_a_missing_cwd_allows_and_says_so(self, repo: Path, untracked: Path) -> None:
        payload = _payload(repo)
        del payload["cwd"]
        result = _handler().handle(payload)
        assert result.decision == Decision.ALLOW
        assert "could not be checked" in "\n".join(result.context or [])


class TestAnUnseenRunByAnExemptAgent:
    def test_is_allowed_with_the_exemption_advisory(self, repo: Path, untracked: Path) -> None:
        handler = _handler()
        payload = _payload(repo)
        payload["tool_input"] = {"command": "perl -E 'say 1'"}
        match = handler._find(payload)
        assert match is not None and match.fail_closed
        result = handler.handle(payload)
        assert result.decision == Decision.ALLOW
        assert "exempt_agent_types" in "\n".join(result.context or [])


class TestGuidance:
    def test_resident_guidance_names_the_option_and_the_lock(self) -> None:
        text = SubagentFullQaBlockerHandler().get_claude_md() or ""
        assert "exempt_agent_types" in text
        assert "one at a time" in text.lower()
        assert "agent_dispatch_recorder" in text


def _lock_path(repo: Path) -> Path:
    from claude_code_hooks_daemon.qa.full_qa_lock import host_lock_path

    return host_lock_path(repo)

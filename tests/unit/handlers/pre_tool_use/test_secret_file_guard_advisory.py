"""secret_file_guard denies only on a positive finding (Plan 00483 A1).

A cap, the deadline, a command the reader cannot parse, a malformed payload or an
internal error never denies: the call is judged on the literal paths in its text
and, if none is protected, allowed with an advisory that says what was not
checked. A defect in building the DENY message of a real finding still denies.
"""

from pathlib import Path
from typing import Any

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import RuleFormatter
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import SecretFileGuardHandler
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

PROTECTED = ".vault-" + "pass"
SECRET_MESSAGE = "a message that must never reach the advisory"


@pytest.fixture(autouse=True)
def _fresh_state():
    reset_data_layer()
    protected_file_index.reset_index_cache()
    yield
    protected_file_index.reset_index_cache()
    reset_data_layer()


def _hook_input(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": tool_input}


def _raise(error: type[Exception]) -> Any:
    def raiser(*_args: object, **_kwargs: object) -> None:
        raise error(SECRET_MESSAGE)

    return raiser


def _advisory(result: GatingResult) -> str:
    """The advisory text of ``result``, which must be an ALLOW that carries one."""
    assert result.decision == Decision.ALLOW
    assert result.context
    assert "could NOT fully judge" in result.context[0]
    assert result.guidance is not None
    assert SECRET_MESSAGE not in result.context[0]
    assert SECRET_MESSAGE not in result.guidance
    return result.context[0]


class TestRules:
    def test_only_the_three_finding_rules_remain(self) -> None:
        rule_ids = {rule.rule_id for rule in SecretFileGuardHandler().get_rules()}
        assert rule_ids == {
            RuleID.SECRET_READ,
            RuleID.SECRET_BASH_MENTION,
            RuleID.SECRET_SCRIPT_AUTHOR,
        }

    def test_every_rule_has_verbose_content(self) -> None:
        for rule in SecretFileGuardHandler().get_rules():
            assert rule.verbose


class TestAnErrorIsAnAdvisory:
    def test_a_bash_route_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sfm, "find_protected_mention_detail", _raise(RuntimeError))
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})
        assert handler.matches(hook_input) is True
        assert "RuntimeError" in _advisory(handler.handle(hook_input))

    def test_a_read_route_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sfm, "protecting_pattern", _raise(ValueError))
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Read", {"file_path": "/proj/ordinary.py"})
        assert handler.matches(hook_input) is True
        assert "ValueError" in _advisory(handler.handle(hook_input))

    def test_a_script_content_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sfm, "find_protected_mention_detail", _raise(RuntimeError))
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Write", {"file_path": "scripts/x.py", "content": "print('hi')"})
        assert "RuntimeError" in _advisory(handler.handle(hook_input))

    def test_a_directory_walk_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard_module, "resolve_project_root", lambda: tmp_path)
        index_project(tmp_path, SecretFileGuardHandler()._patterns())
        monkeypatch.setattr(protected_file_index.ProtectedFileIndex, "find_under", _raise(OSError))
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Grep", {"path": str(tmp_path), "pattern": "x"})
        assert "OSError" in _advisory(handler.handle(hook_input))

    @pytest.mark.parametrize("error", [TimeoutError, OSError])
    def test_the_scan_deadline_is_an_advisory(
        self, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
    ) -> None:
        monkeypatch.setattr(sfm, "find_protected_mention_detail", _raise(error))
        handler = SecretFileGuardHandler()
        result = handler.handle(_hook_input("Bash", {"command": "echo hello"}))
        text = _advisory(result)
        assert ("deadline" in text) is (error is TimeoutError)

    def test_a_nul_byte_path_is_an_advisory_not_a_deny(self) -> None:
        handler = SecretFileGuardHandler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/a\x00b"}))
        assert result.decision == Decision.ALLOW

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_a_malformed_payload_is_an_advisory(self, bad_tool_input: object) -> None:
        handler = SecretFileGuardHandler()
        hook_input = {"tool_name": "Bash", "tool_input": bad_tool_input}
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.ALLOW
        assert SecretFileGuardHandler().handle(hook_input).decision == Decision.ALLOW

    def test_the_advisory_reaches_the_chain_as_an_allow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sfm, "find_protected_mention_detail", _raise(RuntimeError))
        chain = HandlerChain()
        chain.add(SecretFileGuardHandler())
        result = chain.execute(_hook_input("Bash", {"command": "echo hello"}), strict_mode=False)
        assert result.result.decision == Decision.ALLOW

    def test_one_evaluation_serves_matches_and_handle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"count": 0}

        def flaky(*_args: object, **_kwargs: object) -> tuple[str, str] | None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient failure, first call only")
            return None

        monkeypatch.setattr(sfm, "find_protected_mention_detail", flaky)
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})
        assert handler.matches(hook_input) is True
        assert "RuntimeError" in _advisory(handler.handle(hook_input))


class TestAFindingStillDenies:
    @pytest.mark.parametrize("error", [TimeoutError, RuntimeError])
    def test_a_literal_protected_path_denies_when_the_scan_gives_up(
        self, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
    ) -> None:
        monkeypatch.setattr(sfm, "find_protected_mention_detail", _raise(error))
        handler = SecretFileGuardHandler()
        result = handler.handle(_hook_input("Bash", {"command": f"cat {PROTECTED}"}))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert RuleID.SECRET_BASH_MENTION in result.reason

    @pytest.mark.parametrize("failing", ["get_data_layer", "formatter"])
    def test_a_defect_building_the_message_still_denies(
        self, monkeypatch: pytest.MonkeyPatch, failing: str
    ) -> None:
        if failing == "get_data_layer":
            monkeypatch.setattr(guard_module, "get_data_layer", _raise(RuntimeError))
        else:
            monkeypatch.setattr(RuleFormatter, "verbose", _raise(RuntimeError))
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Read", {"file_path": f"/proj/{PROTECTED}"})
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "Matched protected glob" in result.reason
        assert SECRET_MESSAGE not in result.reason

    def test_an_unhashable_transcript_path_still_denies(self) -> None:
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Read", {"file_path": f"/proj/{PROTECTED}"})
        hook_input["transcript_path"] = ["not", "a", "string"]
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY


class TestNoIndexIsAnAdvisory:
    """A recursive read is judged by the index of protected files; with none, it is not judged."""

    def test_a_recursive_search_with_no_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(SecretFileGuardHandler, "_index", lambda self, patterns: None)
        handler = SecretFileGuardHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r x ."},
            "cwd": str(tmp_path),
        }
        assert "index of protected files is not available" in _advisory(handler.handle(hook_input))

    def test_a_grep_rooted_at_a_directory_with_no_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(SecretFileGuardHandler, "_index", lambda self, patterns: None)
        handler = SecretFileGuardHandler()
        hook_input = _hook_input("Grep", {"path": str(tmp_path), "pattern": "x"})
        assert "index of protected files is not available" in _advisory(handler.handle(hook_input))

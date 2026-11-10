"""pipe_blocker: a blacklisted producer the parser cannot place still denies (Plan 00478).

Second review of Task 2.2e. While an unknown producer denied, that tier was the
net for every command whose expensive producer the parser failed to place:
`sleep 1 & pytest | tail` read its producer as `sleep 1 & pytest`, unknown, so
it denied. Once unknown became a warning each such parse gap became an allow,
and enumerating wrappers never converges. So before an unknown pipe may allow,
the whole command is scanned for any blacklisted producer name; if one appears
anywhere, the pipe denies naming it.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.support.unknown_verdict_asserts import assert_unknown_verdict

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

_GUARD = "pipe_blocker"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_PROJECT_CONFIG = _PROJECT_ROOT / ".claude" / "hooks-daemon.yaml"


def _event(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _explanation(reason: str | None) -> str:
    """The deny reason without its echoed COMMAND line, which names every word anyway."""
    lines = (reason or "").splitlines()
    return "\n".join(line for line in lines if not line.startswith("COMMAND:"))


def _project_extra_blacklist() -> list[str]:
    """This repository's own configured ``extra_blacklist`` for pipe_blocker."""
    config = yaml.safe_load(_PROJECT_CONFIG.read_text())
    handlers = config["handlers"]["pre_tool_use"]
    patterns: list[str] = handlers["pipe_blocker"]["options"]["extra_blacklist"]
    return patterns


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


@pytest.fixture
def project_handler() -> PipeBlockerHandler:
    """A handler carrying this repository's configured extra_blacklist."""
    configured = PipeBlockerHandler()
    configured._extra_blacklist = _project_extra_blacklist()
    return configured


class TestABackgroundAmpersandSeparatesStatements:
    """Review C-1: a single `&` ends a statement, so the pipe after it has its own producer."""

    @pytest.mark.parametrize(
        ("command", "producer"),
        [
            ("sleep 1 & pytest | tail -5", "pytest"),
            ("true & pytest | tail", "pytest"),
            ("mytool & cargo test | head", "cargo"),
            ("docker ps | tail & pytest | tail", "pytest"),
        ],
    )
    def test_the_pipe_after_the_ampersand_is_judged_on_its_own_producer(
        self, handler: PipeBlockerHandler, command: str, producer: str
    ) -> None:
        assert handler.matches(_event(command)) is True
        result = handler.handle(_event(command))
        assert result.decision == Decision.DENY
        assert producer in _explanation(result.reason)
        # Placed by the producer extraction itself, not caught by the scan net.
        assert "could not tell which pipe" not in (result.reason or "")

    @pytest.mark.parametrize(
        "command",
        ["pytest 2>&1 | tail -5", "pytest &> out.txt; cat out.txt | tail", "pytest >&2 | tail"],
    )
    def test_a_redirect_ampersand_is_not_a_separator(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        result = handler.handle(_event(command))
        assert result.decision == Decision.DENY

    def test_an_unknown_producer_after_an_ampersand_still_only_warns(
        self, handler: PipeBlockerHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = handler.handle(_event("sleep 1 & docker ps | tail -1"))
        assert_unknown_verdict(result, caplog, _GUARD, "docker")


class TestABlacklistedProducerAnywhereInTheCommandDenies:
    """Review I-1: shapes the wrapper unwrapping does not place still deny."""

    @pytest.mark.parametrize(
        "command",
        [
            "bash -euo pipefail -c 'pytest' | tail",
            "python -u -m pytest | tail",
            "python3 -B -m pytest | tail",
            "python3 -X dev -m pytest | tail",
            "python -W ignore -m pytest | tail",
            "python3 -I -m pytest | tail",
            "python -mpytest | tail",
            "python3 -mpytest tests/ | head",
            "exec pytest | tail",
            "exec -a x pytest | tail",
            "chronic pytest | tail",
            "flock /tmp/l pytest | tail",
            "doas pytest | tail",
            "taskset -c 0 pytest | tail",
            "unbuffer pytest | tail",
            "script -q -c pytest | tail",
            "eval pytest | tail",
            "bash <<< 'pytest | tail'",
            "timeout 5s -- pytest | tail",
            "bash -c 'pytest | grep FAIL' | tail -5",
        ],
    )
    def test_denied_naming_the_blacklisted_producer(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        assert handler.matches(_event(command)) is True
        result = handler.handle(_event(command))
        assert result.decision == Decision.DENY
        assert "pytest" in _explanation(result.reason)

    def test_a_multi_word_blacklist_pattern_is_found_anywhere(
        self, handler: PipeBlockerHandler
    ) -> None:
        result = handler.handle(_event("chronic npm test | tail"))
        assert result.decision == Decision.DENY
        assert "npm" in _explanation(result.reason)

    def test_the_reason_says_the_producer_could_not_be_placed(
        self, handler: PipeBlockerHandler
    ) -> None:
        reason = handler.handle(_event("unbuffer pytest | tail")).reason or ""
        assert "could not tell which pipe" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "docker ps | tail -1",
            "mytool | head",
            "mytool --format json | head -3",
            "timeout 5 docker ps | tail -1",
            "uv run my_report | tail -5",
            "systemctl list-units | tail -n 3",
        ],
    )
    def test_an_unknown_pipe_with_no_blacklisted_word_still_allows(
        self, handler: PipeBlockerHandler, command: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert handler.matches(_event(command)) is True
        result = handler.handle(_event(command))
        assert result.decision == Decision.ALLOW
        assert_unknown_verdict(result, caplog, _GUARD)

    def test_a_blacklisted_name_inside_a_longer_word_does_not_count(
        self, handler: PipeBlockerHandler
    ) -> None:
        """`pytester` and `my-pytest-report` are not pytest: whole words only."""
        result = handler.handle(_event("pytester --list | tail -1"))
        assert result.decision == Decision.ALLOW


class TestTheProjectQaScriptsDenyAtAnyPathAndRunner:
    """Review I-2: this repository's QA scripts deny however they are launched."""

    @pytest.mark.parametrize(
        "command",
        [
            "bash scripts/qa/run_all.sh | tail",
            "bash ./scripts/qa/run_tests.sh | tail -5",
            "sh scripts/qa/run_all.sh | tail",
            "bash -x scripts/qa/run_all.sh | tail",
            "bash -c './scripts/qa/run_all.sh' | tail",
            "time ./scripts/qa/run_all.sh | tail",
            "python3 scripts/qa/llm_qa.py all | tail",
            "python3 scripts/qa/llm_qa.py changed | head -20",
        ],
    )
    def test_denied(self, project_handler: PipeBlockerHandler, command: str) -> None:
        assert project_handler.matches(_event(command)) is True
        assert project_handler.handle(_event(command)).decision == Decision.DENY

    @pytest.mark.parametrize("script", ["run_all.sh.bak", "run_tests.sh.orig", "llm_qa.py.old"])
    def test_a_configured_entry_does_not_match_a_longer_file_name(self, script: str) -> None:
        handler = PipeBlockerHandler()
        handler._extra_blacklist = _project_extra_blacklist()
        assert handler._matches_blacklist_text(script) is False

    @pytest.mark.parametrize("script", ["run_all.sh", "run_tests.sh -v", "llm_qa.py all"])
    def test_a_configured_entry_matches_the_script(self, script: str) -> None:
        handler = PipeBlockerHandler()
        handler._extra_blacklist = _project_extra_blacklist()
        assert handler._matches_blacklist_text(script) is True

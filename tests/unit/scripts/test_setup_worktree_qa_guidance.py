"""`setup_worktree.sh` sends agents to targeted QA, never a denied entry point.

Ledger 00466 N2, graduated to Plan 00463. The script's closing "Agent prompt
template" told every agent "Run ./scripts/qa/run_all.sh before committing.",
and its "Run QA" hint and Step 7 check named the same script. `run_all.sh` is
denied by `enforce_llm_qa`, and a sub-agent running the full suite is exactly
what `subagent_full_qa_blocker` stops: an agent that followed the template was
denied on its first QA call. Full QA is the coordinator's batched integration
gate; a worktree agent runs `llm_qa.py changed`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_full_qa_blocker import (
    FullQaPattern,
    find_full_qa_invocation,
    parse_full_qa_patterns,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "setup_worktree.sh"
#: What `enforce_llm_qa` denies outright.
_DENIED_SCRIPT = "run_all.sh"
_ECHOED = re.compile(r'^\s*echo\s+(?:-e\s+)?"(?P<text>.*)"\s*$')
#: An echoed line that presents a command to type, rather than prose.
_COMMAND_STARTS: tuple[str, ...] = ("cd ", "./", "bash ", "python", "pytest", "uv ")


def _live_patterns() -> list[FullQaPattern]:
    config = ConfigLoader.load(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    options: dict[str, Any] = config["handlers"]["pre_tool_use"]["subagent_full_qa_blocker"][
        "options"
    ]
    patterns, problems = parse_full_qa_patterns(options["full_qa_patterns"])
    assert not problems, problems
    return patterns


def _echoed_commands() -> list[str]:
    """Each command the script prints for someone to run."""
    commands = []
    for line in _SCRIPT.read_text(encoding="utf-8").splitlines():
        match = _ECHOED.match(line)
        if match and match.group("text").strip().startswith(_COMMAND_STARTS):
            commands.append(match.group("text").strip())
    assert commands, "the script prints no command; this test would prove nothing"
    return commands


def test_the_script_never_names_the_denied_runner() -> None:
    assert _DENIED_SCRIPT not in _SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("command", _echoed_commands())
def test_no_printed_command_is_a_full_qa_run(command: str) -> None:
    """A command the script tells an agent to run is never one the guard denies."""
    assert find_full_qa_invocation(command, _live_patterns()) is None, command


def test_the_agent_template_names_targeted_qa_and_the_coordinators_gate() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    template = text[text.index("Agent prompt template") :]
    assert "llm_qa.py changed" in template
    assert "coordinator" in template

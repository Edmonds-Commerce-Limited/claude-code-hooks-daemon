"""`setup_worktree.sh` sends agents to targeted QA, never a denied entry point.

Ledger 00466 N2, graduated to Plan 00463. The script's closing "Agent prompt
template" told every agent "Run ./scripts/qa/run_all.sh before committing.",
and its "Run QA" hint and Step 7 check named the same script. `run_all.sh` is
denied by `enforce_llm_qa`, and a sub-agent running the full suite is exactly
what `subagent_full_qa_blocker` stops: an agent that followed the template was
denied on its first QA call. Full QA is the coordinator's batched integration
gate; a worktree agent runs `llm_qa.py changed`.

The first version of this test checked only printed lines that BEGAN with a
command, so the prose shape of the original defect ("Run ... before
committing.") got past it, as did single-quoted and ``printf`` lines (review 3
R3). It now judges every place a command can start inside every line the
script prints, however that line is quoted, with the guard's own matcher.
"""

from __future__ import annotations

import shlex
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
_PRINT_COMMANDS: frozenset[str] = frozenset({"echo", "printf"})
_ECHO_OPTION_LETTERS: frozenset[str] = frozenset("neE")
_ESCAPES: tuple[str, ...] = ("\\n", "\\t")
#: A command can begin at the start of the text, after one of these words...
_STARTS_AFTER: frozenset[str] = frozenset({"run", "&&", "||", ";", "|"})
#: ...after a word ending in a colon ("QA: pytest tests/")...
_LABEL_END = ":"
#: ...or at a word shaped like a path or an expansion.
_COMMAND_SHAPED_PREFIXES: tuple[str, ...] = ("./", "/", "$", "~", "`")
_LEADING_PUNCTUATION = "(`\"'"
_TRAILING_PUNCTUATION = ".,;:)`\"'"


def _live_patterns() -> list[FullQaPattern]:
    config = ConfigLoader.load(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    options: dict[str, Any] = config["handlers"]["pre_tool_use"]["subagent_full_qa_blocker"][
        "options"
    ]
    patterns, problems = parse_full_qa_patterns(options["full_qa_patterns"])
    assert not problems, problems
    return patterns


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _printed_texts(script: str) -> list[str]:
    """The text of every ``echo`` or ``printf`` line, with shell quoting removed."""
    texts = []
    for line in script.splitlines():
        words = _split(line.strip())
        if not words or words[0] not in _PRINT_COMMANDS:
            continue
        arguments = words[1:]
        if words[0] == "echo":
            while (
                arguments
                and arguments[0][:1] == "-"
                and set(arguments[0][1:]) <= _ECHO_OPTION_LETTERS
            ):
                arguments = arguments[1:]
        text = " ".join(arguments)
        for escape in _ESCAPES:
            text = text.replace(escape, " ")
        texts.append(text)
    return texts


def _candidate_commands(text: str) -> list[str]:
    """Each suffix of ``text`` that starts where prose could start a command."""
    raw = _split(text)
    words = [word.lstrip(_LEADING_PUNCTUATION).rstrip(_TRAILING_PUNCTUATION) for word in raw]
    candidates = []
    for index, word in enumerate(words):
        previous = raw[index - 1] if index else ""
        starts = (
            index == 0
            or previous.lower() in _STARTS_AFTER
            or previous.endswith(_LABEL_END)
            or raw[index].startswith(_COMMAND_SHAPED_PREFIXES)
        )
        if starts and word:
            candidates.append(" ".join(words[index:]))
    return candidates


def _full_runs(script: str, patterns: list[FullQaPattern]) -> list[str]:
    """Every printed text that tells its reader to start a full QA run."""
    return [
        text
        for text in _printed_texts(script)
        if any(
            find_full_qa_invocation(candidate, patterns) is not None
            for candidate in _candidate_commands(text)
        )
    ]


def test_the_script_never_names_the_denied_runner() -> None:
    assert _DENIED_SCRIPT not in _SCRIPT.read_text(encoding="utf-8")


def test_nothing_the_script_prints_tells_an_agent_to_run_full_qa() -> None:
    script = _SCRIPT.read_text(encoding="utf-8")
    assert _printed_texts(script), "the scan found no printed line; it would prove nothing"
    assert _full_runs(script, _live_patterns()) == []


@pytest.mark.parametrize(
    "injected",
    [
        'echo "  Run ./scripts/qa/llm_qa.py all before committing."',
        'echo "  Before committing, run ./scripts/qa/llm_qa.py all."',
        'echo "  Before committing, run ./scripts/qa/run_tests.sh."',
        "echo '  cd x && ./scripts/qa/llm_qa.py all'",
        'echo "  QA: pytest tests/"',
        'printf "  ./scripts/qa/llm_qa.py all\\n"',
        'echo "  bash scripts/qa/run_tests.sh"',
        'echo "  Run pytest tests/unit before committing."',
        'echo -e "  ${GREEN}->${NC} `./scripts/qa/llm_qa.py tests`"',
    ],
)
def test_a_full_run_in_any_printed_shape_is_caught(injected: str) -> None:
    """Review 3 R3: each of these was MISSED by the first version of this test."""
    script = _SCRIPT.read_text(encoding="utf-8") + f"\n{injected}\n"
    assert _full_runs(script, _live_patterns()) != [], injected


def test_the_agent_template_names_targeted_qa_and_the_coordinators_gate() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    template = text[text.index("Agent prompt template") :]
    assert "llm_qa.py changed" in template
    assert "coordinator" in template

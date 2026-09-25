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
script prints, however that line is quoted, with the guard's own matcher. That
includes every word naming a declared program whatever verb precedes it, the
body of a ``cat`` heredoc, and a ``$NAME`` the script assigned (review 4 N7).
So a printed MENTION of a runner reads as an instruction too: name a path
after it (``pytest tests/unit/qa/test_x.py``), or do not name it.

That is deliberately conservative (review 5 n8): a line that FORBIDS the full
run, such as "Never run ./scripts/qa/llm_qa.py all in a sub-agent", is flagged
as well, because telling a prohibition from an instruction would need to read
English. The script says what to run instead, which is the useful half.
"""

from __future__ import annotations

import re
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
#: A candidate command ends at a word that joins it back into prose ("Run
#: pytest BEFORE committing"). Read as operands, those words target the run:
#: under pytest's grammar every positional word is a path, so bare ``pytest``
#: looked targeted and the instruction to run the whole suite was missed.
_PROSE_STOPS: frozenset[str] = frozenset(
    {"after", "again", "and", "before", "first", "if", "instead", "once", "or", "then", "to"}
    | {"until", "when", "while"}
)
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
#: ``cat <<'EOF'``, ``cat <<EOF`` and ``cat <<-EOF``: the body is printed.
_CAT_HEREDOC = re.compile(r"^\s*cat\b[^<]*<<-?\s*(?P<quote>['\"]?)(?P<delim>\w+)(?P=quote)")


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


def _assignments(script: str) -> dict[str, str]:
    """``NAME=value`` lines, so ``$NAME`` in a printed line reads as what it prints."""
    values: dict[str, str] = {}
    for line in script.splitlines():
        words = _split(line.strip())
        if len(words) == 1 and _ASSIGNMENT.match(words[0]):
            name, value = words[0].split("=", 1)
            values[name] = value
    return values


def _expand(text: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace(f"${{{name}}}", value).replace(f"${name}", value)
    return text


def _heredoc_bodies(script: str) -> list[str]:
    """The body lines of every heredoc fed to ``cat``, which prints them."""
    bodies: list[str] = []
    lines = iter(script.splitlines())
    for line in lines:
        opened = _CAT_HEREDOC.search(line)
        if opened is None:
            continue
        delimiter = opened.group("delim")
        for body in lines:
            if body.strip() == delimiter:
                break
            bodies.append(body.strip())
    return bodies


def _printed_texts(script: str) -> list[str]:
    """The text of every ``echo``/``printf`` line and ``cat`` heredoc, quoting removed."""
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
    texts.extend(_heredoc_bodies(script))
    values = _assignments(script)
    return [_expand(text, values) for text in texts]


def _candidate_commands(text: str, programs: frozenset[str]) -> list[str]:
    """Each suffix of ``text`` that starts where prose could start a command.

    That is after a start word, a label or a command-shaped word, and at any
    word naming a declared program, whatever verb comes before it (review 4
    N7): ``Execute pytest tests`` is an instruction however it is phrased.
    Each candidate ends at the first prose connective after its start.
    """
    raw = _split(text)
    words = [word.lstrip(_LEADING_PUNCTUATION).rstrip(_TRAILING_PUNCTUATION) for word in raw]
    stops = [index for index, word in enumerate(words) if word.lower() in _PROSE_STOPS]
    candidates = []
    for index, word in enumerate(words):
        end = next((stop for stop in stops if stop > index), len(words))
        previous = raw[index - 1] if index else ""
        starts = (
            index == 0
            or previous.lower() in _STARTS_AFTER
            or previous.endswith(_LABEL_END)
            or raw[index].startswith(_COMMAND_SHAPED_PREFIXES)
            or word.rsplit("/", 1)[-1] in programs
        )
        if starts and word:
            candidates.append(" ".join(words[index:end]))
    return candidates


def _names_a_full_run(candidate: str, patterns: list[FullQaPattern]) -> bool:
    """Whether the guard judges a candidate a run of a DECLARED full-QA program.

    The guard also denies code it cannot see (a script path built from a
    variable the text never sets, say); that is its caution about a command
    it would have to run, not a printed instruction to run the full suite.
    """
    match = find_full_qa_invocation(candidate, patterns)
    return match is not None and match.pattern_id in {pattern.pattern_id for pattern in patterns}


def _full_runs(script: str, patterns: list[FullQaPattern]) -> list[str]:
    """Every printed text that tells its reader to start a full QA run."""
    programs = frozenset(pattern.command for pattern in patterns)
    return [
        text
        for text in _printed_texts(script)
        if any(
            _names_a_full_run(candidate, patterns)
            for candidate in _candidate_commands(text, programs)
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
        # Review 4 N7: any verb, a heredoc, and a command held in a variable.
        'echo "  Execute pytest tests before committing."',
        'echo "  Then use pytest tests/unit to check."',
        'echo "  Next, invoke python -m pytest tests."',
        'echo "  Finally: run the full suite (pytest)."',
        'echo "  Run pytest before committing."',
        "cat <<'EOF'\n  Run ./scripts/qa/llm_qa.py all before committing.\nEOF",
        "cat <<EOF\n  Then use pytest tests.\nEOF",
        "cat <<-'EOF'\n\tthen use ./scripts/qa/run_tests.sh\n\tEOF",
        'QA_CMD="./scripts/qa/llm_qa.py all"\necho "  Run $QA_CMD before committing."',
        "QA_CMD='pytest tests'\necho \"  Run ${QA_CMD} first.\"",
    ],
)
def test_a_full_run_in_any_printed_shape_is_caught(injected: str) -> None:
    """Review 3 R3 and review 4 N7: each of these was MISSED by an earlier version."""
    script = _SCRIPT.read_text(encoding="utf-8") + f"\n{injected}\n"
    assert _full_runs(script, _live_patterns()) != [], injected


@pytest.mark.parametrize(
    "injected",
    [
        'echo "  Run pytest tests/unit/handlers/test_x.py before committing."',
        "python3 - <<'PY'\nprint('pytest tests')\nPY",
        'echo "  Run ./scripts/qa/llm_qa.py changed first."',
    ],
)
def test_a_targeted_run_or_code_that_is_not_printed_is_not(injected: str) -> None:
    script = _SCRIPT.read_text(encoding="utf-8") + f"\n{injected}\n"
    assert _full_runs(script, _live_patterns()) == [], injected


def test_the_agent_template_names_targeted_qa_and_the_coordinators_gate() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    template = text[text.index("Agent prompt template") :]
    assert "llm_qa.py changed" in template
    assert "coordinator" in template

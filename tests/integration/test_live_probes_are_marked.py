"""A test or script that probes the live daemon must mark the probe (Plan 00466 N12).

``test_documented_hook_probes_are_marked`` holds the DOCUMENTS to this. The
same defect lived in code: ``test_stop_hook_hard_block`` and
``test_tool_use_error_recovery`` sent hand-built Stop payloads through the
live daemon, and every run wrote them into this project's ``verdicts.jsonl``
as a real agent's stops. That was measured, not inferred: the worktree log
held ``phase9-block-probe`` and ``phase9-subagent-block-probe`` records with
no synthetic marker. ``scripts/qa/run_smoke_test.sh`` did the same on every
QA run.

**Which files are judged.** A file is judged when it has a route to the LIVE
daemon, because that daemon's log is the record somebody reads:

- this repository's own hook entry points (``.claude/hooks/<name>``);
- the acceptance fixtures that hand out the live socket (``daemon_socket``,
  ``daemon_running``);
- the live socket found by its glob (``daemon-*.sock``), or ``nc -U``.

A test that starts its own daemon in a temporary directory writes to a log
that is deleted with it, and is not judged.

**What a payload is.** Either of these counts:

- a dict literal carrying ``hook_event_name``, or both ``tool_name`` and
  ``tool_input``;
- a JSON text carrying the same keys. That covers a Python string or bytes
  constant (docstrings excepted) and a shell line.

**What marked means.**

- ``synthetic_source`` names a PROBE-CLASS source (``PROBE_CLASS_SOURCES``).
  A harness source cannot stand for a thread, so a probe marked with one would
  hide every MAIN- or SUB-scoped handler from the test.
- On an event that can carry ``agent_id`` (``AGENT_ID_EVENTS``), ``probe_as``
  is set too. Without it a scoped handler never sees the probe, and a test that
  asserts "no block" passes on nothing.
- A spread counts only when it names a dict literal assigned at the top of
  the same module, so a file declares its marker once. Any other spread, or a
  name the guard cannot resolve, is not marked: the guard cannot see what it
  carries, and reads no annotation.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.handler_scope import event_supports_scope
from claude_code_hooks_daemon.daemon import synthetic_traffic
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PROBE_AS_FIELD,
    PROBE_CLASS_SOURCES,
    SYNTHETIC_SOURCE_FIELD,
    TEST_PROBE,
    ProbeThread,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The trees whose code sends events to a daemon.
CORPUS_GLOBS = (
    "tests/acceptance/**/*.py",
    "tests/integration/**/*.py",
    "scripts/**/*.py",
    "scripts/**/*.sh",
    "scripts/**/*.bash",
)

_PYTHON_SUFFIX = ".py"

#: A route to the live daemon: see the module docstring.
_LIVE_ROUTE = re.compile(
    r"\.claude/hooks/"
    r"|[\"']\.claude[\"']\s*/\s*[\"']hooks[\"']"
    r"|\bdaemon_(?:socket|running)\b"
    r"|daemon-\*\.sock"
    r"|\bnc\s+-U\b"
)

_EVENT_NAME_KEY = "hook_event_name"
_TOOL_NAME_KEY = "tool_name"
_TOOL_KEYS = frozenset({_TOOL_NAME_KEY, "tool_input"})

#: A JSON text that carries an event: the keys double-quoted, as JSON has them.
_JSON_EVENT = re.compile(r"\"hook_event_name\"|\"tool_name\"[^\n]*\"tool_input\"")
_JSON_EVENT_NAME = re.compile(r"\"hook_event_name\"\s*:\s*\"(?P<name>[^\"]+)\"")
_JSON_SOURCE = re.compile(r"\"synthetic_source\"\s*:\s*\"(?P<source>[^\"]+)\"")
_JSON_PROBE_AS = re.compile(r"\"probe_as\"\s*:\s*\"(?P<thread>[^\"]+)\"")
_JSON_TOOL_NAME = '"tool_name"'

_THREADS = frozenset(thread.value for thread in ProbeThread)

Problems = list[tuple[int, str]]


def _verdict(
    *, event: str | None, has_tool: bool, source: str | None, thread: str | None
) -> str | None:
    """Why a payload is not properly marked, or None when it is."""
    if source is None:
        return f"no `{SYNTHETIC_SOURCE_FIELD}`"
    if source not in PROBE_CLASS_SOURCES:
        return f"`{SYNTHETIC_SOURCE_FIELD}` {source!r} is not a probe-class source"
    # A tool payload with no event name goes to a tool event's entry point.
    scoped = event_supports_scope(event) if event is not None else has_tool
    if scoped and thread not in _THREADS:
        return f"no `{PROBE_AS_FIELD}` on a {event or 'tool'} probe"
    return None


def text_payload_problem(text: str) -> str | None:
    """Judge a JSON text; None when it is no payload or is properly marked."""
    if not _JSON_EVENT.search(text) or "{" not in text:
        return None
    event = _JSON_EVENT_NAME.search(text)
    source = _JSON_SOURCE.search(text)
    thread = _JSON_PROBE_AS.search(text)
    return _verdict(
        event=event.group("name") if event else None,
        has_tool=_JSON_TOOL_NAME in text,
        source=source.group("source") if source else None,
        thread=thread.group("thread") if thread else None,
    )


def _resolve(node: ast.expr | None) -> str | None:
    """The string a key or value names: a literal, or a ``synthetic_traffic`` name."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        value = getattr(synthetic_traffic, node.id, None)
        return value if isinstance(value, str) else None
    if isinstance(node, ast.Attribute) and node.attr == "value":
        return _resolve(node.value)
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == ProbeThread.__name__
        and node.attr in ProbeThread.__members__
    ):
        return ProbeThread[node.attr].value
    return None


ModuleDicts = dict[str, ast.Dict]


def module_dicts(tree: ast.Module) -> ModuleDicts:
    """Dict literals bound to a name at the top of the module."""
    bound: ModuleDicts = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Dict):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.value, ast.Dict):
            targets = [statement.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and isinstance(statement.value, ast.Dict):
                bound[target.id] = statement.value
    return bound


def _fields(node: ast.Dict, bound: ModuleDicts) -> dict[str | None, ast.expr]:
    """Every field a dict literal carries, a spread of a module-level dict included."""
    fields: dict[str | None, ast.expr] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None and isinstance(value, ast.Name) and value.id in bound:
            fields.update(_fields(bound[value.id], bound))
        elif key is not None:
            fields[_resolve(key)] = value
    return fields


def dict_payload_problem(node: ast.Dict, bound: ModuleDicts | None = None) -> str | None:
    """Judge a dict literal; None when it is no payload or is properly marked."""
    fields = _fields(node, bound or {})
    names = {name for name in fields if name is not None}
    if _EVENT_NAME_KEY not in names and not _TOOL_KEYS <= names:
        return None
    return _verdict(
        event=_resolve(fields.get(_EVENT_NAME_KEY)),
        has_tool=_TOOL_NAME_KEY in names,
        source=_resolve(fields.get(SYNTHETIC_SOURCE_FIELD)),
        thread=_resolve(fields.get(PROBE_AS_FIELD)),
    )


def _docstring_ids(tree: ast.Module) -> set[int]:
    """Docstrings are prose, so a payload quoted in one is never sent."""
    owners: list[ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = [tree]
    owners.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )
    return {
        id(owner.body[0].value)
        for owner in owners
        if owner.body
        and isinstance(owner.body[0], ast.Expr)
        and isinstance(owner.body[0].value, ast.Constant)
    }


def _constant_problem(node: ast.Constant) -> str | None:
    if isinstance(node.value, str):
        return text_payload_problem(node.value)
    if isinstance(node.value, bytes):
        return text_payload_problem(node.value.decode("utf-8", "replace"))
    return None


def python_problems(source: str) -> Problems:
    tree = ast.parse(source)
    docstrings = _docstring_ids(tree)
    bound = module_dicts(tree)
    problems: Problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            problem = dict_payload_problem(node, bound)
        elif isinstance(node, ast.Constant) and id(node) not in docstrings:
            problem = _constant_problem(node)
        else:
            continue
        if problem is not None:
            problems.append((node.lineno, problem))
    return sorted(problems)


def shell_problems(source: str) -> Problems:
    return [
        (number, problem)
        for number, line in enumerate(source.splitlines(), start=1)
        if (problem := text_payload_problem(line)) is not None
    ]


def is_live_sender(source: str) -> bool:
    return bool(_LIVE_ROUTE.search(source))


def problems_in(path: Path) -> Problems:
    source = path.read_text(encoding="utf-8")
    if not is_live_sender(source):
        return []
    if path.suffix == _PYTHON_SUFFIX:
        return python_problems(source)
    return shell_problems(source)


def _corpus() -> list[Path]:
    found: set[Path] = set()
    for pattern in CORPUS_GLOBS:
        found.update(REPO_ROOT.glob(pattern))
    return sorted(found)


# The samples below are BUILT, never written out: a payload literal in this
# file would be judged by the guard it tests.


def _python_sender(fields: dict[str, object]) -> str:
    """A module with a live route and one dict-literal payload."""
    body = ", ".join(f"{key!r}: {value!r}" for key, value in fields.items())
    return f"HOOK = REPO_ROOT / '.claude' / 'hooks' / 'stop'\npayload = {{{body}}}\n"


def _shell_sender(fields: dict[str, object]) -> str:
    """A script with a live route and one JSON payload."""
    return f"PROBE='{json.dumps(fields)}'\nprintf '%s' \"$PROBE\" | .claude/hooks/stop\n"


_Language = tuple[Callable[[dict[str, object]], str], Callable[[str], Problems]]
_LANGUAGES: list[_Language] = [(_python_sender, python_problems), (_shell_sender, shell_problems)]
_LANGUAGE_IDS = ["python", "shell"]

_STOP: dict[str, object] = {_EVENT_NAME_KEY: "Stop", "stop_hook_active": False}
_MARKED_STOP: dict[str, object] = {
    **_STOP,
    SYNTHETIC_SOURCE_FIELD: TEST_PROBE,
    PROBE_AS_FIELD: ProbeThread.MAIN.value,
}


class TestTheDetector:
    @pytest.mark.parametrize("language", _LANGUAGES, ids=_LANGUAGE_IDS)
    def test_an_unmarked_live_probe_is_caught(self, language: _Language) -> None:
        render, judge = language
        problems = judge(render(_STOP))
        assert problems
        assert SYNTHETIC_SOURCE_FIELD in problems[0][1]

    @pytest.mark.parametrize("language", _LANGUAGES, ids=_LANGUAGE_IDS)
    def test_a_marked_probe_with_its_thread_passes(self, language: _Language) -> None:
        render, judge = language
        source = render(_MARKED_STOP)
        assert is_live_sender(source)
        assert not judge(source)

    def test_a_harness_source_is_not_probe_class(self) -> None:
        source = _python_sender({**_MARKED_STOP, SYNTHETIC_SOURCE_FIELD: "playbook-probe"})
        assert "not a probe-class source" in python_problems(source)[0][1]

    def test_a_scoped_event_needs_probe_as(self) -> None:
        source = _python_sender({**_STOP, SYNTHETIC_SOURCE_FIELD: TEST_PROBE})
        assert PROBE_AS_FIELD in python_problems(source)[0][1]

    def test_a_tool_payload_with_no_event_name_needs_probe_as(self) -> None:
        tool: dict[str, object] = {
            _TOOL_NAME_KEY: "Bash",
            "tool_input": {"command": "true"},
            SYNTHETIC_SOURCE_FIELD: TEST_PROBE,
        }
        assert PROBE_AS_FIELD in shell_problems(_shell_sender(tool))[0][1]

    def test_an_event_that_cannot_carry_a_thread_needs_no_probe_as(self) -> None:
        status: dict[str, object] = {_EVENT_NAME_KEY: "Status", SYNTHETIC_SOURCE_FIELD: TEST_PROBE}
        assert not python_problems(_python_sender(status))

    def test_named_constants_resolve(self) -> None:
        source = (
            "HOOK = '.claude/hooks/stop'\n"
            "payload = {'hook_event_name': 'Stop', SYNTHETIC_SOURCE_FIELD: TEST_PROBE,"
            " PROBE_AS_FIELD: ProbeThread.MAIN.value}\n"
        )
        assert not python_problems(source)

    def test_a_spread_of_an_unseen_mapping_does_not_mark(self) -> None:
        source = "HOOK = '.claude/hooks/stop'\npayload = {'hook_event_name': 'Stop', **MARKER}\n"
        assert python_problems(source)

    def test_a_spread_of_a_module_level_marker_marks(self) -> None:
        source = (
            "HOOK = '.claude/hooks/stop'\n"
            "_PROBE: dict[str, str] = {SYNTHETIC_SOURCE_FIELD: TEST_PROBE, PROBE_AS_FIELD: 'main'}\n"
            "def send():\n"
            "    return {'hook_event_name': 'Stop', **_PROBE}\n"
        )
        assert not python_problems(source)

    def test_the_marker_declaration_is_not_itself_a_payload(self) -> None:
        source = "HOOK = '.claude/hooks/stop'\n_PROBE = {'synthetic_source': 'test-probe'}\n"
        assert not python_problems(source)

    def test_a_docstring_is_prose_not_a_payload(self) -> None:
        source = f'"""Sends {json.dumps(_STOP)} to .claude/hooks/stop."""\n'
        assert not python_problems(source)

    def test_a_system_control_message_is_not_a_payload(self) -> None:
        envelope: dict[str, object] = {"event": "_system", "hook_input": {"action": "health"}}
        assert not python_problems(_python_sender(envelope))

    def test_a_file_with_no_live_route_is_not_judged(self) -> None:
        """A temporary daemon's log is deleted with it."""
        source = f"sock = tmp_path / 'daemon.sock'\npayload = {json.dumps(_STOP)}\n"
        assert not is_live_sender(source)


def test_the_corpus_reaches_the_known_live_senders() -> None:
    """A glob or route typo would otherwise make the assertion below vacuous."""
    senders = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _corpus()
        if is_live_sender(path.read_text(encoding="utf-8"))
    }
    for known in (
        "tests/acceptance/test_stop_hook_hard_block.py",
        "tests/acceptance/test_tool_use_error_recovery.py",
        "tests/integration/test_forwarder_socket_stdin.py",
        "scripts/qa/run_smoke_test.sh",
        "scripts/debug_info.py",
    ):
        assert known in senders, f"{known} is no longer judged"


def test_every_live_probe_is_marked() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {problem}"
        for path in _corpus()
        for number, problem in problems_in(path)
    ]
    assert not offenders, (
        "These payloads reach the live daemon, whose verdicts.jsonl is the real "
        "record, without a probe-class marker, so each run is recorded as a real "
        f"agent's traffic. Add `{SYNTHETIC_SOURCE_FIELD}` (`{TEST_PROBE}` for a test "
        f"or QA script) and, on an event that can carry agent_id, `{PROBE_AS_FIELD}`:\n"
        + "\n".join(offenders)
    )

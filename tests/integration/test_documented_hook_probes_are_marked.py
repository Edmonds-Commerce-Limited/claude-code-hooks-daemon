"""A document that teaches piping a raw payload into a hook must mark it (Plan 00466 N12).

``verdicts.jsonl`` separates synthetic probe traffic from a real agent's by
the ``synthetic_source`` field on the hook event
(``daemon/synthetic_traffic.py``). The Plan 00467 plugin audit fed hand-built
PreToolUse payloads through ``.claude/hooks/pre-tool-use``, copied from the
shape these documents teach, and every one was recorded as REAL traffic —
including the orchestrator-simulate records Plan 00418's enforcement decision
is read from. The marker was documented only in that module's docstring, so
the prober could not have known to set it.

Two rules, both mechanical:

1. Every documented command that pipes or redirects a payload into a hook
   entry point, or sends a hook event straight to the daemon socket, sets
   ``synthetic_source`` in that command. A payload read from a file cannot be
   checked, so it fails too; the helper is the answer there.
2. A document with any such command also shows the helper,
   ``hooks-daemon probe``, which sets the marker itself.

There is no exception. A probe of a handler scoped MAIN or SUB, such as
``auto_continue_stop``, is marked too, and names the thread it stands for
with ``probe_as`` (``core/handler_scope.py`` honours it for a probe-class
source only).

A third rule keeps the probe runnable at all. The guards judge the prober's
OWN Bash command text, so an inline payload that spells out the command a
guard matches (``git reset --hard``) is denied before it reaches the hook.
Every inline probe is therefore judged by this project's handlers, and one
they deny must move its payload into a file (``--file``).

A new example written without the field fails here, not in a month's worth of
misclassified records.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
import yaml

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.daemon.hook_probe import response_decision, response_text
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PROBE_AS_FIELD,
    SYNTHETIC_SOURCE_FIELD,
    TEST_PROBE,
    ProbeThread,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_MAIN_PROBE = {SYNTHETIC_SOURCE_FIELD: TEST_PROBE, PROBE_AS_FIELD: ProbeThread.MAIN.value}

#: Documents an agent or operator follows verbatim. The same corpus as
#: ``test_documented_commands_are_not_self_denied`` plus the project agents
#: and the upgrade-guide template. ``CLAUDE/Plan/`` and the released
#: ``CLAUDE/UPGRADES/`` guides are left out: they record what was run, and
#: rewriting a past command would falsify the record.
DOCUMENT_GLOBS = (
    "README.md",
    "BUG_REPORTING.md",
    "CONTRIBUTING.md",
    "CLAUDE/*.md",
    "CLAUDE/**/*.md",
    "docs/**/*.md",
    "src/claude_code_hooks_daemon/skills/**/*.md",
    ".claude/agents/*.md",
    ".claude/skills/**/*.md",
)

_EXCLUDED_PREFIXES = ("CLAUDE/Plan/", "CLAUDE/UPGRADES/")
_INCLUDED_DESPITE_PREFIX = ("CLAUDE/UPGRADES/upgrade-template/",)

HELPER = "hooks-daemon probe"

#: Any forwarder name, not only the wired ones: the upgrade-guide template
#: teaches ``.claude/hooks/event-type`` as a placeholder the author fills in.
#: ``handlers`` is the project-handler directory, never an entry point.
_HOOK_NAMES = r"(?!handlers/)[a-z][a-z-]*"

#: A payload piped INTO an entry point (``| bash .claude/hooks/stop``, also
#: with an absolute or relative prefix), or redirected into one from a file or
#: a heredoc (``.claude/hooks/pre-tool-use < input.json``).
_DISPATCH = re.compile(
    rf"\|\s*(?:\\\s*)?(?:bash\s+)?[\w./~${{}}\"-]*\.claude/hooks/(?:{_HOOK_NAMES})(?![\w-])"
    rf"|\.claude/hooks/(?:{_HOOK_NAMES})(?![\w-])(?:\s+--no-relay)?\s*<"
)

#: A payload sent straight to the daemon socket skips the entry point but
#: still lands in ``verdicts.jsonl``, so it is a probe too. A ``_system``
#: control message (mode get/set) is not a hook event and records no verdict.
_SOCKET_SEND = re.compile(r"\|\s*(?:\\\s*)?nc\s+-U\b")
_HOOK_ENVELOPE = '"hook_input"'
_CONTROL_EVENT = '"_system"'

#: A heredoc opener; its body is part of the command that opened it.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(?P<delimiter>\w+)\1")


def _documents() -> list[Path]:
    found: set[Path] = set()
    for pattern in DOCUMENT_GLOBS:
        found.update(REPO_ROOT.glob(pattern))
    selected = []
    for path in sorted(found):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(_EXCLUDED_PREFIXES) and not relative.startswith(
            _INCLUDED_DESPITE_PREFIX
        ):
            continue
        selected.append(path)
    return selected


def logical_lines(text: str) -> list[tuple[int, str]]:
    """Join shell continuations so a split command is judged as one.

    Three shapes split a dispatch across lines: a trailing backslash, a
    continuation line that STARTS with the pipe, and a heredoc, whose body up
    to its delimiter is the payload. Each is folded into the line that began
    the command, and that line's number is kept.
    """
    joined: list[tuple[int, str]] = []
    continuing = False
    heredoc_end: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            # A fence ends any command, so an example that never closes its
            # heredoc cannot swallow the rest of the document.
            heredoc_end = None
            continuing = False
        # A markdown table row also starts with a pipe, but it ends with one.
        pipe_continuation = stripped.startswith("|") and not stripped.endswith("|")
        if joined and (continuing or heredoc_end is not None or pipe_continuation):
            start, previous = joined[-1]
            joined[-1] = (start, f"{previous} {stripped}")
            if heredoc_end is not None and stripped == heredoc_end:
                heredoc_end = None
        else:
            joined.append((number, stripped))
            opener = _HEREDOC.search(stripped)
            heredoc_end = opener.group("delimiter") if opener else None
        continuing = stripped.endswith("\\")
    return joined


def is_dispatch(line: str) -> bool:
    """True when this command sends a hook payload the daemon will record."""
    if _DISPATCH.search(line):
        return True
    return bool(_SOCKET_SEND.search(line) and _HOOK_ENVELOPE in line and _CONTROL_EVENT not in line)


def unmarked_dispatches(text: str) -> list[tuple[int, str]]:
    """Every dispatch whose command omits the marker."""
    return [
        (number, line)
        for number, line in logical_lines(text)
        if is_dispatch(line) and SYNTHETIC_SOURCE_FIELD not in line
    ]


def has_dispatch(text: str) -> bool:
    return any(is_dispatch(line) for _, line in logical_lines(text))


#: The helper with its payload on the command line. ``--file`` keeps the
#: payload out of the prober's command, which is the point of it.
_HELPER_INLINE = re.compile(r"hooks-daemon probe\b.*\s--json\b")

#: An inline code span; a prose line quotes its command inside one.
_CODE_SPAN = re.compile(r"`([^`]+)`")


def _is_inline_probe(command: str) -> bool:
    return is_dispatch(command) or bool(_HELPER_INLINE.search(command))


def inline_probes(text: str) -> list[tuple[int, str]]:
    """Every probe command whose payload is spelled out in the command itself.

    A prose line is judged by the code span holding the command, not by the
    sentence around it, which nobody runs.
    """
    probes: list[tuple[int, str]] = []
    for number, line in logical_lines(text):
        spans = [span for span in _CODE_SPAN.findall(line) if _is_inline_probe(span)]
        if spans:
            probes.extend((number, span) for span in spans)
        elif _is_inline_probe(line):
            probes.append((number, line))
    return probes


class TestTheDetector:
    """The guard is only as good as its reading of a command."""

    @pytest.mark.parametrize(
        "text",
        [
            'echo \'{"tool_name":"Bash"}\' | bash .claude/hooks/pre-tool-use',
            "echo '{\"stop_hook_active\":false}' | /workspace/.claude/hooks/stop",
            'echo \'{"tool_name":"Bash"}\' \\\n  | bash .claude/hooks/pre-tool-use',
            'echo \'{"tool_name":"Bash"}\' | \\\n  .claude/hooks/pre-tool-use',
            "echo '{}' | bash ../../.claude/hooks/pre-tool-use",
            ".claude/hooks/pre-tool-use < test-input.json",
            'bash .claude/hooks/pre-tool-use <<\'EOF\'\n{"tool_name":"Bash"}\nEOF',
            'echo \'{"event":"Stop","hook_input":{"stop_hook_active":false}}\' \\\n'
            '  | nc -U "$SOCK"',
            '`echo \'{"tool_name":"Bash"}\' | bash .claude/hooks/pre-tool-use` returns deny',
        ],
    )
    def test_an_unmarked_dispatch_is_caught(self, text: str) -> None:
        assert unmarked_dispatches(text)

    @pytest.mark.parametrize(
        "text",
        [
            'echo \'{"tool_name":"Bash","synthetic_source":"manual-probe"}\''
            " | bash .claude/hooks/pre-tool-use",
            'echo \'{"synthetic_source":"manual-probe"}\' \\\n  | bash .claude/hooks/stop',
            "bash .claude/hooks/pre-tool-use <<'EOF'\n"
            '{"tool_name":"Bash","synthetic_source":"manual-probe"}\nEOF',
        ],
    )
    def test_a_marked_dispatch_passes(self, text: str) -> None:
        assert has_dispatch(text)
        assert not unmarked_dispatches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "| Hook script | `.claude/hooks/status-line` | Entry point |",
            "ls .claude/hooks/handlers/pre_tool_use/",
            'bin/hooks-daemon probe PreToolUse --json \'{"tool_name":"Bash"}\'',
            "cat .claude/hooks/pre-tool-use",
            "cat <<'EOF' > .claude/hooks/pre-tool-use",
            'echo \'{"event":"_system","hook_input":{"action":"get_mode"}}\' | nc -U "$S"',
        ],
    )
    def test_text_that_sends_no_payload_is_not_a_dispatch(self, text: str) -> None:
        assert not has_dispatch(text)

    def test_no_annotation_excuses_an_unmarked_probe(self) -> None:
        """There is no escape hatch. A probe of a MAIN- or SUB-scoped handler
        is marked AND names its thread with `probe_as`; an unmarked one would
        put a fabricated stop in the record as a real agent's."""
        text = (
            "# unmarked-probe: auto_continue_stop is scoped MAIN and never sees a marked probe\n"
            "echo '{\"stop_hook_active\":false}' | bash .claude/hooks/stop"
        )
        assert unmarked_dispatches(text)

    def test_an_inline_helper_payload_is_an_inline_probe(self) -> None:
        text = 'bin/hooks-daemon probe PreToolUse --json \'{"tool_name":"Bash"}\''
        assert inline_probes(text) == [(1, text)]

    def test_a_payload_in_a_file_is_not_an_inline_probe(self) -> None:
        assert not inline_probes("bin/hooks-daemon probe PreToolUse --file payload.json")

    def test_a_prose_line_is_judged_by_its_code_span(self) -> None:
        command = 'echo \'{"synthetic_source":"manual-probe"}\' | bash .claude/hooks/stop'
        assert inline_probes(f"3. **Blocks**: `{command}` returns a block") == [(1, command)]


_JUDGE_CONFIG = "version: '1.0'\ndaemon:\n  idle_timeout_seconds: 600\nhandlers: {}\n"


@pytest.fixture(scope="module")
def judge(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    """Judge a Bash command as this project's own handlers would.

    The prober's command is what a guard sees, so the command is dispatched
    as a Bash PreToolUse through the real controller, with the handler
    section of this repository's own ``.claude/hooks-daemon.yaml``.
    """
    workspace = tmp_path_factory.mktemp("probe-judge")
    (workspace / ".claude").mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".claude" / "hooks-daemon.yaml").write_text(_JUDGE_CONFIG, encoding="utf-8")
    repo_config = (REPO_ROOT / ".claude" / "hooks-daemon.yaml").read_text(encoding="utf-8")
    controller = DaemonController()
    # ``return_value``: initialise() resolves the git remote through subprocess.
    with patch("subprocess.run", return_value=Mock(returncode=0, stdout="/tmp/test\n")):
        controller.initialise(
            handler_config=yaml.safe_load(repo_config)["handlers"], workspace_root=workspace
        )
    judged = 0

    def _judge(command: str) -> dict[str, Any]:
        nonlocal judged
        judged += 1
        # A fresh session per command: a once-per-session guard judges each afresh.
        return controller.process_request(
            {
                "event": "PreToolUse",
                "hook_input": {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "session_id": f"probe-judge-{judged}",
                    "cwd": str(workspace),
                    # Judged as the main thread that would run the command.
                    **_MAIN_PROBE,
                },
            }
        )

    yield _judge
    ProjectContext.reset()


def test_the_judge_denies_an_inline_probe_of_a_guarded_command(judge: Any) -> None:
    """Otherwise the corpus test below would pass on a judge that denies nothing."""
    probe = (
        'echo \'{"tool_name":"Bash","tool_input":{"command":"git reset --hard"},'
        '"synthetic_source":"manual-probe","probe_as":"main"}\' | bash .claude/hooks/pre-tool-use'
    )
    assert response_decision(judge(probe)) == "deny"


def test_no_documented_inline_probe_is_denied_before_it_is_sent(judge: Any) -> None:
    offenders = []
    for path in _documents():
        for number, command in inline_probes(path.read_text(encoding="utf-8")):
            response = judge(command)
            if response_decision(response) == "deny":
                reason = response_text(response).splitlines()[0]
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {reason}")
    assert not offenders, (
        "These documented probes spell out, in the prober's own Bash command, a "
        "command this project's guards deny, so the probe is blocked before it "
        "reaches the hook. Show the payload as a file and send it with "
        f"`{HELPER} <Event> --file <path>`:\n" + "\n".join(offenders)
    )


def test_the_corpus_is_not_empty() -> None:
    """A glob typo would otherwise make every assertion below vacuous."""
    documents = _documents()
    assert any(path.name == "DEBUGGING_HOOKS.md" for path in documents)
    assert any(has_dispatch(path.read_text(encoding="utf-8")) for path in documents)


def test_every_documented_raw_probe_sets_the_synthetic_marker() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line}"
        for path in _documents()
        for number, line in unmarked_dispatches(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"These documented commands send a hand-built payload to a hook entry point "
        f"without `{SYNTHETIC_SOURCE_FIELD}`, so verdicts.jsonl records the probe as a "
        f'real agent\'s traffic. Add `"{SYNTHETIC_SOURCE_FIELD}":"manual-probe"` to the '
        f"payload, or use `{HELPER}`, which sets it. A probe of a MAIN- or "
        f'SUB-scoped handler also names its thread: `"probe_as":"main"`:\n' + "\n".join(offenders)
    )


def test_every_document_that_teaches_a_raw_probe_also_shows_the_helper() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _documents()
        if has_dispatch(text := path.read_text(encoding="utf-8")) and HELPER not in text
    ]
    assert not offenders, (
        f"These documents teach piping a raw payload into a hook but never show "
        f"`{HELPER}`, the helper that marks the probe itself:\n" + "\n".join(offenders)
    )

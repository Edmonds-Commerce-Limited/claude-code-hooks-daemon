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

A new example written without the field fails here, not in a month's worth of
misclassified records.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.synthetic_traffic import SYNTHETIC_SOURCE_FIELD

REPO_ROOT = Path(__file__).resolve().parents[2]

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


class TestTheDetector:
    """The guard is only as good as its reading of a command."""

    @pytest.mark.parametrize(
        "text",
        [
            'echo \'{"tool_name":"Bash"}\' | bash .claude/hooks/pre-tool-use',
            'echo \'{"hook_event_name":"Stop"}\' | /workspace/.claude/hooks/stop',
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
            'echo \'{"hook_event_name":"Stop"}\' | bash .claude/hooks/stop'
        )
        assert unmarked_dispatches(text)


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

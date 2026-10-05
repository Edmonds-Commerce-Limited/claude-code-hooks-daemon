"""`init.sh`'s fail-open answers must validate against EVERY event's output contract.

Claude Code validates hook JSON output strictly. The fail-open branches of
`emit_hook_error` (venv missing, not installed, CI enforced, daemon not
running) used to print `{"hookSpecificOutput": {"hookEventName": <event>,
"additionalContext": ...}}` for every non-Stop event, but most events define no
`hookSpecificOutput` at all (SessionEnd, PreCompact, Notification, ...). In a
client project with no daemon, SessionEnd failed with "Hook JSON output
validation failed", and the remedy text was discarded with the document.

The contract is `contracts/claude-code-hooks/<Event>.json` (read through
`tests/support/event_output_contract.py`); nothing here restates it. Every
event the contracts name is driven through every branch, with both encoders.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

from tests.support.event_output_contract import (
    contract_violations,
    events_accepting_context,
    load_event_contracts,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_INIT_SH: Final[Path] = _REPO_ROOT / "init.sh"
_RUN_TIMEOUT_SECONDS: Final[int] = 120
_MARKER: Final[str] = "@@@EVENT@@@"

#: Tools init.sh may invoke at source time, plus the fallback's own encoder.
_ESSENTIAL_TOOLS: Final[tuple[str, ...]] = (
    "sh",
    "bash",
    "env",
    "python3",
    "cat",
    "dirname",
    "basename",
    "tr",
    "hostname",
    "stat",
    "date",
    "mkdir",
    "touch",
    "chmod",
    "rm",
    "ls",
    "grep",
    "awk",
    "uname",
    "head",
    "cut",
    "sort",
    "wc",
)

#: Each fail-open branch of emit_hook_error / the provisioning answer, as the
#: shell assignments that select it.
_BRANCHES: Final[dict[str, str]] = {
    "not_installed": "_HOOKS_DAEMON_NOT_INSTALLED=true",
    "venv_missing": "_HOOKS_DAEMON_VENV_MISSING=true",
    "ci_enforced": "_HOOKS_DAEMON_CI_ENFORCED=true",
    "daemon_not_running": ":",
    "needs_provision": (
        "_HOOKS_DAEMON_NEEDS_PROVISION=true; _HOOKS_DAEMON_UNPROVISIONED_MODE=warn; "
        "_HOOKS_DAEMON_UNPROVISIONED_MODE_NOTE=''"
    ),
}

_EVENTS: Final[tuple[str, ...]] = tuple(sorted(load_event_contracts()))


def _curated_bin(tmp_path: Path, *, with_jq: bool) -> Path:
    bindir = tmp_path / ("bin-with-jq" if with_jq else "bin-without-jq")
    bindir.mkdir()
    for tool in (*_ESSENTIAL_TOOLS, *(("jq",) if with_jq else ())):
        real = shutil.which(tool)
        if real is not None:
            (bindir / tool).symlink_to(real)
    return bindir


_CACHE: Final[dict[tuple[str, bool], dict[str, str]]] = {}


def _answers(tmp_path: Path, branch: str, *, with_jq: bool) -> dict[str, str]:
    """`{event: stdout}` for one branch, every event answered in one shell.

    Cached per (branch, encoder): the answer depends on nothing else, and each
    run sources init.sh once per event.
    """
    key = (branch, with_jq)
    if key not in _CACHE:
        _CACHE[key] = _run_answers(tmp_path, branch, with_jq=with_jq)
    return _CACHE[key]


def _run_answers(tmp_path: Path, branch: str, *, with_jq: bool) -> dict[str, str]:
    checkout = tmp_path / "client-project"
    (checkout / ".claude").mkdir(parents=True)
    (checkout / ".claude" / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"))
    bindir = _curated_bin(tmp_path, with_jq=with_jq)
    script = (
        f'source "{checkout / ".claude" / "init.sh"}" >/dev/null 2>&1\n'
        "for event in \"$@\"; do\n"
        f'    printf "%s%s\\n" "{_MARKER}" "$event"\n'
        f"    ( {_BRANCHES[branch]}\n"
        '      emit_hook_error "$event" "daemon_not_installed" "no daemon here" '
        "</dev/null 2>/dev/null )\n"
        "done\n"
    )
    result = subprocess.run(
        ["bash", "-c", script, "bash", *_EVENTS],
        capture_output=True,
        text=True,
        env={"PATH": str(bindir), "HOME": str(tmp_path)},
        timeout=_RUN_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    answers: dict[str, str] = {}
    for chunk in result.stdout.split(_MARKER)[1:]:
        event, _, body = chunk.partition("\n")
        answers[event] = body
    return answers


@pytest.fixture(params=[True, False], ids=["jq", "python3-fallback"])
def with_jq(request: pytest.FixtureRequest) -> bool:
    if request.param and shutil.which("jq") is None:
        pytest.skip("jq is not installed on this machine")
    return bool(request.param)


@pytest.mark.parametrize("branch", sorted(_BRANCHES))
class TestEveryEventGetsAContractValidAnswer:
    def test_each_answer_validates_against_the_event_contract(
        self, tmp_path: Path, branch: str, with_jq: bool
    ) -> None:
        answers = _answers(tmp_path, branch, with_jq=with_jq)

        assert set(answers) == set(_EVENTS), "an event produced no answer block"
        problems: list[str] = []
        for event, body in answers.items():
            assert body.strip(), f"{branch}/{event}: no output at all"
            try:
                response = json.loads(body)
            except json.JSONDecodeError as exc:
                problems.append(f"{event}: not JSON ({exc})")
                continue
            problems.extend(f"{event}: {p}" for p in contract_violations(event, response))
        assert not problems, f"{branch}: " + "; ".join(problems)

    def test_the_message_survives_for_every_event(
        self, tmp_path: Path, branch: str, with_jq: bool
    ) -> None:
        """Valid but empty is no fix: the guidance must be in the document."""
        for event, body in _answers(tmp_path, branch, with_jq=with_jq).items():
            if event in ("Stop", "SubagentStop"):
                continue  # a block decision, whose reason carries the message
            text = json.dumps(json.loads(body))
            assert "daemon" in text.lower(), f"{branch}/{event}: {text}"


class TestSessionEndIsTheReportedCase:
    def test_session_end_gets_a_system_message_not_hook_specific_output(
        self, tmp_path: Path, with_jq: bool
    ) -> None:
        answers = _answers(tmp_path, "not_installed", with_jq=with_jq)

        response = json.loads(answers["SessionEnd"])
        assert "hookSpecificOutput" not in response
        assert "daemon" in response["systemMessage"].lower()

    def test_a_context_event_still_gets_additional_context(
        self, tmp_path: Path, with_jq: bool
    ) -> None:
        answers = _answers(tmp_path, "not_installed", with_jq=with_jq)

        hso = json.loads(answers["SessionStart"])["hookSpecificOutput"]
        assert hso["hookEventName"] == "SessionStart"
        assert hso["additionalContext"]

    def test_stop_keeps_its_block_decision(self, tmp_path: Path, with_jq: bool) -> None:
        answers = _answers(tmp_path, "not_installed", with_jq=with_jq)

        assert json.loads(answers["Stop"])["decision"] == "block"


class TestTheShellListMatchesTheContracts:
    """`_HOOKS_DAEMON_CONTEXT_EVENTS` is the one list; the contracts are the truth."""

    def test_the_list_is_exactly_the_events_with_additional_context(self) -> None:
        text = _INIT_SH.read_text(encoding="utf-8")
        line = next(
            ln for ln in text.splitlines() if ln.startswith("_HOOKS_DAEMON_CONTEXT_EVENTS=")
        )
        listed = frozenset(line.split("=", 1)[1].strip('"').split())

        assert listed == events_accepting_context()


class TestTheTransportFailOpen:
    """`send_request_stdin`'s own fail-open (no daemon socket) for every event."""

    def test_each_answer_validates_against_the_event_contract(self, tmp_path: Path) -> None:
        checkout = tmp_path / "client-project"
        (checkout / ".claude").mkdir(parents=True)
        (checkout / ".claude" / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"))
        missing_socket = tmp_path / "s" / "none.sock"
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
        }
        env["CLAUDE_HOOKS_SOCKET_PATH"] = str(missing_socket)
        env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = "5"
        script = (
            'source .claude/init.sh >/dev/null 2>&1\n'
            'for event in "$@"; do\n'
            f'    printf "%s%s\\n" "{_MARKER}" "$event"\n'
            "    printf '{}' | send_request_stdin \"$event\" 2>/dev/null\n"
            "done\n"
        )
        result = subprocess.run(
            ["bash", "-c", script, "bash", *_EVENTS],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT_SECONDS,
            check=False,
        )
        problems: list[str] = []
        for chunk in result.stdout.split(_MARKER)[1:]:
            event, _, body = chunk.partition("\n")
            if not body.strip():
                problems.append(f"{event}: no output")
                continue
            problems.extend(
                f"{event}: {p}" for p in contract_violations(event, json.loads(body))
            )
        assert not problems, "; ".join(problems)

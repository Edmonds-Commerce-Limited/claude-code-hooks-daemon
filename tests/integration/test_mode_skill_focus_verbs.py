"""The ``/mode`` skill's focus verbs (Plan 00501 Task 3.3).

``/mode focus <task>`` and ``/mode focus off`` (or ``done``, ``end``,
``disable``) route to ``hooks-daemon session-mode``; the existing ``get``,
``default`` and ``unattended`` verbs keep routing to ``get-mode``/``set-mode``.
The skill's ``invoke.sh`` prints the procedure, so its output is what is pinned.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "mode"


def _invoke(*args: str) -> str:
    completed = subprocess.run(
        ["bash", str(_SKILL_DIR / "invoke.sh"), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_focus_with_a_task_routes_to_session_mode_focus() -> None:
    out = _invoke("focus", "fix", "the", "parser")
    assert '"$DAEMON_CLI" session-mode focus <task words>' in out


@pytest.mark.parametrize("alias", ["off", "done", "end", "disable"])
def test_each_off_alias_is_documented(alias: str) -> None:
    assert f"`{alias}`" in _invoke("focus", alias)


def test_focus_off_routes_to_session_mode_focus_off() -> None:
    assert '"$DAEMON_CLI" session-mode focus off' in _invoke("focus", "off")


def test_get_also_shows_the_session_modes() -> None:
    out = _invoke("get")
    assert '"$DAEMON_CLI" get-mode' in out
    assert '"$DAEMON_CLI" session-mode get' in out


def test_the_daemon_mode_verbs_are_unchanged() -> None:
    out = _invoke("unattended", "finish")
    assert '"$DAEMON_CLI" set-mode default' in out
    assert '"$DAEMON_CLI" set-mode unattended -m "<message>"' in out


def test_the_skill_page_lists_the_focus_verbs() -> None:
    page = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "/mode focus <task>" in page
    assert "/mode focus off" in page
    assert "get_session_modes" in page

"""The environment segment says when autonomy is off here (Plan 00498 Task 2.3).

The segment already tells desktop, lxc, podman and docker apart, so it is the
natural place to show that the project's `autonomy:` config turned the
work-driving machinery off for this environment. It reads the runtime
`ProjectContext` cached at startup, exactly as before, so it still does no
per-render probing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from tests.support.autonomy import CONTAINERS_ONLY, focus_entry, pin_autonomy, pin_session_modes

from claude_code_hooks_daemon.handlers.status_line.environment_indicator import (
    _COLOR_BLUE,
    _COLOR_GREY,
    _COLOR_RED,
    _COLOR_RESET,
    EnvironmentIndicatorHandler,
)

_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.status_line.environment_indicator."
    "ProjectContext.container_runtime"
)


def _segment(runtime: str | None) -> str:
    with patch(_PATCH_TARGET, return_value=runtime):
        return EnvironmentIndicatorHandler().handle({}).context[0]


def test_a_desktop_where_autonomy_is_off_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_autonomy(monkeypatch, runtime=None, autonomy_config=CONTAINERS_ONLY)
    assert _segment(None) == (
        f"| {_COLOR_RED}💻 desktop{_COLOR_RESET} {_COLOR_GREY}no autonomy{_COLOR_RESET}"
    )


def test_a_container_where_autonomy_is_on_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_autonomy(monkeypatch, runtime="docker", autonomy_config=CONTAINERS_ONLY)
    assert _segment("docker") == f"| {_COLOR_BLUE}🐳 docker{_COLOR_RESET}"


def test_a_project_without_the_block_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_autonomy(monkeypatch, runtime=None)
    assert _segment(None) == f"| {_COLOR_RED}💻 desktop{_COLOR_RESET}"


def test_the_judgement_uses_the_cached_runtime_not_a_live_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The live detector would say "docker" (autonomy on); the cached runtime says
    # host. The segment must follow the cached one.
    pin_autonomy(monkeypatch, runtime="docker", autonomy_config=CONTAINERS_ONLY)
    assert "no autonomy" in _segment(None)


def test_a_session_mode_does_not_add_no_autonomy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "no autonomy" names the ENVIRONMENT; a session's modes get their own
    # segment (Plan 00501 Task 4.1), so a focused container session is unchanged.
    pin_autonomy(monkeypatch, runtime="docker", autonomy_config=CONTAINERS_ONLY)
    pin_session_modes(monkeypatch, tmp_path, focus_entry("s1"))
    with patch(_PATCH_TARGET, return_value="docker"):
        segment = EnvironmentIndicatorHandler().handle({"session_id": "s1"}).context[0]
    assert segment == f"| {_COLOR_BLUE}🐳 docker{_COLOR_RESET}"


def test_no_mode_keeps_the_desktop_no_autonomy_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_autonomy(monkeypatch, runtime=None, autonomy_config=CONTAINERS_ONLY)
    pin_session_modes(monkeypatch, tmp_path)
    with patch(_PATCH_TARGET, return_value=None):
        segment = EnvironmentIndicatorHandler().handle({"session_id": "s1"}).context[0]
    assert segment.endswith(f"{_COLOR_GREY}no autonomy{_COLOR_RESET}")

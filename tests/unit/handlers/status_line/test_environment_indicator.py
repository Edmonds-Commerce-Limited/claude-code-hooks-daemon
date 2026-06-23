"""Tests for EnvironmentIndicatorHandler (Plan 00126).

The status line renders on every Claude Code refresh, so this handler must do
NO per-render work: it reads the container runtime that ProjectContext computed
once at startup and maps it to an icon. Desktop (host) → 💻; docker → 🐳;
podman/generic → 📦.
"""

from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.handlers.status_line.environment_indicator import (
    _COLOR_BLUE,
    _COLOR_CYAN,
    _COLOR_GREY,
    _COLOR_MAGENTA,
    _COLOR_RED,
    _COLOR_RESET,
    EnvironmentIndicatorHandler,
)

_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.status_line.environment_indicator."
    "ProjectContext.container_runtime"
)


class TestEnvironmentIndicatorInit:
    def test_identity_and_flags(self) -> None:
        handler = EnvironmentIndicatorHandler()
        assert handler.handler_id == HandlerID.ENVIRONMENT_INDICATOR
        assert handler.priority == Priority.ENVIRONMENT_INDICATOR
        assert handler.terminal is False

    def test_matches_always_true(self) -> None:
        assert EnvironmentIndicatorHandler().matches({}) is True

    def test_get_claude_md_is_none(self) -> None:
        assert EnvironmentIndicatorHandler().get_claude_md() is None


class TestEnvironmentIndicatorRendering:
    def _segment(self, runtime: str | None) -> str:
        with patch(_PATCH_TARGET, return_value=runtime):
            result = EnvironmentIndicatorHandler().handle({})
        assert result.context, "handler must emit a status segment"
        return result.context[0]

    def test_desktop_host_shows_laptop_icon(self) -> None:
        segment = self._segment(None)
        assert "💻" in segment
        assert "🐳" not in segment and "📦" not in segment

    def test_docker_shows_whale(self) -> None:
        segment = self._segment("docker")
        assert "🐳" in segment
        assert "docker" in segment

    def test_podman_shows_package(self) -> None:
        segment = self._segment("podman")
        assert "📦" in segment
        assert "podman" in segment

    def test_generic_container_shows_package(self) -> None:
        segment = self._segment("generic")
        assert "📦" in segment

    def test_handle_renders_lxc_icon(self) -> None:
        # Plan 00127 Phase 4: an 'lxc' runtime renders the distinct ice-cube glyph.
        # Plan 00136 follow-up: now wrapped in its distinct (cyan) colour.
        segment = self._segment("lxc")
        assert segment == f"| {_COLOR_CYAN}🧊 lxc{_COLOR_RESET}"
        assert "🐳" not in segment and "📦" not in segment and "💻" not in segment

    def test_segment_has_separator_prefix(self) -> None:
        # Not the leftmost segment (git_repo_name is priority 3) — must carry the
        # "| " separator convention used by the other non-first segments.
        assert self._segment(None).startswith("|")


class TestEnvironmentIndicatorColours:
    """Each environment renders in its own colour (user request, 2026-06-23).

    Desktop is red; the container runtimes use distinct, brand-relevant where
    possible, non-semantic colours: docker=blue (brand), podman=magenta/purple
    (brand), lxc=cyan (no strong brand colour — kept distinct), generic=grey.
    Every segment is colour-reset at the end so it never bleeds into the next.
    """

    def _segment(self, runtime: str | None) -> str:
        with patch(_PATCH_TARGET, return_value=runtime):
            return EnvironmentIndicatorHandler().handle({}).context[0]

    def test_desktop_is_red(self) -> None:
        segment = self._segment(None)
        assert segment == f"| {_COLOR_RED}💻 desktop{_COLOR_RESET}"

    def test_docker_is_blue(self) -> None:
        segment = self._segment("docker")
        assert segment == f"| {_COLOR_BLUE}🐳 docker{_COLOR_RESET}"

    def test_podman_is_magenta(self) -> None:
        segment = self._segment("podman")
        assert segment == f"| {_COLOR_MAGENTA}📦 podman{_COLOR_RESET}"

    def test_generic_is_grey(self) -> None:
        segment = self._segment("generic")
        assert segment == f"| {_COLOR_GREY}📦 container{_COLOR_RESET}"

    def test_unknown_runtime_falls_back_to_grey(self) -> None:
        segment = self._segment("kubernetes")
        assert segment == f"| {_COLOR_GREY}📦 kubernetes{_COLOR_RESET}"

    def test_every_segment_resets_colour(self) -> None:
        for runtime in (None, "docker", "podman", "lxc", "generic"):
            assert self._segment(runtime).endswith(_COLOR_RESET)

    def test_reads_cached_value_not_live_probe(self) -> None:
        # The handler must consult ProjectContext (the startup cache), never the
        # live detector — proven by the cached classmethod being the only source.
        with patch(_PATCH_TARGET, return_value="docker") as mock_runtime:
            EnvironmentIndicatorHandler().handle({})
        mock_runtime.assert_called_once()

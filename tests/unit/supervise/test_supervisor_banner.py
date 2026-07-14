"""Plan 00164 Phase 2 — supervisor version marker + startup banner.

The ccy PTY supervisor launches with no visible feedback during the perceptible
start-up lull. This adds:

- a ``__version__`` marker on the standalone supervisor (display + staleness), and
- ``render_startup_banner()`` — an informative ASCII banner shown to stderr as the
  first thing on launch, so a launching ccy session immediately sees
  "ECHD ccy Supervisor" instead of a silent hang.

The banner is a pure function (deterministic, testable). Whether it animates is
gated by ``_should_show_banner`` (TTY + opt-out env) so piped/non-interactive
launches and the test suite stay silent.
"""

from __future__ import annotations

import io

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()


def test_supervisor_has_version_string() -> None:
    version = _mod.__version__
    assert isinstance(version, str)
    # A dotted numeric version like 3.40.0 (leading 'v' optional).
    core = version.lstrip("v")
    parts = core.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:2]), f"unexpected version: {version!r}"


def test_banner_names_product_and_version() -> None:
    banner = _mod.render_startup_banner(version="3.40.0", armed=True)
    assert "ECHD" in banner
    assert "Supervisor" in banner
    assert "3.40.0" in banner


def test_banner_shows_armed_mode() -> None:
    armed = _mod.render_startup_banner(version="3.40.0", armed=True)
    dry = _mod.render_startup_banner(version="3.40.0", armed=False)
    assert "ARMED" in armed
    assert "ARMED" not in dry
    # The dry-run banner must make its harmless mode obvious.
    assert "dry" in dry.lower()


def test_banner_is_multiline_box() -> None:
    banner = _mod.render_startup_banner(version="3.40.0", armed=True)
    assert banner.count("\n") >= 2


def test_should_show_banner_requires_tty() -> None:
    """A non-tty stream (piped output, the test harness) must not animate."""
    non_tty = io.StringIO()
    assert _mod._should_show_banner(non_tty, env={}) is False


def test_should_show_banner_respects_opt_out_env() -> None:
    class _FakeTty(io.StringIO):
        def isatty(self) -> bool:
            return True

    tty = _FakeTty()
    assert _mod._should_show_banner(tty, env={}) is True
    assert _mod._should_show_banner(tty, env={"CLAUDE_SUPERVISE_NO_BANNER": "1"}) is False

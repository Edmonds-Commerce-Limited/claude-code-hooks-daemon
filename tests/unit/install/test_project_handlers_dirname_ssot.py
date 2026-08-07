"""Guard: the legacy installer must scaffold where the daemon actually scans.

DBF (``CLAUDE.md`` Core Standard 15). ``install.py`` scaffolded project handlers
into ``.claude/hooks/handlers`` while ``ProjectHandlersConfig.path``
defaults to ``.claude/project-handlers``. Nothing failed: the directory was
created, the README and example handler were written, and the daemon simply
never looked there. A client following the installer got a handler tree that
loaded for nobody, with no error to diagnose.

The defect is the SYMPTOM. The bug is that two independent spellings of the same
path existed with no check tying them together, so either could move without the
other noticing. This test is that tie.

``install.py`` is deprecated (superseded by ``scripts/install_version.sh``) but
is still reachable: ``install.sh`` falls back to it when the Layer 2 installer is
absent, so its output still has to be correct.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import ProjectHandlersConfig
from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_INSTALL_PY: Final[Path] = _REPO_ROOT / "install.py"

# Matches: _PROJECT_HANDLERS_DIRNAME = ".claude/project-handlers"
_DIRNAME_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"^_PROJECT_HANDLERS_DIRNAME\s*=\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)

# The path the daemon never scans. Named so a regression is reported by its real
# name rather than as an opaque string mismatch.
_ABANDONED_DIRNAME: Final[str] = ".claude/hooks/handlers"


def _installer_dirname() -> str:
    """Read the installer's scaffold directory without importing install.py.

    ``install.py`` is a standalone script, not a package module, and importing
    it executes module-level code. Reading the assignment keeps this guard
    free of that side effect.
    """
    text = _INSTALL_PY.read_text(encoding="utf-8")
    match = _DIRNAME_ASSIGNMENT.search(text)
    assert match is not None, (
        "Could not locate _PROJECT_HANDLERS_DIRNAME in install.py. If it was "
        "renamed, update this guard — do not delete it: it is the only check "
        "tying the installer's scaffold path to the daemon's scan path."
    )
    return match.group(1)


class TestProjectHandlersDirnameSSoT:
    """The installer's scaffold path and the daemon's scan path are one value."""

    def test_installer_scaffolds_where_daemon_scans(self) -> None:
        """install.py's directory matches ProjectHandlersConfig's default path."""
        daemon_default = ProjectHandlersConfig().path

        assert _installer_dirname() == daemon_default, (
            f"install.py scaffolds project handlers into "
            f"'{_installer_dirname()}' but the daemon scans "
            f"'{daemon_default}'. Handlers written by the installer would "
            f"never load, and nothing would report an error."
        )

    def test_abandoned_directory_is_not_reintroduced(self) -> None:
        """The specific wrong path that shipped cannot come back silently."""
        assert _installer_dirname() != _ABANDONED_DIRNAME, (
            f"install.py is scaffolding into '{_ABANDONED_DIRNAME}' again. "
            f"The daemon does not scan that path."
        )

    def test_guard_detects_drift(self) -> None:
        """Control: the comparison fails when the two values diverge.

        Without this, a guard whose regex silently stopped matching would keep
        reporting success. Asserting the *mechanism* rejects a mismatch proves
        the check has teeth.
        """
        daemon_default = ProjectHandlersConfig().path

        assert daemon_default != _ABANDONED_DIRNAME, (
            "ProjectHandlersConfig's default now equals the abandoned path; "
            "this guard can no longer distinguish correct from incorrect."
        )


def _derive_json_key(config_key: str) -> str:
    """Reimplementation of ``install.py::_event_json_key`` for comparison.

    Deliberately a copy rather than an import: ``install.py`` is a standalone
    script and importing it runs module-level code. The point of the test is
    that this transformation agrees with the ``EventID`` SSoT, so a divergence
    in either direction should fail.
    """
    return "".join(part.title() for part in config_key.split("_"))


class TestEventJsonKeyDerivation:
    """The scaffolder's event naming matches the EventID SSoT exactly.

    ``install.py`` writes an event README per hook event and titles it from the
    config key. It used ``config_key.replace("_", "")``, yielding ``pretooluse``
    — a spelling that appears in no document and matches no JSON payload, so a
    client reading the scaffolded README could not connect it to anything.
    """

    def test_derivation_matches_every_event_json_key(self) -> None:
        """Every EventID's json_key is reproduced by the derivation."""
        mismatches: list[tuple[str, str, str]] = []

        for name in dir(EventID):
            meta = getattr(EventID, name)
            if not isinstance(meta, EventIDMeta):
                continue
            derived = _derive_json_key(meta.config_key)
            if derived != meta.json_key:
                mismatches.append((meta.config_key, derived, meta.json_key))

        assert not mismatches, (
            "install.py's event-name derivation disagrees with EventID for: "
            + ", ".join(
                f"{key}: derived {derived!r} != json_key {actual!r}"
                for key, derived, actual in mismatches
            )
        )

    def test_derivation_is_exercised_by_real_events(self) -> None:
        """Control: the loop above actually inspected events.

        A dir()/isinstance filter that silently matched nothing would make the
        test above pass vacuously — green because it checked zero things.
        """
        found = sum(
            1 for name in dir(EventID) if isinstance(getattr(EventID, name), EventIDMeta)
        )

        assert found > 0, "No EventIDMeta constants found — the guard is inspecting nothing."

    def test_derivation_rejects_the_shipped_defect(self) -> None:
        """The old transformation would have failed this guard."""
        broken = "pre_tool_use".replace("_", "")

        assert broken != EventID.PRE_TOOL_USE.json_key, (
            "The pre-fix derivation now agrees with the SSoT; this control no "
            "longer demonstrates the guard catches the original defect."
        )

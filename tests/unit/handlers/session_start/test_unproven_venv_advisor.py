"""Plan 00517 Task 4.2: the SessionStart advisory for UNPROVEN venvs.

A venv with missing or unreadable metadata, or another view's slug, is not
proven stale, so nothing removes it automatically. The advisory puts it in front
of the running agent with the evidence needed to judge it and the exact removal
command, and says nothing at all when there is nothing to report.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.paths import project_path_slug
from claude_code_hooks_daemon.handlers.session_start.unproven_venv_advisor import (
    UnprovenVenvAdvisorHandler,
)

STALE_HASH = "sha256:" + "0" * 64
_RESOLVER = "claude_code_hooks_daemon.daemon.paths.resolve_existing_venv_python"


def _venv(path: Path, lock_hash: str | None = None) -> Path:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    (path / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.11.2\n")
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": lock_hash})
        )
    return path


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "untracked").mkdir()
    with patch(_RESOLVER, return_value=tmp_path / "no-venv" / "bin" / "python"):
        yield tmp_path


def _handler(project: Path) -> UnprovenVenvAdvisorHandler:
    handler = UnprovenVenvAdvisorHandler()
    handler.workspace_root = project
    return handler


def _session(**overrides: Any) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": "startup", **overrides}


class TestUnprovenVenvAdvisor:
    def test_matches_every_session_start_including_resume(self, project: Path) -> None:
        handler = _handler(project)

        assert handler.matches(_session()) is True
        assert handler.matches(_session(source="resume")) is True

    def test_silent_when_there_are_no_venvs(self, project: Path) -> None:
        result = _handler(project).handle(_session())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_every_venv_is_explained(self, project: Path) -> None:
        slug = project_path_slug(project)
        _venv(project / "untracked" / f"venv-{slug}-py310-aaaaaaaa", STALE_HASH)  # proven stale

        assert _handler(project).handle(_session()).context == []

    def test_reports_each_unproven_venv_with_evidence_and_the_removal_command(
        self, project: Path
    ) -> None:
        slug = project_path_slug(project)
        orphan = _venv(project / "untracked" / f"venv-{slug}-py310-aaaaaaaa")
        other_view = _venv(project / "untracked" / "venv-elsewhere-py310-bbbbbbbb", STALE_HASH)

        result = _handler(project).handle(_session())

        text = "\n".join(result.context)
        assert result.decision == Decision.ALLOW
        assert "2 UNPROVEN venv(s)" in text
        assert str(orphan) in text
        assert str(other_view) in text
        assert "no process found using it" in text
        assert "another view (slug 'elsewhere'" in text
        assert f"prune-venvs --unproven {orphan} --force" in text
        assert "confirmed it is unused and safe" in text

    def test_silent_when_the_project_root_is_unknown(self) -> None:
        handler = UnprovenVenvAdvisorHandler()

        with patch(
            "claude_code_hooks_daemon.handlers.session_start.unproven_venv_advisor."
            "ProjectContext.is_initialized",
            return_value=False,
        ):
            assert handler.handle(_session()).context == []

    def test_live_venv_is_not_reported(self, project: Path) -> None:
        slug = project_path_slug(project)
        live = _venv(project / "untracked" / f"venv-{slug}-py310-aaaaaaaa")

        with patch(_RESOLVER, return_value=live / "bin" / "python"):
            assert _handler(project).handle(_session()).context == []

    def test_acceptance_test_is_a_context_case(self) -> None:
        (case,) = UnprovenVenvAdvisorHandler().get_acceptance_tests()

        assert case.expected_decision == Decision.ALLOW

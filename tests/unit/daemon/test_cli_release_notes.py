"""Tests for the cmd_release_notes CLI command (Plan 00141).

Covers the argparse-facing wrapper: version / list / latest / range / json
modes, exit codes (0 found / 1 not-found / 2 bad args), and the known-versions
hint on a bad range.
"""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_release_notes
from claude_code_hooks_daemon.version import __version__


def _make_releases_dir(tmp_path: Path) -> Path:
    d = tmp_path / "RELEASES"
    d.mkdir(parents=True, exist_ok=True)
    for version in ("3.20.0", "3.21.0", "3.27.0"):
        (d / f"v{version}.md").write_text(f"# v{version}\n\nNotes for {version}\n")
    return d


def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "version": None,
        "from_version": None,
        "to_version": None,
        "list_versions": False,
        "latest": False,
        "format": "markdown",
        "releases_dir": str(_make_releases_dir(tmp_path)),
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdReleaseNotes:
    def test_specific_version_found_returns_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_release_notes(_args(tmp_path, version="3.21.0"))
        assert result == 0
        assert "Notes for 3.21.0" in capsys.readouterr().out

    def test_missing_version_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_release_notes(_args(tmp_path, version="9.9.9"))
        assert result == 1
        assert "9.9.9" in capsys.readouterr().out

    def test_list_returns_zero_and_lists_versions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_release_notes(_args(tmp_path, list_versions=True))
        assert result == 0
        out = capsys.readouterr().out
        assert "v3.20.0" in out
        assert "v3.27.0" in out

    def test_latest_returns_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        result = cmd_release_notes(_args(tmp_path, latest=True))
        assert result == 0
        assert "Notes for 3.27.0" in capsys.readouterr().out

    def test_range_returns_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        result = cmd_release_notes(_args(tmp_path, from_version="3.20.0", to_version="3.27.0"))
        assert result == 0
        out = capsys.readouterr().out
        assert "Notes for 3.21.0" in out
        assert "Notes for 3.27.0" in out

    def test_invalid_range_returns_two_and_lists_known(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_release_notes(_args(tmp_path, from_version="3.27.0", to_version="3.20.0"))
        assert result == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "3.27.0" in err

    def test_single_bound_range_returns_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_release_notes(_args(tmp_path, from_version="3.20.0"))
        assert result == 2
        assert "ERROR" in capsys.readouterr().err

    def test_json_output_parses_and_omits_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_release_notes(_args(tmp_path, version="3.21.0", format="json"))
        assert result == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["found"] is True
        assert "text" not in payload
        assert payload["notes"][0]["version"] == "3.21.0"

    def test_defaults_to_installed_version(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A RELEASES dir containing exactly the installed version => default hit.
        d = tmp_path / "RELEASES"
        d.mkdir()
        (d / f"v{__version__}.md").write_text(f"# v{__version__}\n\nInstalled notes\n")
        args = argparse.Namespace(
            version=None,
            from_version=None,
            to_version=None,
            list_versions=False,
            latest=False,
            format="markdown",
            releases_dir=str(d),
        )
        result = cmd_release_notes(args)
        assert result == 0
        assert "Installed notes" in capsys.readouterr().out

    def test_missing_releases_dir_attr_uses_default(self) -> None:
        # No releases_dir attribute => falls back to the packaged RELEASES dir,
        # which contains the installed version, so the default-version lookup hits.
        args = argparse.Namespace(
            version=None,
            from_version=None,
            to_version=None,
            list_versions=False,
            latest=False,
            format="markdown",
        )
        result = cmd_release_notes(args)
        assert result == 0

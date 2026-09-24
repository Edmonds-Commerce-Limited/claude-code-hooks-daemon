"""``cache-gaps`` transcript auto-discovery reads the Claude config dir.

Claude Code writes a project's transcripts under
``<config dir>/projects/<slug>/``, where the config dir is
``$CLAUDE_CONFIG_DIR`` when set (Plan 00468 G13). Looking under a hard-coded
``~/.claude`` finds nothing, or an older session, whenever the variable
points elsewhere.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import _resolve_transcript


def _pin_project(monkeypatch: pytest.MonkeyPatch, project: Path) -> argparse.Namespace:
    monkeypatch.setattr(cli, "get_project_path", lambda _override: project)
    return argparse.Namespace(transcript=None, project_root=project)


def _write_transcript(directory: Path, name: str, mtime: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    transcript = directory / name
    transcript.write_text("{}\n", encoding="utf-8")
    os.utime(transcript, (mtime, mtime))
    return transcript


def test_auto_discovery_looks_under_claude_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    config_dir = tmp_path / "config"
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("HOME", str(home))
    slug = str(project).replace("/", "-")
    _write_transcript(home / ".claude" / "projects" / slug, "home.jsonl", 2_000)
    expected = _write_transcript(config_dir / "projects" / slug, "config.jsonl", 1_000)

    resolved = _resolve_transcript(_pin_project(monkeypatch, project))

    assert resolved == expected


def test_auto_discovery_picks_the_newest_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    config_dir = tmp_path / "config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    session_dir = config_dir / "projects" / str(project).replace("/", "-")
    _write_transcript(session_dir, "older.jsonl", 1_000)
    newest = _write_transcript(session_dir, "newer.jsonl", 2_000)

    resolved = _resolve_transcript(_pin_project(monkeypatch, project))

    assert resolved == newest

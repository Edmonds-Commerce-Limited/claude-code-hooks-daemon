"""``hooks-daemon optimise-checklist`` prints the registry-derived checklist (Plan 00330)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_optimise_checklist

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "config": str(_REPO_ROOT / ".claude" / "hooks-daemon.yaml"),
        "project_root": str(_REPO_ROOT),
        "format": "text",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_text_report_covers_every_area(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_optimise_checklist(_args()) == 0
    out = capsys.readouterr().out
    assert "Safety" in out
    assert "Other guards" in out
    assert "relevant handlers enabled" in out


def test_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_optimise_checklist(_args(format="json")) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["items"]
    assert "relevant" in data["summary"]


def test_missing_config_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_optimise_checklist(_args(config=str(tmp_path / "absent.yaml"))) == 2
    assert "not found" in capsys.readouterr().err.lower()

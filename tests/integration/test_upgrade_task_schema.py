"""Every pre- and post-upgrade task keeps the shared schema (Plan 00376 Tasks 2.3 and 4.1).

Plans are obliged to leave upgrade work in ``CLAUDE/UPGRADES/UNRELEASED/``,
and the release moves it into the versioned guide untouched. The upgrade gate
and the post-upgrade report read it with one loader, so a task whose header
the loader cannot read is a task an upgrading agent is told nothing useful
about. This test reads the real tree -- the holding area and every released
guide -- so a malformed task fails CI at the commit that adds it, not at a
client's upgrade.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.upgrade_tasks import (
    REQUIRED_SECTIONS,
    TaskKind,
    schema_errors,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UPGRADES = _REPO_ROOT / "CLAUDE" / "UPGRADES"
_HOLDING_AREA = _UPGRADES / "UNRELEASED"
_TEMPLATE_DIRNAME = "upgrade-template"


def _tasks() -> list[tuple[TaskKind, Path]]:
    found: list[tuple[TaskKind, Path]] = []
    for kind in TaskKind:
        for tasks_dir in _UPGRADES.rglob(kind.value):
            if _TEMPLATE_DIRNAME in tasks_dir.relative_to(_UPGRADES).parts:
                continue
            found.extend(
                (kind, path) for path in sorted(tasks_dir.glob("*.md")) if path.name != "README.md"
            )
    return found


@pytest.mark.parametrize("kind", list(TaskKind), ids=lambda kind: kind.value)
def test_the_holding_area_has_each_task_directory_with_its_readme(kind: TaskKind) -> None:
    readme = _HOLDING_AREA / kind.value / "README.md"
    assert readme.is_file(), f"{readme.relative_to(_REPO_ROOT)} is missing"
    text = readme.read_text(encoding="utf-8")
    for token in ("# Task:", "**Type**", "**Severity**", "**Applies to**", "**Idempotent**"):
        assert token in text, f"{readme.name} for {kind.value} does not document {token}"
    for section in REQUIRED_SECTIONS:
        assert section in text, f"{readme.name} for {kind.value} does not document {section!r}"


def test_the_pre_upgrade_readme_documents_the_detection_contract() -> None:
    text = (_HOLDING_AREA / TaskKind.PRE.value / "README.md").read_text(encoding="utf-8")
    assert "**Detect**" in text
    assert "**Detect in**" in text


def test_there_are_tasks_to_check() -> None:
    assert _tasks(), "no upgrade task files found -- the scan is broken"


@pytest.mark.parametrize(
    ("kind", "task"),
    _tasks(),
    ids=lambda value: str(value.relative_to(_UPGRADES)) if isinstance(value, Path) else "",
)
def test_every_task_matches_the_schema(kind: TaskKind, task: Path) -> None:
    errors = schema_errors(task, kind)
    assert errors == [], f"{task.relative_to(_REPO_ROOT)}:\n  " + "\n  ".join(errors)

"""Every post-upgrade task is reachable from a MANDATORY upgrade step (Plan 00376 Task 4.3).

A post-upgrade task is work a release ships for the upgrading agent to carry
out. Nothing executes it; the only route to it is an agent following a step
that lists it. The upgrade skill once reached these tasks only through a
passing clause inside its config-advisory step, which fires only when a
config key carries a migration Note, so an upgrade that changed no config key
never read them. These tests pin the whole route:

1. the skill has a numbered, mandatory step that runs
   ``check-post-upgrade-tasks``;
2. ``LLM-UPDATE.md`` runs it in its mandatory Post-Update sequence, and the
   bare Layer 1 script runs it before the metadata block;
3. every task file on disk -- pre- or post-upgrade, released under
   ``v{major}/v{A}-to-v{B}/`` or staged under ``UNRELEASED/`` -- is returned
   by the shared resolver for an upgrade that crosses it (the pre-upgrade
   tasks are read by the upgrade gate, which every route runs; see
   ``test_upgrade_pre_deploy_phase_placement.py``). A misnamed guide directory, a misnamed task
   file or a guide numbered past the current version fails here, at the
   commit that adds it, rather than going unread at upgrade time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.upgrade_guides import UNRELEASED_DIRNAME
from claude_code_hooks_daemon.install.upgrade_tasks import TaskKind, tasks_for_range
from claude_code_hooks_daemon.version import __version__

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_UPGRADES = _REPO_ROOT / "CLAUDE" / "UPGRADES"
_TEMPLATE_DIRNAME = "upgrade-template"
_COMMAND = "check-post-upgrade-tasks"
_SKILL_COPIES = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "upgrade.md",
    _REPO_ROOT / ".claude" / "skills" / "hooks-daemon" / "upgrade.md",
)
_LLM_UPDATE = _REPO_ROOT / "CLAUDE" / "LLM-UPDATE.md"
_LAYER1 = _REPO_ROOT / "scripts" / "upgrade.sh"
_METADATA_SENTINEL = "<<<UPGRADE_METADATA"
_STEP_RE = re.compile(r"^(?P<number>\d+)\. \*\*(?P<title>[^*]+)\*\*", re.MULTILINE)
_MANDATORY_RE = re.compile(r"\bMANDATORY\b", re.IGNORECASE)
_EARLIEST = "0.0.0"


def _numbered_steps(text: str) -> list[tuple[int, str, str]]:
    """(number, title, body) for every top-level numbered step."""
    matches = list(_STEP_RE.finditer(text))
    steps: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        steps.append((int(match.group("number")), match.group("title"), text[match.start() : end]))
    return steps


def _task_files_on_disk() -> list[tuple[TaskKind, Path]]:
    """Every non-README markdown file in any pre- or post-upgrade-tasks/ directory."""
    found: list[tuple[TaskKind, Path]] = []
    for kind in TaskKind:
        for tasks_dir in _UPGRADES.rglob(kind.value):
            if _TEMPLATE_DIRNAME in tasks_dir.relative_to(_UPGRADES).parts:
                continue
            found.extend(
                (kind, path)
                for path in tasks_dir.glob("*.md")
                if path.is_file() and path.name != "README.md"
            )
    return sorted(found, key=lambda item: (item[0].value, str(item[1])))


@pytest.mark.parametrize("skill", _SKILL_COPIES, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_skill_has_a_mandatory_numbered_step_that_lists_the_tasks(skill: Path) -> None:
    steps = [step for step in _numbered_steps(skill.read_text()) if _COMMAND in step[2]]
    assert len(steps) == 1, (
        f"{skill.relative_to(_REPO_ROOT)} must run `{_COMMAND}` in exactly one numbered step; "
        f"found {len(steps)}"
    )
    _number, title, body = steps[0]
    assert "post-upgrade task" in title.lower(), f"the step's own title must name it: {title!r}"
    assert _MANDATORY_RE.search(body), "the step must say it is mandatory"


def test_skill_copies_are_identical() -> None:
    source, deployed = (path.read_text() for path in _SKILL_COPIES)
    assert source == deployed, "the dogfood skill copy has drifted from its source"


def test_llm_update_runs_it_in_a_mandatory_post_update_section() -> None:
    text = _LLM_UPDATE.read_text()
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    owning = [section for section in sections if _COMMAND in section]
    assert any(
        section.startswith("Post-Update:") and _MANDATORY_RE.search(section.splitlines()[0])
        for section in owning
    ), "LLM-UPDATE.md must run the command in a '## Post-Update: ... (MANDATORY)' section"


def test_layer1_script_lists_the_tasks_before_the_metadata_block() -> None:
    text = _LAYER1.read_text()
    command_at = text.find(_COMMAND)
    assert command_at != -1, "scripts/upgrade.sh must run check-post-upgrade-tasks"
    assert command_at < text.find(_METADATA_SENTINEL)


def test_there_are_tasks_to_check() -> None:
    assert _task_files_on_disk(), "no post-upgrade task files found -- the scan is broken"


@pytest.mark.parametrize(
    ("kind", "task"),
    _task_files_on_disk(),
    ids=lambda value: str(value.relative_to(_UPGRADES)) if isinstance(value, Path) else "",
)
def test_every_task_is_listed_for_an_upgrade_that_crosses_it(kind: TaskKind, task: Path) -> None:
    staged = task.relative_to(_UPGRADES).parts[0] == UNRELEASED_DIRNAME
    if staged:
        listed = tasks_for_range(
            kind, __version__, __version__, upgrades_dir=_UPGRADES, include_unreleased=True
        )
    else:
        listed = tasks_for_range(
            kind, _EARLIEST, __version__, upgrades_dir=_UPGRADES, include_unreleased=False
        )
    assert task in {entry.path for entry in listed}, (
        f"{task.relative_to(_REPO_ROOT)} is never listed for an upgrade, so none reaches it. "
        f"Name the file NN-slug.md and put it in CLAUDE/UPGRADES/v{{major}}/v{{A}}-to-v{{B}}/"
        f"{kind.value}/ (B no later than the current version) or in "
        f"CLAUDE/UPGRADES/UNRELEASED/{kind.value}/."
    )

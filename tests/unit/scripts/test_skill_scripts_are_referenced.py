"""A skill's bundled script must be referenced by its markdown (Plan 00324).

Claude Code loads a skill's SKILL.md and nothing else: a sibling script never
auto-executes, and no frontmatter key makes it. A skill that keeps its real
procedure in an `invoke.sh` no markdown mentions therefore runs on the
SKILL.md summary alone — silently, because the skill still appears to work.

`configure`, `mode`, `acceptance-test` and `release` each shipped that way,
and two of them (`mode`, `release`) read arguments the caller's typed
arguments never reached.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Both skill trees: the project's own deployed skills, and the ones the
#: daemon bundles for clients.
_SKILL_ROOTS: Final[tuple[Path, ...]] = (
    _REPO_ROOT / ".claude" / "skills",
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills",
)


def _skill_dirs() -> list[Path]:
    return sorted(
        skill
        for root in _SKILL_ROOTS
        if root.is_dir()
        for skill in root.iterdir()
        if skill.is_dir()
    )


def _bundled_scripts(skill: Path) -> list[Path]:
    """Scripts the model is meant to RUN.

    A leading underscore marks a sourced helper (`_locate-cli.sh`,
    `_resolve-venv.sh`): its caller is a sibling script, never the markdown,
    so requiring a mention would demand a reference to something no agent
    should invoke directly.
    """
    scripts = list(skill.glob("*.sh"))
    scripts.extend(skill.glob("scripts/*.sh"))
    return sorted(p for p in scripts if not p.name.startswith("_"))


def _markdown_text(skill: Path) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in sorted(skill.rglob("*.md"))
    )


def test_every_bundled_skill_script_is_referenced_by_its_markdown() -> None:
    unreferenced: list[str] = []
    for skill in _skill_dirs():
        scripts = _bundled_scripts(skill)
        if not scripts:
            continue
        text = _markdown_text(skill)
        unreferenced.extend(
            str(script.relative_to(_REPO_ROOT)) for script in scripts if script.name not in text
        )

    assert not unreferenced, (
        "These skill scripts are never named by their skill's markdown, so "
        f"Claude Code will never run them: {unreferenced}. Claude Code loads "
        "SKILL.md and nothing else — add an explicit 'run this first' command "
        "(passing the caller's arguments through if the script reads any), or "
        "delete the script if its content has moved into the markdown."
    )

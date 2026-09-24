"""Which parts of ``CLAUDE/UPGRADES/`` an upgrade crosses (Plan 00376).

One resolver for every caller that asks "what does a ``from -> to`` upgrade
cross?": the pre-install REQUIRED READING list in
:mod:`claude_code_hooks_daemon.install.upgrade_compatibility`, and the
``check-post-upgrade-tasks`` command behind the upgrade skill's mandatory
post-upgrade-tasks step.

A versioned guide directory is ``v{A}-to-v{B}`` under any ``v{major}/``
directory. It is crossed when ``from < B <= to``, which is the same half-open
range the truth-changes and config-changes loaders use. ``B`` may carry two or
three components (``v3.57-to-v3.58``, ``v3.62.1-to-v3.63.0``); a missing
patch is zero.

``UNRELEASED/`` has no version: it is what the target tree carries beyond its
own release number. It is read exactly when ``include_unreleased`` says so,
and ``None`` asks the install stamp, as the other UNRELEASED-aware loaders do
(Plan 00291 Task 2.3). A release tag's tree has an empty holding area, so the
question only changes the answer for a branch install.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.install.install_stamp import is_branch_install
from claude_code_hooks_daemon.install.version_parse import parse_version_tuple, strip_tag_prefix

UPGRADES_SUBPATH: Final[Path] = Path("CLAUDE") / "UPGRADES"
UNRELEASED_DIRNAME: Final[str] = "UNRELEASED"
POST_UPGRADE_TASKS_DIRNAME: Final[str] = "post-upgrade-tasks"
UNRELEASED_SOURCE: Final[str] = UNRELEASED_DIRNAME

_README: Final[str] = "README.md"
_MARKDOWN_GLOB: Final[str] = "*.md"
_MAJOR_DIR_GLOB: Final[str] = "v*"
_GUIDE_DIR_RE: Final[re.Pattern[str]] = re.compile(
    r"^v(?P<frm>\d+(?:\.\d+){1,2})-to-v(?P<to>\d+(?:\.\d+){1,2})$"
)
_TASK_FILE_RE: Final[re.Pattern[str]] = re.compile(r"^\d{2,3}-.+\.md$")
_HEADER_FIELD_RE: Final[str] = r"^\*\*{name}\*\*:\s*(?P<value>.+?)\s*$"
_BUILD_METADATA_SEPARATOR: Final[str] = "+"
_VERSION_COMPONENTS: Final[int] = 3
_UNKNOWN_FIELD: Final[str] = "unknown"
_FIELD_TYPE: Final[str] = "Type"
_FIELD_SEVERITY: Final[str] = "Severity"


@dataclass(frozen=True)
class PostUpgradeTask:
    """One task file, and the guide directory (or holding area) it came from."""

    path: Path
    source: str
    task_type: str
    severity: str

    def to_dict(self) -> dict[str, str]:
        """Serialise for ``--format json``."""
        return {
            "path": str(self.path),
            "source": self.source,
            "type": self.task_type,
            "severity": self.severity,
        }


def default_upgrades_dir() -> Path:
    """The ``CLAUDE/UPGRADES`` tree of the daemon checkout this module runs from.

    ``install/`` -> ``claude_code_hooks_daemon/`` -> ``src/`` -> checkout root,
    the same resolution the truth-changes and config-changes loaders use.
    """
    return Path(__file__).parent.parent.parent.parent / UPGRADES_SUBPATH


def _release_tuple(version: str) -> tuple[int, ...]:
    """``'v3.64.0+main.abc1234'`` -> ``(3, 64, 0)``.

    Semver build metadata is dropped because a branch install reports its
    version as ``X.Y.Z+<ref>.<sha>`` (the upgrade metadata's ``to_version``),
    and the release part is what orders it. The result is padded to three
    components so ``3.58`` and ``3.58.0`` compare equal.
    """
    release = version.split(_BUILD_METADATA_SEPARATOR, 1)[0]
    parsed = parse_version_tuple(release)
    return parsed + (0,) * (_VERSION_COMPONENTS - len(parsed))


def _checked_range(from_version: str, to_version: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    from_v = _release_tuple(from_version)
    to_v = _release_tuple(to_version)
    if from_v > to_v:
        raise ValueError(f"from_version ({from_version}) must be <= to_version ({to_version})")
    return from_v, to_v


def crossed_guide_dirs(upgrades_dir: Path, from_version: str, to_version: str) -> list[Path]:
    """Every versioned guide directory in ``(from_version, to_version]``, oldest first.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    from_v, to_v = _checked_range(from_version, to_version)
    if not upgrades_dir.is_dir():
        return []
    crossed: list[tuple[tuple[int, ...], Path]] = []
    for major_dir in upgrades_dir.glob(_MAJOR_DIR_GLOB):
        if not major_dir.is_dir():
            continue
        for guide_dir in major_dir.iterdir():
            match = _GUIDE_DIR_RE.match(guide_dir.name)
            if match is None or not guide_dir.is_dir():
                continue
            target_v = _release_tuple(match.group("to"))
            if from_v < target_v <= to_v:
                crossed.append((target_v, guide_dir))
    crossed.sort(key=lambda item: (item[0], item[1].name))
    return [guide_dir for _, guide_dir in crossed]


def guide_document(guide_dir: Path) -> Path | None:
    """The guide's own document: ``{name}.md``, else ``README.md``, else None.

    A directory holding only ``post-upgrade-tasks/`` or ``release-notes/`` has
    no guide document; its tasks reach the reader through
    :func:`post_upgrade_tasks` instead.
    """
    for candidate in (guide_dir / f"{guide_dir.name}.md", guide_dir / _README):
        if candidate.is_file():
            return candidate
    return None


def unreleased_staged_documents(upgrades_dir: Path) -> list[Path]:
    """Every markdown document staged in ``UNRELEASED/`` apart from scaffolding.

    The holding area is the unreleased half of the next guide: the release
    moves exactly these files into the versioned guide directory. Every
    ``README.md`` is scaffolding (a convention or schema), never content.
    """
    staged_dir = upgrades_dir / UNRELEASED_DIRNAME
    if not staged_dir.is_dir():
        return []
    return sorted(
        (
            path
            for path in staged_dir.rglob(_MARKDOWN_GLOB)
            if path.is_file() and path.name != _README
        ),
        key=lambda path: path.relative_to(staged_dir).as_posix(),
    )


def _header_field(text: str, name: str) -> str:
    match = re.search(_HEADER_FIELD_RE.format(name=name), text, re.MULTILINE)
    return match.group("value") if match else _UNKNOWN_FIELD


def _tasks_in(tasks_dir: Path, source: str) -> list[PostUpgradeTask]:
    if not tasks_dir.is_dir():
        return []
    tasks: list[PostUpgradeTask] = []
    for path in sorted(tasks_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file() or not _TASK_FILE_RE.match(path.name):
            continue
        text = path.read_text(encoding="utf-8")
        tasks.append(
            PostUpgradeTask(
                path=path,
                source=source,
                task_type=_header_field(text, _FIELD_TYPE),
                severity=_header_field(text, _FIELD_SEVERITY),
            )
        )
    return tasks


def post_upgrade_tasks(
    from_version: str,
    to_version: str,
    upgrades_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[PostUpgradeTask]:
    """The post-upgrade tasks of every guide the upgrade crossed, in order.

    Versioned tasks come oldest guide first, then the holding area's when it
    is included. Staged tasks are included whenever ``include_unreleased`` is
    true, even for ``from == to``: a branch install normally reports the same
    release number on both sides.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    base = upgrades_dir if upgrades_dir is not None else default_upgrades_dir()
    tasks: list[PostUpgradeTask] = []
    for guide_dir in crossed_guide_dirs(base, from_version, to_version):
        tasks.extend(_tasks_in(guide_dir / POST_UPGRADE_TASKS_DIRNAME, guide_dir.name))
    if include_unreleased is None:
        include_unreleased = is_branch_install()
    if include_unreleased:
        tasks.extend(
            _tasks_in(base / UNRELEASED_DIRNAME / POST_UPGRADE_TASKS_DIRNAME, UNRELEASED_SOURCE)
        )
    return tasks


def format_post_upgrade_tasks(
    tasks: list[PostUpgradeTask], from_version: str, to_version: str
) -> str:
    """The text form: every task path with its severity, and what to do with it."""
    frm, to = strip_tag_prefix(from_version), strip_tag_prefix(to_version)
    lines = [f"Post-upgrade tasks: v{frm} -> v{to}", ""]
    if not tasks:
        lines.append("No post-upgrade tasks for this version range.")
        return "\n".join(lines)
    lines.append(f"{len(tasks)} task(s) to read and carry out, in this order:")
    for task in tasks:
        lines.append(f"  - [{task.severity}, {task.task_type}] {task.path}")
    lines.extend(
        [
            "",
            "For EACH task: read its header block, skip it only if 'Applies to' does",
            "not cover this project, otherwise follow 'How to detect if this applies",
            "to you', 'How to handle' and 'How to confirm'. Adapt sample commands to",
            "the project; never run them blind. Never edit anything under",
            ".claude/hooks-daemon/. Report the outcome of every task, grouped by",
            "severity (critical first).",
        ]
    )
    return "\n".join(lines)


def run_check_post_upgrade_tasks(
    from_version: str,
    to_version: str,
    upgrades_dir: Path | None = None,
    include_unreleased: bool | None = None,
    output_format: str = "text",
) -> dict[str, Any]:
    """Resolve the tasks for ``check-post-upgrade-tasks``.

    Returns:
        ``from_version``, ``to_version``, ``has_tasks`` and ``tasks`` (dicts),
        plus ``text`` when ``output_format`` is ``'text'``.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    tasks = post_upgrade_tasks(
        from_version,
        to_version,
        upgrades_dir=upgrades_dir,
        include_unreleased=include_unreleased,
    )
    result: dict[str, Any] = {
        "from_version": from_version,
        "to_version": to_version,
        "has_tasks": bool(tasks),
        "tasks": [task.to_dict() for task in tasks],
    }
    if output_format == "text":
        result["text"] = format_post_upgrade_tasks(tasks, from_version, to_version)
    return result

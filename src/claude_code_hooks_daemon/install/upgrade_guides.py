"""Which parts of ``CLAUDE/UPGRADES/`` an upgrade crosses (Plan 00376).

One resolver for every caller that asks "what does a ``from -> to`` upgrade
cross?": the upgrade gate's REQUIRED READING list, the compatibility checker,
and the pre- and post-upgrade task loaders in
:mod:`claude_code_hooks_daemon.install.upgrade_tasks`.

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

Standard library only: the upgrade gate loads this file before the target's
venv exists (see ``upgrade_gate_standalone.py``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.install.install_stamp import is_branch_install
from claude_code_hooks_daemon.install.version_parse import parse_version_tuple
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

UPGRADES_SUBPATH: Final[Path] = Path("CLAUDE") / "UPGRADES"
UNRELEASED_DIRNAME: Final[str] = "UNRELEASED"
UNRELEASED_SOURCE: Final[str] = UNRELEASED_DIRNAME

_README: Final[str] = "README.md"
_MARKDOWN_GLOB: Final[str] = "*.md"
_MAJOR_DIR_GLOB: Final[str] = "v*"
_GUIDE_DIR_RE: Final[re.Pattern[str]] = re.compile(
    r"^v(?P<frm>\d+(?:\.\d+){1,2})-to-v(?P<to>\d+(?:\.\d+){1,2})$"
)
_BUILD_METADATA_SEPARATOR: Final[str] = "+"
_VERSION_COMPONENTS: Final[int] = 3


def default_upgrades_dir() -> Path:
    """The ``CLAUDE/UPGRADES`` tree of the daemon checkout this module runs from.

    ``install/`` -> ``claude_code_hooks_daemon/`` -> ``src/`` -> checkout root,
    the same resolution the truth-changes and config-changes loaders use.
    """
    return Path(__file__).parent.parent.parent.parent / UPGRADES_SUBPATH


def release_tuple(version: str) -> tuple[int, ...]:
    """``'v3.64.0+main.abc1234'`` -> ``(3, 64, 0)``.

    Semver build metadata is dropped because a branch install reports its
    version as ``X.Y.Z+<ref>.<sha>`` (the upgrade metadata's ``to_version``),
    and the release part is what orders it. The result is padded to three
    components so ``3.58`` and ``3.58.0`` compare equal.
    """
    release = version.split(_BUILD_METADATA_SEPARATOR, 1)[0]
    parsed = parse_version_tuple(release)
    return parsed + (0,) * (_VERSION_COMPONENTS - len(parsed))


def checked_range(from_version: str, to_version: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Both ends as release tuples, refusing a backwards range.

    Raises:
        ValueError: on an unparseable version or ``from > to``.
    """
    from_v = release_tuple(from_version)
    to_v = release_tuple(to_version)
    if from_v > to_v:
        raise ValueError(f"from_version ({from_version}) must be <= to_version ({to_version})")
    return from_v, to_v


def crossed_guide_dirs(upgrades_dir: Path, from_version: str, to_version: str) -> list[Path]:
    """Every versioned guide directory in ``(from_version, to_version]``, oldest first.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    from_v, to_v = checked_range(from_version, to_version)
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
            target_v = release_tuple(match.group("to"))
            if from_v < target_v <= to_v:
                crossed.append((target_v, guide_dir))
    crossed.sort(key=lambda item: (item[0], item[1].name))
    return [guide_dir for _, guide_dir in crossed]


def guide_document(guide_dir: Path) -> Path | None:
    """The guide's own document: ``{name}.md``, else ``README.md``, else None.

    A directory holding only task or release-notes directories has no guide
    document; its tasks reach the reader through the task loaders instead.
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
        key=lambda path: path_relative_to(path, staged_dir).as_posix(),
    )


def resolve_include_unreleased(include_unreleased: bool | None) -> bool:
    """``None`` asks the running install's stamp (Plan 00291 Task 2.3)."""
    return is_branch_install() if include_unreleased is None else include_unreleased


def guide_documents(
    upgrades_dir: Path,
    from_version: str,
    to_version: str,
    include_unreleased: bool | None = None,
) -> list[Path]:
    """The reading list: every crossed guide's document, then the staged ones.

    Raises:
        ValueError: on an unparseable version or a backwards range.
    """
    documents = [
        document
        for guide_dir in crossed_guide_dirs(upgrades_dir, from_version, to_version)
        if (document := guide_document(guide_dir)) is not None
    ]
    if resolve_include_unreleased(include_unreleased):
        documents.extend(unreleased_staged_documents(upgrades_dir))
    return documents

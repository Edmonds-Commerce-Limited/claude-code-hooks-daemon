"""Release-notes loading and formatting (Plan 00141).

Reads the daemon's per-version release notes from the ``RELEASES/`` directory
and presents them by exact version, version range, latest, or as a list. The
``RELEASES/vX.Y.Z.md`` files ship with every install (the daemon is delivered
as a git checkout, not a wheel), so this is offline-first — no bundling and no
network access. The range loader mirrors the proven ``truth_changes`` /
``config_migrations`` pattern, including its ``(from, to]`` semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RELEASES_SUBPATH = Path("RELEASES")
_FILE_PREFIX = "v"
_FILE_SUFFIX = ".md"
_VERSION_SEPARATOR = "."
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

_FORMAT_MARKDOWN = "markdown"
_FORMAT_JSON = "json"

_MODE_VERSION = "version"
_MODE_CURRENT = "current"
_MODE_RANGE = "range"
_MODE_LATEST = "latest"
_MODE_LIST = "list"

_SEPARATOR = "\n\n" + ("-" * 70) + "\n\n"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReleaseNote:
    """A single version's release notes.

    Attributes:
        version: Version string, e.g. '3.27.0'.
        content: Full markdown body of the ``RELEASES/vX.Y.Z.md`` file.
        path: Absolute path to the source file.
    """

    version: str
    content: str
    path: str


# ---------------------------------------------------------------------------
# Version utilities + path resolution
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string like '3.27.0' into a sortable tuple."""
    try:
        return tuple(int(x) for x in version.split(_VERSION_SEPARATOR))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid version string: {version!r}") from exc


def _default_releases_dir() -> Path:
    """Return the default ``RELEASES/`` directory under the project root.

    Resolves relative to this module file: install/ -> claude_code_hooks_daemon/
    -> src/ -> project_root, then RELEASES/. Works in both self-install and
    normal installations (same convention as truth_changes/config_migrations).
    """
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / _RELEASES_SUBPATH


def _resolve_dir(releases_dir: Path | None) -> Path:
    """Return the override directory if given, else the default."""
    return releases_dir if releases_dir is not None else _default_releases_dir()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def list_known_release_versions(releases_dir: Path | None = None) -> list[str]:
    """Return sorted versions that have a ``RELEASES/vX.Y.Z.md`` file."""
    base_dir = _resolve_dir(releases_dir)
    if not base_dir.exists():
        return []

    versions: list[str] = []
    for md_file in base_dir.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}"):
        version_str = md_file.stem[len(_FILE_PREFIX) :]
        if not _VERSION_PATTERN.match(version_str):
            continue
        versions.append(version_str)

    versions.sort(key=_parse_version)
    return versions


def load_release_note(version: str, releases_dir: Path | None = None) -> ReleaseNote | None:
    """Load the release note for an exact version, or None if absent."""
    base_dir = _resolve_dir(releases_dir)
    note_path = base_dir / f"{_FILE_PREFIX}{version}{_FILE_SUFFIX}"
    if not note_path.is_file():
        return None
    return ReleaseNote(
        version=version,
        content=note_path.read_text(),
        path=str(note_path),
    )


def load_release_notes_between(
    from_version: str,
    to_version: str,
    releases_dir: Path | None = None,
) -> list[ReleaseNote]:
    """Load all release notes in the range (from_version, to_version].

    from_version is excluded, to_version is included — matching the upgrade
    semantics (you already had from_version; you are adopting up to and
    including to_version).

    Args:
        from_version: Version upgrading from (excluded).
        to_version: Version upgrading to (included).
        releases_dir: Override the RELEASES directory (for testing).

    Returns:
        Notes sorted by version, oldest first.

    Raises:
        ValueError: If from_version > to_version, or a version is unparseable.
    """
    from_v = _parse_version(from_version)
    to_v = _parse_version(to_version)

    if from_v > to_v:
        raise ValueError(f"from_version ({from_version}) must be <= to_version ({to_version})")

    if from_v == to_v:
        return []

    notes: list[ReleaseNote] = []
    for version in list_known_release_versions(releases_dir=releases_dir):
        v = _parse_version(version)
        if from_v < v <= to_v:
            note = load_release_note(version, releases_dir=releases_dir)
            if note is not None:
                notes.append(note)
    return notes


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_list(versions: list[str]) -> str:
    """Format the available-versions list for terminal display."""
    if not versions:
        return "No release notes found."
    lines = [f"Available release notes ({len(versions)} versions):", ""]
    lines.extend(f"  v{v}" for v in versions)
    return "\n".join(lines)


def _format_notes(notes: list[ReleaseNote]) -> str:
    """Concatenate one or more notes for terminal display."""
    return _SEPARATOR.join(note.content.rstrip() for note in notes)


def _note_dict(note: ReleaseNote) -> dict[str, str]:
    return {"version": note.version, "content": note.content, "path": note.path}


# ---------------------------------------------------------------------------
# Run-function (CLI entrypoint)
# ---------------------------------------------------------------------------


def run_release_notes(
    *,
    version: str | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    list_versions: bool = False,
    latest: bool = False,
    current_version: str | None = None,
    output_format: str = _FORMAT_MARKDOWN,
    releases_dir: Path | None = None,
) -> dict[str, Any]:
    """Resolve and format release notes for one of several selection modes.

    Selection precedence: list -> range (from/to) -> latest -> explicit
    version -> installed current_version.

    Args:
        version: Explicit version to show.
        from_version: Range start (excluded). Requires to_version.
        to_version: Range end (included). Requires from_version.
        list_versions: List available versions instead of showing notes.
        latest: Show the newest available version's notes.
        current_version: Fallback target when nothing else is selected
            (typically the installed daemon ``__version__``).
        output_format: 'markdown' (adds a 'text' key to render) or 'json'.
        releases_dir: Override the RELEASES directory (for testing).

    Returns:
        JSON-serialisable dict. Always has: mode, found, versions, notes. In
        markdown format it also has a 'text' key with the rendered output.

    Raises:
        ValueError: If a range is given with only one bound, or from > to,
            or a version string is unparseable.
    """
    mode, versions, notes = _select(
        version=version,
        from_version=from_version,
        to_version=to_version,
        list_versions=list_versions,
        latest=latest,
        current_version=current_version,
        releases_dir=releases_dir,
    )

    found = bool(versions) if mode == _MODE_LIST else bool(notes)

    result: dict[str, Any] = {
        "mode": mode,
        "found": found,
        "versions": versions,
        "notes": [_note_dict(n) for n in notes],
    }

    if output_format != _FORMAT_JSON:
        result["text"] = _render_text(mode, versions, notes, version, current_version)

    return result


def _select(
    *,
    version: str | None,
    from_version: str | None,
    to_version: str | None,
    list_versions: bool,
    latest: bool,
    current_version: str | None,
    releases_dir: Path | None,
) -> tuple[str, list[str], list[ReleaseNote]]:
    """Resolve the selection mode into (mode, versions, notes)."""
    if list_versions:
        return _MODE_LIST, list_known_release_versions(releases_dir=releases_dir), []

    if from_version is not None or to_version is not None:
        if from_version is None or to_version is None:
            raise ValueError("both --from and --to are required for a range")
        notes = load_release_notes_between(from_version, to_version, releases_dir=releases_dir)
        return _MODE_RANGE, [n.version for n in notes], notes

    if latest:
        known = list_known_release_versions(releases_dir=releases_dir)
        if not known:
            return _MODE_LATEST, [], []
        note = load_release_note(known[-1], releases_dir=releases_dir)
        return _MODE_LATEST, [known[-1]], [note] if note else []

    target = version if version is not None else current_version
    mode = _MODE_VERSION if version is not None else _MODE_CURRENT
    if target is None:
        return mode, [], []
    note = load_release_note(target, releases_dir=releases_dir)
    return mode, [target] if note else [], [note] if note else []


def _render_text(
    mode: str,
    versions: list[str],
    notes: list[ReleaseNote],
    version: str | None,
    current_version: str | None,
) -> str:
    """Render the human-facing text body for a resolved selection."""
    if mode == _MODE_LIST:
        return _format_list(versions)
    if notes:
        return _format_notes(notes)
    # Not found — give an actionable message for the selection mode.
    if mode == _MODE_RANGE:
        return "No release notes found in the requested range."
    if mode == _MODE_LATEST:
        return "No release notes found."
    target = version or current_version
    if target is None:
        return "No version specified and no installed version detected. Use --list."
    return f"No release notes found for v{target}. Use --list to see available versions."

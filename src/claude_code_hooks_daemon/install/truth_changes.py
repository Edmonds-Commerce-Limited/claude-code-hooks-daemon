"""Truth-changes manifest loading and reconciliation guidance (Plan 00118).

A *truth-change* records a statement that **was true** about how to work in a
project but became false in a release — replaced by a **new truth**, or retired
entirely. At upgrade time the project LLM is handed the truth-changes for the
version range it crossed and instructed to scan the project's own docs for each
``was`` statement and update it to ``now`` (or remove all reference when ``now``
is empty).

Manifest files live at:
  {project_root}/CLAUDE/UPGRADES/truth-changes/v{X.Y.Z}.yaml

The schema (``was`` / ``now``, plus an optional ``id`` naming the truth) and the
consumption flow are documented in ``CLAUDE/UPGRADES/truth-changes/README.md``.
This module mirrors the proven ``config_migrations`` range-loader pattern, minus
the user-config comparison — truth-changes are guidance, not compared against
anything.

A truth revised in several releases is surfaced ONCE, as its highest-version
entry: entries sharing an ``id`` across manifests form a supersession chain and
only the last link is emitted, with a "revised in" trail naming the releases it
replaces. Un-keyed entries are never collapsed. An agent handed every link of
the chain would assert a claim into the project's docs and then contradict it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.install.install_stamp import is_branch_install
from claude_code_hooks_daemon.install.version_parse import parse_version_tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRUTH_CHANGES_SUBPATH = Path("CLAUDE") / "UPGRADES" / "truth-changes"
_UNRELEASED_DIRNAME = "UNRELEASED"
_MANIFEST_PREFIX = "v"
_MANIFEST_SUFFIX = ".yaml"
_VERSION_SEPARATOR = "."
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

_FIELD_VERSION = "version"
_FIELD_TRUTH_CHANGES = "truth_changes"
_FIELD_WAS = "was"
_FIELD_NOW = "now"
_FIELD_ID = "id"

_FORMAT_TEXT = "text"

_LABEL_NO_CHANGES = "✅ No truth-changes in this range"
_LABEL_HEADER = "Truth-Changes to reconcile"
_LABEL_REVISED_IN = "revised in"
_REMOVAL_INSTRUCTION = "remove all reference to it (no replacement)"
_TRAIL_INSTRUCTION = (
    "An entry marked '{label}' is the CURRENT form of a truth that also changed in "
    "the releases it lists; those earlier forms are deliberately not shown. Reconcile "
    "any earlier form of that statement in the docs to the same NOW."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TruthChange:
    """A single statement that changed truth in a release.

    Attributes:
        was: Natural-language statement that used to be true. Matched
            semantically against the project's own docs by the LLM.
        now: The replacement truth, or None to mean "remove all reference;
            there is no replacement".
        id: Optional stable slug naming the TRUTH (not the release). Entries
            sharing an id across manifests are one truth revised repeatedly;
            only the highest-version link is surfaced. None means "stands
            alone; never collapsed".
    """

    was: str
    now: str | None
    id: str | None = None

    @property
    def is_removal(self) -> bool:
        """Return True when this entry retires a truth with no replacement."""
        # now is str | None; an empty/whitespace-only string also means removal.
        return self.now is None or not self.now.strip()


@dataclass
class TruthChangeManifest:
    """All truth-changes for a single daemon version.

    Attributes:
        version: Version string where these truths changed, e.g. '3.16.0'.
        changes: The list of was/now entries for this version.
    """

    version: str
    changes: list[TruthChange]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TruthChangeManifest:
        """Parse a manifest from a YAML-loaded dictionary.

        Args:
            data: Dictionary loaded from a truth-changes YAML file.

        Returns:
            Parsed TruthChangeManifest.

        Raises:
            KeyError: If a required field (version, or an entry's was) is missing.
            ValueError: If an entry's id is blank, or two entries in this one
                manifest share an id — one release cannot revise a truth twice.
        """
        version = str(data[_FIELD_VERSION])
        entries = data.get(_FIELD_TRUTH_CHANGES) or []
        changes: list[TruthChange] = []
        seen_ids: set[str] = set()
        for entry in entries:
            change_id = _parse_entry_id(entry.get(_FIELD_ID), version)
            if change_id is not None:
                if change_id in seen_ids:
                    raise ValueError(
                        f"truth-changes v{version}: id {change_id!r} appears twice in one "
                        "manifest; a release revises a truth at most once"
                    )
                seen_ids.add(change_id)
            changes.append(
                TruthChange(was=entry[_FIELD_WAS], now=entry.get(_FIELD_NOW), id=change_id)
            )
        return cls(version=version, changes=changes)


def _parse_entry_id(raw: Any, version: str) -> str | None:
    """Return the entry's id slug, or None when the entry carries no id.

    Raises:
        ValueError: If the id is present but blank — an un-keyed entry must be
            written as an absent key, never as an empty one, so that "stands
            alone" is always a deliberate choice visible in the manifest.
    """
    if raw is None:
        return None
    slug = str(raw).strip()
    if not slug:
        raise ValueError(f"truth-changes v{version}: an entry's id is blank; omit the key instead")
    return slug


@dataclass
class SurfacedTruthChange:
    """One entry of the collapsed report: the current link of a truth's chain.

    Attributes:
        version: The manifest version the surfaced entry came from.
        change: The entry itself (highest-version link for a keyed truth).
        superseded_versions: Earlier manifest versions, oldest first, whose
            entry for the same id this one replaces. Empty for an un-keyed
            entry or a keyed entry that changed only once in the range.
    """

    version: str
    change: TruthChange
    superseded_versions: list[str]


# ---------------------------------------------------------------------------
# Version utilities + path resolution
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse '3.16.0' or 'v3.16.0' into a sortable tuple (shared parser)."""
    return parse_version_tuple(version)


def _default_truth_changes_dir() -> Path:
    """Return the default truth-changes directory under the project root.

    Resolves relative to this module file: 3 levels up = src/, 4 = project root,
    then CLAUDE/UPGRADES/truth-changes/. Works in both self-install and normal
    installations (same convention as config_migrations).
    """
    # install/ -> claude_code_hooks_daemon/ -> src/ -> project_root
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / _TRUTH_CHANGES_SUBPATH


def _manifest_files(base_dir: Path, include_unreleased: bool | None) -> list[tuple[str, Path]]:
    """Every ``v{X.Y.Z}.yaml`` in the released directory, plus staging when due.

    Plan 00291 Task 2.3: ``include_unreleased`` left as ``None`` means "ask the
    install stamp" -- a branch install is ahead of the last release, so the
    truths it is ahead on are the staged ones under
    ``<base_dir>/../UNRELEASED/<name>``. A release install never sees them.
    """
    if include_unreleased is None:
        include_unreleased = is_branch_install()
    directories = [base_dir]
    if include_unreleased:
        directories.append(base_dir.parent / _UNRELEASED_DIRNAME / base_dir.name)

    found: list[tuple[str, Path]] = []
    for directory in directories:
        if not directory.exists():
            continue
        for yaml_file in directory.glob(f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}"):
            version_str = yaml_file.stem[len(_MANIFEST_PREFIX) :]
            if not _VERSION_PATTERN.match(version_str):
                continue
            found.append((version_str, yaml_file))
    return found


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_truth_changes_between(
    from_version: str,
    to_version: str,
    truth_changes_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[TruthChangeManifest]:
    """Load all truth-changes manifests in the range (from_version, to_version].

    from_version is excluded, to_version is included — matching the upgrade
    semantics (you already had from_version's truth; you are adopting up to and
    including to_version).

    Args:
        from_version: Version being upgraded from (excluded).
        to_version: Version being upgraded to (included).
        truth_changes_dir: Override the manifest directory (for testing).
        include_unreleased: Also read the UNRELEASED staging directory. ``None``
            (the default) includes it exactly when the running install is a
            branch install.

    Returns:
        Manifests sorted by version, oldest first.

    Raises:
        ValueError: If from_version > to_version, or a version is unparseable.
    """
    from_v = _parse_version(from_version)
    to_v = _parse_version(to_version)

    if from_v > to_v:
        raise ValueError(f"from_version ({from_version}) must be <= to_version ({to_version})")

    if from_v == to_v:
        return []

    base_dir = truth_changes_dir if truth_changes_dir is not None else _default_truth_changes_dir()

    manifests: list[TruthChangeManifest] = []
    for version_str, yaml_file in _manifest_files(base_dir, include_unreleased):
        v = _parse_version(version_str)
        if from_v < v <= to_v:
            with yaml_file.open() as f:
                data: dict[str, Any] = yaml.safe_load(f)
            manifests.append(TruthChangeManifest.from_dict(data))

    manifests.sort(key=lambda m: _parse_version(m.version))
    return manifests


def list_known_truth_change_versions(
    truth_changes_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[str]:
    """Return sorted versions that have a truth-changes manifest file.

    ``include_unreleased`` follows :func:`load_truth_changes_between`.
    """
    base_dir = truth_changes_dir if truth_changes_dir is not None else _default_truth_changes_dir()

    versions = [version for version, _ in _manifest_files(base_dir, include_unreleased)]
    versions.sort(key=_parse_version)
    return versions


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_truth_changes_for_llm(
    manifests: list[TruthChangeManifest],
    from_version: str,
    to_version: str,
) -> str:
    """Format truth-changes as reconciliation instructions for an LLM.

    Args:
        manifests: Manifests for the range (as returned by load_truth_changes_between).
        from_version: Range start (for the header).
        to_version: Range end (for the header).

    Returns:
        Multi-line string instructing the LLM to reconcile project docs.
    """
    lines: list[str] = [f"{_LABEL_HEADER}: v{from_version} → v{to_version}", ""]

    surfaced = collapse_superseded(manifests)
    if not surfaced:
        lines.append(_LABEL_NO_CHANGES)
        lines.append("")
        lines.append("No project-doc reconciliation is needed for this version range.")
        return "\n".join(lines)

    lines.append(
        "For each entry below, scan the PROJECT'S OWN docs (CLAUDE/, docs/, README*, "
        "AGENTS* — never .claude/hooks-daemon/ internals) for the 'was' statement and "
        "reconcile it. Minimal edits."
    )
    if any(item.superseded_versions for item in surfaced):
        lines.append(_TRAIL_INSTRUCTION.format(label=_LABEL_REVISED_IN))
    lines.append("")

    for item in surfaced:
        lines.append(f"• {_format_origin(item)} WAS: {item.change.was.strip()}")
        if item.change.is_removal:
            lines.append(f"  NOW: {_REMOVAL_INSTRUCTION}")
        else:
            now_text = (item.change.now or "").strip()
            lines.append(f"  NOW: {now_text}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _format_origin(item: SurfacedTruthChange) -> str:
    """Render the bracketed origin of a surfaced entry: version, trail, and id."""
    origin = f"v{item.version}"
    if item.superseded_versions:
        trail = ", ".join(f"v{v}" for v in item.superseded_versions)
        origin = f"{origin}, {_LABEL_REVISED_IN} {trail}"
    origin = f"({origin})"
    if item.change.id is not None:
        origin = f"{origin} [{item.change.id}]"
    return origin


def collapse_superseded(manifests: list[TruthChangeManifest]) -> list[SurfacedTruthChange]:
    """Collapse each keyed truth to its highest-version entry, keeping version order.

    Manifests are walked oldest first (the order ``load_truth_changes_between``
    returns). A later entry with the same id displaces the earlier one and
    inherits its trail, so the surfaced entry sits at the position of the
    release that last revised it. Un-keyed entries pass through untouched.

    Args:
        manifests: Manifests for the range, sorted oldest first.

    Returns:
        One entry per un-keyed change plus one per distinct id.
    """
    ordered = sorted(manifests, key=lambda m: _parse_version(m.version))
    surfaced: list[SurfacedTruthChange] = []
    position_by_id: dict[str, int] = {}
    for manifest in ordered:
        for change in manifest.changes:
            trail: list[str] = []
            if change.id is not None and change.id in position_by_id:
                removed_at = position_by_id.pop(change.id)
                earlier = surfaced.pop(removed_at)
                trail = [*earlier.superseded_versions, earlier.version]
                for key, idx in position_by_id.items():
                    if idx > removed_at:
                        position_by_id[key] = idx - 1
            surfaced.append(
                SurfacedTruthChange(
                    version=manifest.version, change=change, superseded_versions=trail
                )
            )
            if change.id is not None:
                position_by_id[change.id] = len(surfaced) - 1
    return surfaced


# ---------------------------------------------------------------------------
# Run-function (CLI entrypoint)
# ---------------------------------------------------------------------------


def run_check_truth_changes(
    from_version: str,
    to_version: str,
    output_format: str = _FORMAT_TEXT,
    truth_changes_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> dict[str, Any]:
    """Load and format truth-changes for a version range.

    Args:
        from_version: Version being upgraded from (excluded from range).
        to_version: Version being upgraded to (included in range).
        output_format: 'text' for LLM-readable instructions, 'json' for machine.
        truth_changes_dir: Override the manifest directory (for testing).
        include_unreleased: Passed through to :func:`load_truth_changes_between`.

    Returns:
        JSON-serialisable dict. Keys: from_version, to_version, has_changes,
        changes (list of {version, was, now, is_removal, id,
        superseded_versions} — superseded links of a keyed truth are collapsed
        here too, so both formats surface the same set), and (text format) text.

    Raises:
        ValueError: If from_version > to_version.
    """
    manifests = load_truth_changes_between(
        from_version,
        to_version,
        truth_changes_dir=truth_changes_dir,
        include_unreleased=include_unreleased,
    )

    changes: list[dict[str, Any]] = [
        {
            "version": item.version,
            "was": item.change.was,
            "now": item.change.now,
            "is_removal": item.change.is_removal,
            "id": item.change.id,
            "superseded_versions": item.superseded_versions,
        }
        for item in collapse_superseded(manifests)
    ]

    result: dict[str, Any] = {
        "from_version": from_version,
        "to_version": to_version,
        "has_changes": bool(changes),
        "changes": changes,
    }

    if output_format == _FORMAT_TEXT:
        result["text"] = format_truth_changes_for_llm(manifests, from_version, to_version)

    return result

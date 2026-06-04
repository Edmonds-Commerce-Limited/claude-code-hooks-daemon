"""Truth-changes manifest loading and reconciliation guidance (Plan 00118).

A *truth-change* records a statement that **was true** about how to work in a
project but became false in a release — replaced by a **new truth**, or retired
entirely. At upgrade time the project LLM is handed the truth-changes for the
version range it crossed and instructed to scan the project's own docs for each
``was`` statement and update it to ``now`` (or remove all reference when ``now``
is empty).

Manifest files live at:
  {project_root}/CLAUDE/UPGRADES/truth-changes/v{X.Y.Z}.yaml

The two-key schema (``was`` / ``now``) and consumption flow are documented in
``CLAUDE/UPGRADES/truth-changes/README.md``. This module mirrors the proven
``config_migrations`` range-loader pattern, minus the user-config comparison —
truth-changes are guidance, not compared against anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRUTH_CHANGES_SUBPATH = Path("CLAUDE") / "UPGRADES" / "truth-changes"
_MANIFEST_PREFIX = "v"
_MANIFEST_SUFFIX = ".yaml"
_VERSION_SEPARATOR = "."
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

_FIELD_VERSION = "version"
_FIELD_TRUTH_CHANGES = "truth_changes"
_FIELD_WAS = "was"
_FIELD_NOW = "now"

_FORMAT_TEXT = "text"

_LABEL_NO_CHANGES = "✅ No truth-changes in this range"
_LABEL_HEADER = "Truth-Changes to reconcile"
_REMOVAL_INSTRUCTION = "remove all reference to it (no replacement)"


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
    """

    was: str
    now: str | None

    @property
    def is_removal(self) -> bool:
        """Return True when this entry retires a truth with no replacement."""
        return self.now is None or (isinstance(self.now, str) and not self.now.strip())


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
        """
        version = data[_FIELD_VERSION]
        entries = data.get(_FIELD_TRUTH_CHANGES) or []
        changes = [
            TruthChange(was=entry[_FIELD_WAS], now=entry.get(_FIELD_NOW))
            for entry in entries
        ]
        return cls(version=str(version), changes=changes)


# ---------------------------------------------------------------------------
# Version utilities + path resolution
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string like '3.16.0' into a sortable tuple."""
    try:
        return tuple(int(x) for x in version.split(_VERSION_SEPARATOR))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid version string: {version!r}") from exc


def _default_truth_changes_dir() -> Path:
    """Return the default truth-changes directory under the project root.

    Resolves relative to this module file: 3 levels up = src/, 4 = project root,
    then CLAUDE/UPGRADES/truth-changes/. Works in both self-install and normal
    installations (same convention as config_migrations).
    """
    # install/ -> claude_code_hooks_daemon/ -> src/ -> project_root
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / _TRUTH_CHANGES_SUBPATH


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_truth_changes_between(
    from_version: str,
    to_version: str,
    truth_changes_dir: Path | None = None,
) -> list[TruthChangeManifest]:
    """Load all truth-changes manifests in the range (from_version, to_version].

    from_version is excluded, to_version is included — matching the upgrade
    semantics (you already had from_version's truth; you are adopting up to and
    including to_version).

    Args:
        from_version: Version being upgraded from (excluded).
        to_version: Version being upgraded to (included).
        truth_changes_dir: Override the manifest directory (for testing).

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
    if not base_dir.exists():
        return []

    manifests: list[TruthChangeManifest] = []
    for yaml_file in base_dir.glob(f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}"):
        version_str = yaml_file.stem[len(_MANIFEST_PREFIX) :]
        if not _VERSION_PATTERN.match(version_str):
            continue
        v = _parse_version(version_str)
        if from_v < v <= to_v:
            with yaml_file.open() as f:
                data: dict[str, Any] = yaml.safe_load(f)
            manifests.append(TruthChangeManifest.from_dict(data))

    manifests.sort(key=lambda m: _parse_version(m.version))
    return manifests


def list_known_truth_change_versions(truth_changes_dir: Path | None = None) -> list[str]:
    """Return sorted versions that have a truth-changes manifest file."""
    base_dir = truth_changes_dir if truth_changes_dir is not None else _default_truth_changes_dir()
    if not base_dir.exists():
        return []

    versions: list[str] = []
    for yaml_file in base_dir.glob(f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}"):
        version_str = yaml_file.stem[len(_MANIFEST_PREFIX) :]
        if not _VERSION_PATTERN.match(version_str):
            continue
        versions.append(version_str)

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

    total = sum(len(m.changes) for m in manifests)
    if total == 0:
        lines.append(_LABEL_NO_CHANGES)
        lines.append("")
        lines.append("No project-doc reconciliation is needed for this version range.")
        return "\n".join(lines)

    lines.append(
        "For each entry below, scan the PROJECT'S OWN docs (CLAUDE/, docs/, README*, "
        "AGENTS* — never .claude/hooks-daemon/ internals) for the 'was' statement and "
        "reconcile it. Minimal edits."
    )
    lines.append("")

    for manifest in manifests:
        for change in manifest.changes:
            lines.append(f"• (v{manifest.version}) WAS: {change.was.strip()}")
            if change.is_removal:
                lines.append(f"  NOW: {_REMOVAL_INSTRUCTION}")
            else:
                now_text = (change.now or "").strip()
                lines.append(f"  NOW: {now_text}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Run-function (CLI entrypoint)
# ---------------------------------------------------------------------------


def run_check_truth_changes(
    from_version: str,
    to_version: str,
    output_format: str = _FORMAT_TEXT,
    truth_changes_dir: Path | None = None,
) -> dict[str, Any]:
    """Load and format truth-changes for a version range.

    Args:
        from_version: Version being upgraded from (excluded from range).
        to_version: Version being upgraded to (included in range).
        output_format: 'text' for LLM-readable instructions, 'json' for machine.
        truth_changes_dir: Override the manifest directory (for testing).

    Returns:
        JSON-serialisable dict. Keys: from_version, to_version, has_changes,
        changes (list of {version, was, now, is_removal}), and (text format) text.

    Raises:
        ValueError: If from_version > to_version.
    """
    manifests = load_truth_changes_between(
        from_version, to_version, truth_changes_dir=truth_changes_dir
    )

    changes: list[dict[str, Any]] = [
        {
            "version": manifest.version,
            "was": change.was,
            "now": change.now,
            "is_removal": change.is_removal,
        }
        for manifest in manifests
        for change in manifest.changes
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

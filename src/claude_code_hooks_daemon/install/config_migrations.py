"""Config migration manifest loading and advisory generation.

Provides a machine-readable manifest system for config changes per version,
plus advisory generation that compares manifests against a user's config to
report what's new or renamed since their previous version.

Manifest files live at:
  {project_root}/CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml

This path is resolved relative to this module file (4 levels up = project root).
Works in both self-install mode (workspace root) and normal installations
(.claude/hooks-daemon/ root).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFESTS_SUBPATH = Path("CLAUDE") / "UPGRADES" / "config-changes"
_MANIFEST_PREFIX = "v"
_MANIFEST_SUFFIX = ".yaml"
_KEY_SEPARATOR = "."
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

_SECTION_HANDLERS = "handlers"
_SECTION_DAEMON = "daemon"

_HANDLER_REFERENCE_DOC = "docs/guides/HANDLER_REFERENCE.md"

_LABEL_ACTION_REQUIRED = "⚠️  Action Required"
_LABEL_RECOMMENDED = "🆕 Recommended — enable these"
_LABEL_NEW_OPTIONS = "💡 New Options Available"
_LABEL_NO_CHANGES = "✅ No Changes Needed"

_VALUE_NOT_SET = "not set"
_BOOL_TRUE = "true"
_BOOL_FALSE = "false"

_FIELD_VERSION = "version"
_FIELD_DATE = "date"
_FIELD_BREAKING = "breaking"
_FIELD_UPGRADE_GUIDE = "upgrade_guide"
_FIELD_CONFIG_CHANGES = "config_changes"
_FIELD_ADDED = "added"
_FIELD_RENAMED = "renamed"
_FIELD_REMOVED = "removed"
_FIELD_CHANGED = "changed"
_FIELD_KEY = "key"
_FIELD_DESCRIPTION = "description"
_FIELD_EXAMPLE_YAML = "example_yaml"
_FIELD_MIGRATION_NOTE = "migration_note"
_FIELD_OLD_KEY = "old_key"
_FIELD_NEW_KEY = "new_key"
_FIELD_RECOMMENDED = "recommended"
_FIELD_DORMANT = "dormant"
_FIELD_RECOMMENDED_VALUE = "recommended_value"


class _Unset:
    """Sentinel type marking an absent value (Plan 00133).

    Distinct from None/False so a manifest's ``recommended_value: false`` or a
    client's ``key: null`` is never confused with "no value provided".
    """

    _instance: "_Unset | None" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "<UNSET>"


# Singleton sentinel for "value not provided" (manifest field absent / key not
# present in user config). See _Unset.
UNSET = _Unset()


# ---------------------------------------------------------------------------
# Dataclasses — Manifest structure
# ---------------------------------------------------------------------------


@dataclass
class ConfigChangeEntry:
    """A single config key that was added, removed, or changed in a version.

    Attributes:
        key: Dotted config path, e.g. 'handlers.post_tool_use.lint_on_edit'
        description: Human-readable description of the change
        example_yaml: Optional YAML snippet showing example usage
        migration_note: Optional note for users migrating from previous version
        recommended: Whether enabling/adopting this is actively recommended
            (promotes it into the "Recommended — enable these" advisory section).
        dormant: Whether the feature is off-by-default and inert until the
            client opts in (used to distinguish a dormant opt-in from a
            default-safe FYI addition).
        recommended_value: The value the client should set this key to. Defaults
            to the UNSET sentinel when not specified. For a ``changed`` entry
            (default flip), the advisory compares the client's current value
            against this and promotes the change when they differ.
    """

    key: str
    description: str
    example_yaml: str | None = None
    migration_note: str | None = None
    recommended: bool = False
    dormant: bool = False
    recommended_value: Any = UNSET


def _change_entry_from_dict(e: dict[str, Any]) -> "ConfigChangeEntry":
    """Build a ConfigChangeEntry from a manifest entry dict (DRY parser).

    ``recommended_value`` defaults to the UNSET sentinel when the field is
    absent, so an explicit ``recommended_value: false`` is preserved.
    """
    return ConfigChangeEntry(
        key=e[_FIELD_KEY],
        description=e.get(_FIELD_DESCRIPTION, ""),
        example_yaml=e.get(_FIELD_EXAMPLE_YAML),
        migration_note=e.get(_FIELD_MIGRATION_NOTE),
        recommended=bool(e.get(_FIELD_RECOMMENDED, False)),
        dormant=bool(e.get(_FIELD_DORMANT, False)),
        recommended_value=e.get(_FIELD_RECOMMENDED_VALUE, UNSET),
    )


@dataclass
class RenamedEntry:
    """A config key that was renamed from one path to another.

    Attributes:
        old_key: Dotted config path before rename
        new_key: Dotted config path after rename
        migration_note: Optional note for users still using the old key
    """

    old_key: str
    new_key: str
    migration_note: str | None = None


@dataclass
class ConfigChanges:
    """All config changes for a single version.

    Attributes:
        added: New config keys introduced in this version
        renamed: Keys renamed from one path to another
        removed: Keys removed (no longer valid)
        changed: Keys with changed semantics or defaults
    """

    added: list[ConfigChangeEntry] = field(default_factory=list)
    renamed: list[RenamedEntry] = field(default_factory=list)
    removed: list[ConfigChangeEntry] = field(default_factory=list)
    changed: list[ConfigChangeEntry] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Return True if any config changes exist in this version."""
        return bool(self.added or self.renamed or self.removed or self.changed)


@dataclass
class ConfigMigrationManifest:
    """Migration manifest for a single daemon version.

    Attributes:
        version: Version string, e.g. '2.12.0'
        date: Release date in ISO format, e.g. '2026-02-12'
        breaking: Whether this version contains breaking changes
        config_changes: Structured list of config changes
        upgrade_guide: Optional path to upgrade guide directory
    """

    version: str
    date: str
    breaking: bool
    config_changes: ConfigChanges
    upgrade_guide: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigMigrationManifest:
        """Parse a manifest from a YAML-loaded dictionary.

        Args:
            data: Dictionary loaded from manifest YAML file

        Returns:
            ConfigMigrationManifest instance

        Raises:
            KeyError: If required fields (version, date) are missing
            ValueError: If field types are invalid
        """
        version = data[_FIELD_VERSION]
        date = data[_FIELD_DATE]
        breaking = bool(data.get(_FIELD_BREAKING, False))
        upgrade_guide: str | None = data.get(_FIELD_UPGRADE_GUIDE)

        changes_data: dict[str, Any] = data.get(_FIELD_CONFIG_CHANGES) or {}

        added = [
            _change_entry_from_dict(e) for e in (changes_data.get(_FIELD_ADDED) or [])
        ]
        renamed = [
            RenamedEntry(
                old_key=e[_FIELD_OLD_KEY],
                new_key=e[_FIELD_NEW_KEY],
                migration_note=e.get(_FIELD_MIGRATION_NOTE),
            )
            for e in (changes_data.get(_FIELD_RENAMED) or [])
        ]
        removed = [
            _change_entry_from_dict(e) for e in (changes_data.get(_FIELD_REMOVED) or [])
        ]
        changed = [
            _change_entry_from_dict(e) for e in (changes_data.get(_FIELD_CHANGED) or [])
        ]

        config_changes = ConfigChanges(
            added=added,
            renamed=renamed,
            removed=removed,
            changed=changed,
        )

        return cls(
            version=version,
            date=date,
            breaking=breaking,
            config_changes=config_changes,
            upgrade_guide=upgrade_guide,
        )


# ---------------------------------------------------------------------------
# Dataclasses — Advisory structure
# ---------------------------------------------------------------------------


@dataclass
class AdvisoryWarning:
    """A warning about a config key that requires user action.

    Typically: user still has an old key that was renamed or removed.

    Attributes:
        key: The problematic config key in user's config
        message: Human-readable description of the issue
        version: Version where this change was introduced
        migration_note: Optional migration guidance
    """

    key: str
    message: str
    version: str
    migration_note: str | None = None


@dataclass
class AdvisorySuggestion:
    """A suggestion about a new config option the user hasn't configured.

    Attributes:
        key: The new config key available since this version
        description: What the option does
        version: Version where this option was introduced
        example_yaml: Optional YAML snippet showing example usage
        recommended: Whether this suggestion is actively recommended (promotes
            it into the "Recommended — enable these" section).
        dormant: Whether the feature is off until the client opts in.
        recommended_value: The value the client should set (UNSET if N/A).
        current_value: The client's current value (UNSET if not set).
        migration_note: Optional migration guidance (e.g. "migrate memory first").
    """

    key: str
    description: str
    version: str
    example_yaml: str | None = None
    recommended: bool = False
    dormant: bool = False
    recommended_value: Any = UNSET
    current_value: Any = UNSET
    migration_note: str | None = None


@dataclass
class MigrationAdvisory:
    """Advisory report comparing manifests against user config.

    Attributes:
        warnings: Breaking/rename issues requiring user action
        suggestions: New options the user might want to configure
        from_version: Version user is upgrading from
        to_version: Version user is upgrading to
    """

    warnings: list[AdvisoryWarning]
    suggestions: list[AdvisorySuggestion]
    from_version: str
    to_version: str


# ---------------------------------------------------------------------------
# Version utilities
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string into a sortable tuple.

    Args:
        version: Version string like '2.10.1'

    Returns:
        Tuple of ints like (2, 10, 1) for numeric comparison

    Raises:
        ValueError: If version string is not parseable
    """
    try:
        return tuple(int(x) for x in version.split(_KEY_SEPARATOR))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid version string: {version!r}") from exc


# ---------------------------------------------------------------------------
# Manifest path resolution
# ---------------------------------------------------------------------------


def _default_manifests_dir() -> Path:
    """Return default path to config-changes manifest directory.

    Resolves relative to this module file: 4 levels up = project root,
    then CLAUDE/UPGRADES/config-changes/.

    Works for both self-install mode and normal installations.
    """
    # install/ → claude_code_hooks_daemon/ → src/ → project_root
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / _MANIFESTS_SUBPATH


# ---------------------------------------------------------------------------
# Public API — Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(
    version: str,
    manifests_dir: Path | None = None,
) -> ConfigMigrationManifest | None:
    """Load a single version manifest from disk.

    Args:
        version: Version string like '2.12.0'
        manifests_dir: Override default manifest directory (for testing)

    Returns:
        Parsed ConfigMigrationManifest, or None if no manifest exists for
        this version
    """
    base_dir = manifests_dir if manifests_dir is not None else _default_manifests_dir()
    manifest_path = base_dir / f"{_MANIFEST_PREFIX}{version}{_MANIFEST_SUFFIX}"

    if not manifest_path.exists():
        return None

    with manifest_path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)

    return ConfigMigrationManifest.from_dict(data)


def load_manifests_between(
    from_version: str,
    to_version: str,
    manifests_dir: Path | None = None,
) -> list[ConfigMigrationManifest]:
    """Load all manifests for versions strictly after from_version up to to_version.

    The range is (from_version, to_version] — from_version is excluded,
    to_version is included.

    Args:
        from_version: Start of range (exclusive) — the version being upgraded from
        to_version: End of range (inclusive) — the version being upgraded to
        manifests_dir: Override default manifest directory (for testing)

    Returns:
        List of manifests sorted by version (oldest first)

    Raises:
        ValueError: If from_version > to_version
    """
    from_v = _parse_version(from_version)
    to_v = _parse_version(to_version)

    if from_v > to_v:
        raise ValueError(f"from_version ({from_version}) must be <= to_version ({to_version})")

    if from_v == to_v:
        return []

    base_dir = manifests_dir if manifests_dir is not None else _default_manifests_dir()

    if not base_dir.exists():
        return []

    manifests: list[ConfigMigrationManifest] = []

    for yaml_file in base_dir.glob(f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}"):
        # Strip 'v' prefix to get version string (glob ensures files start with 'v')
        version_str = yaml_file.stem[len(_MANIFEST_PREFIX) :]

        # Skip files that don't match v{N}.{N}.{N} pattern (e.g. vnot-a-version.yaml)
        if not _VERSION_PATTERN.match(version_str):
            continue

        v = _parse_version(version_str)

        if from_v < v <= to_v:
            with yaml_file.open() as f:
                data: dict[str, Any] = yaml.safe_load(f)
            manifests.append(ConfigMigrationManifest.from_dict(data))

    manifests.sort(key=lambda m: _parse_version(m.version))
    return manifests


# ---------------------------------------------------------------------------
# Public API — Advisory generation
# ---------------------------------------------------------------------------


def _key_present_in_config(key: str, config: dict[str, Any]) -> bool:
    """Check whether a dotted key path exists in the config dict.

    For example, 'handlers.post_tool_use.lint_on_edit' navigates
    config['handlers']['post_tool_use']['lint_on_edit'].

    Args:
        key: Dotted key path like 'handlers.post_tool_use.lint_on_edit'
        config: User config dictionary

    Returns:
        True if the key path resolves to an existing value
    """
    parts = key.split(_KEY_SEPARATOR)
    current: Any = config
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _get_value_at_key(key: str, config: dict[str, Any]) -> Any:
    """Return the value at a dotted key path, or UNSET if absent.

    Distinct from _key_present_in_config because a default-flip advisory must
    compare the client's *value* against a recommended value — and a present
    key holding ``false``/``null`` must be distinguishable from an absent key.
    """
    parts = key.split(_KEY_SEPARATOR)
    current: Any = config
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return UNSET
        current = current[part]
    return current


def generate_migration_advisory(
    from_version: str,
    to_version: str,
    user_config_path: Path,
    manifests_dir: Path | None = None,
) -> MigrationAdvisory:
    """Generate a config migration advisory for the given version range.

    Loads all manifests between from_version and to_version, then compares
    against the user's actual config to:
    - Warn about renamed/removed keys still present in user config
    - Suggest new options not yet configured by the user

    Args:
        from_version: Version user is upgrading from (excluded from range)
        to_version: Version user is upgrading to (included in range)
        user_config_path: Path to user's hooks-daemon.yaml
        manifests_dir: Override default manifest directory (for testing)

    Returns:
        MigrationAdvisory with warnings and suggestions
    """
    with user_config_path.open() as f:
        user_config: dict[str, Any] = yaml.safe_load(f) or {}

    manifests = load_manifests_between(from_version, to_version, manifests_dir=manifests_dir)

    warnings: list[AdvisoryWarning] = []
    suggestions: list[AdvisorySuggestion] = []

    for manifest in manifests:
        # Renamed keys: warn if user still has the old key
        for renamed in manifest.config_changes.renamed:
            if _key_present_in_config(renamed.old_key, user_config):
                warnings.append(
                    AdvisoryWarning(
                        key=renamed.old_key,
                        message=f"Renamed to {renamed.new_key}",
                        version=manifest.version,
                        migration_note=renamed.migration_note,
                    )
                )

        # Added keys: suggest if user doesn't have them yet
        for added in manifest.config_changes.added:
            if not _key_present_in_config(added.key, user_config):
                suggestions.append(
                    AdvisorySuggestion(
                        key=added.key,
                        description=added.description,
                        version=manifest.version,
                        example_yaml=added.example_yaml,
                        recommended=added.recommended,
                        dormant=added.dormant,
                        recommended_value=added.recommended_value,
                        current_value=UNSET,
                        migration_note=added.migration_note,
                    )
                )

        # Changed keys (default flips): promote when the client's current value
        # differs from the recommended value. Covers BOTH a client who never set
        # the key (silently inherits the new default) and one who explicitly
        # holds the old value. Entries without a recommended_value are
        # documentation-only and produce no suggestion.
        for changed in manifest.config_changes.changed:
            if changed.recommended_value is UNSET:
                continue
            current_value = _get_value_at_key(changed.key, user_config)
            if current_value != changed.recommended_value:
                suggestions.append(
                    AdvisorySuggestion(
                        key=changed.key,
                        description=changed.description,
                        version=manifest.version,
                        example_yaml=changed.example_yaml,
                        recommended=changed.recommended,
                        dormant=changed.dormant,
                        recommended_value=changed.recommended_value,
                        current_value=current_value,
                        migration_note=changed.migration_note,
                    )
                )

    return MigrationAdvisory(
        warnings=warnings,
        suggestions=suggestions,
        from_version=from_version,
        to_version=to_version,
    )


# ---------------------------------------------------------------------------
# Public API — Formatting
# ---------------------------------------------------------------------------


def list_known_versions(manifests_dir: Path | None = None) -> list[str]:
    """Return sorted list of versions that have manifest files.

    Args:
        manifests_dir: Override default manifest directory (for testing)

    Returns:
        Sorted list of version strings (oldest first)
    """
    base_dir = manifests_dir if manifests_dir is not None else _default_manifests_dir()

    if not base_dir.exists():
        return []

    versions: list[str] = []
    for yaml_file in base_dir.glob(f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}"):
        # Strip 'v' prefix to get version string (glob ensures files start with 'v')
        version_str = yaml_file.stem[len(_MANIFEST_PREFIX) :]
        # Skip files that don't match v{N}.{N}.{N} pattern (e.g. vnot-a-version.yaml)
        if not _VERSION_PATTERN.match(version_str):
            continue
        versions.append(version_str)

    versions.sort(key=_parse_version)
    return versions


def format_advisory_for_llm(advisory: MigrationAdvisory) -> str:
    """Format a MigrationAdvisory as structured text for LLM consumption.

    Output sections:
    - Header with version range
    - ⚠️  Action Required: renamed/removed keys still in user config
    - 💡 New Options Available: new options not yet configured
    - ✅ No Changes Needed: when no warnings or suggestions

    Args:
        advisory: MigrationAdvisory to format

    Returns:
        Multi-line string suitable for display or LLM context injection
    """
    lines: list[str] = []
    lines.append(f"Config Migration Advisory: v{advisory.from_version} → v{advisory.to_version}")
    lines.append("")

    if not advisory.warnings and not advisory.suggestions:
        lines.append(_LABEL_NO_CHANGES)
        lines.append("")
        lines.append("Your config is up to date for this version range.")
        lines.append("")
        lines.append(f"See {_HANDLER_REFERENCE_DOC} for full option details.")
        return "\n".join(lines)

    if advisory.warnings:
        issue_count = len(advisory.warnings)
        issue_word = "issue" if issue_count == 1 else "issues"
        lines.append(f"{_LABEL_ACTION_REQUIRED} ({issue_count} {issue_word})")
        lines.append("")
        for w in advisory.warnings:
            lines.append("  Your config references a renamed key:")
            lines.append(f"    {w.key} → (since v{w.version})")
            lines.append(f"    {w.message}")
            if w.migration_note:
                lines.append(f"    Update: {w.migration_note}")
        lines.append("")

    recommended = [s for s in advisory.suggestions if s.recommended]
    informational = [s for s in advisory.suggestions if not s.recommended]

    if recommended:
        lines.append(_LABEL_RECOMMENDED)
        lines.append("")
        for s in recommended:
            _append_suggestion_lines(lines, s, show_recommended_value=True)
        lines.append("")

    if informational:
        lines.append(
            f"{_LABEL_NEW_OPTIONS} (since v{advisory.from_version} → v{advisory.to_version})"
        )
        lines.append("")
        for s in informational:
            _append_suggestion_lines(lines, s, show_recommended_value=False)
        lines.append("")

    lines.append(f"See {_HANDLER_REFERENCE_DOC} for full option details.")
    return "\n".join(lines)


def _format_config_value(value: Any) -> str:
    """Render a config value for advisory display (YAML-style booleans)."""
    if value is UNSET:
        return _VALUE_NOT_SET
    if value is True:
        return _BOOL_TRUE
    if value is False:
        return _BOOL_FALSE
    return str(value)


def _append_suggestion_lines(
    lines: list[str],
    suggestion: AdvisorySuggestion,
    *,
    show_recommended_value: bool,
) -> None:
    """Append the formatted lines for a single suggestion to ``lines``."""
    lines.append(f"  v{suggestion.version}: {suggestion.key}")
    lines.append(f"    {suggestion.description}")
    if show_recommended_value and suggestion.recommended_value is not UNSET:
        lines.append(
            f"    Recommended: {suggestion.key.split(_KEY_SEPARATOR)[-1]} = "
            f"{_format_config_value(suggestion.recommended_value)}  "
            f"(your config: {_format_config_value(suggestion.current_value)})"
        )
    if suggestion.migration_note:
        lines.append(f"    Note: {suggestion.migration_note}")
    if suggestion.example_yaml:
        example_line = suggestion.example_yaml.strip().replace("\n", "\n    ")
        lines.append(f"    Example: {example_line}")

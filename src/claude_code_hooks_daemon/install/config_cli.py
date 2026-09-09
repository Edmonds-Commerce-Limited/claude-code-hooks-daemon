"""CLI functions for config diff, merge, and validate operations.

These functions are designed to be called from the daemon CLI (config-diff,
config-merge, config-validate commands) or from bash scripts via Python.

Each function loads YAML files, performs the operation, and returns
a JSON-serializable dictionary for easy consumption by callers.
"""

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.install.config_differ import ConfigDiffer
from claude_code_hooks_daemon.install.config_merger import ConfigMerger
from claude_code_hooks_daemon.install.config_migrations import (
    UNSET,
    format_advisory_for_llm,
    generate_migration_advisory,
)
from claude_code_hooks_daemon.install.config_migrations import (
    list_known_versions as _list_known_versions,
)
from claude_code_hooks_daemon.install.config_validator import ConfigValidator
from claude_code_hooks_daemon.install.handler_key_audit import (
    applied_relocations,
    audit_handler_keys,
    format_findings,
    migrate_relocated_handler_keys,
)
from claude_code_hooks_daemon.install.worktree_seed_report import (
    build_seed_report,
    format_report_for_llm,
    suggested_yaml_block,
)


def _json_safe_value(value: Any) -> Any:
    """Normalise a migration-advisory value for JSON serialization.

    The migrations module uses the ``UNSET`` sentinel to distinguish "no value
    provided" from an explicit ``None``/``False``. JSON has no such sentinel, so
    ``UNSET`` is rendered as ``null`` while every other value (including a real
    ``False`` or ``None``) is passed through unchanged.

    Args:
        value: A possibly-``UNSET`` advisory value.

    Returns:
        ``None`` if the value is ``UNSET``, otherwise the value unchanged.
    """
    return None if value is UNSET else value


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML config file and return as dict.

    Args:
        path: Path to YAML file

    Returns:
        Parsed dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not valid YAML
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML dictionary: {path}")

    return data


def run_config_diff(
    user_config_path: Path,
    default_config_path: Path,
) -> dict[str, Any]:
    """Diff user config against default config and return structured result.

    Args:
        user_config_path: Path to user's current config YAML
        default_config_path: Path to default/example config YAML for current version

    Returns:
        Dictionary with diff results (JSON-serializable)

    Raises:
        FileNotFoundError: If either config file doesn't exist
    """
    user_config = _load_yaml(user_config_path)
    default_config = _load_yaml(default_config_path)

    differ = ConfigDiffer()
    diff = differ.diff(user_config=user_config, default_config=default_config)

    return diff.to_dict()


def run_config_merge(
    user_config_path: Path,
    old_default_config_path: Path,
    new_default_config_path: Path,
) -> dict[str, Any]:
    """Diff user config against old default, then merge onto new default.

    This is the main upgrade operation:
    1. Diff user config vs old default to extract customizations
    2. Apply customizations onto new default config
    3. Return merged config + any conflicts

    Args:
        user_config_path: Path to user's current config YAML
        old_default_config_path: Path to default config from user's current version
        new_default_config_path: Path to default config from new version

    Returns:
        Dictionary with merged config, conflicts, and is_clean flag

    Raises:
        FileNotFoundError: If any config file doesn't exist
    """
    user_config = _load_yaml(user_config_path)
    old_default_config = _load_yaml(old_default_config_path)
    new_default_config = _load_yaml(new_default_config_path)

    # Plan 00362: relocate BEFORE diffing, on both sides. A relocated key the
    # old default also carried would otherwise diff as a priority/enabled
    # change on a handler the new default removed -- a conflict, with the
    # user's `enabled: false` silently replaced by the new default's block.
    # Once the user's entry sits under `pseudo_events`, the differ records it
    # as a custom section and the merger deep-merges it over the new default's
    # nitpick block, so the user's values win and the triggers still arrive.
    user_config, migrations = migrate_relocated_handler_keys(user_config, scaffold=False)
    old_default_config, _ = migrate_relocated_handler_keys(old_default_config, scaffold=False)

    differ = ConfigDiffer()
    diff = differ.diff(user_config=user_config, default_config=old_default_config)

    merger = ConfigMerger()
    result = merger.merge(new_default_config=new_default_config, diff=diff)

    output = result.to_dict()
    output["handler_key_migrations"] = [
        m.to_dict() for m in [*migrations, *result.handler_key_migrations]
    ]
    return output


def run_check_config_migrations(
    from_version: str,
    to_version: str,
    user_config_path: Path,
    output_format: str = "text",
    manifests_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> dict[str, Any]:
    """Generate config migration advisory between two daemon versions.

    Loads all manifests between from_version and to_version, compares against
    the user's config, and returns warnings (renamed/removed keys still in
    config) and suggestions (new options not yet configured).

    Args:
        from_version: Version user is upgrading from (excluded from range)
        to_version: Version user is upgrading to (included in range)
        user_config_path: Path to user's hooks-daemon.yaml
        output_format: 'text' for human-readable, 'json' for machine-readable
        manifests_dir: Override manifest directory (for testing)
        include_unreleased: Also read the UNRELEASED staging manifests; ``None``
            includes them exactly when the running install is a branch install

    Returns:
        Dictionary with advisory results (JSON-serializable).
        Keys: warnings, suggestions, from_version, to_version, has_warnings,
              has_suggestions, text (if format='text')

    Raises:
        FileNotFoundError: If user config file doesn't exist
        ValueError: If from_version > to_version
    """
    if not user_config_path.exists():
        raise FileNotFoundError(f"Config file not found: {user_config_path}")

    advisory = generate_migration_advisory(
        from_version=from_version,
        to_version=to_version,
        user_config_path=user_config_path,
        manifests_dir=manifests_dir,
        include_unreleased=include_unreleased,
    )

    result: dict[str, Any] = {
        "from_version": advisory.from_version,
        "to_version": advisory.to_version,
        "has_warnings": advisory.has_warnings,
        "has_suggestions": bool(advisory.suggestions),
        "stale_handler_keys": [f.to_dict() for f in advisory.stale_handler_keys],
        "warnings": [
            {
                "key": w.key,
                "message": w.message,
                "version": w.version,
                "migration_note": w.migration_note,
            }
            for w in advisory.warnings
        ],
        "suggestions": [
            {
                "key": s.key,
                "description": s.description,
                "version": s.version,
                "example_yaml": s.example_yaml,
                "recommended": s.recommended,
                "dormant": s.dormant,
                "recommended_value": _json_safe_value(s.recommended_value),
                "current_value": _json_safe_value(s.current_value),
                "migration_note": s.migration_note,
            }
            for s in advisory.suggestions
        ],
    }

    if output_format == "text":
        result["text"] = format_advisory_for_llm(advisory)

    return result


def list_known_versions(
    manifests_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[str]:
    """Return sorted list of versions with available manifests.

    Args:
        manifests_dir: Override manifest directory (for testing)
        include_unreleased: Also list the UNRELEASED staging manifests; ``None``
            includes them exactly when the running install is a branch install

    Returns:
        Sorted list of version strings (oldest first)
    """
    return _list_known_versions(manifests_dir=manifests_dir, include_unreleased=include_unreleased)


def run_check_worktree_seed(
    root: Path,
    user_config_path: Path,
    output_format: str = "text",
) -> dict[str, Any]:
    """Report how a project's worktree seed config compares with its repository.

    Unlike :func:`run_check_config_migrations` this takes no version range: the
    question is "is my config current *now*?", answered by scanning the project
    rather than by reading release manifests. The daemon's shipped default for
    seed entries is necessarily empty, so no version-gated advisory could answer
    it (Plan 00267 DESIGN section 6).

    Nothing is written. The suggested YAML is rendered for a human or an agent
    to place, because a PyYAML round-trip would strip every comment out of a
    config file the project owns.

    Args:
        root: Repository root to scan.
        user_config_path: Path to the project's hooks-daemon.yaml.
        output_format: 'text' for human-readable, 'json' for machine-readable.

    Returns:
        Dictionary with the report (JSON-serializable). Keys: configured,
        unconfigured, missing, seed_key_configured, has_drift, suggested_yaml,
        and text (if format='text').

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If the config file is not a YAML mapping.
    """
    config = _load_yaml(user_config_path)
    report = build_seed_report(root, config)

    return {
        "has_drift": report.has_drift,
        "seed_key_configured": report.seed_key_configured,
        "configured": [asdict(entry) for entry in report.configured],
        "unconfigured": [asdict(entry) for entry in report.unconfigured],
        "missing": [asdict(entry) for entry in report.missing],
        "suggested_yaml": suggested_yaml_block(
            report.unconfigured, seed_key_configured=report.seed_key_configured
        ),
        **({"text": format_report_for_llm(report)} if output_format == "text" else {}),
    }


def run_audit_handler_keys(
    config_path: Path,
    migrated_from: Path | None = None,
) -> dict[str, Any]:
    """Audit every ``handlers.<event>.<key>`` against the handler registry.

    Plan 00362. Unlike :func:`run_check_config_migrations` this takes no
    version range: a key is stale against the code that is installed, not
    against a release manifest, so the answer comes from the registry.

    Args:
        config_path: Path to the hooks-daemon.yaml to audit.
        migrated_from: Optional pre-upgrade copy of the same config. When
            given, the result also lists the relocations the upgrade
            performed between the two files (``applied_migrations``), which
            is what the upgrade summary line reports.

    Returns:
        Dictionary with ``has_findings``, ``findings`` (one dict per
        finding, see ``HandlerKeyFinding.to_dict``), ``text`` (one line per
        finding), and ``applied_migrations`` when ``migrated_from`` is given.

    Raises:
        FileNotFoundError: If a config file doesn't exist.
        ValueError: If a config file is not a YAML mapping.
    """
    config = _load_yaml(config_path)
    findings = audit_handler_keys(config)

    result: dict[str, Any] = {
        "has_findings": bool(findings),
        "findings": [f.to_dict() for f in findings],
        "text": "\n".join(format_findings(findings)),
    }
    if migrated_from is not None:
        before = _load_yaml(migrated_from)
        result["applied_migrations"] = [m.to_dict() for m in applied_relocations(before, config)]
    return result


def run_config_validate(
    config_path: Path,
) -> dict[str, Any]:
    """Validate a config file against the Pydantic schema.

    Args:
        config_path: Path to config YAML to validate

    Returns:
        Dictionary with valid flag, errors, warnings, and guidance

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    config = _load_yaml(config_path)

    validator = ConfigValidator()
    result = validator.validate(config)

    return result.to_dict()

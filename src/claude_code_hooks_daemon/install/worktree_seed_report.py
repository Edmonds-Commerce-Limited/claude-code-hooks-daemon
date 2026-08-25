"""Report how a project's worktree seed config compares with its repository.

**Why this exists as a separate thing from config migration.** ``config-merge``
reconciles a daemon default against a user value on upgrade, and
``check-config-migrations`` reports what changed between two released versions.
Neither can help here: the daemon's shipped default for ``seed.entries`` is
necessarily EMPTY, because no default can know which git-ignored local files a
given project happens to have. The answer has to come from scanning the project
itself, and the question — "is my config current *now*?" — is not gated on a
version range at all.

**It reports; it never writes.** The suggested YAML is rendered for a human (or
an agent with an editor) to place. Rewriting ``hooks-daemon.yaml`` through
PyYAML would round-trip away every comment in a heavily-commented file the
project owns, which is a far worse outcome than pasting four lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.constants.config import ConfigKey
from claude_code_hooks_daemon.constants.events import EventID
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.core.worktree_seed import (
    DEFAULT_SEED_MODE,
    SEED_OPTION_KEY,
    SeedEntry,
    build_seed_config,
    parse_seed_config,
)
from claude_code_hooks_daemon.utils.worktree_seed_suggestions import diff_seed_config

_KEY_SEPARATOR: Final = "."

# Composed from the constants that already govern each level, so a rename
# anywhere in that chain moves this key with it rather than stranding it.
SEED_CONFIG_KEY: Final = _KEY_SEPARATOR.join(
    (
        ConfigKey.HANDLERS,
        EventID.WORKTREE_CREATE.config_key,
        HandlerID.WORKTREE_CREATE.config_key,
        ConfigKey.OPTIONS,
        SEED_OPTION_KEY,
    )
)

_YAML_INDENT: Final = 2

_CLEAN_TEXT: Final = "Worktree seed config is up to date — nothing to change."


@dataclass(frozen=True)
class WorktreeSeedReport:
    """How a project's seed config compares with what its repository holds.

    Attributes:
        configured: The entries currently configured, as parsed.
        unconfigured: Repository candidates the config does not mention.
            Informational — the project may have decided against each one.
        missing: Configured entries whose source no longer exists. Urgent: the
            seeding executor fails fast on exactly this, so each one will abort
            the next worktree creation.
        seed_key_configured: Whether the ``seed`` option exists in the config at
            all. A project that configured an empty list has made a decision; a
            project with no key has never seen the option, and the two deserve
            different remediation text.
    """

    configured: tuple[SeedEntry, ...] = ()
    unconfigured: tuple[SeedEntry, ...] = ()
    missing: tuple[SeedEntry, ...] = ()
    seed_key_configured: bool = False

    @property
    def has_drift(self) -> bool:
        """True when there is anything worth a human's attention."""
        return bool(self.unconfigured or self.missing)


def _value_at_key(key: str, config: dict[str, Any]) -> Any | None:
    """Return the value at a dotted key path, or ``None`` when absent.

    ``None`` doubles as "absent" here — unlike the migration advisory, which
    must tell an explicit ``false`` from an unset key, a ``seed`` option present
    but null is indistinguishable in effect from one that is missing.
    """
    current: Any = config
    for part in key.split(_KEY_SEPARATOR):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def build_seed_report(root: Path, config: dict[str, Any]) -> WorktreeSeedReport:
    """Compare a project's configured seed entries with its repository.

    Args:
        root: The repository root to scan.
        config: The parsed ``hooks-daemon.yaml`` contents.

    Returns:
        The report. A malformed ``seed`` value yields no configured entries
        rather than an error — the parser warns and skips shape mistakes, and a
        reporting command must not be the thing that turns a typo into a crash.
    """
    raw_seed = _value_at_key(SEED_CONFIG_KEY, config)
    configured = parse_seed_config(raw_seed)
    drift = diff_seed_config(root, configured)

    return WorktreeSeedReport(
        configured=tuple(configured),
        unconfigured=drift.unconfigured,
        missing=drift.missing,
        seed_key_configured=raw_seed is not None,
    )


def suggested_yaml_block(entries: Sequence[SeedEntry], *, seed_key_configured: bool) -> str:
    """Render entries as a paste-ready YAML block.

    Args:
        entries: The entries to propose.
        seed_key_configured: When the project already has a ``seed`` option, the
            block shows only its contents, since the surrounding nesting is
            already in the file. When it does not, the full path from
            ``handlers:`` down is emitted so the block can be pasted as-is.

    Returns:
        YAML text, or an empty string when there is nothing to propose.
    """
    if not entries:
        return ""

    seed = build_seed_config(entries, DEFAULT_SEED_MODE)

    document: Any = seed
    if not seed_key_configured:
        for part in reversed(SEED_CONFIG_KEY.split(_KEY_SEPARATOR)):
            document = {part: document}

    return str(
        yaml.safe_dump(document, indent=_YAML_INDENT, sort_keys=False, default_flow_style=False)
    )


def format_report_for_llm(report: WorktreeSeedReport) -> str:
    """Render the report as text for a terminal or an agent's context.

    Args:
        report: The report to render.

    Returns:
        Human-readable text. Paths are named; their CONTENTS are never read,
        so a suggestion cannot leak a secret out of the file it proposes.
    """
    if not report.has_drift:
        return _CLEAN_TEXT

    lines: list[str] = ["Worktree seed config drift", ""]

    if report.missing:
        lines.append("MISSING — configured, but no longer present in the repository:")
        lines.extend(f"  - {entry.path} ({entry.mode})" for entry in report.missing)
        lines.append("")
        lines.append(
            "  These abort the NEXT worktree creation: seeding fails fast on an "
            "absent source rather than handing an agent a worktree quietly "
            "missing files it cannot know are absent. Remove each entry, or "
            "restore the file."
        )
        lines.append("")

    if report.unconfigured:
        lines.append("UNCONFIGURED — present in the repository, not mentioned in the config:")
        lines.extend(f"  - {entry.path}" for entry in report.unconfigured)
        lines.append("")
        lines.append(
            "  A fresh worktree will NOT contain these, so an agent running "
            "there works against a different configuration from the session "
            "that spawned it. Add any that belong:"
        )
        lines.append("")
        block = suggested_yaml_block(
            report.unconfigured, seed_key_configured=report.seed_key_configured
        )
        lines.extend(f"    {line}" for line in block.rstrip().splitlines())
        lines.append("")
        lines.append(
            "  Nothing has been written — the config is the project's. Choose "
            "`copy` instead of `symlink` for anything an agent may overwrite, "
            "because a symlinked file writes back to the main checkout."
        )

    return "\n".join(lines).rstrip() + "\n"

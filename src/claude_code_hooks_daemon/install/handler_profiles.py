"""Handler profile application for installer.

Applies predefined handler profiles to hooks-daemon.yaml by toggling
enabled flags while preserving all comments and formatting.

Profiles:
- minimal: Safety handlers only (default — config as-is from yaml.example)
- recommended: Safety + code quality + plan workflow + linting
- strict: All handlers enabled

Profiles are a ONE-SHOT SEED of the user's config at fresh-install time only.
Once ``apply_profile`` has flipped the chosen handlers to ``enabled: true`` in
``.claude/hooks-daemon.yaml``, that file is the single source of truth for which
handlers run — the profile name is not stored and is never re-applied. The
upgrade path deliberately carries zero profile references: the config-merge
preserves a seeded ``enabled: true`` as a user customisation, so the seed
survives upgrades even though the new version's example default still ships the
handler disabled (regression-guarded by
``tests/unit/install/test_handler_profiles.py::TestProfileSeedSurvivesUpgrade``).
To change handlers after install, edit the yaml directly — do not expect
re-running the installer with a different ``HANDLER_PROFILE`` to be the
authority.
"""

import logging
import re
from pathlib import Path
from typing import Final

import yaml

logger = logging.getLogger(__name__)

# Handler names to enable for each profile (cumulative).
# Minimal enables nothing extra (base config already has safety handlers on).
# Recommended adds quality, plan, and workflow handlers.
# Strict adds everything else.

_RECOMMENDED_HANDLERS: Final[list[str]] = [
    # Code quality
    "qa_suppression",
    "tdd_enforcement",
    "lint_on_edit",
    "validate_instruction_content",
    # Plan workflow
    "plan_number_helper",
    "validate_plan_number",
    "plan_time_estimates",
    "plan_workflow",
    "plan_completion_advisor",
    "markdown_organization",
    # Workflow state
    "transcript_archiver",
    # Productivity
    "task_completion_checker",
    "critical_thinking_advisory",
    "task_tdd_advisor",
    "agent_isolation_advisor",
]

_STRICT_ONLY_HANDLERS: Final[list[str]] = [
    "daemon_restart_verifier",
    "lsp_enforcement",
    "npm_command",
    "british_english",
    "subagent_completion_logger",
    "notification_logger",
    "remind_prompt_library",
    "validate_eslint_on_write",
]

PROFILES: Final[dict[str, list[str]]] = {
    "minimal": [],
    "recommended": list(_RECOMMENDED_HANDLERS),
    "strict": list(_RECOMMENDED_HANDLERS) + list(_STRICT_ONLY_HANDLERS),
}

# Pattern to find a handler block and its enabled line.
# Matches: "    handler_name:" followed within 2 lines by "enabled: false"
_HANDLER_BLOCK_PATTERN = re.compile(
    r"^(\s+)({handler_name}):\s*(?:#.*)?\n"
    r"((?:\s+(?:#.*)?\n)*)"  # Optional comment-only lines between
    r"(\s+enabled:\s*)false(\s*(?:#.*)?)\n",
    re.MULTILINE,
)


def get_profile_names() -> list[str]:
    """Return sorted list of available profile names."""
    return sorted(PROFILES.keys())


def all_profile_handler_names() -> set[str]:
    """Return every handler name referenced by any profile.

    ``strict`` is the superset of ``recommended`` plus the strict-only set, so
    its membership covers all profiles. Used to validate the hardcoded profile
    lists against the handler names the shipped config actually declares
    (F-PROFLIST): a renamed/typo'd handler that exists in no config would
    otherwise silently no-op.
    """
    return set(PROFILES["strict"])


def config_handler_names(content: str) -> set[str]:
    """Return the set of handler names declared anywhere in a config yaml.

    Handlers live under ``handlers.<event_type>.<handler_name>``. Parsed
    structurally (comments ignored) so profile entries can be checked against
    the names the config actually declares. Returns an empty set if the content
    is not parseable as the expected mapping shape.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return set()
    if not isinstance(data, dict):
        return set()
    handlers = data.get("handlers")
    if not isinstance(handlers, dict):
        return set()
    names: set[str] = set()
    for event_handlers in handlers.values():
        if isinstance(event_handlers, dict):
            names.update(event_handlers.keys())
    return names


def apply_profile(config_path: Path, profile: str) -> int:
    """Apply a handler profile to a hooks-daemon.yaml file.

    Reads the yaml as text and toggles ``enabled: false`` to ``enabled: true``
    for handlers in the selected profile. Preserves all comments and formatting.

    Args:
        config_path: Path to hooks-daemon.yaml
        profile: Profile name (minimal, recommended, strict)

    Returns:
        Number of handlers toggled from false to true

    Raises:
        ValueError: If profile name is not recognised
    """
    if profile not in PROFILES:
        valid = ", ".join(get_profile_names())
        msg = f"Unknown handler profile: {profile!r}. Valid profiles: {valid}"
        raise ValueError(msg)

    handlers_to_enable = PROFILES[profile]
    if not handlers_to_enable:
        return 0

    content = config_path.read_text()

    # F-PROFLIST: warn (non-fatal) about profile handlers the config does not
    # declare. A partial config may legitimately omit handlers, but a name that
    # exists in NO config is a profile-list typo/rename — surfaced loudly here
    # and guarded against the shipped example by the test suite.
    known = config_handler_names(content)
    for handler_name in handlers_to_enable:
        if handler_name not in known:
            logger.warning(
                "Profile %r references handler %r not present in %s; skipping it",
                profile,
                handler_name,
                config_path,
            )

    count = 0

    for handler_name in handlers_to_enable:
        # Build a specific pattern for this handler
        pattern = re.compile(
            r"^(\s+)"  # Leading indent
            + re.escape(handler_name)
            + r":\s*(?:#.*)?\n"  # handler_name: # optional comment
            r"((?:\s+(?:#.*)?\n)*)"  # Optional comment-only lines
            r"(\s+enabled:\s*)false"  # The enabled: false line
            r"(\s*(?:#.*)?)\n",  # Trailing comment
            re.MULTILINE,
        )
        match = pattern.search(content)
        if match:
            # Replace just "false" with "true" in the enabled line
            start = match.start(3) + len(match.group(3))
            end = start + len("false")
            content = content[:start] + "true " + content[end:]
            count += 1
            logger.info("Enabled handler: %s", handler_name)

    config_path.write_text(content)
    return count

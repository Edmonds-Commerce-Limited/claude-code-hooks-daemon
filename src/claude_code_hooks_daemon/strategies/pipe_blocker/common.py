"""Shared constants for pipe blocker strategies - DRY.

The UNIVERSAL_WHITELIST_PATTERNS defines commands that are always safe to pipe
to tail/head because they are cheap filtering/output commands.
These patterns are NEVER filtered by language settings.
"""

# Commands whose output is always cheap/safe to pipe to tail/head.
# These are filtering/processing commands that don't do expensive computation.
# Patterns use r'^cmd\b' to match command name at start of segment.
UNIVERSAL_WHITELIST_PATTERNS: tuple[str, ...] = (
    r"^grep\b",
    r"^rg\b",
    r"^awk\b",
    r"^sed\b",
    r"^jq\b",
    r"^cut\b",
    r"^sort\b",
    r"^uniq\b",
    r"^tr\b",
    r"^wc\b",
    r"^cat\b",
    r"^echo\b",
    r"^printf\b",
    r"^ls\b",
    r"^git\s+tag\b",
    r"^git\s+status\b",
    r"^git\s+diff\b",
    r"^date\b",
    r"^hostname\b",
    r"^uname\b",
    r"^whoami\b",
    r"^id\b",
    r"^pwd\b",
    r"^env\b",
    r"^printenv\b",
)

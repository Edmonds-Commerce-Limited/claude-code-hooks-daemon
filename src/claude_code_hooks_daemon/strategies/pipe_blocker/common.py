"""Shared constants for pipe blocker strategies - DRY.

The UNIVERSAL_WHITELIST_PATTERNS defines commands that are always safe to pipe
to tail/head because they are cheap filtering/output commands.
These patterns are NEVER filtered by language settings.

The git entries are built from the shared ``GIT_INVOCATION`` grammar rather
than a bare ``^git\\s+``. Anchoring on the bare name meant a global option
defeated the whitelist -- ``git -C <path> log`` piped to ``head`` was denied
as "unrecognized" while the identical bare spelling was allowed. That is a
false POSITIVE, not a bypass, which is why it survived unnoticed: it only
ever cost someone a blocked command they were entitled to run. Reusing the
grammar is the same DRY fix Plan 00202 applied to the evasion class.
"""

from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION, OPTIONAL_PATH
from claude_code_hooks_daemon.utils.secret_file_matching import SECRET_META_SUBCOMMAND

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
    rf"^{GIT_INVOCATION}tag\b",
    rf"^{GIT_INVOCATION}status\b",
    rf"^{GIT_INVOCATION}diff\b",
    # `git log` and `git branch` were advertised as whitelisted by the
    # handler's own CLAUDE.md guidance while absent here, so an agent piping
    # either was denied as "unrecognized" for doing what resident context
    # said was allowed. They belong here on the merits, not merely to match
    # the text: both are as cheap as the already-whitelisted `git diff`, both
    # write continuously (so a closed pipe raises SIGPIPE and they stop), and
    # for both, truncation is the POINT of the pipe rather than the
    # information loss this handler exists to prevent.
    rf"^{GIT_INVOCATION}log\b",
    rf"^{GIT_INVOCATION}branch\b",
    r"^date\b",
    r"^hostname\b",
    r"^uname\b",
    r"^whoami\b",
    r"^id\b",
    r"^pwd\b",
    r"^env\b",
    r"^printenv\b",
    r"^find\b",
    r"^ps\b",
    # `pgrep` belongs beside `ps` on identical merits: a cheap process query
    # that writes continuously (so a closed pipe raises SIGPIPE and it stops),
    # and for which truncation is the POINT of the pipe rather than the
    # information loss this handler exists to prevent.
    #
    # Its absence went unnoticed because the canonical idiom hid it:
    # `ps -o etime= -p $(pgrep -f x | head -1)` attributed the producer to the
    # whitelisted OUTER `ps`, so the inner `pgrep` was never classified.
    # Correcting that attribution (Plan 00221) made the omission visible.
    r"^pgrep\b",
    r"^df\b",
    # The `secret-meta` metadata helper (Plan 00272) is the documented
    # recovery path `secret_file_guard`'s own deny message offers, so its
    # output must be pipeable to a preview command like any other cheap,
    # bounded-output CLI. Two invocation shapes: the direct entrypoint
    # (`hooks-daemon secret-meta`, at any install path — `OPTIONAL_PATH`
    # covers `bin/hooks-daemon`, `.claude/hooks-daemon/bin/hooks-daemon` and
    # a bare PATH install) and the skill wrapper that forwards arbitrary
    # subcommands to it (`daemon-cli.sh secret-meta` — see
    # `.claude/skills/hooks-daemon/scripts/daemon-cli.sh`'s fallback
    # branch). Scoped to the `secret-meta` subcommand only: a bare
    # `hooks-daemon` invocation of some other subcommand is not whitelisted
    # by this entry and still falls through to the normal unknown tier.
    # `daemon-cli.sh` accepts an optional leading `bash ` interpreter
    # invocation because that is exactly how SKILL.md's own case statement
    # forwards every subcommand it dispatches (`bash "$SKILL_DIR/scripts/
    # daemon-cli.sh" "$SUBCOMMAND" "$@"`) -- the script is also independently
    # executable via its own shebang, so both spellings must match.
    rf"^{OPTIONAL_PATH}hooks-daemon\s+{SECRET_META_SUBCOMMAND}\b",
    rf"^(?:bash\s+)?{OPTIONAL_PATH}daemon-cli\.sh\s+{SECRET_META_SUBCOMMAND}\b",
)

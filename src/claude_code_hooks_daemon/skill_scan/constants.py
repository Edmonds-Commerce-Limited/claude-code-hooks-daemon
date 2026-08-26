"""Constants for the skill-opportunity scan pipeline (Plan 00274).

Every literal the pipeline uses is named here (Core Standard 09). The
transcript field/marker contract is the one verified against real Claude
Code jsonl files in BRAINSTORM.md section 2 and frozen by the extraction
unit tests.
"""

from __future__ import annotations

from typing import Final

#: The jsonl record type carrying (possibly) human prompts.
USER_RECORD_TYPE: Final[str] = "user"

#: Field-level exclusion flags: any of these true means machine traffic.
EXCLUDE_FLAGS: Final[tuple[str, ...]] = (
    "isMeta",
    "isSidechain",
    "isCompactSummary",
    "isVisibleInTranscriptOnly",
)

#: Content-level markers (BRAINSTORM.md section 2): a prompt containing one
#: of these is machine traffic, not a human. Config-extensible via the
#: ``extra_exclude_patterns`` option, since agent-team wrappers evolve.
EXCLUDE_CONTENT_MARKERS: Final[tuple[str, ...]] = (
    "<teammate-message",
    "Another Claude session sent a message",
    "<task-notification",
    "[Request interrupted by user",
    "FAILSAFE RECOVERY CHECK",
    "🤖 [ccy-supervisor",
    "<command-name>",
    "<local-command-stdout>",
    "<system-reminder>",
    "<command-message>",
)

#: Normalisation placeholders — paths, shas and numbers are collapsed so
#: near-identical prompts cluster together and path material never reaches
#: the digest verbatim.
PATH_PLACEHOLDER: Final[str] = "<path>"
SHA_PLACEHOLDER: Final[str] = "<sha>"
NUM_PLACEHOLDER: Final[str] = "<num>"

#: Clustering heuristic (PLAN.md Decision 4): token-set Jaccard, greedy.
JACCARD_THRESHOLD: Final[float] = 0.5

#: Digest budget caps — these bound the model's input tokens regardless of
#: transcript volume.
REPRESENTATIVE_MAX_CHARS: Final[int] = 200
DEFAULT_MAX_CLUSTERS: Final[int] = 100
MAX_PAYLOAD_CHARS: Final[int] = 50_000
MAX_REPORT_CLUSTERS: Final[int] = 25

#: Model invocation.
CLAUDE_CLI_BINARY: Final[str] = "claude"
MODEL_TIMEOUT_SECONDS: Final[int] = 300
MODEL_ERROR_DETAIL_MAX_CHARS: Final[int] = 500
NOT_LOGGED_IN_MARKER: Final[str] = "Not logged in"

#: Option defaults (config surface, BRAINSTORM.md section 6).
DEFAULT_CHECK_INTERVAL_DAYS: Final[int] = 7
DEFAULT_TRANSCRIPT_WINDOW_DAYS: Final[int] = 14
DEFAULT_MODEL: Final[str] = "haiku"

#: State file (version_check TTL pattern) under the daemon untracked dir.
STATE_FILE_NAME: Final[str] = "skill_scan_state.json"

#: A failed ATTEMPT quietens the SessionStart advisory for this long, so a
#: permanently-offline box is not nagged every session while still retrying
#: daily (BRAINSTORM.md section 7).
ATTEMPT_QUIET_SECONDS: Final[float] = 86_400.0

SECONDS_PER_DAY: Final[int] = 86_400

#: Report conventions (docs/guides/CREATING_REPORTS.md + Decision 6).
REPORTS_DIR_NAME: Final[str] = "reports"
REPORT_FILE_SUFFIX: Final[str] = "-skill-opportunities.md"

#: Claude Code's per-project transcript layout under the user's home.
CLAUDE_PROJECTS_SUBDIR: Final[tuple[str, str]] = (".claude", "projects")
TRANSCRIPT_GLOB: Final[str] = "*.jsonl"

#: Project skill/command inventory locations (existing-skill suppression).
SKILLS_SUBDIR: Final[tuple[str, str]] = (".claude", "skills")
COMMANDS_SUBDIR: Final[tuple[str, str]] = (".claude", "commands")
MARKDOWN_SUFFIX: Final[str] = ".md"

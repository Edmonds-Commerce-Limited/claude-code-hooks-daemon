"""Handler attribution by deny-message fingerprint (Plan 00116 Task 2b.1).

A transcript records a hook denial as the DENIED tool call's ``reason``
text, not the handler that produced it — the daemon does not stamp a
handler id onto the record. :func:`attribute_deny` resolves a recorded
deny text back to a handler's config key in two stages:

1. **Primary — rule-ID extraction.** Every handler migrated onto
   ``Handler.get_rules() -> list[Rule]`` renders its deny text through
   ``RuleFormatter``, which always leads with ``"BLOCKED [R-<ID>]: ..."``
   (see ``core/rule.py``). This stage extracts that bracketed rule ID and
   looks it up in an index built from ``rule_explain.lookup.discover_handler_rules``
   — the same rule/handler enumeration ``explain-rule`` uses — mapping the
   ID to its owning handler's config key. This covers every migrated
   handler automatically; no per-handler literal needs maintaining here.
2. **Fallback — literal fragment table.** :data:`FINGERPRINT_TABLE` below
   matches a table of distinctive literal substrings captured from
   handlers' PRE-migration deny-reason text. This is load-bearing for
   attributing OLDER transcripts recorded before a handler migrated onto
   ``get_rules()`` — those denials never contained a ``BLOCKED [R-...]``
   header, so stage 1 cannot resolve them, and re-scanning session history
   is the entire point of this module.

Coverage: every ``handlers/pre_tool_use/*.py`` module with a
``Decision.DENY`` path was read to source its fallback fingerprint(s). Two
pairs of handlers were found to share their entire deny-message HEADER
with no other stable literal distinguishing them without also inspecting
the paired tool_use's tool name (out of scope for a content-only,
privacy-safe scan): ``plan_qa_edit`` / ``plan_qa_commit_gate`` both lead
with ``"Plan QA violation(s) — fix before retrying:"``
(``plan_qa/report.py``), and ``docs_qa_edit`` / ``docs_qa_commit_gate``
both lead with ``"Docs QA violation(s) — fix before retrying:"``
(``docs_qa/report.py``). Those four handlers are deliberately NOT in
:data:`FINGERPRINT_TABLE`; see :data:`UNRESOLVED_HANDLER_PAIRS`.

Fallback fingerprint fragments are checked as case-sensitive substrings —
the denial text is the handler's own generated reason, so exact literal
matching is deliberately strict rather than fuzzy.
"""

from __future__ import annotations

import re
from functools import lru_cache

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.rule_explain.lookup import discover_handler_rules

# Matches the leading header every RuleFormatter-rendered deny text carries
# (both ``.terse()`` and ``.verbose()`` start with this — see core/rule.py).
_RULE_ID_HEADER_PATTERN = re.compile(r"BLOCKED \[(R-[A-Z0-9-]+)\]")

# One entry per blocking handler that could be attributed from a stable
# literal fragment of its own deny-reason text. Every fragment below is
# copied verbatim from the handler's source (see module docstring).
FINGERPRINT_TABLE: dict[str, tuple[str, ...]] = {
    HandlerID.SED_BLOCKER.config_key: (
        "BLOCKED: sed is forbidden",
        "BLOCKED: sed command detected",
    ),
    HandlerID.PIPE_BLOCKER.config_key: (
        "BLOCKED: Pipe to tail/head detected",
        "Pipe to tail/head —",
        "pipe-like pattern (`| tail` / `| head`) detected",
    ),
    HandlerID.DESTRUCTIVE_GIT.config_key: ("BLOCKED: Destructive git command detected",),
    HandlerID.ABSOLUTE_PATH.config_key: ("tool requires absolute path",),
    HandlerID.DANGEROUS_PERMISSIONS.config_key: ("BLOCKED: chmod 777 - dangerous permissions",),
    HandlerID.ASK_USER_QUESTION_BLOCKER.config_key: ("BLOCKED: AskUserQuestion without",),
    HandlerID.DAEMON_LOCATION_GUARD.config_key: (
        "BLOCKED: Attempting to cd into .claude/hooks-daemon/",
    ),
    HandlerID.QA_SUPPRESSION.config_key: ("QA SUPPRESSION BLOCKED:",),
    HandlerID.GITHUB_AUTO_CLOSE_KEYWORDS.config_key: (
        "BLOCKED: GitHub auto-closing keyword reference in a git",
    ),
    HandlerID.GIT_STASH.config_key: ("BLOCKED: git stash\n\n",),
    HandlerID.ERROR_HIDING_BLOCKER.config_key: ("BLOCKED: Error-hiding pattern detected",),
    HandlerID.ANCESTRY_PRESERVING_MERGE.config_key: ("severs ancestry",),
    HandlerID.PLAN_TIME_ESTIMATES.config_key: (
        "BLOCKED: Time estimates not allowed in plan documents",
    ),
    HandlerID.ARTIFACT_PUBLISH_BLOCKER.config_key: ("BLOCKED: publishing an artefact",),
    HandlerID.NPM_COMMAND.config_key: (
        "BLOCKED: Piping npm/npx commands is pointless",
        "Must use llm: prefixed command instead of",
    ),
    HandlerID.VALIDATE_INSTRUCTION_CONTENT.config_key: (
        "BLOCKED: Detected",
        "not ephemeral content like",
    ),
    HandlerID.COMMENT_CHANGELOG.config_key: ("BLOCKED: changelog content in a code comment",),
    HandlerID.SECURITY_ANTIPATTERN.config_key: ("SECURITY ANTIPATTERN BLOCKED",),
    HandlerID.PIP_BREAK_SYSTEM.config_key: ("BLOCKED: pip install --break-system-packages",),
    HandlerID.COMMENT_SIZE.config_key: ("BLOCKED: over-long comment (",),
    HandlerID.CURL_PIPE_SHELL.config_key: ("BLOCKED: Piping network content to shell",),
    HandlerID.MARKDOWN_ORGANIZATION.config_key: (
        "MARKDOWN FILE IN WRONG LOCATION",
        "UNTRACKED CLAUDE MEMORY IS DISABLED FOR THIS PROJECT",
    ),
    HandlerID.GH_ISSUE_COMMENTS.config_key: ("BLOCKED: gh issue view requires --comments flag",),
    HandlerID.GH_PR_COMMENTS.config_key: ("BLOCKED: gh pr view requires --comments flag",),
    HandlerID.LOCK_FILE_EDIT_BLOCKER.config_key: ("BLOCKED: Direct editing of lock file",),
    HandlerID.GIT_MESSAGE_BACKTICK.config_key: (
        "BLOCKED: backticks inside a double-quoted git message are",
    ),
    HandlerID.ROOT_RECURSION_GUARD.config_key: (
        "BLOCKED: recursive scan rooted at a catastrophic location",
    ),
    HandlerID.SUDO_PIP.config_key: ("BLOCKED: sudo pip install",),
    HandlerID.PLAN_NUMBER_HELPER.config_key: (
        "hand-creates a plan folder",
        "won't find all plans",
    ),
    HandlerID.WRITE_CLOBBER_GUARD.config_key: (
        "BLOCKED: this Write would destroy a file you have not read",
    ),
    HandlerID.WORKTREE_FILE_COPY.config_key: (
        "BLOCKED: Attempting to copy files from worktree to main repo",
    ),
    HandlerID.SENSITIVE_CONTENT.config_key: ("SENSITIVE CONTENT BLOCKED:",),
    HandlerID.SECRET_FILE_GUARD.config_key: ("SECRET FILE PROTECTED:",),
    HandlerID.QUARANTINE_ARTEFACT_READ_GUARD.config_key: ("QUARANTINE ARTEFACT READ-BOUNDARY:",),
    HandlerID.FLAGGABLE_CONTENT_CHANNEL_GUARD.config_key: ("FLAGGABLE CONTENT CHANNEL:",),
    HandlerID.TDD_ENFORCEMENT.config_key: ("TDD REQUIRED: Cannot create",),
    HandlerID.STAGED_LINT_GATE.config_key: ("STAGED LINT GATE: a syntax check FAILED",),
    HandlerID.LSP_ENFORCEMENT.config_key: ("LSP tool available for this lookup:",),
    HandlerID.BASH_SAFE_MODE.config_key: (
        "BASH SAFE MODE: this multi-statement invocation declares no",
    ),
    HandlerID.VERIFICATION_RESULT_GATE.config_key: ("VERIFICATION RESULT NOT CONSUMED:",),
}

# Handlers with a Decision.DENY path whose deny text could NOT be attributed
# to a single handler by literal fingerprint alone, and why. Not consulted
# by attribute_deny(); kept for documentation and for the coverage test.
UNRESOLVED_HANDLER_PAIRS: dict[str, str] = {
    HandlerID.PLAN_QA_EDIT.config_key: (
        "shares the 'Plan QA violation(s) — fix before retrying:' header with "
        f"{HandlerID.PLAN_QA_COMMIT_GATE.config_key}; both call "
        "plan_qa.report.format_block_reason with no other stable literal"
    ),
    HandlerID.PLAN_QA_COMMIT_GATE.config_key: (
        f"shares its header with {HandlerID.PLAN_QA_EDIT.config_key}; see that entry"
    ),
    HandlerID.DOCS_QA_EDIT.config_key: (
        "shares the 'Docs QA violation(s) — fix before retrying:' header with "
        f"{HandlerID.DOCS_QA_COMMIT_GATE.config_key}; both call "
        "docs_qa.report.format_block_reason with no other stable literal"
    ),
    HandlerID.DOCS_QA_COMMIT_GATE.config_key: (
        f"shares its header with {HandlerID.DOCS_QA_EDIT.config_key}; see that entry"
    ),
}


@lru_cache(maxsize=1)
def _rule_id_to_config_key() -> dict[str, str]:
    """Build a ``rule_id -> handler config_key`` index from every discovered rule.

    Reuses ``rule_explain.lookup.discover_handler_rules`` (the same
    enumeration ``explain-rule`` uses) rather than duplicating handler
    discovery here. Cached because handler discovery walks the package on
    every call and the result is immutable for the life of the process.

    Returns:
        Mapping of upper-cased rule ID to its owning handler's config key.
    """
    return {
        rule.rule_id.upper(): handler.config_key
        for handler in discover_handler_rules()
        for rule in handler.rules
    }


def attribute_deny(text: str) -> str | None:
    """Attribute one deny-reason text to a handler's config key.

    Tries rule-ID extraction first (covers every handler migrated onto
    ``get_rules()``), then falls back to :data:`FINGERPRINT_TABLE` literal
    matching for pre-migration historical transcript text.

    Args:
        text: The deny-reason text recorded in a transcript's tool_result.

    Returns:
        The matching handler's ``config_key``, or ``None`` when neither
        stage resolves the text, or when the fallback stage's fragments
        match more than one handler (an ambiguous match is reported as
        unattributed rather than guessed).
    """
    header_match = _RULE_ID_HEADER_PATTERN.search(text)
    if header_match is not None:
        config_key = _rule_id_to_config_key().get(header_match.group(1).upper())
        if config_key is not None:
            return config_key

    matches = [
        handler
        for handler, fragments in FINGERPRINT_TABLE.items()
        if any(fragment in text for fragment in fragments)
    ]
    if len(matches) != 1:
        return None
    return matches[0]

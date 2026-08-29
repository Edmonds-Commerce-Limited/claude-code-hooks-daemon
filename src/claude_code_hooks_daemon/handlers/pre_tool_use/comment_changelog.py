"""CommentChangelogHandler - blocks changelog narrative accumulating in a comment.

A comment describes CURRENT STATE; a changelog belongs in git, a changelog
file, or a plan's JOURNAL/. The failure mode this handler defends against is
MONOTONIC: nobody deletes from a comment changelog, so it only ever grows
(Plan 00208, field report: a bash version-marker trailing comment reached
5,645 characters, six releases deep, and broke the banner that echoed it).

History as RATIONALE is legitimate and must NOT be flagged -- a comment may
recount the past when the past is the reason the code looks the way it does.
The separating test: does the comment grow via APPEND (changelog), or get
REPLACED when the situation changes (rationale)? Practical proxies: an entry
keyed by a RELEASE NUMBER is a changelog; an entry keyed by a FAILURE MODE
(a plan number, a bug description) is a rationale.

Uses Strategy Pattern for comment SYNTAX only (CommentStrategyRegistry); the
changelog-detection signals themselves are language-agnostic regexes run
against extracted CommentSpan text, mirroring how qa_suppression's matching
logic lives once in the handler while strategies carry only config.
"""

import re
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.comments.extractor import (
    CommentSpan,
    extract_comment_spans,
)
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.registry import (
    CommentStrategyRegistry,
)
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
)

_MODE_BLOCK: Final[str] = "block"
_MODE_WARN: Final[str] = "warn"
_DEFAULT_MAX_HISTORY_ENTRIES: Final[int] = 1

# Built-in default excludes so the "vendor/build/fixture dirs are skipped by
# default" guidance in get_claude_md() below is actually true (Plan 00288
# Task 4.6/C8 — it previously named these defaults without passing any to
# handler_excludes_path). The vendored/build half derives from the canonical
# core (Task 3.2); the fixture-semantics half is a different category and
# mirrors error_hiding_blocker's local convention.
_FIXTURE_EXCLUDE_GLOBS: Final[tuple[str, ...]] = (
    "**/tests/fixtures/**",
    "**/tests/assets/**",
    "**/__fixtures__/**",
)
_DEFAULT_EXCLUDE_GLOBS: Final[tuple[str, ...]] = (
    tuple(f"**/{name}/**" for name in sorted(CORE_VENDORED_BUILD_DIR_NAMES))
    + _FIXTURE_EXCLUDE_GLOBS
)

_FIELD_CONTENT: Final[str] = "content"
_FIELD_NEW_STRING: Final[str] = "new_string"

# A "semver token" is deliberately narrower than "anything with a dot": a
# bare two-part decimal (e.g. Python's "3.11") is common in ordinary prose
# and is NOT treated as a version — only a full three-part release number or
# an explicitly 'v'-prefixed token counts, matching the field report's own
# shape (3.27.0, 3.26.2, ...). Plan/Task numbering in THIS project's own
# style ("Task 3.5.2", "Phase 3.5.2") is ALSO three-part and dotted, so
# tokens immediately preceded by those words are excluded — measured via
# Plan 00208's own whole-repo self-scan (see JOURNAL), which found this
# collision firing on legitimate rationale comments across the codebase.
_SEMVER_TOKEN: Final[str] = r"(?<!Task )(?<!Phase )(?:v?\d+\.\d+\.\d+|v\d+\.\d+)"
_SEMVER_TOKEN_RE: Final[re.Pattern[str]] = re.compile(_SEMVER_TOKEN, re.IGNORECASE)

# ── High-precision signals (BLOCK) ───────────────────────────────────────
# Only these two. The proposal originally specified five signals as each
# "close to unambiguous on its own" — a version arrow, a changelog verb
# naming a version, and 2+ distinct versioned entries were ALSO planned as
# blocking. Plan 00208's whole-repo self-scan measured all five against
# this codebase's own ~1,080 source/test files and found the other three
# fire on legitimate code: version-processing utilities (upgrade
# compatibility checkers, version-range parsers) legitimately cite
# multiple version numbers in their own docstrings; "removed in vX.Y"
# describing an EXTERNAL tool's own deprecation is legitimate rationale,
# not a changelog entry about this project. Only `Prior <version>:` /
# `Previously <version>:` and a dated entry showed ZERO false positives —
# every real hit was either this project's own field-report-style test
# fixture, or the genuine field-report shape itself. The other three
# signals are demoted to advisory (below) rather than dropped.
_PRIOR_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:Prior|Previously)\s+(?:{_SEMVER_TOKEN})\s*:", re.IGNORECASE
)
_DATED_ENTRY_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\d{4}-\d{2}-\d{2}\s*:")

# ── Lower-precision signals (ADVISE only) ────────────────────────────────
_VERSION_ARROW_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_SEMVER_TOKEN})\s*(?:->|→)\s*(?:{_SEMVER_TOKEN})", re.IGNORECASE
)
_CHANGELOG_VERBS: Final[str] = (
    r"Bumped|Removed|Added|Fixed|Changed|Deprecated|Renamed|Patched|Released"
)
_CHANGELOG_VERB_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:{_CHANGELOG_VERBS})\b[^\n.]{{0,40}}\bin\b\s+(?:{_SEMVER_TOKEN})", re.IGNORECASE
)
_BULLET_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:Fixed|Added|Changed):", re.IGNORECASE
)
_MIN_BULLET_RUN_COUNT: Final[int] = 2
# "used to" is ambiguous in English: "we used to retry synchronously"
# (retrospective) vs "a flag used to validate X" (utility sense — "used
# [in order] to"). The self-scan found the utility sense overwhelmingly
# more common in real code comments/docstrings, so this phrase is only
# treated as retrospective when a pronoun subject immediately precedes it.
# "no longer" / "we switched from" showed no comparable ambiguity.
_RETROSPECTIVE_PHRASE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:we|it|this|they|I)\s+used\s+to\b|\bno longer\b|\bwe switched from\b",
    re.IGNORECASE,
)

_MAX_SPANS_SHOWN: Final[int] = 5


def _distinct_dated_or_versioned_entries(text: str) -> set[str]:
    """Return the set of distinct semver/date tokens referenced in ``text``."""
    entries: set[str] = {match.group(0).lower() for match in _SEMVER_TOKEN_RE.finditer(text)}
    entries.update(match.group(0) for match in _DATED_ENTRY_PATTERN.finditer(text))
    return entries


def _block_reasons(text: str) -> list[str]:
    """High-precision signals: each measured with zero false positives (see module docstring)."""
    reasons: list[str] = []
    if _PRIOR_PATTERN.search(text):
        reasons.append("'Prior <version>:' / 'Previously <version>:' phrasing")
    if _DATED_ENTRY_PATTERN.search(text):
        reasons.append("a dated entry (e.g. '2026-08-12: ...')")
    return reasons


def _advisory_reasons(text: str, max_history_entries: int) -> list[str]:
    """Lower-precision signals: suggestive, not conclusive -- advise only."""
    reasons: list[str] = []
    if _VERSION_ARROW_PATTERN.search(text):
        reasons.append("a version-transition arrow (e.g. '1.2 -> 1.3')")
    if _CHANGELOG_VERB_VERSION_PATTERN.search(text):
        reasons.append("a changelog verb naming a version (e.g. 'Removed in v2.1.224')")
    entries = _distinct_dated_or_versioned_entries(text)
    if len(entries) > max_history_entries:
        reasons.append(
            f"{len(entries)} distinct dated/versioned entries in one comment "
            f"(advisory threshold: {max_history_entries})"
        )
    if len(_BULLET_RUN_PATTERN.findall(text)) >= _MIN_BULLET_RUN_COUNT:
        reasons.append("multiple 'Fixed:'/'Added:'/'Changed:' bullet-style entries")
    if _RETROSPECTIVE_PHRASE_PATTERN.search(text):
        reasons.append("retrospective phrasing ('used to', 'no longer', 'we switched from')")
    return reasons


class CommentChangelogHandler(PreToolUseHandlerBase):
    """Block Write/Edit content that writes historical narrative into a comment.

    This is the valuable half of Plan 00208 -- size is a proxy, history is
    the defect. Configuration options (set via config YAML):
        max_history_entries: int - more than this many distinct dated/
            versioned entries in one comment is a changelog regardless of
            phrasing (default 1).
        mode: "block" | "warn" - block denies; warn downgrades every
            high-precision finding to advisory context (default "block").
        languages: list[str] | None - restrict to specific languages.
        exclude_paths: list[str] | None - additional glob excludes.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.COMMENT_CHANGELOG,
            priority=Priority.COMMENT_CHANGELOG,
            # NOT terminal, and that is load-bearing. This handler has an
            # ADVISORY path: softer signals (retrospective phrasing, two
            # versioned entries) return ALLOW with context rather than a
            # deny. The chain breaks on ANY terminal match regardless of
            # decision, so a terminal advisory ALLOW here ended dispatch at
            # priority 31 and silently disabled every higher-numbered
            # handler -- tdd_enforcement (35) among them -- for that write.
            # An ordinary English phrase like "no longer" in a comment was
            # enough to switch TDD enforcement off, and nothing reported it,
            # because a shadowed handler and one that did not match look
            # identical from outside.
            #
            # Denying is not weakened by this: core/chain.py keeps the most
            # restrictive decision seen, so a later advisory ALLOW cannot
            # wash out a non-terminal deny (the Plan 00144 regression).
            # plan_qa_edit already ships blocking and non-terminal.
            terminal=False,
            tags=[
                HandlerTag.MULTI_LANGUAGE,
                HandlerTag.CONTENT_QUALITY,
                HandlerTag.BLOCKING,
            ],
        )
        self._registry = CommentStrategyRegistry.create_default()
        self._languages: list[str] | None = None
        self._languages_applied: bool = False
        self._max_history_entries: int = _DEFAULT_MAX_HISTORY_ENTRIES
        self._mode: str = _MODE_BLOCK
        self._exclude_paths: list[str] | None = None

    def _apply_language_filter(self) -> None:
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or self._project_languages
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    def _get_content(self, hook_input: dict[str, Any]) -> str:
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.EDIT:
            return str(tool_input.get(_FIELD_NEW_STRING, ""))
        return str(tool_input.get(_FIELD_CONTENT, ""))

    def _is_excluded(self, file_path: str) -> bool:
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            defaults=_DEFAULT_EXCLUDE_GLOBS,
        )

    def _find_violations(
        self, content: str, strategy: CommentStrategy
    ) -> list[tuple[CommentSpan, list[str], list[str]]]:
        """Return (span, block_reasons, advisory_reasons) for every flagged span."""
        violations: list[tuple[CommentSpan, list[str], list[str]]] = []
        for span in extract_comment_spans(content, strategy.syntax):
            block = _block_reasons(span.text)
            advisory = _advisory_reasons(span.text, self._max_history_entries)
            if block or advisory:
                violations.append((span, block, advisory))
        return violations

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check whether the content being written has a flagged comment span."""
        self._apply_language_filter()

        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return False

        if any(skip_dir in file_path for skip_dir in strategy.skip_directories):
            return False
        if self._is_excluded(file_path):
            return False

        content = self._get_content(hook_input)
        if not content:
            return False

        return bool(self._find_violations(content, strategy))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny (or advise) when a comment span carries changelog narrative."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return GatingResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return GatingResult(decision=Decision.ALLOW)

        content = self._get_content(hook_input)
        if not content:
            return GatingResult(decision=Decision.ALLOW)

        violations = self._find_violations(content, strategy)
        if not violations:
            return GatingResult(decision=Decision.ALLOW)

        blocking = [(span, reasons) for span, reasons, _advisory in violations if reasons]
        if blocking and self._mode == _MODE_BLOCK:
            return GatingResult(decision=Decision.DENY, reason=self._build_deny_reason(blocking))

        return GatingResult(decision=Decision.ALLOW, context=[self._build_advisory(violations)])

    def _build_deny_reason(self, blocking: list[tuple[CommentSpan, list[str]]]) -> str:
        lines: list[str] = []
        for span, reasons in blocking[:_MAX_SPANS_SHOWN]:
            preview = span.text if len(span.text) <= 120 else span.text[:117] + "..."
            reasons_text = "; ".join(reasons)
            lines.append(f"  - {reasons_text}\n    {preview!r}")
        spans_text = "\n".join(lines)

        return (
            f"BLOCKED: changelog content in a code comment ({len(blocking)} comment(s)).\n\n"
            f"{spans_text}\n\n"
            "Comments describe CURRENT STATE only. Move the history:\n"
            "  - what changed and when  -> git (it is already there — the commit message)\n"
            "  - release notes for humans -> the project's changelog file\n"
            "  - in-flight narrative      -> the plan's JOURNAL/ day-file\n\n"
            "Keep in the comment only what is true of the code as it stands now.\n\n"
            "If this is RATIONALE (why the code looks the way it does, anchored to a "
            "failure mode) rather than a changelog, rephrase without dated/versioned "
            "entries — key it to the failure mode, not the release number."
        )

    def _build_advisory(self, violations: list[tuple[CommentSpan, list[str], list[str]]]) -> str:
        lines = ["ADVISORY: comment content resembles changelog narrative"]
        for span, block, advisory in violations[:_MAX_SPANS_SHOWN]:
            for reason in (*block, *advisory):
                preview = span.text if len(span.text) <= 80 else span.text[:77] + "..."
                lines.append(f"  - {reason}: {preview!r}")
        lines.append(
            "Comments describe current state only — consider moving history to git, "
            "a changelog file, or the plan's JOURNAL/."
        )
        return "\n".join(lines)

    def get_claude_md(self) -> str | None:
        return (
            "## comment_changelog — no changelog narrative in code comments\n\n"
            "A `Write`/`Edit` that puts HISTORICAL NARRATIVE into a code comment is "
            "blocked. A comment "
            "describes CURRENT STATE; changelog narrative belongs in git (the commit "
            "message), the project's changelog file, or a plan's `JOURNAL/` day-file.\n\n"
            "**Blocked (high-precision) signals**, either of which denies the write:\n"
            "- `Prior <version>:` / `Previously <version>:` phrasing\n"
            "- a dated entry (`2026-08-12: ...`)\n\n"
            "Both were measured with ZERO false positives across this project's own "
            "~1,080 source/test files (Plan 00208's whole-repo self-scan) — every real "
            "hit was either the field-report shape itself or this handler's own test "
            "fixtures.\n\n"
            "**NOT blocked — advisory only**: a version-transition arrow "
            "(`1.2 -> 1.3`), a changelog verb naming a version (`Removed in v2.1.224`), "
            "two or more distinct versioned/dated entries in one comment (configurable "
            "via `max_history_entries`, default 1), `Fixed:`/`Added:`/`Changed:` bullet "
            "runs, retrospective phrasing (`used to`, `no longer`, `we switched from`). "
            "These four started as blocking signals but the same self-scan found each "
            "firing on legitimate code — version-processing utilities (upgrade "
            "compatibility checkers) legitimately cite multiple versions in their own "
            'docstrings, and "removed in vX.Y" describing an EXTERNAL tool\'s own '
            "deprecation is rationale, not a changelog entry about this project.\n\n"
            "**History as RATIONALE is legitimate and is NOT flagged.** A comment may "
            "recount the past when the past is the reason the code looks the way it is "
            "now, and re-litigating it would reintroduce a fixed bug — e.g. `# Plan "
            "00047: do NOT re-add DISABLE_MOUSE, see...`. The separating test: an entry "
            "keyed by a RELEASE NUMBER is a changelog; an entry keyed by a FAILURE MODE "
            "(a plan number, a bug description) is a rationale.\n\n"
            "**No escape hatch** — unlike `comment_size`, this handler has no "
            "`MUST_..._BECAUSE` override: changelog content should be MOVED to git/a "
            "changelog file/a plan JOURNAL/, never exempted in place.\n\n"
            "**Scope**: only comment spans are scanned (not code), via the same "
            "Strategy Pattern language registry as `qa_suppression`. `.md` files are "
            "skipped entirely — markdown prose is not a comment. Only the ADDED text "
            "is checked on `Edit` (`new_string`) — removing changelog content is "
            "never blocked.\n\n"
            "**Excluded paths**: vendor/build/fixture dirs are skipped by default. "
            "Exempt more paths via "
            "`handlers.pre_tool_use.comment_changelog.options.exclude_paths` or the "
            "project-wide `daemon.exclude_paths`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: per-language DENY cases plus a near-miss ALLOW case."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        tests: list[Any] = []
        for strategy in self._registry.all_strategies:
            if hasattr(strategy, "get_acceptance_tests"):
                tests.extend(strategy.get_acceptance_tests())

        # Near-miss ALLOW case: history as RATIONALE (keyed by a plan/failure
        # mode, not a release number) must NOT be flagged, even though it
        # also recounts the past -- this is the make-or-break distinction
        # the whole handler exists to get right.
        tests.append(
            AcceptanceTest(
                title="comment_changelog: plan-number-keyed rationale is allowed",
                command=(
                    "Use the Write tool to create "
                    "/tmp/acceptance-test-comment-changelog-rationale/example.py "
                    "whose content has a '#' comment reading "
                    "'History (Plan 00047 -- do NOT re-add DISABLE_MOUSE without "
                    "reading this): fullscreen draws on the terminal alt-screen...'"
                ),
                description=(
                    "A rationale comment keyed by a plan/failure-mode reference "
                    "(not a release number) must be ALLOWED even though it "
                    "recounts history -- the make-or-break distinction"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses /tmp path - safe. Verify the file is created, not blocked.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-comment-changelog-rationale"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-comment-changelog-rationale"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            )
        )
        return tests

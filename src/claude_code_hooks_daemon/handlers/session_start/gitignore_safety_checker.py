"""GitignoreSafetyCheckerHandler - warns when required .claude/ paths are not gitignored.

Runs on SessionStart (new sessions only). Uses content-hash caching so the
filesystem check only re-runs when .gitignore or .claude/.gitignore actually changes.

**A protected glob's ignore line must never swallow ciphertext** (Plan
00459). The globs select by NAME, and an Ansible Vault encrypted vars file
can match one whose name describes what it holds; committing it is the
point of Vault. So each session, uncached (a file can be encrypted or
decrypted without the `.gitignore` changing), the protected files git knows
about are checked with the shared ``encrypted_at_rest`` detector: an advised
glob line is followed by a ``!/<path>`` negation for every ciphertext file it
would catch, and ciphertext an existing rule already ignores is reported
with the negation that re-includes it. Plaintext protected files must stay
ignored, exactly as before. Only format names leave the detector, so no
content reaches this advisory.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.encrypted_at_rest import is_encrypted_at_rest
from claude_code_hooks_daemon.utils.git_file_states import (
    gitignore_negation,
    scan_git_file_states,
    unignore_advice,
)
from claude_code_hooks_daemon.utils.secret_file_matching import (
    path_is_protected,
    resolve_configured_patterns,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

# Each entry: (root_gitignore_pattern, scoped_claude_gitignore_pattern, human_description)
# root_pattern   — substring to look for in root .gitignore lines
# scoped_pattern — equivalent substring for .claude/.gitignore (relative, no .claude/ prefix)
# description    — shown in advisory when entry is missing
_STATIC_GITIGNORE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        ".claude/worktrees",
        "worktrees",
        ".claude/worktrees/ (Claude Code managed worktrees — path is not configurable)",
    ),
    (
        ".CLAUDE.md.pre-inject",
        "",
        ".CLAUDE.md.pre-inject (ClaudeMdInjector backup — session artifact, never commit)",
    ),
    (
        ".claude/scheduled_tasks.lock",
        "scheduled_tasks.lock",
        ".claude/scheduled_tasks.lock (ScheduleWakeup/cron runtime lock — never commit)",
    ),
)


def _protected_pattern_entries() -> tuple[tuple[str, str, str], ...]:
    """One required gitignore entry per EFFECTIVE protected glob, derived not restated.

    A file whose contents may never be read into context certainly may never
    enter git history, so the never-commit list must cover the never-read one
    -- and "the never-read one" is `resolve_configured_patterns()`, not the
    shipped defaults alone: a project's own `secret_file_guard.options.
    protected_paths` merges onto the defaults (additive is the default mode),
    and a glob added there must show up here too, or a file the guard refuses
    to read stays perfectly committable.

    Derived rather than restated, because a hand-written approximation of a
    glob is not the glob (Plan 00412, F-HYG-1): a gitignore line matching only
    an exact suffix does not match a `.bak` beside it, so a project can satisfy
    this advisory in full and still commit a file the daemon refuses to read.

    `secret_file_guard` denies authoring these globs as literal text, which
    makes the same point mechanically: there is one place they are allowed to
    live, and this is not it.

    A glob is not `.claude/`-scoped, so the scoped pattern is the root pattern.
    """
    return tuple(
        (
            pattern,
            pattern,
            f"{pattern} (a protected path — its contents may never be read, "
            "so it must never be committed)",
        )
        for pattern in resolve_configured_patterns()
    )


def _required_gitignore_patterns() -> tuple[tuple[str, str, str], ...]:
    """Static daemon-artefact patterns plus one entry per effective protected glob.

    Computed at CALL time, not import time: `resolve_configured_patterns()`
    reads the project's loaded config, which has not happened yet when this
    module is first imported. Building the derived entries once at import
    time froze the answer at the shipped defaults regardless of what a
    project later configures.
    """
    return _STATIC_GITIGNORE_PATTERNS + _protected_pattern_entries()


_GITIGNORE_FILE = ".gitignore"
_CLAUDE_GITIGNORE_FILE = ".claude/.gitignore"
_CACHE_FILE_NAME = "gitignore_safety_cache.json"
# A leading '!' in .gitignore negates (un-ignores) a pattern — never coverage.
_GITIGNORE_NEGATION_PREFIX = "!"

_NEGATION_CAVEAT = (
    "An Ansible Vault ENCRYPTED file matching a protected glob is meant to be "
    "tracked: follow the glob with a `!/<path>` line for it."
)
_SWALLOWED_HEADING = (
    "⚠️  GITIGNORE SAFETY: .gitignore ignores an encrypted file that should be tracked"
)


@dataclass(frozen=True)
class _Ciphertext:
    """A protected file git knows about whose content is a whole-file vault payload."""

    relpath: str
    ignored: bool


class GitignoreSafetyCheckerHandler(SessionStartHandlerBase):
    """Warn when required .claude/ paths are absent from .gitignore.

    Advisory handler — runs on new sessions only, caches by gitignore content hash
    to avoid redundant filesystem reads on every session start.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GITIGNORE_SAFETY_CHECKER,
            priority=Priority.GITIGNORE_SAFETY_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    # ------------------------------------------------------------------
    # Project root / cache file helpers
    # ------------------------------------------------------------------

    def _get_project_root(self) -> Path | None:
        """Return project root from ProjectContext, or cwd fallback."""
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for gitignore check")
            return Path.cwd()

    def _get_cache_file(self) -> Path:
        """Return path to the cache file inside the daemon untracked dir."""
        try:
            cache_dir = ProjectContext.daemon_untracked_dir()
            return cache_dir / _CACHE_FILE_NAME
        except (OSError, RuntimeError):
            fallback = Path.cwd() / "untracked"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback / _CACHE_FILE_NAME

    # ------------------------------------------------------------------
    # Gitignore content hash (cache invalidation key)
    # ------------------------------------------------------------------

    def _compute_gitignore_hash(self, project_root: Path) -> str:
        """MD5 of root .gitignore + .claude/.gitignore content (not security — cache key only)."""
        content = ""
        for rel in (_GITIGNORE_FILE, _CLAUDE_GITIGNORE_FILE):
            path = project_root / rel
            if path.exists():
                try:
                    content += path.read_text(errors="replace")
                except OSError as exc:
                    logger.debug("Could not read %s for hash: %s", path, exc)
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()  # nosec B324

    # ------------------------------------------------------------------
    # Missing entry detection
    # ------------------------------------------------------------------

    def _read_gitignore_lines(self, project_root: Path) -> set[str]:
        """Return non-blank, non-comment lines from all relevant gitignore files."""
        lines: set[str] = set()
        for rel in (_GITIGNORE_FILE, _CLAUDE_GITIGNORE_FILE):
            path = project_root / rel
            if not path.exists():
                continue
            try:
                for raw in path.read_text(errors="replace").splitlines():
                    stripped = raw.strip()
                    if stripped and not stripped.startswith("#"):
                        lines.add(stripped)
            except OSError as exc:
                logger.debug("Could not read %s for gitignore check: %s", path, exc)
        return lines

    @staticmethod
    def _line_covers_pattern(line: str, pattern: str) -> bool:
        """Return True if a gitignore ``line`` actually ignores ``pattern``.

        Uses parsed-ignore semantics, not raw substring matching:

        - Negation lines (``!...``) un-ignore a path and never count as coverage.
        - The entry token (trailing slash stripped) must either equal the required
          pattern (also slash-normalised) or be a parent directory of it
          (``pattern`` starts with ``entry + "/"``). This rejects unrelated
          substring matches like ``.claude/worktrees-archive/`` while still
          accepting an ancestor directory such as ``.claude/``.
        """
        if line.startswith(_GITIGNORE_NEGATION_PREFIX):
            return False
        entry = line.rstrip("/")
        target = pattern.rstrip("/")
        if not entry or not target:
            return False
        return entry == target or target.startswith(entry + "/")

    def _find_missing_entries(self, project_root: Path) -> list[str]:
        """Return descriptions of required patterns absent from any gitignore."""
        lines = self._read_gitignore_lines(project_root)
        missing: list[str] = []
        for root_pattern, scoped_pattern, description in _required_gitignore_patterns():
            covered = any(self._line_covers_pattern(line, root_pattern) for line in lines) or (
                scoped_pattern != ""
                and any(self._line_covers_pattern(line, scoped_pattern) for line in lines)
            )
            if not covered:
                missing.append(description)
        return missing

    # ------------------------------------------------------------------
    # Cache read / write / validation
    # ------------------------------------------------------------------

    def _is_cache_valid(self, cache_file: Path, current_hash: str) -> bool:
        """Return True if cache exists and stored hash matches current gitignore content."""
        if not cache_file.exists():
            return False
        try:
            data = json.loads(cache_file.read_text())
            return bool(data.get("gitignore_hash") == current_hash)
        except (OSError, json.JSONDecodeError, KeyError):
            return False

    def _get_cached_missing_entries(self, cache_file: Path) -> list[str] | None:
        """Return cached missing entries list, or None on any read/parse error."""
        try:
            data = json.loads(cache_file.read_text())
            result = data.get("missing_entries")
            return list(result) if isinstance(result, list) else None
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def _write_cache(self, cache_file: Path, gitignore_hash: str, missing: list[str]) -> None:
        """Persist cache entry."""
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps({"gitignore_hash": gitignore_hash, "missing_entries": missing})
            )
        except (OSError, TypeError) as exc:
            logger.debug("Failed to write gitignore safety cache: %s", exc)

    # ------------------------------------------------------------------
    # Handler protocol
    # ------------------------------------------------------------------

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Check gitignore safety, using content-hash cache to minimise I/O.

        Only the missing-line check is cached: its answer depends on the
        ``.gitignore`` content alone. Which protected files are ciphertext
        depends on file content, so that is checked every time.
        """
        project_root = self._get_project_root()
        if project_root is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        ciphertext = self._find_ciphertext(project_root)
        cache_file = self._get_cache_file()
        current_hash = self._compute_gitignore_hash(project_root)

        if self._is_cache_valid(cache_file, current_hash):
            cached = self._get_cached_missing_entries(cache_file)
            if cached is not None:
                return self._build_result(cached, ciphertext, project_root)

        # Cache miss — re-scan
        missing = self._find_missing_entries(project_root)
        self._write_cache(cache_file, current_hash, missing)
        return self._build_result(missing, ciphertext, project_root)

    def _find_ciphertext(self, project_root: Path) -> list[_Ciphertext]:
        """Protected files git knows about whose content is a whole-file vault.

        Empty outside a git repository: without git there is no ignore state
        to judge, and the advisory falls back to the caveat line.
        """
        states = scan_git_file_states(project_root)
        if states is None:
            return []
        patterns = resolve_configured_patterns()
        found: list[_Ciphertext] = []
        for relpath in sorted(states.all_paths):
            absolute = project_root / relpath
            if not path_is_protected(str(absolute), patterns):
                continue
            if is_encrypted_at_rest(absolute, project_root):
                found.append(_Ciphertext(relpath=relpath, ignored=states.is_ignored(relpath)))
        return found

    def _build_result(
        self,
        missing: list[str],
        ciphertext: list[_Ciphertext] | None = None,
        project_root: Path | None = None,
    ) -> AdvisoryResult:
        """Build AdvisoryResult from missing entries and the ciphertext found."""
        found = ciphertext or []
        swallowed = [item.relpath for item in found if item.ignored]
        context = self._missing_section(missing, found, project_root) if missing else []
        if swallowed:
            if context:
                context.append("")
            context += [_SWALLOWED_HEADING, ""]
            context += [f"  {relpath}: {unignore_advice(relpath)}" for relpath in swallowed]
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    def _missing_section(
        self, missing: list[str], ciphertext: list[_Ciphertext], project_root: Path | None
    ) -> list[str]:
        context = [
            "⚠️  GITIGNORE SAFETY: Required .claude/ paths are not gitignored",
            "",
            "The following paths should be in .gitignore or .claude/.gitignore",
            "but are currently missing. They may be accidentally committed:",
            "",
        ]
        for entry in missing:
            context.append(f"  ❌ {entry}")
        context += [
            "",
            "Fix: add the missing entries to your root .gitignore, e.g.:",
            "",
        ]
        protected = set(resolve_configured_patterns())
        advises_a_protected_glob = False
        for root_pattern, _, description in _required_gitignore_patterns():
            if description not in missing:
                continue
            context.append(f"  {root_pattern}")
            if root_pattern not in protected:
                continue
            advises_a_protected_glob = True
            # Never advise a glob that would swallow an existing encrypted
            # file: the negation must follow it, since the last match wins.
            context += [
                f"  {gitignore_negation(item.relpath)}"
                for item in ciphertext
                if project_root is not None
                and path_is_protected(str(project_root / item.relpath), (root_pattern,))
            ]
        context += [
            "",
            "These paths are managed by Claude Code and must never be committed.",
        ]
        if advises_a_protected_glob:
            context.append(_NEGATION_CAVEAT)
        return context

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="gitignore safety checker - reports status on new session",
                command='echo "test"',
                description=(
                    "Verifies gitignore safety check runs on new sessions and "
                    "reports whether .claude/ paths are properly gitignored."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GITIGNORE|gitignore|worktrees"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]

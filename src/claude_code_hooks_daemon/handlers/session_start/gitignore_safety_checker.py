"""GitignoreSafetyCheckerHandler - warns when required .claude/ paths are not gitignored.

Runs on SessionStart (new sessions only). Uses content-hash caching so the
filesystem check only re-runs when .gitignore or .claude/.gitignore actually changes.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext

logger = logging.getLogger(__name__)

# Each entry: (root_gitignore_pattern, scoped_claude_gitignore_pattern, human_description)
# root_pattern   — substring to look for in root .gitignore lines
# scoped_pattern — equivalent substring for .claude/.gitignore (relative, no .claude/ prefix)
# description    — shown in advisory when entry is missing
_REQUIRED_GITIGNORE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        ".claude/worktrees",
        "worktrees",
        ".claude/worktrees/ (Claude Code managed worktrees — path is not configurable)",
    ),
)

_GITIGNORE_FILE = ".gitignore"
_CLAUDE_GITIGNORE_FILE = ".claude/.gitignore"
_CACHE_FILE_NAME = "gitignore_safety_cache.json"
_RESUME_TRANSCRIPT_MIN_BYTES = 100


class GitignoreSafetyCheckerHandler(Handler):
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

    def _find_missing_entries(self, project_root: Path) -> list[str]:
        """Return descriptions of required patterns absent from any gitignore."""
        lines = self._read_gitignore_lines(project_root)
        missing: list[str] = []
        for root_pattern, scoped_pattern, description in _REQUIRED_GITIGNORE_PATTERNS:
            covered = any(root_pattern in line for line in lines) or (
                scoped_pattern != "" and any(scoped_pattern in line for line in lines)
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

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False
        try:
            path = Path(transcript_path)
            return path.exists() and path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return not self._is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check gitignore safety, using content-hash cache to minimise I/O."""
        project_root = self._get_project_root()
        if project_root is None:
            return HookResult(decision=Decision.ALLOW, context=[])

        cache_file = self._get_cache_file()
        current_hash = self._compute_gitignore_hash(project_root)

        if self._is_cache_valid(cache_file, current_hash):
            cached = self._get_cached_missing_entries(cache_file)
            if cached is not None:
                return self._build_result(cached)

        # Cache miss — re-scan
        missing = self._find_missing_entries(project_root)
        self._write_cache(cache_file, current_hash, missing)
        return self._build_result(missing)

    def _build_result(self, missing: list[str]) -> HookResult:
        """Build HookResult from missing entries list."""
        if not missing:
            return HookResult(decision=Decision.ALLOW, context=[])

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
        for root_pattern, _, description in _REQUIRED_GITIGNORE_PATTERNS:
            if description in missing:
                context.append(f"  {root_pattern}/")
        context += [
            "",
            "These paths are managed by Claude Code and must never be committed.",
        ]
        return HookResult(decision=Decision.ALLOW, context=context)

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

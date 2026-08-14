"""Git branch handler for status line.

Shows current git branch with magicmonty-style status icons:
↑N ahead, ↓N behind, ●N staged, ✚N changed, ✖N conflicts,
…N untracked, ⚑N stashed.

Fails silently if not in a git repo or if git commands error.
"""

import logging
import os
import subprocess  # nosec B404 - subprocess used for git commands only (trusted system tool)
import threading
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, Timeout
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

_COLOR_GREEN = "\033[32m"
_COLOR_RED = "\033[31m"
_COLOR_YELLOW = "\033[33m"
_COLOR_CYAN = "\033[36m"
_COLOR_GREY = "\033[37m"
_COLOR_ORANGE = "\033[38;5;208m"
_COLOR_PINK = "\033[38;5;205m"
_COLOR_RESET = "\033[0m"

_ICON_AHEAD = "↑"
_ICON_BEHIND = "↓"
_ICON_STAGED = "●"
_ICON_CHANGED = "✚"
_ICON_CONFLICTS = "✖"
_ICON_UNTRACKED = "…"
_ICON_STASHED = "⚑"
_ICON_WORKTREE = "🌳"

# Linked-worktree detection (filesystem-only, no subprocess on the render path).
# A linked worktree's top-level ``.git`` is a FILE containing
# ``gitdir: <main>/.git/worktrees/<name>``; the main worktree has a ``.git``
# DIRECTORY, and a submodule's ``.git`` file points at ``.../modules/<name>``.
_GIT_DIR_ENTRY = ".git"
_GIT_FILE_GITDIR_PREFIX = "gitdir:"
_WORKTREE_GITDIR_MARKER = "/worktrees/"

_PORCELAIN_BRANCH_AB_PREFIX = "# branch.ab "
_PORCELAIN_UNTRACKED_PREFIX = "? "
_PORCELAIN_ORDINARY_PREFIX = "1 "
_PORCELAIN_RENAMED_PREFIX = "2 "
_PORCELAIN_UNMERGED_PREFIX = "u "
_PORCELAIN_UNCHANGED = "."
_PORCELAIN_XY_START = 2
_PORCELAIN_XY_END = 4
_BRANCH_AB_FIELD_COUNT = 2

# Background fetch: the ahead/behind counts above compare against the LOCAL
# remote-tracking ref, which is only as fresh as the last `git fetch`. A
# long-lived daemon that never fetches would show "in sync" forever while the
# remote moves on. Renders therefore kick a TTL-gated fetch in a daemon
# thread — never on the render hot path, never interactive, never fatal.
_DEFAULT_FETCH_INTERVAL_SECONDS = 300

# Render TTL cache (Plan 00155 T4). Each render forks ~4 git processes; under
# output streaming the status line re-renders every ~300 ms. Serving renders
# from a short per-cwd cache cuts that fork churn with at most TTL-bounded
# staleness. The render is asynchronous, so this is a CPU/battery win, not a
# latency win. TTL <= 0 disables the cache entirely.
#
# THE VALUE MUST NOT SIT BETWEEN 1x AND 2x THE RENDER INTERVAL (Plan 00238).
# A TTL in that band does not merely cache poorly, it RESONATES: a miss at
# render k caches at t_k, the next render lands inside the window (hit), the
# one after lands outside it (miss) — so the cache settles into an exact
# alternating hit/miss steady state and throws away half its own value by
# construction, not by chance.
#
# This was not hypothetical. At 2.0s against a measured ~1.04s render interval
# the live miss rate was 57 of 115 renders (49.6%) over a 120s window, costing
# ~5,760 git subprocess spawns/hour from this handler alone — the largest
# single spawn source in the whole status-line chain.
#
# The value is therefore derived, not chosen: it is _RENDER_TTL_INTERVAL_MULTIPLE
# times the TYPICAL render interval, so the steady state serves at least that
# many renders per miss. Re-derive it, do not nudge it, if the render rate
# changes.
#
# The basis is the MEDIAN interval, not the minimum, and that distinction is
# not pedantry — a longer interval is the WORSE case for a fixed TTL (it covers
# fewer renders), so sizing against the fastest observed rate flatters the
# result. A first version of the paired guard made exactly that mistake and
# would have passed the 2.0s value it was written to catch.
_MEASURED_RENDER_INTERVAL_SECONDS = 1.043
_RENDER_TTL_INTERVAL_MULTIPLE = 5
_RENDER_TTL_ROUNDING_PLACES = 1
_DEFAULT_RENDER_TTL_SECONDS = round(
    _RENDER_TTL_INTERVAL_MULTIPLE * _MEASURED_RENDER_INTERVAL_SECONDS,
    _RENDER_TTL_ROUNDING_PLACES,
)

_GIT_TERMINAL_PROMPT_ENV = "GIT_TERMINAL_PROMPT"
_GIT_TERMINAL_PROMPT_DISABLED = "0"
_GIT_SSH_COMMAND_ENV = "GIT_SSH_COMMAND"
_GIT_SSH_BATCH_MODE = "ssh -oBatchMode=yes"
_FETCH_THREAD_NAME = "status-git-branch-fetch"


class GitBranchHandler(Handler):
    """Show current git branch with magicmonty-style status icons if in a git repo."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_BRANCH,
            priority=Priority.GIT_BRANCH,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.GIT, HandlerTag.NON_TERMINAL],
        )
        # Default branch cached per repo toplevel — a long-lived daemon serves
        # many repos, so a single shared cache would mis-colour branches when
        # the status line re-renders for a different project/worktree.
        self._default_branch_by_repo: dict[str, str | None] = {}
        # Background-fetch state, keyed per repo toplevel (config options
        # `auto_fetch` / `fetch_interval_seconds` land via the registry's
        # setattr injection and override these defaults).
        self._auto_fetch: bool = True
        self._fetch_interval_seconds: float = _DEFAULT_FETCH_INTERVAL_SECONDS
        self._fetch_lock = threading.Lock()
        self._last_fetch_started: dict[str, float] = {}
        self._fetch_inflight: set[str] = set()
        # Render TTL cache keyed by cwd: cwd -> (monotonic timestamp, context).
        # Config option `render_ttl_seconds` lands via the registry's setattr
        # injection and overrides this default.
        #
        # Plan 00157 (review follow-up): like the sibling per-repo dicts above,
        # this grows one entry per distinct cwd the daemon renders for — a small,
        # directory-bounded key space in practice (a handful of project roots /
        # worktrees per daemon lifetime), cleared wholesale on daemon restart. An
        # LRU bound would be premature complexity (YAGNI) for that key space;
        # unbounded-per-directory growth is an accepted, documented trade-off.
        self._render_ttl_seconds: float = _DEFAULT_RENDER_TTL_SECONDS
        self._render_cache: dict[str, tuple[float, list[str]]] = {}

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Get current git branch with status icons and format for status line.

        Renders are served from a short per-cwd TTL cache (Plan 00155 T4) so a
        stream of rapid status renders does not fork ~4 git processes each time.
        A cache miss computes the render via :meth:`_render_git_context` and
        stores it; staleness is bounded by ``_render_ttl_seconds``.

        Args:
            hook_input: Status event input with workspace data

        Returns:
            HookResult with formatted git branch + icons, or empty if not in git repo
        """
        workspace = hook_input.get("workspace", {})
        cwd = workspace.get("current_dir") or workspace.get("project_dir")

        if not cwd or not Path(cwd).exists():
            return HookResult(context=[])

        cached = self._cached_render(cwd)
        if cached is not None:
            return HookResult(context=cached)

        context = self._render_git_context(cwd)
        self._store_render(cwd, context)
        return HookResult(context=context)

    def _cached_render(self, cwd: str) -> list[str] | None:
        """Return the cached render for ``cwd`` if still within the TTL, else None.

        A TTL of <= 0 disables caching (always a miss).
        """
        if self._render_ttl_seconds <= 0:
            return None
        entry = self._render_cache.get(cwd)
        if entry is None:
            return None
        cached_at, context = entry
        if (time.monotonic() - cached_at) >= self._render_ttl_seconds:
            return None
        return context

    def _store_render(self, cwd: str, context: list[str]) -> None:
        """Cache a freshly computed render for ``cwd`` (no-op when caching is disabled)."""
        if self._render_ttl_seconds <= 0:
            return
        self._render_cache[cwd] = (time.monotonic(), context)

    def _render_git_context(self, cwd: str) -> list[str]:
        """Compute the git branch + icons context for ``cwd`` (uncached).

        Returns a single-element context list, or an empty list when ``cwd`` is
        not a git repo or any git command fails.
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                return []

            repo_toplevel = result.stdout.decode().strip()

            # Keep remote-tracking refs fresh so ahead/behind counts are
            # honest — TTL-gated, runs in a daemon thread, never blocks
            # this render (the NEXT render shows the updated counts).
            self._maybe_start_background_fetch(repo_toplevel, cwd)

            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=True,
            )

            branch = result.stdout.decode().strip()
            if branch:
                # A linked worktree recolours the branch pink and appends a tree
                # icon, regardless of default-branch status. Resolve the default
                # branch first regardless (keeps the per-repo cache warm and the
                # git-call sequence stable) so only the colour choice diverges.
                default_branch = self._resolve_default_branch(repo_toplevel, cwd)
                is_worktree = self._is_linked_worktree(repo_toplevel)
                if is_worktree:
                    color = _COLOR_PINK
                elif default_branch is None:
                    color = _COLOR_GREY
                elif branch == default_branch:
                    color = _COLOR_GREEN
                else:
                    color = _COLOR_ORANGE
                icons = self._format_git_status_icons(cwd)
                worktree_prefix = f"{_ICON_WORKTREE} " if is_worktree else ""
                return [f"| ⎇ {worktree_prefix}{color}{branch}{_COLOR_RESET}{icons}"]

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to get git branch: %s", e)
        except Exception as e:
            logger.error("Unexpected error in git branch handler: %s", e, exc_info=True)

        return []

    def _is_linked_worktree(self, repo_toplevel: str) -> bool:
        """Return True when ``repo_toplevel`` is a git *linked* worktree.

        Git stores a linked worktree (created via ``git worktree add``) with a
        top-level ``.git`` FILE whose ``gitdir:`` line points into
        ``<main>/.git/worktrees/<name>``. The main worktree has a ``.git``
        DIRECTORY, and a submodule's ``.git`` file points at
        ``.../modules/<name>`` instead — so matching the ``/worktrees/`` marker
        in the gitdir target distinguishes a worktree from both.

        This is a filesystem probe (``.git`` stat + a small text read), never a
        subprocess, so it adds nothing to the render's git-fork budget. Any
        failure (missing/unreadable ``.git``, a non-str toplevel under a mocked
        render) fails safe to ``False`` — the status line must never crash.
        """
        try:
            git_path = Path(repo_toplevel) / _GIT_DIR_ENTRY
            if not git_path.is_file():
                return False
            content = git_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError, TypeError) as e:
            logger.debug("Worktree detection failed for %r: %s", repo_toplevel, e)
            return False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(_GIT_FILE_GITDIR_PREFIX):
                target = stripped[len(_GIT_FILE_GITDIR_PREFIX) :].strip()
                return _WORKTREE_GITDIR_MARKER in target
        return False

    def _resolve_default_branch(self, repo_toplevel: str, cwd: str) -> str | None:
        """Return the cached default branch for a repo, detecting it once per repo.

        The result is keyed by ``repo_toplevel`` so each distinct repository
        (or worktree) gets its own correct default branch, even though this
        handler instance is reused across many status-line renders.
        """
        if repo_toplevel not in self._default_branch_by_repo:
            self._default_branch_by_repo[repo_toplevel] = self._get_default_branch(cwd)
        return self._default_branch_by_repo[repo_toplevel]

    def _maybe_start_background_fetch(self, repo_toplevel: str, cwd: str) -> bool:
        """Start a TTL-gated background ``git fetch`` for this repo if due.

        The remote-tracking refs the ahead/behind icons compare against are
        local snapshots — without a periodic fetch a long-lived daemon shows
        "in sync" forever. This never blocks the render: the fetch runs in a
        daemon thread and the NEXT render picks up the refreshed counts. The
        first render after daemon start always triggers a fetch.

        Returns:
            True when a fetch thread was started for this call.
        """
        if not self._auto_fetch:
            return False

        now = time.monotonic()
        with self._fetch_lock:
            if repo_toplevel in self._fetch_inflight:
                return False
            last = self._last_fetch_started.get(repo_toplevel)
            if last is not None and (now - last) < self._fetch_interval_seconds:
                return False
            self._fetch_inflight.add(repo_toplevel)
            self._last_fetch_started[repo_toplevel] = now

        self._start_fetch_thread(repo_toplevel, cwd)
        return True

    def _start_fetch_thread(self, repo_toplevel: str, cwd: str) -> None:
        """Spawn the daemon thread that performs the actual fetch."""
        thread = threading.Thread(
            target=self._run_background_fetch,
            args=(repo_toplevel, cwd),
            name=_FETCH_THREAD_NAME,
            daemon=True,
        )
        thread.start()

    def _run_background_fetch(self, repo_toplevel: str, cwd: str) -> None:
        """Run ``git fetch --quiet`` non-interactively; tolerate all failures.

        ``GIT_TERMINAL_PROMPT=0`` and SSH batch mode guarantee the fetch can
        never hang waiting for credentials; offline/failed fetches are logged
        at debug level and simply leave the counts as stale as before.
        """
        try:
            env = os.environ.copy()
            env[_GIT_TERMINAL_PROMPT_ENV] = _GIT_TERMINAL_PROMPT_DISABLED
            env.setdefault(_GIT_SSH_COMMAND_ENV, _GIT_SSH_BATCH_MODE)
            subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "fetch", "--quiet"],
                cwd=cwd,
                env=env,
                capture_output=True,
                timeout=Timeout.GIT_FETCH_BACKGROUND,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.debug("Background git fetch failed for %s: %s", repo_toplevel, e)
        finally:
            with self._fetch_lock:
                self._fetch_inflight.discard(repo_toplevel)

    def _get_default_branch(self, cwd: str) -> str | None:
        """Detect the default branch for the repo.

        Strategy:
        1. Try git symbolic-ref refs/remotes/origin/HEAD (fast, no network)
        2. Fall back to checking if 'main' or 'master' exist locally
        3. Return None if undetermined (branch will be shown grey)
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.decode().strip().split("/")[-1]

            for candidate in ("main", "master"):
                result = (
                    subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                        ["git", "show-ref", "--verify", f"refs/heads/{candidate}"],
                        cwd=cwd,
                        capture_output=True,
                        timeout=Timeout.GIT_STATUS_SHORT,
                        check=False,
                    )
                )
                if result.returncode == 0:
                    return candidate
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to detect default branch: %s", e)

        return None

    def _format_git_status_icons(self, cwd: str) -> str:
        """Render magicmonty-style status icons after the branch name.

        Parses ``git status --porcelain=v2 --branch`` for ahead/behind,
        staged/unstaged change counts, untracked files, and conflicts, then
        appends a stash count from ``git stash list``.

        Returns:
            Leading-space-prefixed icon string (e.g. ' ↑2 ●1 ✚3'), or an
            empty string on any subprocess failure / clean working tree.
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "status", "--porcelain=v2", "--branch"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode != 0:
                return ""

            ahead, behind, staged, changed, untracked, conflicts = self._parse_porcelain(
                result.stdout.decode()
            )
            stashed = self._get_stash_count(cwd)
            return self._render_icons(
                ahead=ahead,
                behind=behind,
                staged=staged,
                changed=changed,
                conflicts=conflicts,
                untracked=untracked,
                stashed=stashed,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.debug("Failed to render git status icons: %s", e)
            return ""
        except Exception as e:
            logger.error("Unexpected error in git status icons: %s", e, exc_info=True)
            return ""

    @staticmethod
    def _parse_porcelain(stdout: str) -> tuple[int, int, int, int, int, int]:
        """Parse porcelain v2 output into (ahead, behind, staged, changed, untracked, conflicts).

        Lines we recognise:
            ``# branch.ab +N -M`` — ahead/behind counts
            ``1 XY ...`` / ``2 XY ...`` — ordinary/renamed entries (X=staged, Y=worktree)
            ``? path`` — untracked
            ``u XY ...`` — unmerged (conflict)
        """
        ahead = behind = staged = changed = untracked = conflicts = 0
        for line in stdout.splitlines():
            if line.startswith(_PORCELAIN_BRANCH_AB_PREFIX):
                fields = line[len(_PORCELAIN_BRANCH_AB_PREFIX) :].split()
                if len(fields) == _BRANCH_AB_FIELD_COUNT:
                    a, b = GitBranchHandler._parse_branch_ab(fields[0], fields[1])
                    if a is not None and b is not None:
                        ahead, behind = a, b
            elif line.startswith(_PORCELAIN_UNTRACKED_PREFIX):
                untracked += 1
            elif line.startswith(_PORCELAIN_ORDINARY_PREFIX) or line.startswith(
                _PORCELAIN_RENAMED_PREFIX
            ):
                xy = line[_PORCELAIN_XY_START:_PORCELAIN_XY_END]
                if len(xy) >= _BRANCH_AB_FIELD_COUNT:
                    if xy[0] != _PORCELAIN_UNCHANGED:
                        staged += 1
                    if xy[1] != _PORCELAIN_UNCHANGED:
                        changed += 1
            elif line.startswith(_PORCELAIN_UNMERGED_PREFIX):
                conflicts += 1
        return ahead, behind, staged, changed, untracked, conflicts

    @staticmethod
    def _parse_branch_ab(ahead_field: str, behind_field: str) -> tuple[int | None, int | None]:
        """Parse the ``+N -M`` fields of a ``# branch.ab`` line.

        Returns (None, None) when either field is malformed — caller keeps prior values.
        """
        try:
            return int(ahead_field.lstrip("+")), int(behind_field.lstrip("-"))
        except ValueError as e:
            logger.debug("Malformed branch.ab fields %r %r: %s", ahead_field, behind_field, e)
            return None, None

    @staticmethod
    def _render_icons(
        *,
        ahead: int,
        behind: int,
        staged: int,
        changed: int,
        conflicts: int,
        untracked: int,
        stashed: int,
    ) -> str:
        """Render non-zero counts as a space-separated, leading-space-prefixed icon string."""
        parts: list[str] = []
        if ahead:
            parts.append(f"{_COLOR_GREEN}{_ICON_AHEAD}{ahead}{_COLOR_RESET}")
        if behind:
            parts.append(f"{_COLOR_RED}{_ICON_BEHIND}{behind}{_COLOR_RESET}")
        if staged:
            parts.append(f"{_COLOR_GREEN}{_ICON_STAGED}{staged}{_COLOR_RESET}")
        if changed:
            parts.append(f"{_COLOR_YELLOW}{_ICON_CHANGED}{changed}{_COLOR_RESET}")
        if conflicts:
            parts.append(f"{_COLOR_RED}{_ICON_CONFLICTS}{conflicts}{_COLOR_RESET}")
        if untracked:
            parts.append(f"{_COLOR_GREY}{_ICON_UNTRACKED}{untracked}{_COLOR_RESET}")
        if stashed:
            parts.append(f"{_COLOR_CYAN}{_ICON_STASHED}{stashed}{_COLOR_RESET}")
        if not parts:
            return ""
        return " " + " ".join(parts)

    def _get_stash_count(self, cwd: str) -> int:
        """Return the number of stashed entries (``git stash list`` line count).

        Returns 0 on any subprocess failure.
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "stash", "list"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode != 0:
                return 0
            return sum(1 for line in result.stdout.decode().splitlines() if line.strip())
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            return 0

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="git branch handler test",
                command='echo "test"',
                description="Tests git branch handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]

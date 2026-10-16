"""Result cache and background runner for the SessionStart QA sweeps (Plan 00495 Task 2.6).

``docs_qa_sweep`` and ``plan_qa_sweep`` re-run their whole check catalogue on
every new session: about 6 CPU-seconds on this repository, enough to overrun
the dispatch budget and drop the handlers behind them. Their findings are a
pure function of the project tree, the policy, the daemon version and (for the
plan sweep) git history and the date, so a result computed for one fingerprint
of those inputs is valid for any later session that sees the same fingerprint.

Two properties are deliberate:

- A cached result is served ONLY for the exact fingerprint it was computed for.
  The fingerprint covers the stat of every file in the project outside a small
  prune list, not just the markdown the sweep parses, because the checks also
  open files they link to (a dead link appears when a non-markdown target is
  deleted). A changed input is a miss; the old result is never served as current.
- A miss runs the sweep on a background thread and waits a short, bounded time
  for it. A sweep that finishes inside the wait is delivered in this session; one
  that does not is reported as pending (with the last known result, labelled as
  possibly out of date) and lands in the cache for the next session. The
  SessionStart chain therefore never blocks on a slow sweep.
"""

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

SWEEP_CACHE_DIR_NAME: Final[str] = "sweep-cache"
# How long a miss may hold up the SessionStart chain before it is reported pending.
DEFAULT_WAIT_SECONDS: Final[float] = 1.0

# Directories pruned at any depth: VCS metadata, dependency trees and tool caches
# that no sweep reads and that churn without meaning.
_PRUNED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "htmlcov",
    }
)
# Pruned only at these project-root-relative locations: the daemon's own runtime
# directory (self-install) and the vendored daemon install (client install), both
# outside every sweep's corpus. A nested directory of the same name is project content.
_PRUNED_ROOT_PATHS: Final[frozenset[str]] = frozenset({"untracked", ".claude/hooks-daemon"})

_CACHE_KEY_FINGERPRINT: Final[str] = "fingerprint"
_CACHE_KEY_CONTEXT: Final[str] = "context"


class SweepState(Enum):
    """Where a sweep outcome came from."""

    CACHED = "cached"
    COMPUTED = "computed"
    PENDING = "pending"


@dataclass(frozen=True)
class SweepOutcome:
    """What a SessionStart sweep has to report this session.

    ``context`` is the advisory text for a current result (``CACHED`` or
    ``COMPUTED``) and is empty while ``PENDING``; ``last_known`` is the previous
    cached result, set only while ``PENDING``, for display labelled as possibly stale.
    """

    state: SweepState
    context: list[str]
    last_known: list[str] = field(default_factory=list)

    def advisory(self, label: str, cli_hint: str) -> list[str]:
        """The context lines to inject: the result, or the pending notice."""
        if self.state is SweepState.PENDING:
            return pending_context(label, self.last_known, cli_hint)
        return self.context


class _Run:
    """One background sweep computation, shared by every request for its fingerprint."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.context: list[str] = []
        self.error: Exception | None = None


_IN_FLIGHT: dict[tuple[str, str], _Run] = {}
_IN_FLIGHT_LOCK = threading.Lock()


def tree_fingerprint(project_root: Path, extra: Sequence[str]) -> str:
    """Fingerprint the project tree plus the non-file inputs of a sweep.

    Args:
        project_root: Directory walked; every file outside the prune list
            contributes its relative path, mtime, size and inode.
        extra: The other inputs that can change findings (policy, daemon
            version, date, git state), each already rendered stable text.

    Returns:
        Hex digest that changes whenever any contributing input changes.
    """
    digest = hashlib.sha256()
    for part in extra:
        digest.update(part.encode("utf-8", "surrogateescape"))
        digest.update(b"\x00")
    for current, dir_names, file_names in os.walk(project_root):
        relative_dir = os.path.relpath(current, project_root).replace(os.sep, "/")
        dir_names[:] = sorted(
            name
            for name in dir_names
            if name not in _PRUNED_DIR_NAMES
            and _join_relative(relative_dir, name) not in _PRUNED_ROOT_PATHS
        )
        for name in sorted(file_names):
            try:
                stat = (Path(current) / name).lstat()
            except FileNotFoundError as exc:
                log_and_continue(
                    logger,
                    exc,
                    reason=f"{name} deleted between the directory listing and its stat; "
                    "the next walk omits it, so the fingerprint moves anyway",
                    level=logging.DEBUG,
                )
                continue
            entry = f"{_join_relative(relative_dir, name)}\x00{stat.st_mtime_ns}\x00"
            digest.update(
                f"{entry}{stat.st_size}\x00{stat.st_ino}\n".encode("utf-8", "surrogateescape")
            )
    return digest.hexdigest()


def _join_relative(relative_dir: str, name: str) -> str:
    """``relative_dir/name`` with the walk root (``.``) contributing no prefix."""
    return name if relative_dir == "." else f"{relative_dir}/{name}"


def run_cached_sweep(
    name: str,
    cache_dir: Path,
    fingerprint: str,
    compute: Callable[[], list[str]],
    wait_seconds: float,
) -> SweepOutcome:
    """Serve the cached result for ``fingerprint``, or compute it off the chain.

    Args:
        name: Sweep identity; names the cache file.
        cache_dir: Writable runtime directory the cache lives under.
        fingerprint: Digest of every input of the sweep (see :func:`tree_fingerprint`).
        compute: Runs the sweep and returns its advisory context lines. Runs on a
            background thread, so it must not depend on per-dispatch state.
        wait_seconds: Longest a miss may wait for ``compute`` before reporting pending.

    Returns:
        ``CACHED`` for a hit, ``COMPUTED`` when ``compute`` finished inside the wait,
        ``PENDING`` when it did not (the result still lands in the cache).

    Raises:
        Exception: Whatever ``compute`` raised, when it failed inside the wait.
            A failure after the wait is logged, and the next session recomputes.
    """
    cache_file = cache_dir / SWEEP_CACHE_DIR_NAME / f"{name}.json"
    cached = _read_cache(cache_file)
    if cached is not None and cached[0] == fingerprint:
        return SweepOutcome(SweepState.CACHED, cached[1])

    run = _start_or_join(cache_file, fingerprint, compute)
    if not run.done.wait(wait_seconds):
        return SweepOutcome(SweepState.PENDING, [], cached[1] if cached is not None else [])
    if run.error is not None:
        raise run.error
    return SweepOutcome(SweepState.COMPUTED, run.context)


def pending_context(label: str, last_known: list[str], cli_hint: str) -> list[str]:
    """Advisory lines for a sweep that has not finished yet.

    Args:
        label: Human name of the sweep, e.g. ``"Docs QA sweep"``.
        last_known: The previous cached result, shown labelled as possibly stale.
        cli_hint: The directive that runs the sweep in the foreground.
    """
    lines = [
        f"{label}: still running in the background; its report is cached for the next "
        "session start."
    ]
    if last_known:
        lines.append("Last known findings (from an earlier sweep, may be out of date):")
        lines.extend(last_known)
    lines.extend(["", cli_hint])
    return lines


def _start_or_join(cache_file: Path, fingerprint: str, compute: Callable[[], list[str]]) -> _Run:
    """The in-flight run for this fingerprint, started on a daemon thread if absent."""
    key = (str(cache_file), fingerprint)
    with _IN_FLIGHT_LOCK:
        existing = _IN_FLIGHT.get(key)
        if existing is not None:
            return existing
        run = _Run()
        _IN_FLIGHT[key] = run
    threading.Thread(
        target=_work,
        args=(run, key, cache_file, fingerprint, compute),
        name=f"sweep-cache-{cache_file.stem}",
        daemon=True,
    ).start()
    return run


def _work(
    run: _Run,
    key: tuple[str, str],
    cache_file: Path,
    fingerprint: str,
    compute: Callable[[], list[str]],
) -> None:
    """Thread body: compute, persist, and release every waiter."""
    try:
        run.context = compute()
        _write_cache(cache_file, fingerprint, run.context)
    except Exception as exc:
        # Handed to a waiting caller to re-raise; logged for the one that gave up waiting.
        run.error = exc
        logger.exception("Sweep %s failed in the background", cache_file.stem)
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT.pop(key, None)
        run.done.set()


def _read_cache(cache_file: Path) -> tuple[str, list[str]] | None:
    """The cached ``(fingerprint, context)``, or ``None`` when absent or unreadable."""
    if not cache_file.is_file():
        return None
    payload: object = None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"unreadable sweep cache {cache_file} is treated as a miss and rewritten",
        )
    if not isinstance(payload, dict):
        logger.warning("Ignoring malformed sweep cache %s: not an object", cache_file)
        return None
    fingerprint = payload.get(_CACHE_KEY_FINGERPRINT)
    context = payload.get(_CACHE_KEY_CONTEXT)
    if not isinstance(fingerprint, str) or not isinstance(context, list):
        logger.warning("Ignoring malformed sweep cache %s: wrong field types", cache_file)
        return None
    return fingerprint, [str(line) for line in context]


def _write_cache(cache_file: Path, fingerprint: str, context: list[str]) -> None:
    """Persist atomically; a failed write costs only the next session a recompute."""
    payload = json.dumps({_CACHE_KEY_FINGERPRINT: fingerprint, _CACHE_KEY_CONTEXT: context})
    temp_file = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(payload, encoding="utf-8")
        temp_file.replace(cache_file)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"sweep cache {cache_file} not written; the next session recomputes the sweep",
        )

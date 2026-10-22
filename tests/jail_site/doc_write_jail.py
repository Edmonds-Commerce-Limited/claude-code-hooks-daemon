"""Refuse every write to a tracked generated doc of ANY checkout (Plan 00474 N280).

A test run once left an older ``<hooksdaemon>`` block in the MAIN checkout's
``CLAUDE.md``. The conftest guard restores the file after the fact and only for
the checkout the run belongs to; this module stops the write itself, in every
checkout of the repository, in the pytest process and in every Python it spawns.

Mechanism: a ``sys.addaudithook`` hook, which sees ``open``, ``os.rename`` and
``os.remove`` however the code reached them (``Path.write_text``, ``shutil``,
``os.replace`` over a temp file, a symlink). The paths to protect travel to
child interpreters through the environment, and ``sitecustomize.py`` in this
directory arms each child from it, so a CLI the test spawns is covered with no
change to production code.

Standard library only: ``sitecustomize`` imports this file as a top-level module
before anything else in the child is importable. It also runs inside the
deliberately old interpreters the entry-point tests spawn, so everything executed
at runtime must work on the oldest of ``tests.old_python.OLD_VERSIONS`` (tuple
``isinstance`` arguments, no ``Path.readlink``); annotations are exempt because
of the ``__future__`` import. ``tests/unit/test_doc_write_jail_old_python.py``
enforces it.

Limits, stated rather than hidden: a child started with ``python -I`` or
``-S`` ignores ``PYTHONPATH``, a test that clears the environment passes none of
it on, and a non-Python process (``sed``, ``cp``) is not seen at all.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

#: Single source of truth for the protected files; ``tests/conftest.py`` imports it.
PROTECTED_RELATIVE_PATHS: tuple[str, ...] = ("CLAUDE.md", ".claude/HOOKS-DAEMON.md")

#: Environment variable carrying the protected absolute paths to child interpreters.
ENV_PROTECTED = "HOOKS_TEST_DOC_JAIL_PATHS"

#: Environment variable naming the file refusals are appended to.
ENV_LOG = "HOOKS_TEST_DOC_JAIL_LOG"

_GIT_TIMEOUT_SECONDS = 10

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


class DocWriteRefused(PermissionError):
    """A write to a protected generated doc was attempted and refused."""


class _Jail:
    """The armed state: what is protected and where refusals are recorded."""

    def __init__(self, protected: frozenset[str], log: Path | None) -> None:
        self.protected = protected
        self.log = log

    def check(
        self,
        event: str,
        target: object,
        *,
        follow_link: bool = True,
        dir_fd: object = None,
    ) -> None:
        """Raise :class:`DocWriteRefused` if ``target`` resolves to a protected path.

        ``follow_link`` is False for a rename or delete, which acts on a symlink
        itself and never on what it points at: removing a link to a protected
        doc leaves the doc alone. ``dir_fd`` is the directory a relative
        ``target`` is relative to, as ``shutil.rmtree`` passes it.
        """
        if not isinstance(target, (str, bytes, os.PathLike)):
            return
        try:
            resolved = _resolve(os.fsdecode(target), dir_fd, follow_link)
        except (TypeError, ValueError, OSError):
            return
        if resolved not in self.protected:
            return
        self._record(event, resolved)
        raise DocWriteRefused(
            f"{event} on {resolved} refused: a test run may not write a tracked "
            "generated doc of any checkout (Plan 00474 N280). Point the code at a "
            "tmp_path project instead."
        )

    def _record(self, event: str, resolved: str) -> None:
        if self.log is None:
            return
        line = f"{os.getpid()}\t{event}\t{resolved}\n".encode()
        with contextlib.suppress(OSError):
            _append(self.log, line)


def _resolve(path: str, dir_fd: object, follow_link: bool) -> str:
    """Absolute, symlink-resolved form of ``path``.

    The last component stays literal when ``follow_link`` is False. Raises OSError
    when a ``dir_fd`` cannot be named.
    """
    candidate = Path(path)
    if dir_fd is not None and dir_fd != -1 and not candidate.is_absolute():
        candidate = Path(f"/proc/self/fd/{dir_fd}").resolve() / candidate
    if follow_link:
        return str(candidate.resolve())
    return str(candidate.absolute().parent.resolve() / candidate.name)


def _append(path: Path, data: bytes) -> None:
    """Append with ``os`` primitives: a test that patches ``open`` must not break the record."""
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def _read_from(path: Path, offset: int) -> bytes:
    """Read from ``offset`` with ``os`` primitives, for the same reason as :func:`_append`."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.lseek(descriptor, offset, os.SEEK_SET)
        chunks = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


_state: _Jail | None = None
_hook_installed = False
_local = threading.local()


def _audit(event: str, args: tuple[object, ...]) -> None:
    jail = _state
    if jail is None or getattr(_local, "allowed_depth", 0) > 0:
        return
    if event == "open":
        flags = args[2]
        if isinstance(flags, int) and flags & _WRITE_FLAGS:
            jail.check(event, args[0])
    elif event == "os.rename":
        jail.check(event, args[0], follow_link=False, dir_fd=args[2])
        jail.check(event, args[1], follow_link=False, dir_fd=args[3])
    elif event == "os.remove":
        jail.check(event, args[0], follow_link=False, dir_fd=args[1])


def install(protected: frozenset[str], log: Path | None) -> object | None:
    """Arm the jail over ``protected`` (resolved absolute paths), logging to ``log``.

    Returns:
        The state it replaced, an opaque token for :func:`restore`.
    """
    global _state, _hook_installed
    previous = _state
    _state = _Jail(protected, log)
    if not _hook_installed:
        sys.addaudithook(_audit)
        _hook_installed = True
    return previous


def restore(previous: object | None) -> None:
    """Put back what :func:`install` returned; ``None`` leaves the jail inert.

    An audit hook cannot be removed, so "off" means the hook stays and refuses
    nothing.
    """
    global _state
    if previous is not None and not isinstance(previous, _Jail):
        raise TypeError(f"not a state returned by install(): {previous!r}")
    _state = previous


def install_from_environment() -> None:
    """Arm from :data:`ENV_PROTECTED` / :data:`ENV_LOG`; do nothing when unset."""
    raw = os.environ.get(ENV_PROTECTED)
    if not raw:
        return
    log = os.environ.get(ENV_LOG)
    install(frozenset(raw.split(os.pathsep)), Path(log) if log else None)


@contextlib.contextmanager
def allowed() -> Iterator[None]:
    """Let THIS thread write protected paths: for the conftest guard's own restore."""
    _local.allowed_depth = getattr(_local, "allowed_depth", 0) + 1
    try:
        yield
    finally:
        _local.allowed_depth -= 1


def checkout_roots(repo_root: Path) -> list[Path]:
    """Every checkout of the repository ``repo_root`` belongs to, itself included.

    Read from ``git worktree list``, so a run in a linked worktree also protects
    the main checkout, which is the checkout the incident damaged.
    """
    own = repo_root.resolve()
    roots = [own]
    try:
        completed = subprocess.run(
            ["git", "-C", str(own), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return roots
    if completed.returncode != 0:
        return roots
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            root = Path(line[len("worktree ") :]).resolve()
            if root not in roots:
                roots.append(root)
    return roots


def protected_paths(roots: list[Path]) -> frozenset[str]:
    """The protected generated docs of every root, as resolved absolute strings."""
    return frozenset(
        str(root / relative) for root in roots for relative in PROTECTED_RELATIVE_PATHS
    )


def environment_for_children(protected: frozenset[str], log: Path) -> dict[str, str]:
    """The environment entries that arm a spawned Python over ``protected``."""
    site_dir = str(Path(__file__).resolve().parent)
    existing = os.environ.get("PYTHONPATH")
    python_path = site_dir if not existing else os.pathsep.join([site_dir, existing])
    return {
        "PYTHONPATH": python_path,
        ENV_PROTECTED: os.pathsep.join(sorted(protected)),
        ENV_LOG: str(log),
    }


def log_offset(log: Path) -> int:
    """Current size of the refusal log; 0 when it does not exist yet."""
    try:
        return log.stat().st_size
    except OSError:
        return 0


def refusals_since(log: Path, offset: int) -> list[str]:
    """Refusal lines appended after ``offset``."""
    try:
        return _read_from(log, offset).decode("utf-8", "replace").splitlines()
    except OSError:
        return []


@contextlib.contextmanager
def consuming_refusals(log: Path) -> Iterator[None]:
    """Discard refusals logged inside the block: for a test that provokes one on purpose."""
    offset = log_offset(log)
    try:
        yield
    finally:
        if log.exists():
            os.truncate(log, offset)

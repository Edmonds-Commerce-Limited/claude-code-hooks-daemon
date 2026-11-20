"""Pack the loose files of one run and one verdict together (Plan 00627 Task 3.5).

DESIGN.md section 5.1: thousands of loose files become a handful of archives.
Each file is claimed on its own (``.sweeping-<name>``, one directory), then
every claim of a batch is packed into one archive, members ``./.sweeping-<name>``
in that directory, by the same argv-only, scrubbed-environment GNU tar as a
single entry (:mod:`scratch_archive_pack`).

The contract with the rest of the store is unchanged: one index record per
entry. A batch writes one record per file, all naming the same archive and
SHA-256. A file is then removed or resumed by :mod:`scratch_archive_remove`
like any entry, its proof being the restricted ``tar --compare`` of its one
member (the partly-removed path), never the member set of the whole archive.

Only regular files and symbolic links are loose files here: a directory is an
entry of its own, and a special file is never packed. A file with more than one
hard link, a claim from another directory, or a file changed since its claim
refuses the whole batch and leaves no archive; the claims are the caller's to
release. Nothing here removes anything but the unrecorded archive of a refused
batch (through :meth:`ArchiveStore.discard_unrecorded`).
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - argv only, never a shell
from collections.abc import Sequence
from dataclasses import dataclass

from claude_code_hooks_daemon.core.scratch_archive import (
    ArchiveRecord,
    ArchiveStore,
    StoreRefused,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    Claimed,
    Node,
    WalkRefused,
    check_entry_name,
    fingerprint_of,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    DEFAULT_TAR_TIMEOUT_SECONDS,
    TarDidNotRun,
    TarTool,
    VerifyFailed,
    batched_compare,
    digest_fd,
    read_member_names,
    run_tar,
    tar_create_args,
)

#: The kinds a loose file may be.
LOOSE_KINDS = frozenset({"file", "symlink"})


class BatchRefused(Exception):
    """The batch was not packed; no archive of it remains."""


@dataclass(frozen=True)
class LooseFile:
    """A loose file due for packing: its name in the directory, verdict and size."""

    name: str
    verdict: str
    size: int


@dataclass(frozen=True)
class BatchPackResult:
    """A packed, verified, fsynced batch archive that no record names yet."""

    archive_id: str
    entries: tuple[str, ...]
    kinds: tuple[str, ...]
    size: int
    sha256: str


def plan_batches(
    files: Sequence[LooseFile], *, max_members: int, max_bytes: int
) -> list[tuple[str, tuple[str, ...]]]:
    """Group loose files by verdict, then split by member count and bytes.

    Names are sorted within a verdict; a file larger than ``max_bytes`` is a
    batch of its own. Raises :class:`BatchRefused` on a repeated or bad name.
    """
    if max_members < 1 or max_bytes < 1:
        raise BatchRefused("batch limits must be positive")
    seen: set[str] = set()
    by_verdict: dict[str, list[LooseFile]] = {}
    for item in files:
        try:
            check_entry_name(item.name)
        except ValueError as exc:
            raise BatchRefused(str(exc)) from exc
        if item.name in seen:
            raise BatchRefused(f"{item.name!r} is listed twice")
        seen.add(item.name)
        by_verdict.setdefault(item.verdict, []).append(item)
    batches: list[tuple[str, tuple[str, ...]]] = []
    for verdict in sorted(by_verdict):
        current: list[str] = []
        used = 0
        for item in sorted(by_verdict[verdict], key=lambda f: f.name):
            full = len(current) >= max_members or used + item.size > max_bytes
            if current and full:
                batches.append((verdict, tuple(current)))
                current, used = [], 0
            current.append(item.name)
            used += item.size
        if current:
            batches.append((verdict, tuple(current)))
    return batches


def _same_dir(fd_a: int, fd_b: int) -> bool:
    a, b = os.fstat(fd_a), os.fstat(fd_b)
    return (a.st_ino, a.st_dev) == (b.st_ino, b.st_dev)


def _loose_node(handle: Claimed) -> Node:
    """Walk one claimed loose file; refuse anything but an unchanged, singly linked file or link."""
    try:
        listing = walk_tree(handle.parent_fd, handle.claimed_name, max_inodes=1)
    except WalkRefused as exc:
        raise BatchRefused(f"{handle.name!r} cannot be walked: {exc}") from exc
    node = listing.root
    if node.kind not in LOOSE_KINDS:
        raise BatchRefused(f"{handle.name!r} is a {node.kind}, not a loose file")
    if node.nlink > 1:
        raise BatchRefused(f"{handle.name!r} has {node.nlink} hard links")
    if fingerprint_of(listing) != handle.fingerprint:
        raise BatchRefused(f"{handle.name!r} changed since its claim")
    return node


def _check_claims(claims: Sequence[Claimed]) -> list[Node]:
    if not claims:
        raise BatchRefused("an empty batch")
    names = [c.claimed_name for c in claims]
    if len(set(names)) != len(names):
        raise BatchRefused("a file is in the batch twice")
    first = claims[0].parent_fd
    for handle in claims[1:]:
        if not _same_dir(first, handle.parent_fd):
            raise BatchRefused(f"{handle.name!r} is claimed in another directory")
    return [_loose_node(c) for c in claims]


def verify_batch(
    parent_fd: int,
    claimed_names: Sequence[str],
    store: ArchiveStore,
    archive_id: str,
    *,
    tar: TarTool,
    expected_sha256: str | None = None,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    """Verify a batch archive holds exactly ``claimed_names``, each unchanged.

    Returns ``(size, sha256)``; raises :class:`VerifyFailed`.
    """
    wanted = sorted(f"./{n}" for n in claimed_names)
    try:
        archive_fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    try:
        size, sha = digest_fd(archive_fd)
        if expected_sha256 is not None and sha != expected_sha256:
            raise VerifyFailed("archive SHA-256 differs from its record")
        os.lseek(archive_fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(archive_fd), "rb") as handle:
            names = read_member_names(handle)
        if len(names) != len(set(names)) or sorted(names) != wanted:
            raise VerifyFailed(
                f"batch member set differs ({len(names)} members, {len(wanted)} expected)"
            )
        batched_compare(parent_fd, archive_fd, wanted, tar=tar, timeout=timeout)
    finally:
        os.close(archive_fd)
    return size, sha


def pack_batch(
    claims: Sequence[Claimed],
    store: ArchiveStore,
    archive_id: str,
    *,
    tar: TarTool,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> BatchPackResult:
    """Pack claimed loose files of one directory into ``<id>.tar``; verify and fsync it.

    Raises :class:`BatchRefused` with no archive left; the claims are the
    caller's to release.
    """
    if not store.locked:
        raise BatchRefused("packing a batch needs the store lock")
    nodes = _check_claims(claims)
    parent_fd = claims[0].parent_fd
    claimed = [c.claimed_name for c in claims]
    try:
        archive_fd = store.create_archive(archive_id)
    except StoreRefused as exc:
        raise BatchRefused(str(exc)) from exc
    try:
        try:
            _create(parent_fd, claimed, archive_fd, tar=tar, timeout=timeout)
            os.fsync(archive_fd)
        finally:
            os.close(archive_fd)
        os.fsync(store.dir_fd)
        size, sha = verify_batch(parent_fd, claimed, store, archive_id, tar=tar, timeout=timeout)
        if [_loose_node(c) for c in claims] != nodes:
            raise VerifyFailed("a file changed while the batch was packed")
    except (BatchRefused, VerifyFailed, OSError) as exc:
        store.discard_unrecorded(archive_id)
        raise BatchRefused(f"batch refused: {exc}") from exc
    return BatchPackResult(
        archive_id=archive_id,
        entries=tuple(c.name for c in claims),
        kinds=tuple(n.kind for n in nodes),
        size=size,
        sha256=sha,
    )


def _create(
    parent_fd: int, claimed: Sequence[str], archive_fd: int, *, tar: TarTool, timeout: float
) -> None:
    names = b"".join(os.fsencode(f"./{n}") + b"\0" for n in claimed)
    cwd_fd = os.dup(parent_fd)
    try:
        proc = run_tar(
            tar, tar_create_args(), cwd_fd=cwd_fd, stdin=names, stdout=archive_fd, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TarDidNotRun(f"tar --create did not run: {exc}") from exc
    finally:
        os.close(cwd_fd)
    if proc.returncode != 0 or proc.stderr:
        raise VerifyFailed(
            f"tar --create failed (exit {proc.returncode}, "
            f"{len(proc.stderr.splitlines())} stderr lines)"
        )


def batch_records(
    result: BatchPackResult,
    *,
    directory: str,
    checkout: str,
    verdict: str,
    proof_ids: tuple[str, ...],
    packed_at: str,
    expires_at: str | None,
) -> tuple[ArchiveRecord, ...]:
    """One record per file of a packed batch, all naming the batch archive."""
    return tuple(
        ArchiveRecord(
            archive_id=result.archive_id,
            original_path=f"{directory}/{name}",
            checkout=checkout,
            verdict=verdict,
            proof_ids=proof_ids,
            packed_at=packed_at,
            expires_at=expires_at,
            counts={kind: 1},
            archive_size=result.size,
            sha256=result.sha256,
            skipped=(),
            restore_command=(
                f"hooks-daemon scratch-sweep restore {result.archive_id} "
                f"--entry {f'{directory}/{name}'!r}"
            ),
        )
        for name, kind in zip(result.entries, result.kinds, strict=True)
    )

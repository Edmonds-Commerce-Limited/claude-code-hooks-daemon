"""The on-disk remote-docs store (Plan 00326 Tasks 2.3/2.4).

Reading, writing, refreshing and staleness-checking the vendored tree. Kept
separate from :mod:`capture` so the pure URL/bytes logic stays testable with
no filesystem, and separate from the CLI so no hook handler ever reaches a
network or an argv parser.

The refresh short-circuit is the point of D4's raw-bytes hash: an unchanged
upstream costs one fetch and rewrites only ``fetched_at``, which is what
makes checking often actually affordable.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

from claude_code_hooks_daemon.remote_docs.capture import (
    DEFAULT_STALE_AFTER_DAYS,
    CaptureError,
    FetchFn,
    capture,
)
from claude_code_hooks_daemon.remote_docs.provenance import (
    UNREVIEWED,
    Provenance,
    ProvenanceError,
    parse_provenance,
)

logger = logging.getLogger(__name__)

_MARKDOWN_GLOB = "*.md"


class RefreshOutcome(Enum):
    """What a refresh did, so the caller can report rather than guess."""

    #: Upstream hash matched; only ``fetched_at`` moved.
    UNCHANGED = "unchanged"
    #: Upstream changed; the body was rewritten.
    UPDATED = "updated"
    #: The file carries no usable provenance, so there is nothing to refresh.
    UNREADABLE = "unreadable"
    #: The fetch itself failed.
    FAILED = "failed"


@dataclass(frozen=True)
class StoredDocument:
    """One file in the remote tree, parsed as far as it can be."""

    path: Path
    provenance: Provenance | None
    errors: tuple[ProvenanceError, ...]

    @property
    def ok(self) -> bool:
        return self.provenance is not None


def iter_document_paths(tree_root: Path) -> Iterator[Path]:
    """Every markdown file in the tree, or nothing when it does not exist."""
    if not tree_root.is_dir():
        return
    yield from sorted(tree_root.rglob(_MARKDOWN_GLOB))


def read_document(path: Path) -> StoredDocument:
    """Parse one stored document, never raising on unreadable content."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("remote doc unreadable (%s): %s", path, exc)
        return StoredDocument(
            path=path,
            provenance=None,
            errors=(ProvenanceError("file", f"could not be read as UTF-8 text: {exc}"),),
        )
    parsed = parse_provenance(content)
    return StoredDocument(path=path, provenance=parsed.provenance, errors=parsed.errors)


def list_documents(tree_root: Path) -> list[StoredDocument]:
    """Every document in the tree, parsed. A missing tree lists nothing."""
    return [read_document(path) for path in iter_document_paths(tree_root)]


def write_capture(
    tree_root: Path,
    url: str,
    *,
    fetch_fn: FetchFn,
    now: datetime | None = None,
    licence: str = UNREVIEWED,
    stale_after_days: int | None = DEFAULT_STALE_AFTER_DAYS,
) -> Path:
    """Capture ``url`` and write it into ``tree_root``.

    Returns the written path.

    Raises:
        CaptureError: propagated from :func:`capture`, plus any write failure,
            so a caller has exactly one exception type to report.
    """
    result = capture(
        url,
        fetch_fn=fetch_fn,
        now=now,
        licence=licence,
        stale_after_days=stale_after_days,
    )
    destination = tree_root / result.relative_path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(result.content, encoding="utf-8")
    except OSError as exc:
        raise CaptureError(f"could not write {destination}: {exc}") from exc
    return destination


def refresh_document(
    path: Path,
    *,
    fetch_fn: FetchFn,
    now: datetime | None = None,
) -> RefreshOutcome:
    """Re-fetch one stored document from the URL recorded inside it.

    The recorded ``source_url`` is the input, so a refresh never needs the
    caller to remember where a file came from. A matching ``source_sha256``
    means upstream is unchanged: the body is left exactly as it is and only
    ``fetched_at`` (and the recomputed ``stale_after`` window) moves.

    A human judgement already recorded on the document -- the ``licence`` --
    is carried across. Re-deriving it would silently discard a review.
    """
    stored = read_document(path)
    if stored.provenance is None:
        return RefreshOutcome.UNREADABLE

    previous = stored.provenance
    fetched_at = now or datetime.now(UTC)

    try:
        result = capture(
            previous.source_url,
            fetch_fn=fetch_fn,
            now=fetched_at,
            licence=previous.licence,
            stale_after_days=_stale_window_days(previous),
        )
    except CaptureError as exc:
        logger.debug("refresh fetch failed for %s: %s", path, exc)
        return RefreshOutcome.FAILED

    unchanged = result.source_sha256 == previous.source_sha256
    try:
        path.write_text(result.content, encoding="utf-8")
    except OSError as exc:
        logger.debug("refresh write failed for %s: %s", path, exc)
        return RefreshOutcome.FAILED

    return RefreshOutcome.UNCHANGED if unchanged else RefreshOutcome.UPDATED


def _stale_window_days(provenance: Provenance) -> int | None:
    """Re-derive the document's freshness window from its own record.

    A pinned (``never``) document stays pinned across refreshes; otherwise the
    original window length is preserved rather than reset to the default, so a
    project that widened or narrowed one keeps its choice.
    """
    if isinstance(provenance.stale_after, str):
        return None
    window = (provenance.stale_after - provenance.fetched_at.date()).days
    return window if window > 0 else DEFAULT_STALE_AFTER_DAYS


def check_staleness(tree_root: Path, *, today: date | None = None) -> list[StoredDocument]:
    """Documents needing attention: stale, or with unreadable provenance.

    A malformed document is deliberately included. Reporting a corpus as
    clean while part of it cannot be parsed would be the same
    silence-as-success failure the sweep exists to prevent.
    """
    when = today or datetime.now(UTC).date()
    flagged: list[StoredDocument] = []
    for document in list_documents(tree_root):
        if document.provenance is None or document.provenance.is_stale(when):
            flagged.append(document)
    return flagged

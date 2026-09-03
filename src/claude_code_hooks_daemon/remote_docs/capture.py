"""Capture an upstream document into the remote-docs tree (Tasks 2.1/2.2).

The canonical capture path is a RAW https fetch (D2). Plan 00326 Task 0.1
established by measurement that ``WebFetch`` returns the fast model's ANSWER
to a prompt rather than the page -- ``tool_response.result`` for a 559-byte
page was a single sentence -- so no capture route may go through it.

Network access is injected, never imported at call time: ``capture`` takes a
``fetch_fn``, which is how ``install/relay_deploy.py`` keeps its own fetching
testable and https-only. The default implementation lives in the CLI layer,
because a hook handler must never perform network I/O.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final
from urllib.parse import urlparse

from claude_code_hooks_daemon.remote_docs.provenance import (
    NEVER,
    UNREVIEWED,
    Fidelity,
)


@dataclass(frozen=True)
class FetchResult:
    """Fetched bytes, plus how the fetcher says it obtained them.

    ``source`` is the fetcher's own account (``accept-markdown``,
    ``html-fallback``, ...). It is recorded in provenance because "upstream
    served this as markdown" and "we extracted this from HTML" are
    materially different claims about how close the stored text is to the
    document.

    It deliberately does NOT raise ``fidelity``. ``agent-browser`` only
    guarantees an unchanged response body under ``--raw``, which capture does
    not use, so treating ``accept-markdown`` as verbatim would over-claim.
    """

    content: bytes
    source: str | None = None


#: Signature of the injected fetcher. Returning plain ``bytes`` stays valid;
#: a fetcher with something to say about provenance returns a FetchResult.
FetchFn = Callable[[str], "bytes | FetchResult"]

_REQUIRED_SCHEME: Final[str] = "https"
_MARKDOWN_SUFFIX: Final[str] = ".md"
_INDEX_STEM: Final[str] = "index"

#: Extensions replaced by ``.md`` rather than kept and doubled up.
_REPLACEABLE_SUFFIXES: Final[tuple[str, ...]] = (".html", ".htm", ".md", ".txt")

#: Characters kept verbatim in a path segment; everything else becomes "-".
_UNSAFE_CHARS: Final[re.Pattern[str]] = re.compile(r"[^a-zA-Z0-9._-]+")

#: Length of the short digest appended when the readable form is lossy.
_DISAMBIGUATOR_LENGTH: Final[int] = 8

#: Default freshness window when the caller names none.
DEFAULT_STALE_AFTER_DAYS: Final[int] = 90


class CaptureError(RuntimeError):
    """A capture could not be completed, with a human-readable reason."""


@dataclass(frozen=True)
class CaptureResult:
    """A captured document, ready to be written into the remote tree."""

    #: Tree-relative destination, e.g. ``example.com/docs/page.md``.
    relative_path: str
    #: Full file content: provenance frontmatter followed by the upstream body.
    content: str
    #: SHA-256 of the RAW upstream bytes (D4).
    source_sha256: str


def _require_https(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != _REQUIRED_SCHEME or not parsed.netloc:
        raise CaptureError(f"refusing a non-{_REQUIRED_SCHEME} URL: {url!r}")
    return url


def _sanitise_segment(segment: str) -> str:
    """Make one path segment filesystem-safe, never empty, never traversal."""
    cleaned = _UNSAFE_CHARS.sub("-", segment).strip("-")
    # A segment of only dots would be "." or ".." -- traversal, not a name.
    if not cleaned or set(cleaned) <= {"."}:
        return "-"
    return cleaned


def derive_relative_path(url: str) -> str:
    """Derive a stable, readable, tree-relative path for ``url``.

    Shape is ``<host>/<url path>.md``, so a vendored corpus browses like the
    sites it came from. Two properties matter more than prettiness:

    * **Deterministic** -- the same URL always derives the same path, which is
      what lets ``refresh`` find the file it captured earlier.
    * **Non-colliding where it counts** -- when the readable form would be
      lossy (a query string, or characters that had to be replaced), a short
      digest of the FULL url is appended. Without it, ``?v=1`` and ``?v=2``
      would silently overwrite each other.
    """
    _require_https(url)
    parsed = urlparse(url)

    host = _sanitise_segment(parsed.netloc.lower())
    raw_segments = [segment for segment in parsed.path.split("/") if segment]
    segments = [_sanitise_segment(segment) for segment in raw_segments]

    # An implied `index` is a faithful, unambiguous rendering, not a lossy
    # one: `/docs` derives to `docs.md` and `/docs/` to `docs/index.md`, so
    # the two cannot collide and need no disambiguator.
    lossy = False
    implied_index = False
    if not segments:
        segments = [_INDEX_STEM]
        implied_index = True
    elif parsed.path.endswith("/"):
        segments.append(_INDEX_STEM)
        implied_index = True

    stem = segments[-1]
    for suffix in _REPLACEABLE_SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)] or _INDEX_STEM
            break
    segments[-1] = stem

    # Lossy whenever the readable form threw information away.
    if parsed.query or parsed.fragment:
        lossy = True
    if segments[:-1] != raw_segments[: len(segments) - 1]:
        lossy = True
    if raw_segments and not implied_index and stem != raw_segments[-1]:
        # A replaced extension is expected, not lossy; a sanitised name is.
        expected = raw_segments[-1]
        for suffix in _REPLACEABLE_SUFFIXES:
            if expected.lower().endswith(suffix):
                expected = expected[: -len(suffix)] or _INDEX_STEM
                break
        if stem != expected:
            lossy = True

    if lossy:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:_DISAMBIGUATOR_LENGTH]
        segments[-1] = f"{segments[-1]}-{digest}"

    return "/".join([host, *segments]) + _MARKDOWN_SUFFIX


def _render_frontmatter(
    *,
    source_url: str,
    fetched_at: datetime,
    source_sha256: str,
    licence: str,
    stale_after: date | str,
    fidelity: Fidelity,
    fetch_method: str | None,
) -> str:
    stale = stale_after if isinstance(stale_after, str) else stale_after.isoformat()
    # Omitted rather than written empty when unknown: an absent optional field
    # parses cleanly, whereas `fetch_method:` with no value does not.
    method_line = f"fetch_method: {fetch_method}\n" if fetch_method else ""
    return (
        "---\n"
        f"source_url: {source_url}\n"
        f"fetched_at: {fetched_at.isoformat()}\n"
        f"fidelity: {fidelity.value}\n"
        f"source_sha256: {source_sha256}\n"
        f"licence: {licence}\n"
        f"stale_after: {stale}\n"
        f"{method_line}"
        "---\n\n"
    )


def capture(
    url: str,
    *,
    fetch_fn: FetchFn,
    now: datetime | None = None,
    licence: str = UNREVIEWED,
    stale_after_days: int | None = DEFAULT_STALE_AFTER_DAYS,
    fidelity: Fidelity = Fidelity.VERBATIM,
    fetch_method: str | None = None,
) -> CaptureResult:
    """Fetch ``url`` and render it as a provenance-bearing document.

    ``stale_after_days`` of ``None`` records the :data:`NEVER` sentinel, for a
    deliberately frozen archival snapshot (D6).

    ``fidelity`` defaults to verbatim because the default ``fetch_fn`` is a raw
    fetch, but a fetcher that RENDERS or rewords must pass its own lower claim
    -- nothing here may assert verbatim on another component's behalf (D3).

    Raises:
        CaptureError: the URL is not https, the fetch failed, or the response
            was not decodable text. Every failure is this one type, because
            the caller is a CLI that must report a reason rather than a
            traceback.
    """
    _require_https(url)
    fetched_at = now or datetime.now(UTC)

    try:
        fetched = fetch_fn(url)
    except CaptureError:
        raise
    except (OSError, ValueError) as exc:
        raise CaptureError(f"fetch failed for {url}: {exc}") from exc

    # A fetcher may return plain bytes or a FetchResult; normalise so the
    # older contract keeps working at every existing call site.
    normalised = fetched if isinstance(fetched, FetchResult) else FetchResult(content=fetched)
    raw: bytes = normalised.content
    if normalised.source and fetch_method:
        fetch_method = f"{fetch_method} ({normalised.source})"

    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaptureError(
            f"{url} did not return decodable UTF-8 text; only text documents "
            "can be vendored as markdown"
        ) from exc

    stale_after: date | str = (
        NEVER if stale_after_days is None else (fetched_at.date() + timedelta(days=stale_after_days))
    )
    digest = hashlib.sha256(raw).hexdigest()

    frontmatter = _render_frontmatter(
        source_url=url,
        fetched_at=fetched_at,
        source_sha256=digest,
        licence=licence,
        stale_after=stale_after,
        fidelity=fidelity,
        fetch_method=fetch_method,
    )

    return CaptureResult(
        relative_path=derive_relative_path(url),
        content=frontmatter + body,
        source_sha256=digest,
    )

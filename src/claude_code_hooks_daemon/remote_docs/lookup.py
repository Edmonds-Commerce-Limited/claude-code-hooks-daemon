"""Finding the vendored copy of a URL (Plan 00326 Task 5.1).

A corpus nobody is routed to is a corpus nobody reads. This is the lookup
that lets a handler answer "do we already have this page?" before an agent
fetches it.

The lookup has to tolerate the small spelling differences between the URL
someone captured and the one someone later fetches -- a trailing slash, a
``#section`` anchor, a campaign tag, an upper-case host -- without being
over-eager in the other direction. A query string can be load-bearing
(``?version=3`` is a different page), so only KNOWN tracking parameters are
dropped, never the query wholesale.

Both sides are normalised: the stored ``source_url`` as well as the one
being looked up. Normalising only the query would mean a corpus captured
with decorated URLs never routes anyone.
"""

import logging
from pathlib import Path
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from claude_code_hooks_daemon.remote_docs.store import (
    StoredDocument,
    iter_document_paths,
    read_document,
)

logger = logging.getLogger(__name__)

# Campaign and referral tags only. Anything that could select CONTENT stays,
# because dropping it would route an agent to the wrong document -- a worse
# failure than not routing them at all.
_TRACKING_PREFIXES: Final[tuple[str, ...]] = ("utm_",)
_TRACKING_PARAMS: Final[frozenset[str]] = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref",
        "ref_src",
        "s_kwcid",
        "yclid",
    }
)
_DEFAULT_PORTS: Final[dict[str, str]] = {"https": "443", "http": "80"}


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_PARAMS or lowered.startswith(_TRACKING_PREFIXES)


def normalise_url(url: str) -> str:
    """A canonical spelling of ``url`` for identity comparison.

    Lowercases scheme and host, drops a default port, drops the fragment,
    drops known tracking parameters, sorts the remaining query, and strips a
    trailing slash from a non-root path.

    Never raises: the caller is a hook running on someone's fetch, and a
    malformed URL must not crash it. An unparseable value is returned
    unchanged, so it simply fails to match anything.
    """
    try:
        split = urlsplit(url)
        if not split.scheme or not split.netloc:
            return url

        host = (split.hostname or "").lower()
        port = split.port
        if port is not None and str(port) != _DEFAULT_PORTS.get(split.scheme.lower()):
            host = f"{host}:{port}"

        query = urlencode(
            sorted(pair for pair in parse_qsl(split.query, keep_blank_values=True) if not _is_tracking(pair[0]))
        )

        path = split.path
        if path.endswith("/") and path != "/":
            path = path.rstrip("/")

        return urlunsplit((split.scheme.lower(), host, path, query, ""))
    except ValueError as exc:
        # urlsplit raises on a malformed port, e.g. `https://host:notaport/`.
        logger.debug("could not normalise URL %r: %s", url, exc)
        return url


def find_document(tree_root: Path, url: str) -> StoredDocument | None:
    """The stored document captured from ``url``, or None.

    Compares normalised URLs rather than derived paths: the path derivation
    is lossy by design (it appends a digest for query strings), so two URLs
    that should match can derive different paths, and a stored document's
    own recorded ``source_url`` is the authoritative answer to "where did
    this come from?".

    An unreadable document is skipped rather than aborting the search -- one
    bad file must not hide every good one behind it.
    """
    target = normalise_url(url)
    for path in iter_document_paths(tree_root):
        document = read_document(path)
        if document.provenance is None:
            continue
        if normalise_url(document.provenance.source_url) == target:
            return document
    return None

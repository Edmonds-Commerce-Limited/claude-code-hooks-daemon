"""Provenance frontmatter for vendored remote documents (Plan 00326 Tasks 1.1/1.2).

Every document in the remote tree carries YAML frontmatter recording where it
came from, when it was captured, the hash of the RAW upstream bytes, and --
the field a naive schema omits -- its ``fidelity``: whether the stored bytes
are the upstream document or a paraphrase of it (D2/D3).

The ``fidelity`` distinction is not decorative. A summarising fetch layer
fabricated contract detail in this repository during the Plan 00271 audit,
and Plan 00326 Task 0.1 later confirmed by capture that ``WebFetch`` returns
a model's ANSWER rather than the page. A document marked ``summarised`` is a
lead, never a citation.

Parsing NEVER raises: :func:`parse_provenance` returns a :class:`ParseResult`
carrying either a :class:`Provenance` or a tuple of :class:`ProvenanceError`.
The callers are hook handlers, where an escaping exception would take down the
gate rather than report a bad document.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final
from urllib.parse import urlparse

import yaml

from claude_code_hooks_daemon.utils.markdown_format import split_frontmatter

#: Licence sentinel: capture happened, licence review did not (D13). Parses
#: cleanly so capture is never blocked, but is reportable so the debt is
#: visible rather than silent.
UNREVIEWED: Final[str] = "unreviewed"

#: ``stale_after`` sentinel for a deliberately frozen archival snapshot (D6).
NEVER: Final[str] = "never"

#: A hex SHA-256 digest: exactly 64 hex characters.
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{64}\Z", re.IGNORECASE)

#: Only https is a legitimate provenance source; see ``install/relay_deploy``
#: for the same scheme restriction on the fetching side.
_REQUIRED_SCHEME: Final[str] = "https"

_FIELD_FRONTMATTER: Final[str] = "frontmatter"
_FIELD_SOURCE_URL: Final[str] = "source_url"
_FIELD_FETCHED_AT: Final[str] = "fetched_at"
_FIELD_FIDELITY: Final[str] = "fidelity"
_FIELD_SOURCE_SHA256: Final[str] = "source_sha256"
_FIELD_LICENCE: Final[str] = "licence"
_FIELD_STALE_AFTER: Final[str] = "stale_after"

_OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "upstream_version",
    "fetch_method",
    "retrieved_by",
)


class Fidelity(StrEnum):
    """How faithfully the stored markdown represents the upstream document."""

    #: Byte-equivalent to the upstream source (modulo encoding).
    VERBATIM = "verbatim"
    #: Format-converted (HTML to markdown) but not reworded.
    CONVERTED = "converted"
    #: Passed through a model. A lead, never a citation.
    SUMMARISED = "summarised"


@dataclass(frozen=True)
class ProvenanceError:
    """One rejected field and why, addressed to whoever must fix the file."""

    field: str
    message: str


@dataclass(frozen=True)
class Provenance:
    """Validated provenance for one vendored document."""

    source_url: str
    fetched_at: datetime
    fidelity: Fidelity
    source_sha256: str
    licence: str
    #: A date, or the literal :data:`NEVER` for a frozen snapshot.
    stale_after: date | str
    upstream_version: str | None = None
    fetch_method: str | None = None
    retrieved_by: str | None = None

    @property
    def licence_is_unreviewed(self) -> bool:
        """Whether the licence is the :data:`UNREVIEWED` sentinel (D13)."""
        return self.licence == UNREVIEWED

    def is_stale(self, today: date) -> bool:
        """Whether this document has passed its ``stale_after`` date.

        Inclusive on the named day: a document whose ``stale_after`` is today
        is still good, and expires the following day. :data:`NEVER` is never
        stale.
        """
        if isinstance(self.stale_after, str):
            return False
        return today > self.stale_after


@dataclass(frozen=True)
class ParseResult:
    """Outcome of parsing a document: a Provenance, or the reasons there isn't one."""

    provenance: Provenance | None
    errors: tuple[ProvenanceError, ...]
    #: The document body with frontmatter removed (empty when unparseable).
    body: str = ""

    @property
    def ok(self) -> bool:
        """Whether the document carried valid provenance."""
        return self.provenance is not None


def _load_frontmatter(content: str) -> tuple[dict[str, Any] | None, ProvenanceError | None, str]:
    """Split and YAML-parse the frontmatter block, never raising."""
    block, body = split_frontmatter(content)
    if not block:
        return (
            None,
            ProvenanceError(
                _FIELD_FRONTMATTER,
                "no YAML frontmatter found; a remote document must open with a "
                "--- delimited provenance block",
            ),
            "",
        )
    # Strip the two --- delimiter lines; split_frontmatter returns them.
    inner = block.split("\n", 1)[1].rsplit("---", 1)[0]
    try:
        loaded = yaml.safe_load(inner)
    except yaml.YAMLError as exc:
        return (
            None,
            ProvenanceError(_FIELD_FRONTMATTER, f"frontmatter is not valid YAML: {exc}"),
            "",
        )
    if not isinstance(loaded, dict):
        return (
            None,
            ProvenanceError(
                _FIELD_FRONTMATTER, "frontmatter must be a mapping of field names to values"
            ),
            "",
        )
    return loaded, None, body


def _require_str(data: dict[str, Any], field: str) -> tuple[str | None, ProvenanceError | None]:
    """Read a required field as a non-empty string."""
    raw = data.get(field)
    if raw is None:
        return None, ProvenanceError(field, f"required field `{field}` is missing")
    text = str(raw).strip()
    if not text:
        return None, ProvenanceError(field, f"required field `{field}` is empty")
    return text, None


def _parse_source_url(text: str) -> tuple[str | None, ProvenanceError | None]:
    parsed = urlparse(text)
    if parsed.scheme != _REQUIRED_SCHEME or not parsed.netloc:
        return None, ProvenanceError(
            _FIELD_SOURCE_URL,
            f"`{_FIELD_SOURCE_URL}` must be an absolute {_REQUIRED_SCHEME}:// URL",
        )
    return text, None


def _parse_fetched_at(text: str) -> tuple[datetime | None, ProvenanceError | None]:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, ProvenanceError(
            _FIELD_FETCHED_AT, f"`{_FIELD_FETCHED_AT}` must be an ISO 8601 timestamp"
        )
    if parsed.tzinfo is None:
        return None, ProvenanceError(
            _FIELD_FETCHED_AT,
            f"`{_FIELD_FETCHED_AT}` must carry a UTC offset; a naive timestamp is "
            "ambiguous across machines",
        )
    return parsed, None


def _parse_fidelity(text: str) -> tuple[Fidelity | None, ProvenanceError | None]:
    try:
        return Fidelity(text.lower()), None
    except ValueError:
        allowed = ", ".join(item.value for item in Fidelity)
        return None, ProvenanceError(
            _FIELD_FIDELITY, f"`{_FIELD_FIDELITY}` must be one of: {allowed}"
        )


def _parse_sha256(text: str) -> tuple[str | None, ProvenanceError | None]:
    if _SHA256_RE.match(text) is None:
        return None, ProvenanceError(
            _FIELD_SOURCE_SHA256,
            f"`{_FIELD_SOURCE_SHA256}` must be 64 hex characters (a SHA-256 of "
            "the RAW upstream bytes)",
        )
    return text.lower(), None


def _parse_stale_after(text: str) -> tuple[date | str | None, ProvenanceError | None]:
    if text.lower() == NEVER:
        return NEVER, None
    try:
        return date.fromisoformat(text), None
    except ValueError:
        return None, ProvenanceError(
            _FIELD_STALE_AFTER,
            f"`{_FIELD_STALE_AFTER}` must be an ISO date (YYYY-MM-DD) or `{NEVER}`",
        )


def parse_provenance(content: str) -> ParseResult:
    """Parse a vendored document's provenance frontmatter.

    Reports EVERY invalid field rather than stopping at the first: fixing a
    bad capture one error per run would be a slog, and the caller renders the
    whole list in a single deny message.
    """
    data, structural_error, body = _load_frontmatter(content)
    if data is None:
        assert structural_error is not None
        return ParseResult(provenance=None, errors=(structural_error,))

    errors: list[ProvenanceError] = []

    url_text, err = _require_str(data, _FIELD_SOURCE_URL)
    source_url = None
    if err is not None:
        errors.append(err)
    else:
        assert url_text is not None
        source_url, err = _parse_source_url(url_text)
        if err is not None:
            errors.append(err)

    fetched_text, err = _require_str(data, _FIELD_FETCHED_AT)
    fetched_at = None
    if err is not None:
        errors.append(err)
    else:
        assert fetched_text is not None
        fetched_at, err = _parse_fetched_at(fetched_text)
        if err is not None:
            errors.append(err)

    fidelity_text, err = _require_str(data, _FIELD_FIDELITY)
    fidelity = None
    if err is not None:
        errors.append(err)
    else:
        assert fidelity_text is not None
        fidelity, err = _parse_fidelity(fidelity_text)
        if err is not None:
            errors.append(err)

    sha_text, err = _require_str(data, _FIELD_SOURCE_SHA256)
    source_sha256 = None
    if err is not None:
        errors.append(err)
    else:
        assert sha_text is not None
        source_sha256, err = _parse_sha256(sha_text)
        if err is not None:
            errors.append(err)

    licence, err = _require_str(data, _FIELD_LICENCE)
    if err is not None:
        errors.append(err)

    stale_text, err = _require_str(data, _FIELD_STALE_AFTER)
    stale_after: date | str | None = None
    if err is not None:
        errors.append(err)
    else:
        assert stale_text is not None
        stale_after, err = _parse_stale_after(stale_text)
        if err is not None:
            errors.append(err)

    if errors:
        return ParseResult(provenance=None, errors=tuple(errors), body=body)

    assert source_url is not None
    assert fetched_at is not None
    assert fidelity is not None
    assert source_sha256 is not None
    assert licence is not None
    assert stale_after is not None

    optional = {name: _optional_str(data, name) for name in _OPTIONAL_FIELDS}
    return ParseResult(
        provenance=Provenance(
            source_url=source_url,
            fetched_at=fetched_at,
            fidelity=fidelity,
            source_sha256=source_sha256,
            licence=licence,
            stale_after=stale_after,
            **optional,
        ),
        errors=(),
        body=body,
    )


def _optional_str(data: dict[str, Any], field: str) -> str | None:
    """Read an optional field, treating blank as absent."""
    raw = data.get(field)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None

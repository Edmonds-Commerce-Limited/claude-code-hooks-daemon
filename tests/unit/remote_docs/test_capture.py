"""URL-to-path derivation and raw capture (Plan 00326 Tasks 2.1/2.2).

D2: the canonical capture path is a RAW fetch. Task 0.1 confirmed by
measurement that `WebFetch` hands back the fast model's answer to a prompt
rather than the page, so nothing here may route through it.

The network is never touched in tests -- `capture()` takes an injected
`fetch_fn`, mirroring `install/relay_deploy.py`'s testability pattern.
"""

import hashlib
from datetime import UTC, date, datetime

import pytest

from claude_code_hooks_daemon.remote_docs.capture import (
    CaptureError,
    capture,
    derive_relative_path,
)
from claude_code_hooks_daemon.remote_docs.provenance import (
    UNREVIEWED,
    Fidelity,
    parse_provenance,
)

_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


class TestDerivePath:
    def test_host_becomes_the_first_segment(self) -> None:
        assert derive_relative_path("https://example.com/docs/page").startswith("example.com/")

    def test_path_is_preserved_and_suffixed_with_md(self) -> None:
        assert derive_relative_path("https://example.com/docs/page") == "example.com/docs/page.md"

    def test_bare_host_becomes_index(self) -> None:
        assert derive_relative_path("https://example.com") == "example.com/index.md"

    def test_trailing_slash_becomes_index(self) -> None:
        assert derive_relative_path("https://example.com/docs/") == "example.com/docs/index.md"

    def test_html_extension_is_replaced_not_doubled(self) -> None:
        assert derive_relative_path("https://example.com/a/b.html") == "example.com/a/b.md"

    def test_derivation_is_deterministic(self) -> None:
        url = "https://example.com/docs/page"

        assert derive_relative_path(url) == derive_relative_path(url)

    def test_unsafe_characters_are_sanitised(self) -> None:
        result = derive_relative_path("https://example.com/a b/c:d")

        assert " " not in result
        assert ":" not in result

    def test_urls_differing_only_by_query_do_not_collide(self) -> None:
        """A query string carries meaning; dropping it would overwrite."""
        a = derive_relative_path("https://example.com/p?v=1")
        b = derive_relative_path("https://example.com/p?v=2")

        assert a != b

    def test_path_traversal_cannot_escape_the_tree(self) -> None:
        result = derive_relative_path("https://example.com/../../etc/passwd")

        assert ".." not in result.split("/")

    def test_non_https_url_is_rejected(self) -> None:
        with pytest.raises(CaptureError):
            derive_relative_path("http://example.com/p")


class TestCapture:
    def _fetch(self, body: bytes):
        def fetch_fn(url: str) -> bytes:
            return body

        return fetch_fn

    def test_captured_document_carries_valid_provenance(self) -> None:
        result = capture(
            "https://example.com/docs/page",
            fetch_fn=self._fetch(b"# Upstream\n\nBody.\n"),
            now=_NOW,
        )

        parsed = parse_provenance(result.content)
        assert parsed.errors == ()
        assert parsed.provenance is not None

    def test_source_url_and_fetched_at_are_recorded(self) -> None:
        result = capture(
            "https://example.com/docs/page",
            fetch_fn=self._fetch(b"# Upstream\n"),
            now=_NOW,
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.source_url == "https://example.com/docs/page"
        assert provenance.fetched_at == _NOW

    def test_hash_is_of_the_RAW_bytes_not_the_written_file(self) -> None:
        """D4: the hash must answer "did UPSTREAM change?".

        Hashing the written file would fold our own frontmatter into the
        digest, so every refresh would look like an upstream change and the
        cheap no-op path would never fire.
        """
        body = b"# Upstream\n\nBody.\n"
        result = capture("https://example.com/p", fetch_fn=self._fetch(body), now=_NOW)

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.source_sha256 == hashlib.sha256(body).hexdigest()

    def test_raw_capture_is_recorded_as_verbatim(self) -> None:
        result = capture("https://example.com/p", fetch_fn=self._fetch(b"# X\n"), now=_NOW)

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fidelity is Fidelity.VERBATIM

    def test_licence_defaults_to_the_unreviewed_sentinel(self) -> None:
        """D13: capture is never blocked on a licence decision, but the
        absence of one is recorded rather than left blank."""
        result = capture("https://example.com/p", fetch_fn=self._fetch(b"# X\n"), now=_NOW)

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.licence == UNREVIEWED

    def test_declared_licence_is_used_when_given(self) -> None:
        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(b"# X\n"),
            now=_NOW,
            licence="CC-BY-4.0",
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.licence == "CC-BY-4.0"

    def test_stale_after_is_computed_from_the_ttl(self) -> None:
        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(b"# X\n"),
            now=_NOW,
            stale_after_days=30,
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.stale_after == date(2026, 10, 3)

    def test_upstream_body_is_preserved_verbatim(self) -> None:
        body = b"# Upstream\n\nExact wording matters.\n"
        result = capture("https://example.com/p", fetch_fn=self._fetch(body), now=_NOW)

        assert body.decode() in result.content

    def test_relative_path_is_derived_from_the_url(self) -> None:
        result = capture(
            "https://example.com/docs/page", fetch_fn=self._fetch(b"# X\n"), now=_NOW
        )

        assert result.relative_path == "example.com/docs/page.md"

    def test_a_fetch_failure_is_raised_as_captureerror(self) -> None:
        def boom(url: str) -> bytes:
            raise OSError("network down")

        with pytest.raises(CaptureError):
            capture("https://example.com/p", fetch_fn=boom, now=_NOW)

    def test_undecodable_bytes_are_reported_not_crashed(self) -> None:
        with pytest.raises(CaptureError):
            capture(
                "https://example.com/p",
                fetch_fn=self._fetch(b"\xff\xfe\x00binary"),
                now=_NOW,
            )


class TestReportedSource:
    """A fetcher may report HOW it got the text; that belongs in provenance.

    `accept-markdown` (upstream served markdown) and `html-fallback` (we
    extracted it from HTML) are materially different claims about how close
    the stored text is to the document — but NOT different enough to change
    `fidelity`, because without `--raw` the content is still normalised.
    Recording it preserves the distinction without over-claiming on it.
    """

    def _fetch(self, result):
        def fetch_fn(url: str):
            return result

        return fetch_fn

    def test_a_plain_bytes_fetcher_still_works(self) -> None:
        """The contract stays backwards-compatible: bytes remain valid."""
        result = capture("https://example.com/p", fetch_fn=self._fetch(b"# X\n"), now=_NOW)

        assert "# X" in result.content

    def test_a_reported_source_is_recorded_alongside_the_method(self) -> None:
        from claude_code_hooks_daemon.remote_docs.capture import FetchResult

        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(FetchResult(content=b"# X\n", source="accept-markdown")),
            now=_NOW,
            fetch_method="agent-browser",
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fetch_method == "agent-browser (accept-markdown)"

    def test_a_reported_source_does_not_upgrade_fidelity(self) -> None:
        """Upstream serving markdown does not make OUR copy the response body.

        agent-browser only guarantees an unchanged body under `--raw`, which
        capture does not use, so claiming verbatim here would over-claim on
        one observation.
        """
        from claude_code_hooks_daemon.remote_docs.capture import FetchResult

        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(FetchResult(content=b"# X\n", source="accept-markdown")),
            now=_NOW,
            fidelity=Fidelity.CONVERTED,
            fetch_method="agent-browser",
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fidelity is Fidelity.CONVERTED

    def test_the_hash_is_of_the_returned_content(self) -> None:
        from claude_code_hooks_daemon.remote_docs.capture import FetchResult

        body = b"# X\n"
        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(FetchResult(content=body, source="html-fallback")),
            now=_NOW,
        )

        assert result.source_sha256 == hashlib.sha256(body).hexdigest()

    def test_no_source_leaves_the_method_unadorned(self) -> None:
        from claude_code_hooks_daemon.remote_docs.capture import FetchResult

        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(FetchResult(content=b"# X\n", source=None)),
            now=_NOW,
            fetch_method="https-get",
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fetch_method == "https-get"


class TestDeclaredFidelity:
    """The fetcher declares its own claim; capture must not overwrite it.

    A browser-rendered capture is a markdown rendering of the DOM, not the
    upstream bytes. Recording it as ``verbatim`` would make a paraphrase
    citable, which is the exact failure the field exists to prevent (D3).
    """

    def _fetch(self, body: bytes):
        def fetch_fn(url: str) -> bytes:
            return body

        return fetch_fn

    def test_a_raw_fetch_still_defaults_to_verbatim(self) -> None:
        result = capture("https://example.com/p", fetch_fn=self._fetch(b"# X\n"), now=_NOW)

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fidelity is Fidelity.VERBATIM

    def test_a_declared_conversion_is_recorded_as_converted(self) -> None:
        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(b"# X\n"),
            now=_NOW,
            fidelity=Fidelity.CONVERTED,
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fidelity is Fidelity.CONVERTED

    def test_the_fetch_method_is_recorded_when_given(self) -> None:
        """Which tool produced the bytes changes how much the hash means."""
        result = capture(
            "https://example.com/p",
            fetch_fn=self._fetch(b"# X\n"),
            now=_NOW,
            fidelity=Fidelity.CONVERTED,
            fetch_method="agent-browser",
        )

        provenance = parse_provenance(result.content).provenance
        assert provenance is not None
        assert provenance.fetch_method == "agent-browser"

    def test_no_fetch_method_line_is_emitted_when_unknown(self) -> None:
        result = capture("https://example.com/p", fetch_fn=self._fetch(b"# X\n"), now=_NOW)

        assert "fetch_method:" not in result.content

"""Finding the vendored copy of a URL (Plan 00326 Task 5.1).

The corpus is only worth building if an agent about to fetch a URL is routed
to the local copy instead. That routing is a LOOKUP, and the lookup has to
tolerate the small spelling differences between the URL someone captured and
the URL someone later fetches: a trailing slash, a `#section` anchor, a
`?utm_source=` campaign tag, an upper-case host.

Normalisation must not be over-eager in the other direction. A query string
can be load-bearing (`?version=3` is a different page), so only KNOWN
tracking parameters are dropped -- never the query wholesale.
"""

from datetime import UTC, datetime
from pathlib import Path

from claude_code_hooks_daemon.remote_docs.lookup import find_document, normalise_url
from claude_code_hooks_daemon.remote_docs.store import write_capture

_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def _fetch(body: bytes = b"# Upstream\n"):
    def fetch_fn(url: str) -> bytes:
        return body

    return fetch_fn


def _seed(tree: Path, url: str) -> Path:
    return write_capture(tree, url, fetch_fn=_fetch(), now=_NOW)


class TestNormalise:
    def test_the_host_is_lowercased(self) -> None:
        assert normalise_url("https://Example.COM/docs") == "https://example.com/docs"

    def test_a_fragment_is_dropped(self) -> None:
        """An anchor selects part of the same document."""
        assert normalise_url("https://example.com/docs#install") == "https://example.com/docs"

    def test_a_trailing_slash_is_dropped(self) -> None:
        assert normalise_url("https://example.com/docs/") == "https://example.com/docs"

    def test_the_root_path_stays_addressable(self) -> None:
        """Stripping the root slash would leave a host with no path at all."""
        assert normalise_url("https://example.com/") == "https://example.com/"

    def test_known_tracking_parameters_are_dropped(self) -> None:
        assert (
            normalise_url("https://example.com/docs?utm_source=x&utm_campaign=y")
            == "https://example.com/docs"
        )

    def test_a_meaningful_query_is_preserved(self) -> None:
        """`?version=3` is a different page, not a decorated one."""
        assert (
            normalise_url("https://example.com/docs?version=3")
            == "https://example.com/docs?version=3"
        )

    def test_tracking_is_stripped_without_losing_the_rest(self) -> None:
        assert (
            normalise_url("https://example.com/d?version=3&utm_source=x")
            == "https://example.com/d?version=3"
        )

    def test_query_order_does_not_change_identity(self) -> None:
        assert normalise_url("https://example.com/d?b=2&a=1") == normalise_url(
            "https://example.com/d?a=1&b=2"
        )

    def test_a_default_port_is_dropped(self) -> None:
        assert normalise_url("https://example.com:443/docs") == "https://example.com/docs"

    def test_a_non_default_port_is_kept(self) -> None:
        assert normalise_url("https://example.com:8443/docs") == "https://example.com:8443/docs"

    def test_a_malformed_url_is_returned_unchanged_rather_than_raising(self) -> None:
        """The caller is a hook on someone's fetch; it must never crash it."""
        assert normalise_url("not a url") == "not a url"


class TestFind:
    def test_an_exact_url_is_found(self, tmp_path: Path) -> None:
        written = _seed(tmp_path, "https://example.com/docs/page")

        found = find_document(tmp_path, "https://example.com/docs/page")

        assert found is not None
        assert found.path == written

    def test_a_url_that_was_never_captured_is_not_found(self, tmp_path: Path) -> None:
        _seed(tmp_path, "https://example.com/docs/page")

        assert find_document(tmp_path, "https://example.com/other") is None

    def test_a_missing_tree_finds_nothing(self, tmp_path: Path) -> None:
        assert find_document(tmp_path / "absent", "https://example.com/p") is None

    def test_a_fragment_still_finds_the_document(self, tmp_path: Path) -> None:
        _seed(tmp_path, "https://example.com/docs/page")

        assert find_document(tmp_path, "https://example.com/docs/page#install") is not None

    def test_a_tracking_parameter_still_finds_the_document(self, tmp_path: Path) -> None:
        _seed(tmp_path, "https://example.com/docs/page")

        found = find_document(tmp_path, "https://example.com/docs/page?utm_source=newsletter")

        assert found is not None

    def test_host_case_does_not_matter(self, tmp_path: Path) -> None:
        _seed(tmp_path, "https://example.com/docs/page")

        assert find_document(tmp_path, "https://EXAMPLE.com/docs/page") is not None

    def test_a_document_captured_with_a_decorated_url_is_still_found(self, tmp_path: Path) -> None:
        """Normalisation applies to the STORED url too, not just the query.

        Capturing `...page#install` and later fetching the bare URL must
        match: otherwise a corpus captured sloppily never routes anyone.
        """
        _seed(tmp_path, "https://example.com/docs/page#install")

        assert find_document(tmp_path, "https://example.com/docs/page") is not None

    def test_an_unreadable_document_does_not_break_the_search(self, tmp_path: Path) -> None:
        """One bad file must not hide every good one behind it."""
        bad = tmp_path / "example.com" / "bad.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("# no frontmatter\n", encoding="utf-8")
        _seed(tmp_path, "https://example.com/docs/page")

        assert find_document(tmp_path, "https://example.com/docs/page") is not None

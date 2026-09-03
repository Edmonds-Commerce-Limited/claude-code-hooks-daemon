"""The on-disk remote-docs store: write, refresh, list, check (Tasks 2.3/2.4).

The refresh short-circuit is the load-bearing behaviour here. D4 records the
hash of the RAW upstream bytes precisely so "did it actually change?" costs
one fetch and no rewrite -- the same trick the hand-rolled
`HOOK-CONTRACT-REFRESH.md` procedure already relies on at step 2.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from claude_code_hooks_daemon.remote_docs.capture import CaptureError
from claude_code_hooks_daemon.remote_docs.store import (
    RefreshOutcome,
    check_staleness,
    list_documents,
    refresh_document,
    write_capture,
)

_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
_LATER = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
_BODY = b"# Upstream\n\nBody.\n"


def _fetch(body: bytes):
    def fetch_fn(url: str) -> bytes:
        return body

    return fetch_fn


def _seed(root: Path, body: bytes = _BODY) -> Path:
    return write_capture(
        root,
        "https://example.com/docs/page",
        fetch_fn=_fetch(body),
        now=_NOW,
    )


class TestWrite:
    def test_writes_under_the_derived_path(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        assert written == tmp_path / "example.com" / "docs" / "page.md"
        assert written.is_file()

    def test_creates_missing_parent_directories(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        assert written.parent.is_dir()

    def test_written_content_round_trips_through_the_parser(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        documents = list_documents(tmp_path)
        assert [doc.path for doc in documents] == [written]
        assert documents[0].provenance is not None


class TestContentGuard:
    """Task 2.5: a capture writes from a CLI, bypassing the Write-tool hook.

    Without a guard here, fetching an authenticated page would vendor its
    secrets into the repository with no check at all.
    """

    def test_a_rejected_capture_writes_nothing(self, tmp_path: Path) -> None:
        def reject(content: str) -> str | None:
            return "matches the sensitive-content pattern `aws-key`"

        try:
            write_capture(
                tmp_path,
                "https://example.com/p",
                fetch_fn=_fetch(_BODY),
                now=_NOW,
                content_guard=reject,
            )
        except CaptureError as exc:
            assert "aws-key" in str(exc)
        else:
            raise AssertionError("a rejected capture should raise")

        assert list(tmp_path.rglob("*.md")) == []

    def test_a_clean_capture_passes_the_guard(self, tmp_path: Path) -> None:
        def allow(content: str) -> str | None:
            return None

        written = write_capture(
            tmp_path,
            "https://example.com/p",
            fetch_fn=_fetch(_BODY),
            now=_NOW,
            content_guard=allow,
        )

        assert written.is_file()

    def test_the_guard_sees_the_upstream_body(self, tmp_path: Path) -> None:
        seen: list[str] = []

        def record(content: str) -> str | None:
            seen.append(content)
            return None

        write_capture(
            tmp_path,
            "https://example.com/p",
            fetch_fn=_fetch(b"# Upstream\n\nsecret-ish payload\n"),
            now=_NOW,
            content_guard=record,
        )

        assert "secret-ish payload" in seen[0]


class TestRefresh:
    def test_unchanged_upstream_is_a_no_op_beyond_fetched_at(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)
        before = written.read_text()

        outcome = refresh_document(written, fetch_fn=_fetch(_BODY), now=_LATER)

        assert outcome is RefreshOutcome.UNCHANGED
        after = written.read_text()
        assert after != before  # fetched_at moved
        assert "Body." in after

    def test_unchanged_refresh_moves_fetched_at_forward(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        refresh_document(written, fetch_fn=_fetch(_BODY), now=_LATER)

        documents = list_documents(tmp_path)
        provenance = documents[0].provenance
        assert provenance is not None
        assert provenance.fetched_at == _LATER

    def test_changed_upstream_rewrites_the_body(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        outcome = refresh_document(
            written, fetch_fn=_fetch(b"# Upstream\n\nRewritten.\n"), now=_LATER
        )

        assert outcome is RefreshOutcome.UPDATED
        assert "Rewritten." in written.read_text()

    def test_refresh_reuses_the_recorded_source_url(self, tmp_path: Path) -> None:
        """Refresh must not need the URL passed in again -- it is in the file."""
        written = _seed(tmp_path)
        seen: list[str] = []

        def recording_fetch(url: str) -> bytes:
            seen.append(url)
            return _BODY

        refresh_document(written, fetch_fn=recording_fetch, now=_LATER)

        assert seen == ["https://example.com/docs/page"]

    def test_refresh_preserves_a_declared_licence(self, tmp_path: Path) -> None:
        """A licence is a human judgement; a refresh must not discard it."""
        written = write_capture(
            tmp_path,
            "https://example.com/p",
            fetch_fn=_fetch(_BODY),
            now=_NOW,
            licence="CC-BY-4.0",
        )

        refresh_document(written, fetch_fn=_fetch(b"# New\n"), now=_LATER)

        provenance = list_documents(tmp_path)[0].provenance
        assert provenance is not None
        assert provenance.licence == "CC-BY-4.0"

    def test_refreshing_a_document_without_provenance_is_reported(self, tmp_path: Path) -> None:
        orphan = tmp_path / "example.com" / "hand-written.md"
        orphan.parent.mkdir(parents=True)
        orphan.write_text("# No frontmatter here\n")

        outcome = refresh_document(orphan, fetch_fn=_fetch(_BODY), now=_LATER)

        assert outcome is RefreshOutcome.UNREADABLE


class TestListAndCheck:
    def test_empty_tree_lists_nothing(self, tmp_path: Path) -> None:
        assert list_documents(tmp_path) == []

    def test_missing_tree_is_not_an_error(self, tmp_path: Path) -> None:
        assert list_documents(tmp_path / "absent") == []

    def test_a_malformed_document_is_listed_with_its_errors(self, tmp_path: Path) -> None:
        bad = tmp_path / "example.com" / "bad.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("---\nsource_url: https://example.com\n---\n\nbody\n")

        documents = list_documents(tmp_path)

        assert len(documents) == 1
        assert documents[0].provenance is None
        assert documents[0].errors != ()

    def test_check_reports_a_stale_document(self, tmp_path: Path) -> None:
        _seed(tmp_path)

        stale = check_staleness(tmp_path, today=date(2027, 1, 1))

        assert len(stale) == 1

    def test_check_is_silent_while_fresh(self, tmp_path: Path) -> None:
        _seed(tmp_path)

        assert check_staleness(tmp_path, today=date(2026, 9, 4)) == []

    def test_a_malformed_document_counts_as_needing_attention(self, tmp_path: Path) -> None:
        """Unparseable provenance is not "fresh" -- it is unknown, and the
        check must not report a corpus as clean when part of it is unreadable.
        """
        bad = tmp_path / "example.com" / "bad.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("# no frontmatter\n")

        assert check_staleness(tmp_path, today=date(2026, 9, 4)) != []

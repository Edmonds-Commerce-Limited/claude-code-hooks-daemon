"""The on-disk remote-docs store: write, refresh, list, check (Tasks 2.3/2.4).

The refresh short-circuit is the load-bearing behaviour here. D4 records the
hash of the RAW upstream bytes precisely so "did it actually change?" costs
one fetch and no rewrite -- the same trick the hand-rolled
`HOOK-CONTRACT-REFRESH.md` procedure already relies on at step 2.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from claude_code_hooks_daemon.remote_docs.capture import CaptureError
from claude_code_hooks_daemon.remote_docs.provenance import UNREVIEWED, Fidelity
from claude_code_hooks_daemon.remote_docs.store import (
    RefreshOutcome,
    check_licence_drift,
    check_staleness,
    list_documents,
    read_document,
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


class TestOverwriteProtection:
    """Issue #42 / Plan 00424: a second `add` of one URL must not silently
    replace the first capture's body.

    `write_capture` derives the same destination for the same URL every time
    (`derive_relative_path` is deterministic), so a second capture landed on
    the first one's file with no existence check at all: the earlier body was
    gone, `fetched_at` and `source_sha256` moved, and the call returned
    normally with no refusal and no report.
    """

    def test_a_second_write_without_force_refuses_and_writes_nothing(self, tmp_path: Path) -> None:
        first = _seed(tmp_path)
        before = first.read_text()

        try:
            write_capture(
                tmp_path,
                "https://example.com/docs/page",
                fetch_fn=_fetch(b"# Upstream\n\nReplaced.\n"),
                now=_LATER,
            )
        except CaptureError as exc:
            assert str(first) in str(exc)
        else:
            raise AssertionError(
                "a second capture onto an existing destination should refuse, "
                "not silently replace the first body"
            )

        assert first.read_text() == before

    def test_the_refusal_names_the_existing_captures_provenance(self, tmp_path: Path) -> None:
        import hashlib

        first = _seed(tmp_path)

        try:
            write_capture(
                tmp_path,
                "https://example.com/docs/page",
                fetch_fn=_fetch(b"# Upstream\n\nReplaced.\n"),
                now=_LATER,
            )
        except CaptureError as exc:
            message = str(exc)
            assert _NOW.isoformat() in message
            assert hashlib.sha256(_BODY).hexdigest() in message
        else:
            raise AssertionError("expected a refusal naming the existing capture")

        assert first.is_file()

    def test_force_replaces_the_existing_capture(self, tmp_path: Path) -> None:
        first = _seed(tmp_path)

        written = write_capture(
            tmp_path,
            "https://example.com/docs/page",
            fetch_fn=_fetch(b"# Upstream\n\nReplaced.\n"),
            now=_LATER,
            force=True,
        )

        assert written == first
        assert "Replaced." in written.read_text()

    def test_a_first_capture_of_a_new_url_is_unaffected(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        assert written.is_file()
        assert "Body." in written.read_text()

    def test_the_refusal_is_decided_before_the_fetch(self, tmp_path: Path) -> None:
        """A repeated `add` must cost no network round trip.

        `derive_relative_path` needs no network access, so the existence
        check can run before `fetch_fn` is ever called -- pinned here with a
        fetcher that fails the test if it runs at all, rather than resting on
        statement order in `write_capture` staying as written.
        """
        first = _seed(tmp_path)

        def never_call(url: str) -> bytes:
            raise AssertionError("fetch_fn must not run when the refusal already applies")

        try:
            write_capture(
                tmp_path,
                "https://example.com/docs/page",
                fetch_fn=never_call,
                now=_LATER,
            )
        except CaptureError as exc:
            assert str(first) in str(exc)
        else:
            raise AssertionError("expected a refusal")


class TestTheRefreshPathIsGuardedToo:
    """Plan 00412: the same guarantee, on the path that skipped it.

    `write_capture` refuses to vendor content the sensitive-content scanner
    rejects, because a CLI write bypasses the Write-tool hook. `refresh_document`
    performs the same fetch and the same write, so the same reasoning applies —
    and it applies MORE strongly, because upstream content can have changed
    since the capture a human ran deliberately. That is the point of a refresh.

    Found by the `declared-invariant-pairs` Detector's first call-path row.

    The rejected body below is a harmless placeholder: the guard is a stub, so
    what makes these tests work is the stub's verdict, never the bytes. Writing
    a realistic credential here would put one in git history to no purpose.
    """

    _REJECTED_BODY = b"# Upstream\n\nlooks-like-a-credential\n"

    def test_a_refresh_whose_new_body_is_rejected_writes_nothing(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)
        before = written.read_text()

        outcome = refresh_document(
            written,
            fetch_fn=_fetch(self._REJECTED_BODY),
            now=_LATER,
            content_guard=lambda content: "matches the sensitive-content pattern `aws-key`",
        )

        assert outcome is RefreshOutcome.REFUSED
        assert written.read_text() == before

    def test_a_refusal_is_distinct_from_a_failed_fetch(self) -> None:
        """`REFUSED` and `FAILED` are different facts and must read differently.

        A failed fetch is a transient network problem to retry; a refusal means
        upstream is now serving something that must not enter the repository,
        which is a thing for a human to look at.
        """
        assert RefreshOutcome.REFUSED is not RefreshOutcome.FAILED
        assert RefreshOutcome.REFUSED.value == "refused"

    def test_a_clean_refresh_still_updates(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)

        outcome = refresh_document(
            written,
            fetch_fn=_fetch(b"# Upstream\n\nNew body.\n"),
            now=_LATER,
            content_guard=lambda content: None,
        )

        assert outcome is RefreshOutcome.UPDATED
        assert "New body." in written.read_text()

    def test_the_guard_sees_the_newly_fetched_body(self, tmp_path: Path) -> None:
        written = _seed(tmp_path)
        seen: list[str] = []

        def record(content: str) -> str | None:
            seen.append(content)
            return None

        refresh_document(
            written,
            fetch_fn=_fetch(b"# Upstream\n\nfreshly served payload\n"),
            now=_LATER,
            content_guard=record,
        )

        assert "freshly served payload" in seen[0]

    def test_an_unchanged_refresh_is_still_scanned(self, tmp_path: Path) -> None:
        """The short-circuit must not become a way past the guard.

        An unchanged hash still rewrites the file, so bytes are still written;
        and a guard's pattern list can change between runs even when upstream
        has not.
        """
        written = _seed(tmp_path)
        seen: list[str] = []

        def record(content: str) -> str | None:
            seen.append(content)
            return None

        refresh_document(written, fetch_fn=_fetch(_BODY), now=_LATER, content_guard=record)

        assert seen, "an unchanged refresh skipped the guard entirely"

    def test_no_guard_supplied_keeps_the_previous_behaviour(self, tmp_path: Path) -> None:
        """The parameter is optional, exactly as it is on `write_capture`."""
        written = _seed(tmp_path)

        outcome = refresh_document(written, fetch_fn=_fetch(b"# Upstream\n\nNew.\n"), now=_LATER)

        assert outcome is RefreshOutcome.UPDATED


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


class TestLicenceDriftAgainstKnownSources:
    """`known_sources` applies at CAPTURE, so it never reaches what is already
    vendored (ledger 00413 N8).

    Recording a domain's licence is advertised as the right move — the capture
    advisory recommends it over per-file frontmatter — but it changes nothing
    for the files already captured from that domain, which for any domain
    anyone has actually used is every file they care about.

    Neither documented route closes the gap: hand-editing frontmatter is
    correctly denied, and `refresh` compares the SOURCE HASH, so a
    content-identical refresh has no reason to re-stamp a licence that is a
    local judgement rather than source content. Only re-running `add` works,
    and that is undocumented and reads as destructive.

    So the drift is REPORTED. The fix is then the caller's to apply, but they
    can no longer be unaware of it.
    """

    def test_a_document_disagreeing_with_its_domain_is_reported(self, tmp_path: Path) -> None:
        _seed(tmp_path)

        drift = check_licence_drift(tmp_path, {"example.com": "CC-BY-4.0"})

        assert len(drift) == 1
        assert drift[0].expected == "CC-BY-4.0"

    def test_the_report_names_the_recorded_licence_too(self, tmp_path: Path) -> None:
        """A report saying only what is EXPECTED cannot be acted on."""
        _seed(tmp_path)

        drift = check_licence_drift(tmp_path, {"example.com": "CC-BY-4.0"})

        assert drift[0].recorded == UNREVIEWED

    def test_an_agreeing_document_is_silent(self, tmp_path: Path) -> None:
        _seed(tmp_path)

        assert check_licence_drift(tmp_path, {"example.com": UNREVIEWED}) == []

    def test_an_undeclared_domain_is_silent(self, tmp_path: Path) -> None:
        """Declaring nothing must not turn every document into a finding.

        `known_sources` is opt-in; a project that has declared no domains has
        expressed no expectation to disagree with.
        """
        _seed(tmp_path)

        assert check_licence_drift(tmp_path, {}) == []

    def test_a_different_domain_is_not_matched(self, tmp_path: Path) -> None:
        """Host matching is exact, mirroring what RemoteDocs.md already states."""
        _seed(tmp_path)

        assert check_licence_drift(tmp_path, {"other.example.com": "CC-BY-4.0"}) == []

    def test_a_malformed_document_is_skipped_rather_than_crashing(self, tmp_path: Path) -> None:
        """Unparseable provenance is already `check_staleness`'s finding.

        Reporting it twice, under a heading about licences, would send the
        reader to fix the wrong thing.
        """
        bad = tmp_path / "example.com" / "bad.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("# no frontmatter\n")

        assert check_licence_drift(tmp_path, {"example.com": "CC-BY-4.0"}) == []

    def test_a_missing_tree_is_not_an_error(self, tmp_path: Path) -> None:
        assert check_licence_drift(tmp_path / "absent", {"example.com": "CC-BY-4.0"}) == []


class TestFidelityIsCarriedThrough:
    """A rendering fetcher's lower claim must survive the trip to disk.

    The store is where the document is finally written, so a fidelity that
    got dropped anywhere along the way becomes a permanent overclaim in the
    corpus rather than a transient one.
    """

    def test_write_capture_records_the_declared_fidelity(self, tmp_path: Path) -> None:
        written = write_capture(
            tmp_path,
            "https://example.com/docs/page",
            fetch_fn=_fetch(_BODY),
            now=_NOW,
            fidelity=Fidelity.CONVERTED,
            fetch_method="agent-browser",
        )

        provenance = read_document(written).provenance
        assert provenance is not None
        assert provenance.fidelity is Fidelity.CONVERTED
        assert provenance.fetch_method == "agent-browser"

    def test_refresh_records_the_fidelity_of_the_refetch(self, tmp_path: Path) -> None:
        """A refresh re-fetches, so the NEW fetcher's claim applies -- not the
        claim recorded when the document was first captured.
        """
        written = _seed(tmp_path)

        refresh_document(
            written,
            fetch_fn=_fetch(b"# Changed\n"),
            now=_LATER,
            fidelity=Fidelity.CONVERTED,
            fetch_method="agent-browser",
        )

        provenance = read_document(written).provenance
        assert provenance is not None
        assert provenance.fidelity is Fidelity.CONVERTED
        assert provenance.fetch_method == "agent-browser"

"""Tests for the remote-docs provenance schema and parser (Plan 00326 Tasks 1.1/1.2).

Every required field has an acceptance test AND a rejection test, which is
Task 1.1's stated done-when condition. Malformed input must always come back
as a typed :class:`ParseResult` carrying errors -- an exception escaping the
parser would take down whichever hook handler called it.
"""

from datetime import UTC, date, datetime

from claude_code_hooks_daemon.remote_docs.provenance import (
    NEVER,
    UNREVIEWED,
    Fidelity,
    parse_provenance,
)

_SHA = "e" * 64


def _frontmatter(**overrides: str) -> str:
    """A valid provenance document, with named fields overridden or dropped."""
    fields: dict[str, str] = {
        "source_url": "https://example.com/docs/page",
        "fetched_at": "2026-09-03T10:00:00+00:00",
        "fidelity": "verbatim",
        "source_sha256": _SHA,
        "licence": "CC-BY-4.0",
        "stale_after": "2026-12-01",
    }
    fields.update(overrides)
    lines = [f"{key}: {value}" for key, value in fields.items() if value != ""]
    return "---\n" + "\n".join(lines) + "\n---\n\n# Upstream page\n\nBody text.\n"


class TestValidDocument:
    def test_all_required_fields_parse(self) -> None:
        result = parse_provenance(_frontmatter())

        assert result.errors == ()
        assert result.provenance is not None
        assert result.provenance.source_url == "https://example.com/docs/page"
        assert result.provenance.fidelity is Fidelity.VERBATIM
        assert result.provenance.source_sha256 == _SHA
        assert result.provenance.licence == "CC-BY-4.0"

    def test_fetched_at_is_timezone_aware(self) -> None:
        result = parse_provenance(_frontmatter())

        assert result.provenance is not None
        assert result.provenance.fetched_at == datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

    def test_stale_after_date_is_parsed(self) -> None:
        result = parse_provenance(_frontmatter())

        assert result.provenance is not None
        assert result.provenance.stale_after == date(2026, 12, 1)

    def test_optional_fields_default_to_none(self) -> None:
        result = parse_provenance(_frontmatter())

        assert result.provenance is not None
        assert result.provenance.upstream_version is None
        assert result.provenance.fetch_method is None
        assert result.provenance.retrieved_by is None

    def test_optional_fields_are_read_when_present(self) -> None:
        result = parse_provenance(_frontmatter(upstream_version="2.1.259"))

        assert result.errors == ()
        assert result.provenance is not None
        assert result.provenance.upstream_version == "2.1.259"

    def test_body_is_returned_separately_from_frontmatter(self) -> None:
        result = parse_provenance(_frontmatter())

        assert "# Upstream page" in result.body
        assert "source_sha256" not in result.body


class TestStructuralRejection:
    def test_no_frontmatter_is_an_error_not_an_exception(self) -> None:
        result = parse_provenance("# Just a document\n\nNo frontmatter here.\n")

        assert result.provenance is None
        assert any(error.field == "frontmatter" for error in result.errors)

    def test_unparseable_yaml_is_an_error_not_an_exception(self) -> None:
        result = parse_provenance("---\nsource_url: [unclosed\n---\n\nbody\n")

        assert result.provenance is None
        assert any(error.field == "frontmatter" for error in result.errors)

    def test_frontmatter_that_is_not_a_mapping_is_rejected(self) -> None:
        result = parse_provenance("---\n- a list item\n---\n\nbody\n")

        assert result.provenance is None
        assert any(error.field == "frontmatter" for error in result.errors)

    def test_empty_content_is_rejected(self) -> None:
        result = parse_provenance("")

        assert result.provenance is None
        assert result.errors != ()


class TestRequiredFieldRejection:
    """One rejection test per required field (Task 1.1 done-when)."""

    def test_missing_source_url_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(source_url=""))

        assert result.provenance is None
        assert any(error.field == "source_url" for error in result.errors)

    def test_missing_fetched_at_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(fetched_at=""))

        assert result.provenance is None
        assert any(error.field == "fetched_at" for error in result.errors)

    def test_missing_fidelity_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(fidelity=""))

        assert result.provenance is None
        assert any(error.field == "fidelity" for error in result.errors)

    def test_missing_source_sha256_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(source_sha256=""))

        assert result.provenance is None
        assert any(error.field == "source_sha256" for error in result.errors)

    def test_missing_licence_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(licence=""))

        assert result.provenance is None
        assert any(error.field == "licence" for error in result.errors)

    def test_missing_stale_after_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(stale_after=""))

        assert result.provenance is None
        assert any(error.field == "stale_after" for error in result.errors)

    def test_every_missing_field_is_reported_not_just_the_first(self) -> None:
        """A one-at-a-time parser would make fixing a bad capture a slog."""
        result = parse_provenance("---\nsource_url: https://example.com\n---\n\nbody\n")

        reported = {error.field for error in result.errors}
        assert {"fetched_at", "fidelity", "source_sha256", "licence"} <= reported


class TestFieldValueValidation:
    def test_non_https_source_url_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(source_url="http://example.com/x"))

        assert result.provenance is None
        assert any(error.field == "source_url" for error in result.errors)

    def test_non_url_source_url_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(source_url="not a url"))

        assert result.provenance is None
        assert any(error.field == "source_url" for error in result.errors)

    def test_unknown_fidelity_value_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(fidelity="probably-fine"))

        assert result.provenance is None
        assert any(error.field == "fidelity" for error in result.errors)

    def test_each_known_fidelity_value_is_accepted(self) -> None:
        for value in ("verbatim", "converted", "summarised"):
            result = parse_provenance(_frontmatter(fidelity=value))

            assert result.errors == (), f"{value} should be valid"
            assert result.provenance is not None
            assert result.provenance.fidelity is Fidelity(value)

    def test_malformed_sha256_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(source_sha256="abc123"))

        assert result.provenance is None
        assert any(error.field == "source_sha256" for error in result.errors)

    def test_non_hex_sha256_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(source_sha256="z" * 64))

        assert result.provenance is None
        assert any(error.field == "source_sha256" for error in result.errors)

    def test_naive_fetched_at_is_rejected(self) -> None:
        """A timestamp without an offset is ambiguous across machines."""
        result = parse_provenance(_frontmatter(fetched_at="2026-09-03T10:00:00"))

        assert result.provenance is None
        assert any(error.field == "fetched_at" for error in result.errors)

    def test_unparseable_fetched_at_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(fetched_at="last Tuesday"))

        assert result.provenance is None
        assert any(error.field == "fetched_at" for error in result.errors)

    def test_unparseable_stale_after_is_rejected(self) -> None:
        result = parse_provenance(_frontmatter(stale_after="soon"))

        assert result.provenance is None
        assert any(error.field == "stale_after" for error in result.errors)


class TestSentinels:
    def test_unreviewed_licence_is_accepted_and_flagged(self) -> None:
        """D13: an unreviewed licence parses, but is not silently fine."""
        result = parse_provenance(_frontmatter(licence=UNREVIEWED))

        assert result.errors == ()
        assert result.provenance is not None
        assert result.provenance.licence == UNREVIEWED
        assert result.provenance.licence_is_unreviewed is True

    def test_declared_licence_is_not_flagged_as_unreviewed(self) -> None:
        result = parse_provenance(_frontmatter())

        assert result.provenance is not None
        assert result.provenance.licence_is_unreviewed is False

    def test_stale_after_never_is_accepted(self) -> None:
        """D6/C4: a deliberately frozen archival snapshot never goes stale."""
        result = parse_provenance(_frontmatter(stale_after=NEVER))

        assert result.errors == ()
        assert result.provenance is not None
        assert result.provenance.stale_after == NEVER


class TestStaleness:
    def test_document_past_its_stale_after_is_stale(self) -> None:
        result = parse_provenance(_frontmatter(stale_after="2026-01-01"))

        assert result.provenance is not None
        assert result.provenance.is_stale(date(2026, 9, 3)) is True

    def test_document_before_its_stale_after_is_fresh(self) -> None:
        result = parse_provenance(_frontmatter(stale_after="2026-12-01"))

        assert result.provenance is not None
        assert result.provenance.is_stale(date(2026, 9, 3)) is False

    def test_stale_after_is_inclusive_on_the_day_itself(self) -> None:
        """On the named day the document is still good; it expires after it."""
        result = parse_provenance(_frontmatter(stale_after="2026-09-03"))

        assert result.provenance is not None
        assert result.provenance.is_stale(date(2026, 9, 3)) is False
        assert result.provenance.is_stale(date(2026, 9, 4)) is True

    def test_never_is_never_stale(self) -> None:
        result = parse_provenance(_frontmatter(stale_after=NEVER))

        assert result.provenance is not None
        assert result.provenance.is_stale(date(2099, 1, 1)) is False

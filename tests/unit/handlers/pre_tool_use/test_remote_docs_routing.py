"""Routing agents to the vendored copy (Plan 00326 Tasks 5.1 and 5.3).

A corpus nobody is routed to is a corpus nobody reads. One handler, two
branches:

* ``WebFetch`` — vendored and fresh, DENY and name the local path; vendored
  but stale, ALLOW, because the fetch IS the refresh; not vendored, ALLOW
  with a capture hint.
* ``Read`` — a stale document in the tree is allowed with an advisory, so
  the warning arrives WITH the content and cannot be skipped (D16).

The capture hint is deliberately conditional on the tree existing. A project
that vendors nothing has not opted into any of this, and a hint on every
fetch would be pure noise -- the fastest way to teach someone to ignore
advisories.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_routing import (
    RemoteDocsRoutingHandler,
)
from claude_code_hooks_daemon.remote_docs.store import write_capture

_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
_ROOT = Path("/tmp/test")
_URL = "https://example.com/docs/page"


def _fetch(body: bytes = b"# Upstream\n"):
    def fetch_fn(url: str) -> bytes:
        return body

    return fetch_fn


@pytest.fixture(autouse=True)
def _mock_project_context(tmp_path: Path):
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = tmp_path
        yield mock


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return tmp_path / "remote-docs"


@pytest.fixture
def handler(tmp_path: Path) -> RemoteDocsRoutingHandler:
    instance = RemoteDocsRoutingHandler()
    instance.today_reader = lambda: date(2026, 9, 4)
    return instance


def _seed(tree: Path, url: str = _URL, days: int = 90, licence: str = "CC-BY-4.0") -> Path:
    """Seed a document. Licence defaults to a REVIEWED one on purpose.

    The capture default is the `unreviewed` sentinel, which is itself an
    advisory trigger — seeding with it would make "is this silent?" tests
    pass or fail for the wrong reason.
    """
    return write_capture(
        tree, url, fetch_fn=_fetch(), now=_NOW, stale_after_days=days, licence=licence
    )


def _webfetch(url: str) -> dict[str, Any]:
    return {"tool_name": "WebFetch", "tool_input": {"url": url}}


def _read(path: Path) -> dict[str, Any]:
    return {"tool_name": "Read", "tool_input": {"file_path": str(path)}}


class TestWebFetchVendored:
    def test_a_fresh_vendored_url_is_denied(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        _seed(tree)

        result = handler.handle(_webfetch(_URL))

        assert result.decision is Decision.DENY

    def test_the_denial_names_the_local_path(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """A deny that does not say where the copy is just blocks work."""
        _seed(tree)

        reason = handler.handle(_webfetch(_URL)).reason or ""

        assert "page.md" in reason

    def test_the_denial_names_the_refresh_route(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """Wanting genuinely newer content is legitimate; name the way to it."""
        _seed(tree)

        reason = handler.handle(_webfetch(_URL)).reason or ""

        assert "remote-docs refresh" in reason

    def test_a_stale_vendored_url_is_allowed(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """The fetch IS the refresh -- denying it would strand the document."""
        _seed(tree, days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        assert handler.handle(_webfetch(_URL)).decision is Decision.ALLOW

    def test_a_decorated_url_still_matches_the_vendored_copy(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        _seed(tree)

        result = handler.handle(_webfetch(_URL + "?utm_source=x#install"))

        assert result.decision is Decision.DENY


class TestWebFetchNotVendored:
    """The nudge is scoped to DECLARED documentation domains.

    Hinting on every unvendored URL would fire on a GitHub issue, a Stack
    Overflow answer, a status page — most of which nobody wants vendored.
    An advisory that is usually wrong is one people learn to skim past, so
    the project says which domains are documentation sources and only those
    are nudged.
    """

    def test_an_unvendored_url_is_allowed(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        _seed(tree)

        result = handler.handle(_webfetch("https://other.example/thing"))

        assert result.decision is Decision.ALLOW

    def test_a_declared_domain_gets_a_capture_nudge(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        _seed(tree)
        handler.declared_domains_reader = lambda: {"docs.example"}

        context = handler.handle(_webfetch("https://docs.example/guide")).context or []

        assert any("remote-docs add" in line for line in context)

    def test_an_undeclared_domain_is_silent(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """Most fetches are not documentation; nudging them all is noise."""
        _seed(tree)
        handler.declared_domains_reader = lambda: {"docs.example"}

        assert handler.matches(_webfetch("https://other.example/thing")) is False

    def test_a_declared_subdomain_match_is_exact_not_suffix(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """`docs.example` must not match `evil-docs.example`."""
        _seed(tree)
        handler.declared_domains_reader = lambda: {"docs.example"}

        assert handler.matches(_webfetch("https://evil-docs.example/x")) is False

    def test_the_declared_domain_match_ignores_host_case(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        _seed(tree)
        handler.declared_domains_reader = lambda: {"docs.example"}

        assert handler.matches(_webfetch("https://DOCS.Example/guide")) is True

    def test_no_declared_domains_means_no_nudges(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """Declaring nothing opts out of nudging entirely, without disabling routing."""
        _seed(tree)
        handler.declared_domains_reader = lambda: set()

        assert handler.matches(_webfetch("https://docs.example/guide")) is False

    def test_a_vendored_url_is_still_routed_on_an_undeclared_domain(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """Declaration governs NUDGING, not routing to a copy we already hold."""
        _seed(tree)
        handler.declared_domains_reader = lambda: set()

        assert handler.handle(_webfetch(_URL)).decision is Decision.DENY

    def test_no_hint_when_the_project_vendors_nothing(
        self, handler: RemoteDocsRoutingHandler
    ) -> None:
        """No tree means no opt-in at all."""
        assert handler.matches(_webfetch("https://other.example/thing")) is False


class TestReadBranch:
    def test_reading_a_fresh_document_is_silent(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        written = _seed(tree)

        assert handler.matches(_read(written)) is False

    def test_reading_a_stale_document_advises(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        written = _seed(tree, days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        result = handler.handle(_read(written))

        assert result.decision is Decision.ALLOW
        assert result.context

    def test_the_read_advisory_names_the_dates_and_the_remedy(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        written = _seed(tree, days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        joined = "\n".join(handler.handle(_read(written)).context or [])

        assert "2026-09-03" in joined
        assert "remote-docs refresh" in joined

    def test_an_unreviewed_licence_is_named_in_the_same_advisory(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """Two advisories for one Read is how one of them gets ignored (D16)."""
        written = _seed(tree, days=1, licence="unreviewed")
        handler.today_reader = lambda: date(2026, 12, 1)

        joined = "\n".join(handler.handle(_read(written)).context or [])

        assert "licence" in joined.lower()
        assert "stale since" in joined

    def test_a_fresh_but_unreviewed_document_still_advises(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        """An unreviewed licence is a standing fact, not a staleness symptom.

        The capture default IS the sentinel, so this is the common case for
        a young corpus rather than an edge one.
        """
        written = _seed(tree, licence="unreviewed")

        assert handler.matches(_read(written)) is True
        joined = "\n".join(handler.handle(_read(written)).context or [])
        assert "licence" in joined.lower()
        assert "stale since" not in joined

    def test_a_read_outside_the_tree_is_ignored(
        self, handler: RemoteDocsRoutingHandler, tree: Path, tmp_path: Path
    ) -> None:
        _seed(tree)
        other = tmp_path / "docs" / "guide.md"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("# local\n", encoding="utf-8")

        assert handler.matches(_read(other)) is False


class TestScope:
    def test_other_tools_are_ignored(self, handler: RemoteDocsRoutingHandler, tree: Path) -> None:
        _seed(tree)

        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is False

    def test_a_webfetch_without_a_url_is_ignored(
        self, handler: RemoteDocsRoutingHandler, tree: Path
    ) -> None:
        _seed(tree)

        assert handler.matches({"tool_name": "WebFetch", "tool_input": {}}) is False

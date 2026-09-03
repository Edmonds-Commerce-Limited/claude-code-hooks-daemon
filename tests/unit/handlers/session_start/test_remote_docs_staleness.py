"""SessionStart sweep over the vendored remote-docs tree (Plan 00326 Task 4.3).

A `stale_after` date in a file nobody reads changes nothing. This is the
surface that makes staleness arrive without anyone running a command.

It ADVISES rather than blocks (D7): staleness is a judgement a human may
knowingly accept — an upstream that has not changed in a year is not a
problem — whereas absent provenance is a fact, which is the gate's job.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.remote_docs_staleness import (
    RemoteDocsStalenessHandler,
)
from claude_code_hooks_daemon.remote_docs.store import write_capture

_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
_STARTUP: dict[str, Any] = {"hook_event_name": "SessionStart", "source": "startup"}


def _fetch(body: bytes = b"# Upstream\n\nBody.\n"):
    def fetch_fn(url: str) -> bytes:
        return body

    return fetch_fn


def _seed(tree: Path, url: str = "https://example.com/docs/page", days: int = 90) -> Path:
    return write_capture(tree, url, fetch_fn=_fetch(), now=_NOW, stale_after_days=days)


@pytest.fixture
def handler(tmp_path: Path) -> RemoteDocsStalenessHandler:
    instance = RemoteDocsStalenessHandler()
    instance.tree_reader = lambda: tmp_path / "remote-docs"
    instance.today_reader = lambda: date(2026, 9, 4)
    return instance


class TestScope:
    def test_it_runs_on_a_new_session(self, handler: RemoteDocsStalenessHandler) -> None:
        assert handler.matches(_STARTUP) is True

    def test_it_stays_quiet_on_resume(self, handler: RemoteDocsStalenessHandler) -> None:
        """A resumed session already saw this report; repeating it is noise."""
        assert handler.matches({"hook_event_name": "SessionStart", "source": "resume"}) is False

    def test_it_ignores_other_events(self, handler: RemoteDocsStalenessHandler) -> None:
        assert handler.matches({"hook_event_name": "PreToolUse"}) is False

    def test_it_can_be_disabled(self, handler: RemoteDocsStalenessHandler) -> None:
        handler.configure({"enabled": False})

        assert handler.matches(_STARTUP) is False


class TestReport:
    def test_a_missing_tree_is_silent(self, handler: RemoteDocsStalenessHandler) -> None:
        """Most projects vendor nothing; they must never see this handler."""
        result = handler.handle(_STARTUP)

        assert result.context == []

    def test_a_fresh_corpus_is_silent(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        _seed(tmp_path / "remote-docs")

        assert handler.handle(_STARTUP).context == []

    def test_a_stale_document_is_reported(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        _seed(tmp_path / "remote-docs", days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        context = handler.handle(_STARTUP).context

        assert any("page.md" in line for line in context)

    def test_the_report_never_blocks(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        _seed(tmp_path / "remote-docs", days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        assert handler.handle(_STARTUP).decision is Decision.ALLOW

    def test_the_report_names_the_refresh_command(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        """A report with no next step makes the reader go and look it up."""
        _seed(tmp_path / "remote-docs", days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        assert any("remote-docs refresh" in line for line in handler.handle(_STARTUP).context)

    def test_an_unreadable_document_is_reported_too(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        """Unparseable provenance is not fresh -- it is unknown."""
        bad = tmp_path / "remote-docs" / "example.com" / "bad.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("# no frontmatter\n", encoding="utf-8")

        assert any("bad.md" in line for line in handler.handle(_STARTUP).context)

    def test_the_remedy_does_not_vary_by_install_mode(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        """Task 4.4: a client's vendored docs ARE theirs to refresh.

        `contract_staleness` splits its remedy — in a client install the
        vendored contract lives under the upgrade-overwritten daemon tree,
        so the advice is "upgrade the daemon". Remote docs are the opposite:
        the tree is project-owned wherever it lives, so telling a client to
        upgrade the daemon would be wrong, and there is nothing to branch on.
        """
        from unittest.mock import patch

        _seed(tmp_path / "remote-docs", days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        with patch(
            "claude_code_hooks_daemon.core.ProjectContext.self_install_mode",
            return_value=True,
        ):
            maintainer = handler.handle(_STARTUP).context
        with patch(
            "claude_code_hooks_daemon.core.ProjectContext.self_install_mode",
            return_value=False,
        ):
            client = handler.handle(_STARTUP).context

        assert maintainer == client
        assert not any("upgrade" in line.lower() for line in client)

    def test_the_remote_tree_is_not_classified_as_vendored(self) -> None:
        """Vendored means third-party and not ours to touch; this tree is ours.

        Misclassifying it would make every vendor-skipping handler ignore the
        tree, and would contradict `remote-docs refresh` being the supported
        way to update it.
        """
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        layout = ProjectLayout.built_in_default()
        path = f"{layout.remote_docs_dir}/example.com/page.md"

        assert layout.is_remote_docs_path(path) is True
        assert layout.is_vendored_path(path) is False

    def test_a_large_corpus_report_is_bounded(
        self, handler: RemoteDocsStalenessHandler, tmp_path: Path
    ) -> None:
        """A hundred stale files must not push the session's other advice away."""
        tree = tmp_path / "remote-docs"
        for index in range(40):
            _seed(tree, url=f"https://example.com/docs/page{index}", days=1)
        handler.today_reader = lambda: date(2026, 12, 1)

        context = handler.handle(_STARTUP).context

        assert len(context) < 20
        assert any("40" in line for line in context)

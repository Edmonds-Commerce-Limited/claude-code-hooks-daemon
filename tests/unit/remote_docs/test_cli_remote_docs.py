"""The `remote-docs` CLI subcommand (Plan 00326 Tasks 2.1/2.3/2.4).

Procedure belongs in a script, not in prose an agent re-derives each time
(the Plan 00324 lesson). These tests drive `cmd_remote_docs` directly with an
injected fetcher, so no test touches the network.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from claude_code_hooks_daemon.daemon.cli import cmd_remote_docs

_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
_BODY = b"# Upstream\n\nBody.\n"


def _fetch(body: bytes = _BODY):
    def fetch_fn(url: str) -> bytes:
        return body

    return fetch_fn


def _args(root: Path, action: str, **overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "project_root": root,
        "remote_docs_action": action,
        "url": None,
        "path": None,
        "all_docs": False,
        "licence": None,
        "stale_after_days": None,
        "json_output": False,
        "fetch_fn": _fetch(),
        "now": _NOW,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _tree(root: Path) -> Path:
    return root / "remote-docs"


class TestAdd:
    def test_add_captures_to_the_derived_path(self, tmp_path: Path) -> None:
        code = cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/docs/page"))

        assert code == 0
        assert (_tree(tmp_path) / "example.com" / "docs" / "page.md").is_file()

    def test_add_records_a_declared_licence(self, tmp_path: Path) -> None:
        cmd_remote_docs(
            _args(tmp_path, "add", url="https://example.com/p", licence="CC-BY-4.0")
        )

        content = (_tree(tmp_path) / "example.com" / "p.md").read_text()
        assert "licence: CC-BY-4.0" in content

    def test_add_rejects_a_non_https_url_without_a_traceback(self, tmp_path: Path) -> None:
        code = cmd_remote_docs(_args(tmp_path, "add", url="http://example.com/p"))

        assert code == 1

    def test_add_reports_a_failed_fetch_as_an_exit_code(self, tmp_path: Path) -> None:
        def boom(url: str) -> bytes:
            raise OSError("network down")

        code = cmd_remote_docs(
            _args(tmp_path, "add", url="https://example.com/p", fetch_fn=boom)
        )

        assert code == 1


class TestListAndCheck:
    def test_list_of_an_empty_tree_succeeds(self, tmp_path: Path) -> None:
        assert cmd_remote_docs(_args(tmp_path, "list")) == 0

    def test_list_reports_captured_documents(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        assert cmd_remote_docs(_args(tmp_path, "list")) == 0

    def test_check_is_clean_for_a_fresh_capture(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        assert cmd_remote_docs(_args(tmp_path, "check")) == 0

    def test_check_exits_nonzero_when_a_document_is_stale(self, tmp_path: Path) -> None:
        """Non-zero on stale is what makes the check usable in CI."""
        cmd_remote_docs(
            _args(tmp_path, "add", url="https://example.com/p", stale_after_days=1)
        )

        later = _args(tmp_path, "check", now=datetime(2027, 1, 1, tzinfo=UTC))
        assert cmd_remote_docs(later) == 1

    def test_check_exits_nonzero_for_unparseable_provenance(self, tmp_path: Path) -> None:
        bad = _tree(tmp_path) / "example.com"
        bad.mkdir(parents=True)
        (bad / "hand-written.md").write_text("# no frontmatter\n")

        assert cmd_remote_docs(_args(tmp_path, "check")) == 1


class TestRefresh:
    def test_refresh_all_succeeds_on_unchanged_upstream(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        assert cmd_remote_docs(_args(tmp_path, "refresh", all_docs=True)) == 0

    def test_refresh_rewrites_a_changed_document(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        code = cmd_remote_docs(
            _args(
                tmp_path,
                "refresh",
                all_docs=True,
                fetch_fn=_fetch(b"# Upstream\n\nRewritten.\n"),
            )
        )

        assert code == 0
        assert "Rewritten." in (_tree(tmp_path) / "example.com" / "p.md").read_text()

    def test_refresh_of_a_single_path(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))
        target = _tree(tmp_path) / "example.com" / "p.md"

        assert cmd_remote_docs(_args(tmp_path, "refresh", path=target)) == 0

    def test_refresh_without_a_target_is_an_error(self, tmp_path: Path) -> None:
        """Neither --all nor a path: refuse rather than guess."""
        assert cmd_remote_docs(_args(tmp_path, "refresh")) == 2


class TestRemotePolicy:
    """`documentation.remote` moves two judgements from per-file to per-project."""

    def _configure(self, root: Path, body: str) -> None:
        config_dir = root / ".claude"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "hooks-daemon.yaml").write_text(body, encoding="utf-8")

    def test_a_known_source_prefills_the_licence(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.remote_docs.store import read_document

        self._configure(
            tmp_path,
            "documentation:\n"
            "  remote:\n"
            "    known_sources:\n"
            "      example.com: CC-BY-4.0\n",
        )

        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        document = read_document(_tree(tmp_path) / "example.com" / "p.md")
        assert document.provenance is not None
        assert document.provenance.licence == "CC-BY-4.0"

    def test_an_explicit_licence_still_wins_over_the_config(self, tmp_path: Path) -> None:
        """The flag is the narrower statement; config is the standing default."""
        from claude_code_hooks_daemon.remote_docs.store import read_document

        self._configure(
            tmp_path,
            "documentation:\n  remote:\n    known_sources:\n      example.com: CC-BY-4.0\n",
        )

        cmd_remote_docs(
            _args(tmp_path, "add", url="https://example.com/p", licence="MIT")
        )

        document = read_document(_tree(tmp_path) / "example.com" / "p.md")
        assert document.provenance is not None
        assert document.provenance.licence == "MIT"

    def test_an_unknown_source_still_records_the_sentinel(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.remote_docs.provenance import UNREVIEWED
        from claude_code_hooks_daemon.remote_docs.store import read_document

        self._configure(
            tmp_path,
            "documentation:\n  remote:\n    known_sources:\n      other.example: CC-BY-4.0\n",
        )

        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        document = read_document(_tree(tmp_path) / "example.com" / "p.md")
        assert document.provenance is not None
        assert document.provenance.licence == UNREVIEWED

    def test_the_configured_staleness_window_is_applied(self, tmp_path: Path) -> None:
        from datetime import date

        from claude_code_hooks_daemon.remote_docs.store import read_document

        self._configure(
            tmp_path, "documentation:\n  remote:\n    default_staleness_days: 7\n"
        )

        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        document = read_document(_tree(tmp_path) / "example.com" / "p.md")
        assert document.provenance is not None
        assert document.provenance.stale_after == date(2026, 9, 10)


class TestGeneratedIndex:
    """An index that silently goes stale answers "no" confidently and wrongly."""

    def _index(self, root: Path) -> Path:
        from claude_code_hooks_daemon.remote_docs.index import INDEX_RELATIVE_PATH

        return root / INDEX_RELATIVE_PATH

    def test_add_regenerates_the_index(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        assert "https://example.com/p" in self._index(tmp_path).read_text(encoding="utf-8")

    def test_refresh_regenerates_the_index(self, tmp_path: Path) -> None:
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))
        self._index(tmp_path).write_text("stale\n", encoding="utf-8")

        cmd_remote_docs(_args(tmp_path, "refresh", all_docs=True))

        assert "stale" not in self._index(tmp_path).read_text(encoding="utf-8")

    def test_a_failed_capture_does_not_claim_the_document(self, tmp_path: Path) -> None:
        """The index must describe the tree, not what we hoped to add to it."""

        def boom(url: str) -> bytes:
            raise OSError("network down")

        cmd_remote_docs(
            _args(tmp_path, "add", url="https://example.com/p", fetch_fn=boom)
        )

        index = self._index(tmp_path)
        if index.exists():
            assert "https://example.com/p" not in index.read_text(encoding="utf-8")

    def test_the_index_is_not_written_inside_the_vendored_tree(self, tmp_path: Path) -> None:
        """Inside, it would have no provenance and the gate would deny it."""
        cmd_remote_docs(_args(tmp_path, "add", url="https://example.com/p"))

        assert _tree(tmp_path) not in self._index(tmp_path).parents


class TestFetcherSelection:
    """agent-browser is the default; losing it must be visible, not silent."""

    def _fetcher(self, warning: str | None):
        from claude_code_hooks_daemon.remote_docs.fetchers import ResolvedFetcher
        from claude_code_hooks_daemon.remote_docs.provenance import Fidelity

        return ResolvedFetcher(
            fetch_fn=_fetch(),
            fidelity=Fidelity.CONVERTED,
            method="agent-browser",
            warning=warning,
        )

    def test_the_resolved_fidelity_reaches_the_written_document(
        self, tmp_path: Path
    ) -> None:
        from claude_code_hooks_daemon.remote_docs.provenance import Fidelity
        from claude_code_hooks_daemon.remote_docs.store import read_document

        cmd_remote_docs(
            _args(
                tmp_path,
                "add",
                url="https://example.com/p",
                fetch_fn=None,
                fetcher=self._fetcher(None),
            )
        )

        document = read_document(_tree(tmp_path) / "example.com" / "p.md")
        assert document.provenance is not None
        assert document.provenance.fidelity is Fidelity.CONVERTED
        assert document.provenance.fetch_method == "agent-browser"

    def test_a_fallback_warning_is_printed_when_fetching(
        self, tmp_path: Path, capsys
    ) -> None:
        cmd_remote_docs(
            _args(
                tmp_path,
                "add",
                url="https://example.com/p",
                fetch_fn=None,
                fetcher=self._fetcher("agent-browser is not installed"),
            )
        )

        assert "agent-browser is not installed" in capsys.readouterr().err

    def test_no_warning_is_printed_for_an_action_that_never_fetches(
        self, tmp_path: Path, capsys
    ) -> None:
        """`list` reads the tree. Warning about a fetcher it never uses is noise."""
        cmd_remote_docs(
            _args(
                tmp_path,
                "list",
                fetch_fn=None,
                fetcher=self._fetcher("agent-browser is not installed"),
            )
        )

        assert "agent-browser is not installed" not in capsys.readouterr().err

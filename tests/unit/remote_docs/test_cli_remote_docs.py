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

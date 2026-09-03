"""Ordinary docs-QA checks never judge vendored upstream prose (Task 1.4).

D10, as amended: the remote tree sits OUTSIDE both corpus-collected trees, so
no ``scope_exclude_globs`` entry is needed to keep the existing checks off it.
That is a claim about corpus collection, and a claim is worth a test -- the
cost of it being wrong is a permanent stream of findings against prose this
project did not write and cannot fix.
"""

import argparse
from pathlib import Path

from claude_code_hooks_daemon.daemon.cli import cmd_docs_qa

#: Content deliberately shaped to trip ordinary documentation checks if the
#: file were ever treated as part of this project's corpus: a dead relative
#: link, and the kind of prose the human-tree terseness rule dislikes.
_UPSTREAM_CONTENT = """---
source_url: https://example.com/docs/page
fetched_at: 2026-09-03T10:00:00+00:00
fidelity: verbatim
source_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
licence: CC-BY-4.0
stale_after: 2026-12-01
---

# Upstream Page

See [the other page](./does-not-exist.md) for details.

This paragraph is upstream prose we neither authored nor may edit.
"""


def _args(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        sweep=True,
        check_staged=False,
        lint=None,
        json_output=False,
    )


def _scaffold(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "CLAUDE").mkdir(parents=True)
    (root / "CLAUDE" / "Foo.md").write_text("# Foo\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text("version: '2.0'\n")
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    return root


def test_sweep_is_clean_with_a_remote_doc_present(tmp_path: Path) -> None:
    """A remote document that would otherwise trip checks yields no findings."""
    root = _scaffold(tmp_path)
    remote = root / "remote-docs" / "example.com"
    remote.mkdir(parents=True)
    (remote / "page.md").write_text(_UPSTREAM_CONTENT)

    assert cmd_docs_qa(_args(root)) == 0


def test_the_same_content_in_the_human_tree_is_not_clean(tmp_path: Path) -> None:
    """The control: the content really is check-tripping.

    Without this, the test above could pass because the sweep finds nothing
    anywhere, and would prove nothing about the remote tree's exclusion.
    """
    root = _scaffold(tmp_path)
    human = root / "docs"
    human.mkdir(parents=True)
    (human / "page.md").write_text(_UPSTREAM_CONTENT)

    assert cmd_docs_qa(_args(root)) == 1

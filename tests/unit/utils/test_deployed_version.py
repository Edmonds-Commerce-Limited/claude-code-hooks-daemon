"""Tests for the tracked deployed-version reader (Plan 00386 Task 2.1).

`.claude/hooks-daemon/` is gitignored, so the installed clone is per-checkout,
while the assets it deploys are TRACKED. The only machine-readable record of the
version those tracked assets came from is the header `docs_generator` writes into
`.claude/HOOKS-DAEMON.md`. GitHub issue #38 concluded no such marker existed,
having grepped for a `daemon_version` key — it is there, spelled as prose.

One parser, shared: `generated_doc_hand_edit` already matched this exact line, so
the pattern moved here rather than being written a second time. Two parsers for
one line is how they drift apart, and the one that silently stops matching is the
one nobody notices.
"""

from pathlib import Path

from claude_code_hooks_daemon.utils.deployed_version import (
    TRACKED_VERSION_DOC_REL_PATH,
    read_tracked_deployed_version,
    version_marker_in,
)

_HEADER = "> Generated on 2026-09-11 (v3.63.0) by `generate-docs`. Regenerate: ...\n"


def _write_doc(root: Path, body: str) -> None:
    doc = root / TRACKED_VERSION_DOC_REL_PATH
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(body, encoding="utf-8")


class TestVersionMarkerIn:
    def test_reads_the_version_from_the_generated_header(self) -> None:
        assert version_marker_in(_HEADER) == "3.63.0"

    def test_finds_it_below_other_content(self) -> None:
        assert version_marker_in("# Title\n\n" + _HEADER + "\nmore\n") == "3.63.0"

    def test_absent_marker_is_none(self) -> None:
        assert version_marker_in("# Just a document\n") is None

    def test_a_differently_worded_header_is_not_guessed_at(self) -> None:
        """Narrow on purpose: this is the ONE shape the generator emits."""
        assert version_marker_in("> Built on 2026-09-11 (v3.63.0) by generate-docs\n") is None

    def test_a_non_semver_version_is_not_matched(self) -> None:
        assert version_marker_in("> Generated on 2026-09-11 (v3.63) by `generate-docs`.\n") is None


class TestReadTrackedDeployedVersion:
    def test_reads_from_the_tracked_doc(self, tmp_path: Path) -> None:
        _write_doc(tmp_path, _HEADER)
        assert read_tracked_deployed_version(tmp_path) == "3.63.0"

    def test_missing_file_is_none_not_an_error(self, tmp_path: Path) -> None:
        """A project that has never generated the doc is a normal state."""
        assert read_tracked_deployed_version(tmp_path) is None

    def test_present_but_unmarked_is_none(self, tmp_path: Path) -> None:
        _write_doc(tmp_path, "# Hooks Daemon\n\nno header here\n")
        assert read_tracked_deployed_version(tmp_path) is None

    def test_undecodable_bytes_are_none_not_an_error(self, tmp_path: Path) -> None:
        doc = tmp_path / TRACKED_VERSION_DOC_REL_PATH
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_bytes(b"\xff\xfe not utf-8 \xff")
        assert read_tracked_deployed_version(tmp_path) is None


class TestSharedWithTheDocsQaCheck:
    def test_the_docs_qa_check_uses_this_same_pattern(self) -> None:
        """Guards the SSoT: if `generated_doc_hand_edit` ever grows its own copy
        again, this fails rather than letting the two drift silently."""
        from claude_code_hooks_daemon.docs_qa.checks import generated_doc_hand_edit
        from claude_code_hooks_daemon.utils.deployed_version import VERSION_MARKER_RE

        assert generated_doc_hand_edit._VERSION_MARKER_RE is VERSION_MARKER_RE

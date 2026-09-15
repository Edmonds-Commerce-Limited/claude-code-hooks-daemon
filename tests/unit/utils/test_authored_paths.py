"""Resolving a path an author wrote in a document — Plan 00412 (RED first).

The bug this exists to kill: ``Path.exists()`` stats the path exactly as
written, so a ``..`` segment is walked through the FILESYSTEM and every
directory along the way has to exist. A link written in the first document of a
brand-new directory therefore resolves to False while naming a file that is
right there on disk.

Lexical normalisation is not merely a workaround for that. It is the more
faithful answer: a markdown renderer resolves ``..`` in a link by text, so the
lexical result is the one a reader of the rendered document will experience.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.authored_paths import authored_path_exists


class TestTheOriginatingBug:
    """A `..` link from a directory that does not exist yet."""

    def test_a_parent_link_resolves_from_a_directory_that_does_not_exist(
        self, tmp_path: Path
    ) -> None:
        """The exact shape that denied a write and could not be retried.

        ``Security/`` is absent — the write that would create it is the one
        being judged — and ``Routine/x.md`` is present. The honest answer is
        True, and stat-ing the unnormalised join gives False.
        """
        (tmp_path / "Routine").mkdir()
        (tmp_path / "Routine" / "x.md").write_text("hi")

        assert authored_path_exists(tmp_path / "Security", "../Routine/x.md")

    def test_the_unnormalised_form_really_does_disagree(self, tmp_path: Path) -> None:
        """Pins the defect itself, so the fix cannot be quietly reverted."""
        (tmp_path / "Routine").mkdir()
        (tmp_path / "Routine" / "x.md").write_text("hi")

        assert not (tmp_path / "Security" / "../Routine/x.md").exists()


class TestOrdinaryResolution:
    """The cases that already worked, which must keep working."""

    def test_a_plain_relative_target(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("hi")

        assert authored_path_exists(tmp_path, "a.md")

    def test_a_nested_relative_target(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.md").write_text("hi")

        assert authored_path_exists(tmp_path, "sub/a.md")

    def test_a_missing_target_is_still_missing(self, tmp_path: Path) -> None:
        """Normalising must not turn a genuine dead link into a live one."""
        assert not authored_path_exists(tmp_path, "nope.md")

    def test_a_missing_target_behind_a_parent_hop_is_still_missing(self, tmp_path: Path) -> None:
        """The whole value of the check survives the fix."""
        (tmp_path / "Routine").mkdir()

        assert not authored_path_exists(tmp_path / "Security", "../Routine/nope.md")

    def test_an_absolute_target_ignores_the_base(self, tmp_path: Path) -> None:
        """pathlib's own rule, relied on by the leading-slash link convention."""
        (tmp_path / "a.md").write_text("hi")

        assert authored_path_exists(tmp_path / "elsewhere", str(tmp_path / "a.md"))

    def test_a_directory_counts_as_existing(self, tmp_path: Path) -> None:
        """A link may legitimately point at a directory."""
        (tmp_path / "sub").mkdir()

        assert authored_path_exists(tmp_path, "sub")

    def test_a_walk_above_the_base_that_lands_nowhere_is_false(self, tmp_path: Path) -> None:
        """`..` is still resolved, not ignored — it just resolves by text."""
        assert not authored_path_exists(tmp_path, "../../definitely-not-here-00412")

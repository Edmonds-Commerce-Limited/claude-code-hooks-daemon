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

from claude_code_hooks_daemon.utils.authored_paths import (
    authored_path,
    authored_path_exists,
    contained_authored_path,
)


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


class TestTheNormalisedJoin:
    """`authored_path` — the lexical join, with no filesystem access at all.

    Extracted so a caller that needs the PATH rather than a yes/no answer does
    not have to re-derive the normalisation and get it subtly different.
    """

    def test_a_parent_hop_is_resolved_by_text(self, tmp_path: Path) -> None:
        assert authored_path(tmp_path / "Security", "../Routine/x.md") == (
            tmp_path / "Routine" / "x.md"
        )

    def test_nothing_needs_to_exist(self, tmp_path: Path) -> None:
        """The whole point: no stat, so an absent directory changes nothing."""
        result = authored_path(tmp_path / "nowhere", "../also-nowhere/x.md")

        assert result == tmp_path / "also-nowhere" / "x.md"
        assert not result.exists()


class TestContainment:
    """`contained_authored_path` — a DIFFERENT question from existence.

    Normalising makes `src/../../etc/passwd` resolve FAITHFULLY to a real
    file; that is not the same as it being a file the daemon may open. This
    helper answers "will the open land inside `base`", which is the question
    to ask before reading a path a document named.
    """

    def test_an_ordinary_target_is_returned(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("hi")

        assert contained_authored_path(tmp_path, "a.md") == tmp_path / "a.md"

    def test_a_target_that_does_not_exist_is_still_contained(self, tmp_path: Path) -> None:
        """Containment is about WHERE, not about whether it is there.

        The caller still has to handle a missing file; conflating the two
        would report an escape as a missing file and vice versa.
        """
        assert contained_authored_path(tmp_path, "sub/nope.md") == tmp_path / "sub" / "nope.md"

    def test_a_parent_hop_inside_the_base_is_allowed(self, tmp_path: Path) -> None:
        """`..` is not itself the hazard — leaving `base` is."""
        (tmp_path / "Routine").mkdir()
        (tmp_path / "Routine" / "x.md").write_text("hi")

        assert contained_authored_path(tmp_path, "Security/../Routine/x.md") == (
            tmp_path / "Routine" / "x.md"
        )

    def test_a_parent_hop_that_escapes_is_refused(self, tmp_path: Path) -> None:
        """The traversal vector, refused by the only test that can see it."""
        assert contained_authored_path(tmp_path / "repo", "../outside.md") is None

    def test_an_absolute_target_is_refused(self, tmp_path: Path) -> None:
        """`base / "/etc/passwd"` discards `base` entirely — pathlib's own rule.

        So an absolute target needs no `..` at all to escape, and a rule that
        only looked for `..` would miss it completely.
        """
        assert contained_authored_path(tmp_path, "/etc/passwd") is None

    def test_a_symlink_pointing_out_of_the_base_is_refused(self, tmp_path: Path) -> None:
        """The third vector, and the one lexical normalisation cannot see.

        This is where containment and `authored_path_exists` DIVERGE on
        purpose. A markdown renderer resolves a link by text, so a docs check
        predicting what a reader sees must stay lexical. An open() follows the
        symlink, so a check predicting what the daemon will READ must not.
        Same input, two correct answers, because the questions differ.
        """
        outside = tmp_path / "outside.md"
        outside.write_text("secret")
        base = tmp_path / "repo"
        base.mkdir()
        (base / "link.md").symlink_to(outside)

        assert contained_authored_path(base, "link.md") is None

    def test_a_symlink_staying_inside_the_base_is_allowed(self, tmp_path: Path) -> None:
        """Containment refuses ESCAPE, not symlinks as such."""
        base = tmp_path / "repo"
        (base / "real").mkdir(parents=True)
        (base / "real" / "x.md").write_text("hi")
        (base / "link.md").symlink_to(base / "real" / "x.md")

        assert contained_authored_path(base, "link.md") == base / "link.md"

    def test_a_symlinked_base_does_not_refuse_its_own_children(self, tmp_path: Path) -> None:
        """The false positive that would make this unusable.

        A checkout reached through a symlinked path (a worktree, a container
        mount) has a real path that differs from `base`. Comparing a resolved
        candidate against an UNRESOLVED base would refuse every file in such a
        repository.
        """
        real = tmp_path / "real-repo"
        real.mkdir()
        (real / "a.md").write_text("hi")
        base = tmp_path / "linked-repo"
        base.symlink_to(real)

        assert contained_authored_path(base, "a.md") == base / "a.md"

"""Tests for TDD common utilities."""

import pytest

from claude_code_hooks_daemon.strategies.tdd.common import (
    COMMON_TEST_DIRECTORIES,
    is_in_common_test_directory,
    matches_directory,
)


def test_common_test_directories_is_tuple() -> None:
    """COMMON_TEST_DIRECTORIES should be a tuple."""
    assert isinstance(COMMON_TEST_DIRECTORIES, tuple)


def test_common_test_directories_has_expected_entries() -> None:
    """COMMON_TEST_DIRECTORIES should contain expected test directory patterns.

    No leading slash (Plan 00458): matched project-relative via
    matches_path_segment, and a leading slash would never land at the start
    of a relative path's first segment.
    """
    assert "tests/" in COMMON_TEST_DIRECTORIES
    assert "test/" in COMMON_TEST_DIRECTORIES
    assert "__tests__/" in COMMON_TEST_DIRECTORIES
    assert "spec/" in COMMON_TEST_DIRECTORIES


def test_is_in_common_test_directory_positive_cases() -> None:
    """Files in common test directories should return True."""
    assert is_in_common_test_directory("/workspace/tests/unit/test_file.py") is True
    assert is_in_common_test_directory("/workspace/test/helpers.go") is True
    assert is_in_common_test_directory("/app/__tests__/Component.test.tsx") is True
    assert is_in_common_test_directory("/project/spec/model_spec.rb") is True


def test_is_in_common_test_directory_negative_cases() -> None:
    """Files NOT in common test directories should return False."""
    assert is_in_common_test_directory("/workspace/src/module.py") is False
    assert is_in_common_test_directory("/workspace/lib/helper.js") is False
    assert is_in_common_test_directory("/workspace/app/controller.php") is False


def test_a_directory_merely_ending_in_test_is_not_a_match() -> None:
    """``latest/`` merely ends in ``test/`` -- not a match (Plan 00458)."""
    assert is_in_common_test_directory("/workspace/latest/build.py") is False


def test_a_project_living_under_a_directory_named_tests_is_still_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project-relative matching must not be fooled by an ANCESTOR directory
    named ``tests`` -- only a ``tests/`` segment INSIDE the project should
    classify a file as already-a-test."""
    from pathlib import Path

    from claude_code_hooks_daemon.core import project_context as pc

    root = "/home/dev/tests/proj"
    monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
    monkeypatch.setattr(
        pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
    )

    assert is_in_common_test_directory(f"{root}/src/main.py") is False


@pytest.mark.parametrize("entry", COMMON_TEST_DIRECTORIES)
def test_every_entry_a_directory_merely_ending_in_it_is_not_a_match(entry: str) -> None:
    """Every entry of COMMON_TEST_DIRECTORIES, not just tests/ -- per review
    feedback on Plan 00458: the bare substring bug applied identically to
    test/, __tests__/ and spec/, and a fix proven against one entry does not
    prove it against the others."""
    # "x" prefixed directly onto the entry: the whole entry string is still
    # present as a substring, but its start is preceded by "x", not "/" --
    # the exact boundary a bare `in` test cannot see.
    collision = f"x{entry}".rstrip("/")
    assert is_in_common_test_directory(f"/workspace/{collision}/file.py") is False


@pytest.mark.parametrize("entry", COMMON_TEST_DIRECTORIES)
def test_every_entry_directly_present_is_still_a_match(entry: str) -> None:
    assert is_in_common_test_directory(f"/workspace/{entry}file.py") is True


def test_matches_directory_with_leading_slash() -> None:
    """Directory patterns with leading slash should match."""
    directories = ("/vendor/", "/node_modules/")
    assert matches_directory("/workspace/vendor/package/file.php", directories) is True
    assert matches_directory("/app/node_modules/lib/index.js", directories) is True
    assert matches_directory("/workspace/src/file.py", directories) is False


def test_matches_directory_without_leading_slash() -> None:
    """Directory patterns without leading slash should be normalized and match."""
    directories = ("vendor/", "node_modules/")
    assert matches_directory("/workspace/vendor/package/file.php", directories) is True
    assert matches_directory("/app/node_modules/lib/index.js", directories) is True


def test_matches_directory_without_trailing_slash() -> None:
    """Directory patterns without trailing slash should be normalized and match."""
    directories = ("/vendor", "/node_modules")
    assert matches_directory("/workspace/vendor/package/file.php", directories) is True
    assert matches_directory("/app/node_modules/lib/index.js", directories) is True


def test_matches_directory_no_patterns() -> None:
    """Empty directory tuple should return False for all paths."""
    directories: tuple[str, ...] = ()
    assert matches_directory("/workspace/src/file.py", directories) is False
    assert matches_directory("/workspace/vendor/file.php", directories) is False


def test_matches_directory_complex_patterns() -> None:
    """Complex nested directory patterns should match correctly."""
    directories = ("/tests/fixtures/", "/.venv/", "/migrations/")
    assert matches_directory("/workspace/tests/fixtures/data.json", directories) is True
    assert (
        matches_directory("/project/.venv/lib/python/site-packages/module.py", directories) is True
    )
    assert matches_directory("/app/migrations/001_initial.sql", directories) is True
    assert matches_directory("/workspace/tests/unit/test_file.py", directories) is False


class TestMatchesDirectoryIsProjectRelative:
    """``matches_directory`` used to match against the ABSOLUTE path even
    though it was already segment-bounded, so it did not share the
    substring-collision half of Plan 00458's defect, only the project-
    relativity half: a project living under an ancestor directory sharing a
    pattern's name had every file misclassified. Follow-up per the owner's
    "no half measures" rule -- extends the Plan 00458 fix to every
    per-language TDD strategy's ``_SOURCE_DIRECTORIES``/``_SKIP_DIRECTORIES``,
    which all share this one function."""

    def test_a_real_skip_dir_inside_the_project_is_still_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        root = "/proj"
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
        )

        assert matches_directory(f"{root}/vendor/lib.py", ("vendor/",)) is True

    def test_a_project_living_under_an_ancestor_named_like_a_skip_dir_is_still_tdd_gated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The team-lead's own example: a project cloned under
        ``/srv/vendor/app/`` must not have its own ``src/`` files
        misclassified as vendored just because ``vendor`` sits in an
        ANCESTOR directory -- TDD enforcement must still see them as
        ordinary source, not silently skipped."""
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        root = "/srv/vendor/app"
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
        )

        assert matches_directory(f"{root}/src/main.py", ("vendor/",)) is False

    def test_source_directory_classification_still_works_inside_the_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other direction: ``_SOURCE_DIRECTORIES`` entries carry a
        leading slash by convention (``"/src/"``) -- still classified
        correctly once stripped and resolved relative to the project."""
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        root = "/proj"
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
        )

        assert matches_directory(f"{root}/src/main.py", ("/src/",)) is True

    def test_a_project_living_under_an_ancestor_named_like_a_source_dir_is_not_misclassified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The team-lead's other example (``/home/u/build/proj/``, applied
        here to a source-directory pattern): a file that is NOT under the
        project's own ``src/`` must not be classified as one merely because
        ``src`` sits in an ancestor directory."""
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        root = "/home/u/src/proj"
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
        )

        assert matches_directory(f"{root}/lib/thing.py", ("/src/",)) is False

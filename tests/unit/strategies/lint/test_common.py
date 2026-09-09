"""Tests for Lint Strategy common utilities."""

import stat
import tempfile
from pathlib import Path

from claude_code_hooks_daemon.strategies.lint.common import (
    COMMON_SKIP_PATHS,
    lint_output_dir,
    matches_skip_path,
)


class TestCommonSkipPaths:
    def test_common_skip_paths_is_tuple(self) -> None:
        assert isinstance(COMMON_SKIP_PATHS, tuple)

    def test_common_skip_paths_contains_node_modules(self) -> None:
        assert "node_modules/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_dist(self) -> None:
        assert "dist/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_vendor(self) -> None:
        assert "vendor/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_build(self) -> None:
        assert ".build/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_coverage(self) -> None:
        assert "coverage/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_venv(self) -> None:
        assert ".venv/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_venv_no_dot(self) -> None:
        assert "venv/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_next(self) -> None:
        # Plan 00288 Task 3.2: newly-accepted core delta.
        assert ".next/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_third_party(self) -> None:
        # Plan 00288 Task 3.2: newly-accepted core delta.
        assert "third_party/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_keeps_pycache_and_git_as_domain_extras(self) -> None:
        # Not part of the core; lint keeps these two as its own extras
        # (measurement doc §3).
        assert "__pycache__/" in COMMON_SKIP_PATHS
        assert ".git/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_has_exact_membership(self) -> None:
        assert set(COMMON_SKIP_PATHS) == {
            "node_modules/",
            "vendor/",
            "third_party/",
            "dist/",
            "build/",
            ".build/",
            "target/",
            ".next/",
            ".venv/",
            "venv/",
            "coverage/",
            "__pycache__/",
            ".git/",
        }


class TestLintOutputDir:
    """One unpredictable, per-process destination for compiler artefacts.

    Kotlin and Rust both need somewhere to put the class files and metadata
    their check commands emit, and both used to name a fixed path in the
    shared temp directory. That is the classic insecure-temporary-directory
    shape: on a multi-user host another user can pre-create the name as a
    symlink and steer compiler output through it, and two concurrent lint runs
    share the directory regardless.
    """

    def test_the_directory_exists(self) -> None:
        assert Path(lint_output_dir()).is_dir()

    def test_the_path_is_absolute(self) -> None:
        """``lint_on_edit`` runs the command from an unspecified cwd."""
        assert Path(lint_output_dir()).is_absolute()

    def test_the_same_directory_is_reused_within_the_process(self) -> None:
        """A fresh directory per call would leak one per linted file."""
        assert lint_output_dir() == lint_output_dir()

    def test_the_name_is_not_predictable(self) -> None:
        """The whole point: a name an attacker can guess can be pre-created."""
        assert lint_output_dir() != str(Path(tempfile.gettempdir()) / "claude-hooks-daemon-lint")

    def test_only_the_owner_can_reach_it(self) -> None:
        """0700, so no other user can read the artefacts or swap the target."""
        mode = Path(lint_output_dir()).stat().st_mode
        assert stat.S_IMODE(mode) == 0o700

    def test_the_path_carries_no_shell_metacharacter(self) -> None:
        """It is interpolated into a command run with no shell.

        ``tempfile`` draws its suffix from an alphanumeric alphabet, so this
        holds by construction -- but the command strings are asserted safe in
        ``test_lint_commands_are_runnable_as_declared.py`` and this is the one
        component of them that is not a literal.
        """
        assert not set(lint_output_dir()) & set(" \t'\"|&;<>$`*?()[]{}!#~")


class TestMatchesSkipPath:
    def test_matches_node_modules(self) -> None:
        assert matches_skip_path("/workspace/node_modules/pkg/index.js", COMMON_SKIP_PATHS) is True

    def test_matches_dist(self) -> None:
        assert matches_skip_path("/workspace/dist/bundle.js", COMMON_SKIP_PATHS) is True

    def test_matches_vendor(self) -> None:
        assert matches_skip_path("/workspace/vendor/lib/foo.rb", COMMON_SKIP_PATHS) is True

    def test_does_not_match_src(self) -> None:
        assert matches_skip_path("/workspace/src/app/main.py", COMMON_SKIP_PATHS) is False

    def test_does_not_match_lib(self) -> None:
        assert matches_skip_path("/workspace/lib/helper.rb", COMMON_SKIP_PATHS) is False

    def test_matches_custom_skip_paths(self) -> None:
        custom = ("custom_skip/",)
        assert matches_skip_path("/workspace/custom_skip/foo.py", custom) is True

    def test_does_not_match_custom_skip_paths(self) -> None:
        custom = ("custom_skip/",)
        assert matches_skip_path("/workspace/src/foo.py", custom) is False

    def test_empty_skip_paths(self) -> None:
        assert matches_skip_path("/workspace/anything/foo.py", ()) is False

    def test_matches_venv(self) -> None:
        assert (
            matches_skip_path("/workspace/.venv/lib/python3.12/site.py", COMMON_SKIP_PATHS) is True
        )

    def test_does_not_match_build_as_substring_of_rebuild(self) -> None:
        # Plan 00295 Task 1.1: "build/" must not match inside "rebuild/" --
        # that is a different, first-party directory that merely ends with
        # the same letters.
        custom = ("build/",)
        assert matches_skip_path("src/rebuild/x.py", custom) is False

    def test_does_not_match_venv_as_substring_of_myvenv(self) -> None:
        custom = ("venv/",)
        assert matches_skip_path("src/myvenv/x.py", custom) is False

    def test_does_not_match_build_as_substring_of_prebuild(self) -> None:
        custom = ("build/",)
        assert matches_skip_path("app/prebuild/y.ts", custom) is False

    def test_matches_build_as_a_real_path_segment(self) -> None:
        custom = ("build/",)
        assert matches_skip_path("app/build/y.ts", custom) is True

    def test_matches_build_at_start_of_path_with_no_leading_separator(self) -> None:
        custom = ("build/",)
        assert matches_skip_path("build/y.ts", custom) is True

    def test_matches_real_segment_even_when_a_false_substring_precedes_it(self) -> None:
        # "rebuild/" is a false hit but "build/" also occurs later as a real
        # segment -- the real occurrence must still be found.
        custom = ("build/",)
        assert matches_skip_path("src/rebuild/build/x.py", custom) is True

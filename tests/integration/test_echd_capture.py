"""Plan 00164 Phase 6 — the `echd-capture` output-capture helper.

Agents defeat the pipe_blocker with pointless theatre: they redirect full output
to a file and then echo ALL of it to stdout anyway (net token bloat). The intent
of "capture full, read a slice" is exactly what a helper should make trivial.

`echd-capture` reads stdin, tees the FULL stream to a capture file, and prints
only a bounded preview (tail by default, or head) followed by the absolute path
to the full capture for follow-up. These tests exercise the bundled template
(the file ``install.bin_wrapper.deploy_echd_capture`` copies to
``{daemon_root}/bin/echd-capture``, Plan 00362 Task 1.3) directly via a bash
pipeline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ECHD_CAPTURE = (
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "echd-capture"
)


def _run_pipe_with_env(
    producer: str, capture_args: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run ``producer | echd-capture <capture_args>`` under an explicit env."""
    # Group the producer so its full stdout (and exit status) flows into the pipe.
    script = f"set -o pipefail\n{{ {producer} ; }} | '{ECHD_CAPTURE}' {capture_args}\n"
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", **env},
    )


def _run_pipe(
    producer: str, capture_args: str, capture_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Run ``producer | echd-capture <capture_args>`` with a controlled dir."""
    return _run_pipe_with_env(producer, capture_args, {"ECHD_CAPTURE_DIR": str(capture_dir)})


def _capture_file_from_output(stdout: str) -> Path:
    """Extract the absolute capture path the helper prints in its footer.

    The footer prints ``(full output: /abs/path.txt)`` so strip the surrounding
    parenthesis punctuation from the extracted token.
    """
    for token in stdout.replace("\n", " ").split():
        cleaned = token.strip("()")
        if cleaned.startswith("/") and "command-output" in cleaned:
            return Path(cleaned)
    raise AssertionError(f"No capture path found in output:\n{stdout}")


def test_helper_exists_and_executable() -> None:
    assert ECHD_CAPTURE.is_file(), f"Expected helper at {ECHD_CAPTURE} (Plan 00164 Phase 6)"
    import os

    assert os.access(ECHD_CAPTURE, os.X_OK), f"{ECHD_CAPTURE} must be executable"


def test_default_shows_tail_preview(tmp_path: Path) -> None:
    """Default preview is the LAST N lines (N defaults to 20)."""
    producer = "printf 'L%s\\n' $(seq 1 50)"
    result = _run_pipe(producer, "5", tmp_path)
    assert result.returncode == 0, result.stderr
    # Last 5 lines present; an early line NOT present in the preview.
    assert "L50" in result.stdout
    assert "L46" in result.stdout
    assert "L1\n" not in result.stdout


def test_full_output_captured_to_file(tmp_path: Path) -> None:
    """Even when only a few preview lines show, the FULL stream is captured."""
    producer = "printf 'L%s\\n' $(seq 1 50)"
    result = _run_pipe(producer, "5", tmp_path)
    capture = _capture_file_from_output(result.stdout)
    assert capture.is_file()
    body = capture.read_text()
    assert "L1\n" in body
    assert "L50\n" in body
    assert body.count("\n") == 50


def test_head_mode(tmp_path: Path) -> None:
    producer = "printf 'L%s\\n' $(seq 1 50)"
    result = _run_pipe(producer, "--head 5", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "L1" in result.stdout
    assert "L5" in result.stdout
    assert "L50\n" not in result.stdout


def test_footer_reports_absolute_path_and_line_count(tmp_path: Path) -> None:
    producer = "printf 'L%s\\n' $(seq 1 12)"
    result = _run_pipe(producer, "3", tmp_path)
    capture = _capture_file_from_output(result.stdout)
    assert capture.is_absolute()
    # The footer should name how many lines the full capture holds.
    assert "12" in result.stdout


def test_preserves_upstream_failure_with_pipefail(tmp_path: Path) -> None:
    """With `set -o pipefail`, a failing producer makes the pipeline non-zero
    even though the helper itself succeeds — so agents still see failures."""
    producer = "printf 'partial\\n'; exit 7"
    result = _run_pipe(producer, "5", tmp_path)
    assert (
        result.returncode == 7
    ), f"pipefail pipeline must surface the producer's non-zero exit; got {result.returncode}"
    # Output was still captured despite the failure.
    capture = _capture_file_from_output(result.stdout)
    assert "partial" in capture.read_text()


def test_short_output_shown_in_full(tmp_path: Path) -> None:
    """When the stream is shorter than N, the whole thing is the preview."""
    producer = "printf 'only-line\\n'"
    result = _run_pipe(producer, "20", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "only-line" in result.stdout


def test_all_mode_prints_the_whole_stream(tmp_path: Path) -> None:
    """``--all`` captures as usual but shows every line as the preview."""
    producer = "printf 'L%s\\n' $(seq 1 40)"
    result = _run_pipe(producer, "--all", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "L1\n" in result.stdout
    assert "L40\n" in result.stdout
    # The footer says "all 40" rather than naming a truncated slice.
    assert "showing all 40 lines" in result.stdout
    capture = _capture_file_from_output(result.stdout)
    assert capture.read_text().count("\n") == 40


def test_label_is_embedded_in_the_capture_filename(tmp_path: Path) -> None:
    """``--label NAME`` makes a capture identifiable among its siblings."""
    result = _run_pipe("printf 'x\\n'", "--label pytest-run 5", tmp_path)
    assert result.returncode == 0, result.stderr
    capture = _capture_file_from_output(result.stdout)
    assert capture.name.startswith("command-output-pytest-run-")


def test_label_unsafe_characters_are_replaced(tmp_path: Path) -> None:
    """A label carrying path separators or spaces cannot escape the dir."""
    result = _run_pipe("printf 'x\\n'", "--label 'a b/../c' 5", tmp_path)
    assert result.returncode == 0, result.stderr
    capture = _capture_file_from_output(result.stdout)
    assert capture.parent == tmp_path
    # Separators, spaces and dots all collapse to underscores.
    assert capture.name.startswith("command-output-a_b____c-")


def test_unknown_argument_exits_two(tmp_path: Path) -> None:
    """A mistyped flag is a usage error, not a silent default."""
    result = _run_pipe("printf 'x\\n'", "--bogus", tmp_path)
    assert result.returncode == 2, result.stdout
    assert "unknown argument: --bogus" in result.stderr


class TestCaptureDirectoryUnusable:
    """The helper must never eat the stream it exists to preserve.

    pipe_blocker tells every agent to use this helper INSTEAD of a truncating
    pipe, on the grounds that truncation loses data. A capture directory that
    cannot be created must therefore degrade to a plain pass-through, not
    consume stdin and report success with an empty preview.
    """

    def test_stream_passes_through_when_dir_cannot_be_created(self, tmp_path: Path) -> None:
        """Parent exists but refuses directory creation: every byte still shows."""
        result = _run_pipe("printf 'line-a\\nline-b\\nline-c\\n'", "2", Path("/proc/nonexistent/x"))
        assert "line-a" in result.stdout
        assert "line-b" in result.stdout
        assert "line-c" in result.stdout

    def test_pass_through_warns_on_stderr(self, tmp_path: Path) -> None:
        """The degradation is announced, so nobody thinks a capture exists."""
        result = _run_pipe("printf 'line-a\\n'", "2", Path("/proc/nonexistent/x"))
        assert "echd-capture" in result.stderr
        assert "passing output through unchanged" in result.stderr
        # No footer: there is no capture file to point at.
        assert "full output:" not in result.stdout

    def test_pass_through_when_parent_is_a_regular_file(self, tmp_path: Path) -> None:
        """ENOTDIR is the portable form of the same failure."""
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("regular file\n", encoding="utf-8")
        result = _run_pipe("printf 'kept\\n'", "2", blocker / "captures")
        assert "kept" in result.stdout
        assert "passing output through unchanged" in result.stderr

    def test_capture_write_failure_exits_non_zero(self, tmp_path: Path) -> None:
        """Directory exists but holds no files: fail loudly rather than exit 0.

        ``/proc`` is the root-proof trigger — ``mkdir -p`` succeeds because it
        already exists, and creating a regular file inside it fails for every
        user, so this pins the branch without relying on file permissions.
        """
        result = _run_pipe("printf 'x\\n'", "2", Path("/proc"))
        assert result.returncode == 1, f"expected a loud failure, got {result.returncode}"
        assert "echd-capture" in result.stderr
        assert "full output:" not in result.stdout


class TestTheLastResortDirectoryIsUnpredictable:
    """Plan 00364 Task 2.8.

    With no project root and no explicit override the helper fell back to a
    FIXED name in a world-writable directory. ``mkdir -p`` follows a
    pre-existing symlink, so anyone who created that name first could
    redirect every capture on the machine to a path they control. The
    fallback is rare but it is the branch that fires when
    ``CLAUDE_PROJECT_DIR`` is unset, which is how it was noticed.
    """

    def test_the_fallback_dir_is_not_a_fixed_name(self, tmp_path: Path) -> None:
        result = _run_pipe_with_env("printf 'x\\n'", "2", {"TMPDIR": str(tmp_path)})
        assert result.returncode == 0, result.stderr

        capture = _capture_file_from_output(result.stdout)
        assert capture.parent.parent == tmp_path
        assert capture.parent != tmp_path / "echd-captures"

    def test_two_runs_do_not_share_a_directory(self, tmp_path: Path) -> None:
        """An attacker cannot pre-create the name, because it is not known."""
        first = _run_pipe_with_env("printf 'x\\n'", "2", {"TMPDIR": str(tmp_path)})
        second = _run_pipe_with_env("printf 'y\\n'", "2", {"TMPDIR": str(tmp_path)})

        one = _capture_file_from_output(first.stdout).parent
        two = _capture_file_from_output(second.stdout).parent
        assert one != two

    def test_the_fallback_dir_is_private_to_its_owner(self, tmp_path: Path) -> None:
        result = _run_pipe_with_env("printf 'x\\n'", "2", {"TMPDIR": str(tmp_path)})
        capture = _capture_file_from_output(result.stdout)
        assert capture.parent.stat().st_mode & 0o077 == 0

    def test_an_explicit_override_still_wins(self, tmp_path: Path) -> None:
        """The precedence chain is unchanged; only the last rung moved."""
        explicit = tmp_path / "explicit"
        result = _run_pipe_with_env(
            "printf 'x\\n'",
            "2",
            {"ECHD_CAPTURE_DIR": str(explicit), "TMPDIR": str(tmp_path / "ignored")},
        )
        assert _capture_file_from_output(result.stdout).parent == explicit

    def test_a_project_dir_still_wins_over_the_fallback(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        result = _run_pipe_with_env(
            "printf 'x\\n'",
            "2",
            {"CLAUDE_PROJECT_DIR": str(project), "TMPDIR": str(tmp_path / "ignored")},
        )
        assert _capture_file_from_output(result.stdout).parent == project / "untracked" / "captures"

    def test_an_uncreatable_fallback_still_passes_the_stream_through(self, tmp_path: Path) -> None:
        """The pass-through promise holds for this branch too."""
        result = _run_pipe_with_env(
            "printf 'kept-a\\nkept-b\\n'", "2", {"TMPDIR": "/proc/nonexistent/nope"}
        )
        assert "kept-a" in result.stdout
        assert "kept-b" in result.stdout
        assert "full output:" not in result.stdout
        assert "echd-capture" in result.stderr


class TestHelpStopsAtTheHeader:
    """``--help`` prints the usage block, not every comment in the file.

    Plan 00364 Task 2.8. It ran a comment-extraction pipeline over the whole
    script, so the help text trailed off into the implementation's own
    inline rationale — including the comments explaining the failure modes,
    which is not what a user asking for usage wants.
    """

    def _help(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(ECHD_CAPTURE), "--help"],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )

    def test_the_usage_block_is_printed(self) -> None:
        result = self._help()
        assert result.returncode == 0
        assert "capture full piped output" in result.stdout
        assert "--label NAME" in result.stdout
        assert "Capture directory precedence" in result.stdout

    def test_implementation_comments_are_not_printed(self) -> None:
        """Everything below the first line of code is the script's business."""
        result = self._help()
        assert "Filesystem-safe label" not in result.stdout
        assert "Unique capture filename" not in result.stdout
        assert "Emit the bounded preview" not in result.stdout

    def test_the_shebang_is_not_printed_as_help(self) -> None:
        result = self._help()
        assert "/bin/bash" not in result.stdout

    def test_short_form_matches_long_form(self) -> None:
        short = subprocess.run(
            ["bash", str(ECHD_CAPTURE), "-h"],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
        assert short.stdout == self._help().stdout


def test_the_deployed_copy_matches_the_template() -> None:
    """``bin/echd-capture`` is the template, deployed. Drift is invisible."""
    deployed = REPO_ROOT / "bin" / "echd-capture"
    assert deployed.read_text(encoding="utf-8") == ECHD_CAPTURE.read_text(encoding="utf-8")

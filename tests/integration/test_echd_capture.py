"""Plan 00164 Phase 6 — the `echd-capture` output-capture helper.

Agents defeat the pipe_blocker with pointless theatre: they redirect full output
to a file and then echo ALL of it to stdout anyway (net token bloat). The intent
of "capture full, read a slice" is exactly what a helper should make trivial.

`echd-capture` reads stdin, tees the FULL stream to a capture file, and prints
only a bounded preview (tail by default, or head) followed by the absolute path
to the full capture for follow-up. These tests exercise the deployed script
directly via a bash pipeline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ECHD_CAPTURE = REPO_ROOT / "scripts" / "echd-capture"


def _run_pipe(
    producer: str, capture_args: str, capture_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Run ``producer | echd-capture <capture_args>`` with a controlled dir."""
    # Group the producer so its full stdout (and exit status) flows into the pipe.
    script = f"set -o pipefail\n{{ {producer} ; }} | '{ECHD_CAPTURE}' {capture_args}\n"
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={"ECHD_CAPTURE_DIR": str(capture_dir), "PATH": "/usr/bin:/bin"},
    )


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
    assert result.returncode == 7, (
        "pipefail pipeline must surface the producer's non-zero exit; " f"got {result.returncode}"
    )
    # Output was still captured despite the failure.
    capture = _capture_file_from_output(result.stdout)
    assert "partial" in capture.read_text()


def test_short_output_shown_in_full(tmp_path: Path) -> None:
    """When the stream is shorter than N, the whole thing is the preview."""
    producer = "printf 'only-line\\n'"
    result = _run_pipe(producer, "20", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "only-line" in result.stdout

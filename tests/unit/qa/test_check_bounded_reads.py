"""Tests for the bounded-intent-unbounded-read QA checker (Plan 00231).

The defect class: code that DECLARES a bound (``maxlen=N``, a slice) while
reading a file UNBOUNDEDLY. ``deque(f, maxlen=20)`` says "I want twenty lines"
and then iterates every line in the file to get them — 162 ms on a 74 MB
transcript versus 17 ms for the equivalent bounded seek, growing linearly and
forever as the file appends.

The declared bound is what makes this mechanically checkable: it is the
author's own statement of intent, sitting next to a read that ignores it. A
whole-file read with NO declared bound is not a defect (loading a config is
fine), which is why the rule keys on the pair rather than on reads alone.

Plan 00177 fixed exactly this in ``TranscriptReader.load_tail`` by seeking.
It did not fix the sibling ``has_recent_stop_hook_block``, which kept the
``deque`` spelling — a hand-fix cannot generalise, so this checker exists to
make the class unrepeatable rather than to remove one instance.
"""

import json
import subprocess  # nosec B404 - subprocess used for running the QA checker only
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_bounded_reads.py"
_JSON_OUTPUT = _REPO_ROOT / "untracked" / "qa" / "bounded_reads.json"


def _run_checker(scan_path: Path) -> dict[str, Any]:
    """Run the checker against ``scan_path`` and return its parsed JSON."""
    subprocess.run(  # nosec B603 - trusted first-party checker script
        [sys.executable, str(_CHECKER), "--json", "--path", str(scan_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert _JSON_OUTPUT.exists(), f"Expected JSON output at {_JSON_OUTPUT}"
    data: dict[str, Any] = json.loads(_JSON_OUTPUT.read_text())
    return data


def _write(tmp_path: Path, source: str) -> Path:
    """Write ``source`` as a module in an isolated scan directory."""
    module = tmp_path / "sample.py"
    module.write_text(source, encoding="utf-8")
    return tmp_path


def _violations(tmp_path: Path, source: str) -> list[dict[str, Any]]:
    data = _run_checker(_write(tmp_path, source))
    violations: list[dict[str, Any]] = data["violations"]
    return violations


class TestDequeOverAFileHandle:
    """``deque(f, maxlen=N)`` — the exact shape found in stop_hook_helpers."""

    def test_flags_deque_maxlen_over_with_open_handle(self, tmp_path: Path) -> None:
        """The bug as written: bounded intent, whole-file iteration."""
        violations = _violations(
            tmp_path,
            "from collections import deque\n"
            "def tail(path):\n"
            "    with open(path) as f:\n"
            "        return deque(f, maxlen=20)\n",
        )
        assert len(violations) == 1
        assert violations[0]["rule"] == "bounded-intent-unbounded-read"
        assert violations[0]["line"] == 4

    def test_flags_deque_over_path_open_handle(self, tmp_path: Path) -> None:
        """``Path.open()`` binds a file handle just as ``open()`` does."""
        violations = _violations(
            tmp_path,
            "from collections import deque\n"
            "def tail(path):\n"
            "    with path.open('rb') as handle:\n"
            "        return deque(handle, maxlen=5)\n",
        )
        assert len(violations) == 1

    def test_ignores_deque_over_an_in_memory_sequence(self, tmp_path: Path) -> None:
        """A bounded window over a list is free — nothing is re-read."""
        violations = _violations(
            tmp_path,
            "from collections import deque\n"
            "def recent(items):\n"
            "    return deque(items, maxlen=20)\n",
        )
        assert violations == []

    def test_ignores_deque_without_maxlen(self, tmp_path: Path) -> None:
        """No declared bound means no contradiction to detect."""
        violations = _violations(
            tmp_path,
            "from collections import deque\n"
            "def all_lines(path):\n"
            "    with open(path) as f:\n"
            "        return deque(f)\n",
        )
        assert violations == []


class TestSlicedWholeFileReads:
    """A slice applied to a materialised whole-file read."""

    def test_flags_readlines_with_tail_slice(self, tmp_path: Path) -> None:
        violations = _violations(
            tmp_path,
            "def tail(path):\n"
            "    with open(path) as f:\n"
            "        return f.readlines()[-20:]\n",
        )
        assert len(violations) == 1

    def test_flags_read_text_splitlines_with_head_slice(self, tmp_path: Path) -> None:
        """Head slices waste just as much as tail slices."""
        violations = _violations(
            tmp_path,
            "from pathlib import Path\n"
            "def head(path):\n"
            "    return Path(path).read_text().splitlines()[:10]\n",
        )
        assert len(violations) == 1

    def test_flags_list_over_handle_with_slice(self, tmp_path: Path) -> None:
        violations = _violations(
            tmp_path,
            "def tail(path):\n    with open(path) as f:\n        return list(f)[-3:]\n",
        )
        assert len(violations) == 1

    def test_ignores_unsliced_readlines(self, tmp_path: Path) -> None:
        """Reading a whole file on purpose is not this rule's business."""
        violations = _violations(
            tmp_path,
            "def every_line(path):\n    with open(path) as f:\n        return f.readlines()\n",
        )
        assert violations == []

    def test_ignores_indexing_a_whole_file_read(self, tmp_path: Path) -> None:
        """A single index is not a declared window; only slices are."""
        violations = _violations(
            tmp_path,
            "def first(path):\n    with open(path) as f:\n        return f.readlines()[0]\n",
        )
        assert violations == []


class TestCorrectPatternsStaySilent:
    """The remedies this rule steers toward must never be flagged."""

    def test_ignores_bounded_seek_read(self, tmp_path: Path) -> None:
        """The ``load_tail`` shape: seek to a window, read only that."""
        violations = _violations(
            tmp_path,
            "def tail(path, size, max_bytes):\n"
            "    with open(path, 'rb') as f:\n"
            "        f.seek(max(0, size - max_bytes))\n"
            "        return f.read().splitlines()\n",
        )
        assert violations == []

    def test_ignores_streaming_iteration(self, tmp_path: Path) -> None:
        """Line-by-line iteration is bounded in MEMORY and declares no window."""
        violations = _violations(
            tmp_path,
            "def scan(path):\n"
            "    with open(path) as f:\n"
            "        for line in f:\n"
            "            yield line\n",
        )
        assert violations == []

    def test_ignores_islice_head(self, tmp_path: Path) -> None:
        """``islice`` over a handle is lazy — it stops reading at N."""
        violations = _violations(
            tmp_path,
            "from itertools import islice\n"
            "def head(path):\n"
            "    with open(path) as f:\n"
            "        return list(islice(f, 10))\n",
        )
        assert violations == []


class TestEscapeHatch:
    """A genuine exception is declared in place, following project convention."""

    def test_inline_marker_exempts_the_line(self, tmp_path: Path) -> None:
        violations = _violations(
            tmp_path,
            "from collections import deque\n"
            "def tail(path):\n"
            "    with open(path) as f:\n"
            "        # bounded-read-exempt: fixture file, never exceeds 10 lines\n"
            "        return deque(f, maxlen=20)\n",
        )
        assert violations == []


class TestTheCheckerReportsUsefully:
    """A finding must name the file, line and remedy."""

    def test_violation_carries_file_line_and_remediation(self, tmp_path: Path) -> None:
        violations = _violations(
            tmp_path,
            "from collections import deque\n"
            "def tail(path):\n"
            "    with open(path) as f:\n"
            "        return deque(f, maxlen=20)\n",
        )
        assert len(violations) == 1
        finding = violations[0]
        assert finding["file"].endswith("sample.py")
        assert finding["line"] == 4
        assert "seek" in finding["message"].lower()

    def test_clean_tree_reports_passed(self, tmp_path: Path) -> None:
        data = _run_checker(_write(tmp_path, "def noop():\n    return 1\n"))
        assert data["summary"]["passed"] is True
        assert data["summary"]["total_violations"] == 0

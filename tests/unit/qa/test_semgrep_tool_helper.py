"""The shared semgrep argv helper pins the interpreter next to the version."""

from pathlib import Path

import pytest

from tests.support import semgrep_tool

_PYTHON_PIN_FILE = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "semgrep-python.txt"


class TestSemgrepArgv:
    def test_argv_passes_the_pinned_python(self) -> None:
        pin = _PYTHON_PIN_FILE.read_text(encoding="utf-8").strip()
        argv = semgrep_tool.semgrep_argv()
        assert argv[argv.index("--python") + 1] == pin

    def test_a_missing_python_pin_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(semgrep_tool, "_PYTHON_FILE", tmp_path / "absent.txt")
        with pytest.raises(RuntimeError, match="no semgrep python pinned"):
            semgrep_tool.semgrep_argv()

    def test_an_empty_python_pin_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        empty = tmp_path / "python.txt"
        empty.write_text("\n", encoding="utf-8")
        monkeypatch.setattr(semgrep_tool, "_PYTHON_FILE", empty)
        with pytest.raises(RuntimeError, match="no semgrep python pinned"):
            semgrep_tool.semgrep_argv()

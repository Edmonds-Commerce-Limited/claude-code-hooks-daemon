"""Tests for scripts/qa/check_module_length.py (N314, report-only)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "check_module_length.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_module_length", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_module_length = _load()


def _module(root: Path, relative: str, lines: int) -> None:
    path = root / "src" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n" * lines, encoding="utf-8")


class TestScan:
    def test_a_module_over_the_bound_is_reported(self, tmp_path: Path) -> None:
        _module(tmp_path, "pkg/big.py", check_module_length.MAX_MODULE_LINES + 1)
        findings, scanned = check_module_length.scan(tmp_path)
        assert [f.file for f in findings] == ["src/pkg/big.py"]
        assert findings[0].lines == check_module_length.MAX_MODULE_LINES + 1
        assert scanned == 1

    def test_a_module_at_the_bound_is_not_reported(self, tmp_path: Path) -> None:
        _module(tmp_path, "pkg/edge.py", check_module_length.MAX_MODULE_LINES)
        findings, _scanned = check_module_length.scan(tmp_path)
        assert findings == []

    def test_findings_are_ordered_longest_first(self, tmp_path: Path) -> None:
        bound = check_module_length.MAX_MODULE_LINES
        _module(tmp_path, "a.py", bound + 5)
        _module(tmp_path, "b.py", bound + 50)
        findings, _scanned = check_module_length.scan(tmp_path)
        assert [f.file for f in findings] == ["src/b.py", "src/a.py"]

    def test_only_python_under_src_is_scanned(self, tmp_path: Path) -> None:
        bound = check_module_length.MAX_MODULE_LINES
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "long.py").write_text("x = 1\n" * (bound + 1))
        _module(tmp_path, "notes.txt", bound + 1)
        findings, scanned = check_module_length.scan(tmp_path)
        assert findings == []
        assert scanned == 0

    def test_a_missing_src_directory_fails_fast(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            check_module_length.scan(tmp_path)


class TestMain:
    def test_exits_zero_even_with_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _module(tmp_path, "big.py", check_module_length.MAX_MODULE_LINES + 1)
        assert check_module_length.main(["--root", str(tmp_path)]) == 0
        output = capsys.readouterr().out
        assert "src/big.py" in output
        assert "owner" in output

    def test_exits_zero_and_says_so_when_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _module(tmp_path, "small.py", 3)
        assert check_module_length.main(["--root", str(tmp_path)]) == 0
        assert "No module over" in capsys.readouterr().out

    def test_a_missing_src_is_an_operational_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert check_module_length.main(["--root", str(tmp_path)]) == 2
        assert "ERROR" in capsys.readouterr().err

    def test_an_empty_src_is_an_operational_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "src").mkdir()
        assert check_module_length.main(["--root", str(tmp_path)]) == 2
        assert "found no modules" in capsys.readouterr().err

    def test_json_artifact_is_written(self, tmp_path: Path) -> None:
        _module(tmp_path, "big.py", check_module_length.MAX_MODULE_LINES + 1)
        assert check_module_length.main(["--root", str(tmp_path), "--json"]) == 0
        payload = json.loads(
            (tmp_path / "untracked" / "qa" / "module_length.json").read_text(encoding="utf-8")
        )
        assert payload["tool"] == "module_length"
        assert payload["summary"]["mode"] == "report-only"
        assert payload["summary"]["modules_over_bound"] == 1
        assert payload["summary"]["files_scanned"] == 1
        assert payload["summary"]["bound"] == check_module_length.MAX_MODULE_LINES
        assert payload["violations"][0]["file"] == "src/big.py"

    def test_report_stdout_prints_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _module(tmp_path, "small.py", 3)
        assert check_module_length.main(["--root", str(tmp_path), "--report-stdout"]) == 0
        assert json.loads(capsys.readouterr().out)["summary"]["files_scanned"] == 1

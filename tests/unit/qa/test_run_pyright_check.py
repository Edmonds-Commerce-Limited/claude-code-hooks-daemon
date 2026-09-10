"""Tests for the pyright QA gate (Plan 00368 Task 2.1).

The gate exists so that every diagnostic the language server shows an agent
is a real defect: ``pyright --project <root> --outputjson`` over the tree
``pyrightconfig.json`` scopes, failing on ANY error-severity diagnostic.

Three things are pinned here, each for a reason:

- The plumbing is proved against pyright ITSELF (a fixture tree with one
  deliberate error fails; a clean one passes), not against a mocked JSON
  blob, because the JSON shape is pyright's contract and a parser that only
  ever sees its own test data cannot notice when that contract moves.
- A missing binary is a tool FAILURE carrying a one-line install
  instruction, never a skip. A gate that silently stands down when its tool
  is absent reports green for a tree it never looked at.
- The ``llm_qa.py`` wiring (registry entry, summariser, position before
  ``smoke_test``) is asserted the way the other tools' wiring is.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"

# A return of ``int`` where ``str`` is declared: reportReturnType, an ERROR
# under pyright's default rule set, so it fails the gate without any project
# configuration and without depending on this repo's own pyrightconfig.
_ONE_ERROR_SOURCE = "def f(x: int) -> str:\n    return x\n"
_CLEAN_SOURCE = "def f(x: int) -> str:\n    return str(x)\n"


def _load_module(name: str) -> types.ModuleType:
    """Import a ``scripts/qa`` module by path (the directory is not a package)."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> types.ModuleType:
    return _load_module("run_pyright_check")


@pytest.fixture(scope="module")
def llm_qa() -> types.ModuleType:
    return _load_module("llm_qa")


def _fixture_tree(root: Path, source: str) -> Path:
    """A minimal pyright project: one package, one module, a config scoping it."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text(source, encoding="utf-8")
    (root / "pyrightconfig.json").write_text(json.dumps({"include": ["pkg"]}), encoding="utf-8")
    return root


def _report(root: Path, checker: types.ModuleType) -> dict[str, Any]:
    path = root / "untracked" / "qa" / checker.OUTPUT_FILENAME
    assert path.is_file(), f"no report written at {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# ── Binary resolution ──────────────────────────────────────────────


class TestBinaryResolution:
    def test_prefers_the_venv_sibling_of_the_interpreter(
        self, checker: types.ModuleType, tmp_path: Path
    ) -> None:
        venv_bin = tmp_path / "bin"
        venv_bin.mkdir()
        sibling = venv_bin / "pyright"
        sibling.write_text("#!/bin/sh\n", encoding="utf-8")
        sibling.chmod(0o755)
        resolved = checker.resolve_pyright_binary(
            venv_bin=venv_bin, path_lookup=lambda _name: "/usr/local/bin/pyright"
        )
        assert resolved == sibling

    def test_falls_back_to_path(self, checker: types.ModuleType, tmp_path: Path) -> None:
        resolved = checker.resolve_pyright_binary(
            venv_bin=tmp_path / "nowhere", path_lookup=lambda _name: "/opt/bin/pyright"
        )
        assert resolved == Path("/opt/bin/pyright")

    def test_none_when_absent_everywhere(self, checker: types.ModuleType, tmp_path: Path) -> None:
        resolved = checker.resolve_pyright_binary(
            venv_bin=tmp_path / "nowhere", path_lookup=lambda _name: None
        )
        assert resolved is None

    def test_the_project_venv_carries_pyright(self, checker: types.ModuleType) -> None:
        """The dev extra installs it; the gate must not depend on a global install."""
        resolved = checker.resolve_pyright_binary(path_lookup=lambda _name: None)
        assert resolved is not None, (
            "pyright is not in the QA interpreter's venv. It is a pinned dev extra "
            "(pyproject.toml); provision with "
            "`UV_PROJECT_ENVIRONMENT=<the QA venv> uv sync --frozen --all-extras`."
        )


# ── Real runs against pyright ──────────────────────────────────────


class TestGateAgainstRealPyright:
    def test_one_deliberate_error_fails(self, checker: types.ModuleType, tmp_path: Path) -> None:
        root = _fixture_tree(tmp_path, _ONE_ERROR_SOURCE)
        exit_code = checker.main(["--json", "--root", str(root)])
        assert exit_code == checker.EXIT_ERRORS
        report = _report(root, checker)
        assert report["tool"] == "pyright"
        assert report["summary"]["passed"] is False
        assert report["summary"]["total_errors"] == 1
        assert report["summary"]["files_analyzed"] == 1
        (error,) = report["errors"]
        assert error["file"] == "pkg/mod.py"
        assert error["line"] == 2
        assert error["rule"] == "reportReturnType"
        assert "str" in error["message"]

    def test_clean_tree_passes(self, checker: types.ModuleType, tmp_path: Path) -> None:
        root = _fixture_tree(tmp_path, _CLEAN_SOURCE)
        exit_code = checker.main(["--json", "--root", str(root)])
        assert exit_code == checker.EXIT_SUCCESS
        report = _report(root, checker)
        assert report["summary"]["passed"] is True
        assert report["summary"]["total_errors"] == 0
        assert report["summary"]["files_analyzed"] == 1
        assert report["errors"] == []
        assert report["summary"]["pyright_version"]

    def test_config_exclude_is_honoured(self, checker: types.ModuleType, tmp_path: Path) -> None:
        """The gate analyses what pyrightconfig.json scopes, nothing wider."""
        root = _fixture_tree(tmp_path, _CLEAN_SOURCE)
        noise = root / "untracked" / "other" / "pkg"
        noise.mkdir(parents=True)
        (noise / "mod.py").write_text(_ONE_ERROR_SOURCE, encoding="utf-8")
        assert checker.main(["--json", "--root", str(root)]) == checker.EXIT_SUCCESS


# ── Failure modes ──────────────────────────────────────────────────


class TestMissingBinaryIsAFailure:
    def test_reports_failure_with_install_instruction(
        self, checker: types.ModuleType, tmp_path: Path
    ) -> None:
        root = _fixture_tree(tmp_path, _CLEAN_SOURCE)
        exit_code = checker.main(
            ["--json", "--root", str(root), "--pyright", str(tmp_path / "missing" / "pyright")]
        )
        assert exit_code == checker.EXIT_OPERATIONAL
        report = _report(root, checker)
        assert report["summary"]["passed"] is False
        error = report["summary"]["error"]
        assert "uv sync --frozen --all-extras" in error
        # A bare `uv sync` targets uv's default .venv, not the QA venv, so an
        # instruction without this env var installs where the gate never looks.
        assert "UV_PROJECT_ENVIRONMENT" in error
        assert report["errors"] == []


class TestInterpreterIsPassedExplicitly:
    def test_the_qa_interpreter_overrides_the_config_venv(
        self, checker: types.ModuleType, tmp_path: Path
    ) -> None:
        """``pyrightconfig.json`` names ``untracked/venv``, a symlink only the
        main checkout has; a worktree or a CI runner has the fingerprint-keyed
        venv and no symlink, so without ``--pythonpath`` every third-party
        import is reported missing there (597 of them, measured)."""
        argv_log = tmp_path / "argv.txt"
        fake = tmp_path / "pyright"
        fake.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > {argv_log}\n"
            'echo \'{"version":"x","generalDiagnostics":[],"summary":{"filesAnalyzed":0}}\'\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)
        root = _fixture_tree(tmp_path / "proj", _CLEAN_SOURCE)
        interpreter = tmp_path / "venv" / "bin" / "python"
        exit_code = checker.main(
            [
                "--json",
                "--root",
                str(root),
                "--pyright",
                str(fake),
                "--pythonpath",
                str(interpreter),
            ]
        )
        assert exit_code == checker.EXIT_SUCCESS
        argv = argv_log.read_text(encoding="utf-8").splitlines()
        assert argv == ["--project", str(root), "--pythonpath", str(interpreter), "--outputjson"]

    def test_defaults_to_the_running_interpreter(self, checker: types.ModuleType) -> None:
        import sys

        assert checker.default_interpreter() == Path(sys.executable)


class TestReportBuilding:
    def test_warnings_do_not_fail_the_gate(self, checker: types.ModuleType) -> None:
        raw = {
            "version": "1.1.413",
            "generalDiagnostics": [
                {
                    "file": "/root/pkg/a.py",
                    "severity": "warning",
                    "message": "unused",
                    "range": {"start": {"line": 0, "character": 0}},
                    "rule": "reportUnusedImport",
                }
            ],
            "summary": {"filesAnalyzed": 1, "errorCount": 0, "warningCount": 1},
        }
        report = checker.build_report(raw, Path("/root"))
        assert report["summary"]["passed"] is True
        assert report["summary"]["total_errors"] == 0
        assert report["summary"]["warnings"] == 1
        assert report["errors"] == []

    def test_error_rows_are_root_relative_and_one_based(self, checker: types.ModuleType) -> None:
        raw = {
            "version": "1.1.413",
            "generalDiagnostics": [
                {
                    "file": "/root/pkg/a.py",
                    "severity": "error",
                    "message": "boom",
                    "range": {"start": {"line": 4, "character": 2}},
                    "rule": "reportAttributeAccessIssue",
                },
                {
                    "file": "/elsewhere/b.py",
                    "severity": "error",
                    "message": "no rule field",
                    "range": {"start": {"line": 0, "character": 0}},
                },
            ],
            "summary": {"filesAnalyzed": 2, "errorCount": 2, "warningCount": 0},
        }
        report = checker.build_report(raw, Path("/root"))
        assert report["summary"]["passed"] is False
        assert report["summary"]["total_errors"] == 2
        assert report["errors"][0] == {
            "file": "pkg/a.py",
            "line": 5,
            "rule": "reportAttributeAccessIssue",
            "message": "boom",
        }
        assert report["errors"][1]["file"] == "/elsewhere/b.py"
        assert report["errors"][1]["rule"] == ""

    def test_unparseable_output_is_operational(
        self, checker: types.ModuleType, tmp_path: Path
    ) -> None:
        fake = tmp_path / "pyright"
        fake.write_text("#!/bin/sh\necho 'not json'\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        root = _fixture_tree(tmp_path / "proj", _CLEAN_SOURCE)
        exit_code = checker.main(["--json", "--root", str(root), "--pyright", str(fake)])
        assert exit_code == checker.EXIT_OPERATIONAL
        report = _report(root, checker)
        assert report["summary"]["passed"] is False
        assert "not JSON" in report["summary"]["error"]


# ── llm_qa.py wiring ───────────────────────────────────────────────


class TestLlmQaWiring:
    def test_pyright_in_registry_with_required_fields(self, llm_qa: types.ModuleType) -> None:
        registry: dict[str, Any] = llm_qa.TOOL_REGISTRY
        assert "pyright" in registry, f"'pyright' missing from TOOL_REGISTRY: {list(registry)}"
        config = registry["pyright"]
        assert config.command[-2:] == [str(SCRIPTS_DIR / "run_pyright_check.py"), "--json"]
        assert config.json_file == "pyright.json"
        assert llm_qa.detail_array_key(config.jq_hint) == "errors"

    def test_pyright_runs_beside_the_other_type_checker(self, llm_qa: types.ModuleType) -> None:
        names: list[str] = llm_qa.ALL_TOOL_NAMES
        assert names.index("pyright") == names.index("type_check") + 1
        assert names[-1] == "smoke_test"

    def test_summarizer_names_errors_and_files(self, llm_qa: types.ModuleType) -> None:
        summarizers: dict[str, Callable[[dict[str, Any]], str]] = llm_qa.SUMMARIZERS
        assert "pyright" in summarizers
        text = summarizers["pyright"](
            {"summary": {"total_errors": 3, "files_analyzed": 412, "passed": False}}
        )
        assert text == "3 errors (412 files analysed)"

    def test_summarizer_reads_zero_when_the_tool_never_ran(self, llm_qa: types.ModuleType) -> None:
        text = llm_qa.SUMMARIZERS["pyright"]({"summary": {"passed": False, "error": "no binary"}})
        assert text == "0 errors (0 files analysed)"

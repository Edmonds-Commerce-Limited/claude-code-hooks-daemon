"""The `install-mode-marker` Detector (N386): ONE definition of "is this a self-install".

`daemon/install_layout.py` (Python) and `scripts/install/mode_guard.sh` (shell)
are the two definitions. Any other file that TESTS whether
``src/claude_code_hooks_daemon`` exists, in order to DECIDE the install mode,
is a third copy that drifts: three of the first four Python copies used
``.exists()`` where the rule is ``.is_dir()``.

The distinction the Detector has to draw: the same path appears all over this
repository because the QA scripts SCAN the source tree
(``REPO_ROOT / "src" / "claude_code_hooks_daemon"``). Building that path, or
checking that the scanner's own tree is there, is not a decision. A decision
asks about a root the CALLER supplied -- a parameter, an attribute, the
environment -- whereas a scan builds from where the script itself lives.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_CHECKER: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "check_install_mode_marker.py"

_PY_DEFINITION: Final[str] = "src/claude_code_hooks_daemon/daemon/install_layout.py"
_SH_DEFINITION: Final[str] = "scripts/install/mode_guard.sh"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_install_mode_marker", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _flagged(checker: ModuleType, tmp_path: Path, relative: str, source: str) -> list[int]:
    _write(tmp_path, relative, source)
    return [v.line for v in checker.scan_tree(tmp_path)]


_PY_DECISIONS: Final[dict[str, str]] = {
    "slash-join-exists": (
        "def f(project_root):\n"
        "    return (project_root / 'src' / 'claude_code_hooks_daemon').exists()\n"
    ),
    "slash-join-is-dir": (
        "def f(project_root):\n"
        "    return (project_root / 'src' / 'claude_code_hooks_daemon').is_dir()\n"
    ),
    "bound-name": (
        "def f(project_root):\n"
        "    daemon_src = project_root / 'src' / 'claude_code_hooks_daemon'\n"
        "    if daemon_src.exists():\n"
        "        return True\n"
        "    return False\n"
    ),
    "joinpath": (
        "def f(root):\n    return root.joinpath('src', 'claude_code_hooks_daemon').is_dir()\n"
    ),
    "starred-module-tuple": (
        "_PARTS = ('src', 'claude_code_hooks_daemon')\n"
        "def f(root):\n"
        "    return root.joinpath(*_PARTS).exists()\n"
    ),
    "os-path-join": (
        "import os\n"
        "def f(root):\n"
        "    return os.path.isdir(os.path.join(root, 'src', 'claude_code_hooks_daemon'))\n"
    ),
    "one-literal-with-a-slash": (
        "def f(root):\n    return (root / 'src/claude_code_hooks_daemon').exists()\n"
    ),
    "f-string": (
        "import os\n"
        "def f(root):\n"
        "    return os.path.exists(f'{root}/src/claude_code_hooks_daemon')\n"
    ),
    "attribute-root": (
        "class C:\n"
        "    def f(self):\n"
        "        return (self.project_root / 'src' / 'claude_code_hooks_daemon').is_dir()\n"
    ),
    "environment-root": (
        "import os\n"
        "from pathlib import Path\n"
        "def f():\n"
        "    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR') or Path.cwd())\n"
        "    return (project_dir / 'src' / 'claude_code_hooks_daemon').exists()\n"
    ),
    "relative-to-the-cwd": (
        "from pathlib import Path\n"
        "def f():\n    return Path('src/claude_code_hooks_daemon').is_dir()\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_PY_DECISIONS))
def test_python_decisions_are_reported(checker: ModuleType, tmp_path: Path, name: str) -> None:
    assert _flagged(checker, tmp_path, "pkg/mod.py", _PY_DECISIONS[name]) != []


_PY_SCANS: Final[dict[str, str]] = {
    "scan-root-constant": (
        "from pathlib import Path\n"
        "_REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        "_DEFAULT_SCAN_ROOT = _REPO_ROOT / 'src' / 'claude_code_hooks_daemon'\n"
        "def f(walk):\n    return walk(_DEFAULT_SCAN_ROOT)\n"
    ),
    "scan-root-existence-check": (
        "from pathlib import Path\n"
        "_REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        "_DEFAULT_SCAN_ROOT = _REPO_ROOT / 'src' / 'claude_code_hooks_daemon'\n"
        "def f():\n"
        "    if not _DEFAULT_SCAN_ROOT.is_dir():\n"
        "        return 1\n"
        "    return 0\n"
    ),
    "scan-root-rebound-to-an-argument": (
        "import sys\n"
        "from pathlib import Path\n"
        "_REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        "_DEFAULT_SCAN_ROOT = _REPO_ROOT / 'src' / 'claude_code_hooks_daemon'\n"
        "def f():\n"
        "    scan_root = _DEFAULT_SCAN_ROOT\n"
        "    scan_root = Path(sys.argv[1]).resolve()\n"
        "    return scan_root.is_dir()\n"
    ),
    "script-anchored-local": (
        "from pathlib import Path\n"
        "def main():\n"
        "    script_path = Path(__file__).resolve()\n"
        "    project_root = script_path.parent.parent.parent\n"
        "    src_dir = project_root / 'src' / 'claude_code_hooks_daemon'\n"
        "    if not src_dir.exists():\n"
        "        return 1\n"
        "    return 0\n"
    ),
    "file-anchored-inline": (
        "from pathlib import Path\n"
        "def f():\n"
        "    return (Path(__file__).parents[2] / 'src' / 'claude_code_hooks_daemon').exists()\n"
    ),
    "a-file-deeper-in-the-tree": (
        "def f(project_root):\n"
        "    return (project_root / 'src' / 'claude_code_hooks_daemon' / 'version.py').is_file()\n"
    ),
    "path-built-and-never-tested": (
        "def f(project_root):\n"
        "    return sorted((project_root / 'src' / 'claude_code_hooks_daemon').rglob('*.py'))\n"
    ),
    "a-different-package": (
        "def f(project_root):\n    return (project_root / 'src' / 'other_package').exists()\n"
    ),
    "tuple-declared-but-only-used-to-build-a-scan-path": (
        "_PARTS = ('src', 'claude_code_hooks_daemon')\n"
        "def f(root, walk):\n    return walk(root.joinpath(*_PARTS))\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_PY_SCANS))
def test_python_scans_are_not_reported(checker: ModuleType, tmp_path: Path, name: str) -> None:
    assert _flagged(checker, tmp_path, "pkg/mod.py", _PY_SCANS[name]) == []


_SH_DECISIONS: Final[dict[str, str]] = {
    "single-bracket": 'if [ -d "$root/src/claude_code_hooks_daemon" ]; then echo y; fi\n',
    "double-bracket": 'if [[ -d "${PROJECT_ROOT}/src/claude_code_hooks_daemon" ]]; then :; fi\n',
    "negated": 'if [[ ! -d "$R/src/claude_code_hooks_daemon" ]]; then exit 1; fi\n',
    "exists-flag": '[[ -e "$R/src/claude_code_hooks_daemon" ]] && echo y\n',
    "trailing-slash": '[ -d "$R/src/claude_code_hooks_daemon/" ] && echo y\n',
    "test-builtin": 'test -d "$R/src/claude_code_hooks_daemon" && echo y\n',
    "second-operand": '[[ ! -f "$R/install.py" ]] || [[ ! -d "$R/src/claude_code_hooks_daemon" ]]\n',
    "bound-variable": 'marker="$R/src/claude_code_hooks_daemon"\n[ -d "$marker" ] && echo y\n',
    "bound-braced-variable": 'M="$R/src/claude_code_hooks_daemon"\n[[ -d "${M}" ]] && echo y\n',
}


@pytest.mark.parametrize("name", sorted(_SH_DECISIONS))
def test_shell_decisions_are_reported(checker: ModuleType, tmp_path: Path, name: str) -> None:
    assert _flagged(checker, tmp_path, "scripts/tool.sh", _SH_DECISIONS[name]) != []


_SH_SCANS: Final[dict[str, str]] = {
    "coverage-flag": "pytest --cov=src/claude_code_hooks_daemon\n",
    "a-file-deeper-in-the-tree": '[[ -f "$R/src/claude_code_hooks_daemon/version.py" ]] && echo y\n',
    "a-sourced-file": 'source "$R/src/claude_code_hooks_daemon/daemon/paths.py"\n',
    "path-built-and-never-tested": 'scan_root="$R/src/claude_code_hooks_daemon"\nfind "$scan_root"\n',
    "mkdir": 'mkdir -p "$R/src/claude_code_hooks_daemon"\n',
    "a-comment": '# [ -d "$R/src/claude_code_hooks_daemon" ] was the old test\n',
    "printed-text": 'echo "no src/claude_code_hooks_daemon here"\n',
    "other-package": '[ -d "$R/src/other_package" ] && echo y\n',
}


@pytest.mark.parametrize("name", sorted(_SH_SCANS))
def test_shell_scans_are_not_reported(checker: ModuleType, tmp_path: Path, name: str) -> None:
    assert _flagged(checker, tmp_path, "scripts/tool.sh", _SH_SCANS[name]) == []


def test_an_extensionless_shell_script_is_read(checker: ModuleType, tmp_path: Path) -> None:
    source = '#!/usr/bin/env bash\n[ -d "$R/src/claude_code_hooks_daemon" ] && echo y\n'

    assert _flagged(checker, tmp_path, "bin/tool", source) == [2]


class TestTheTwoDefinitionsAreTheOnlyExemptFiles:
    def test_the_python_definition_may_test_the_marker(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        assert _flagged(checker, tmp_path, _PY_DEFINITION, _PY_DECISIONS["joinpath"]) == []

    def test_the_shell_definition_may_test_the_marker(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        assert _flagged(checker, tmp_path, _SH_DEFINITION, _SH_DECISIONS["single-bracket"]) == []

    def test_the_same_python_content_anywhere_else_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        assert _flagged(checker, tmp_path, "src/other.py", _PY_DECISIONS["joinpath"]) != []

    def test_the_same_shell_content_anywhere_else_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        assert (
            _flagged(checker, tmp_path, "scripts/install/other.sh", _SH_DECISIONS["single-bracket"])
            != []
        )


def test_python_that_does_not_parse_decides_nothing(checker: ModuleType, tmp_path: Path) -> None:
    """It cannot run, and the tree keeps deliberate syntax-error fixtures; lint owns the defect."""
    _write(tmp_path, "pkg/broken.py", "def f(:\n")

    assert checker.scan_tree(tmp_path) == []


def test_a_file_that_cannot_be_decoded_is_reported_not_skipped(
    checker: ModuleType, tmp_path: Path
) -> None:
    """A file the Detector cannot read could hide a decision, so it is not a pass."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "binary.sh").write_bytes(b"\xff\xfe\x00 not utf-8")

    violations = checker.scan_tree(tmp_path)

    assert [v.rule for v in violations] == ["install-mode-marker-unreadable"]


def test_a_runtime_state_directory_is_not_scanned(checker: ModuleType, tmp_path: Path) -> None:
    """`untracked/` holds worktrees and venvs: other checkouts, not project source."""
    _write(tmp_path, "untracked/worktrees/x/mod.py", _PY_DECISIONS["joinpath"])

    assert checker.scan_tree(tmp_path) == []


def test_the_violation_names_the_rule_to_call(checker: ModuleType, tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _PY_DECISIONS["joinpath"])
    _write(tmp_path, "scripts/tool.sh", _SH_DECISIONS["single-bracket"])

    messages = {v.file: v.to_dict()["message"] for v in checker.scan_tree(tmp_path)}

    assert "is_self_install_mode" in messages["pkg/mod.py"]
    assert "is_self_install_checkout" in messages["scripts/tool.sh"]


class TestTheCommandLine:
    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_CHECKER), "--json", "--path", str(root)],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )

    def test_a_clean_tree_passes_and_reports_how_much_it_looked_at(self, tmp_path: Path) -> None:
        _write(tmp_path, "pkg/mod.py", "VALUE = 1\n")

        result = self._run(tmp_path)

        assert result.returncode == 0, result.stdout
        report = json.loads((tmp_path / "install_mode_marker.json").read_text(encoding="utf-8"))
        assert report["summary"]["files_scanned"] == 1

    def test_a_decision_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, "pkg/mod.py", _PY_DECISIONS["joinpath"])

        assert self._run(tmp_path).returncode == 1

    def test_a_tree_with_nothing_to_scan_fails(self, tmp_path: Path) -> None:
        assert self._run(tmp_path).returncode == 1


def test_this_repository_has_no_third_copy(checker: ModuleType) -> None:
    """The real tree: every file but the two definitions asks the rule."""
    violations = checker.scan_tree(_REPO_ROOT)

    assert [f"{v.file}:{v.line}" for v in violations] == []

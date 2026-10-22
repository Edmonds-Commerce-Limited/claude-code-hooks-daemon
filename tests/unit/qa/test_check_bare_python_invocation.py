"""The `bare-python-invocation` Detector (Plan 00546, GitHub #130).

A first-party shell script that runs ``python3`` / ``python`` by its bare name
runs whatever ``PATH`` resolves first, which may be older than the declared
minimum (``requires-python``). The scripts that install, upgrade and dispatch
hooks have already resolved the interpreter the daemon runs on (the venv's
``bin/python`` or ``HOOKS_DAEMON_PYTHON``), and must run Python on that one.

The originating instance is ``eager_cleanup_stale_venvs`` in
``scripts/install/venv.sh``, which ran ``python3 "$paths_script" ...``.
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
_CHECKER: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "check_bare_python_invocation.py"

#: The original instance, as it stood in scripts/install/venv.sh before the fix.
_ORIGINAL_INSTANCE: Final[str] = """\
#!/usr/bin/env bash
eager_cleanup_stale_venvs() {
    local verdicts
    if ! verdicts="$(python3 "$paths_script" list-stale-venvs \\
        --daemon-dir "$daemon_dir" --current-venv "$current_abs")"; then
        return 0
    fi
}
"""


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_bare_python_invocation", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _lines(checker: ModuleType, source: str) -> list[int]:
    return list(checker.bare_python_lines(source))


class TestOriginalInstance:
    def test_the_command_substitution_that_started_it_is_found(self, checker: ModuleType) -> None:
        assert _lines(checker, _ORIGINAL_INSTANCE) == [4]

    def test_the_fixed_form_is_clean(self, checker: ModuleType) -> None:
        fixed = _ORIGINAL_INSTANCE.replace('$(python3 "$paths', '$("$interpreter" "$paths')
        assert _lines(checker, fixed) == []


class TestCommandPosition:
    @pytest.mark.parametrize(
        "source",
        [
            "python3 script.py",
            "python script.py",
            "python3",
            "x=$(python3 -c 'print(1)')",
            "x=`python3 -c 'print(1)'`",
            'x="$(python3 -c "print(1)")"',
            "if python3 -c 'import yaml'; then :; fi",
            "if ! python3 -c 'import yaml'; then :; fi",
            "true && python3 a.py",
            "false || python3 a.py",
            "echo x | python3 -c 'import sys'",
            "cd d; python3 a.py",
            "(python3 a.py)",
            "{ python3 a.py; }",
            "FOO=1 python3 a.py",
            "exec python3 a.py",
            "env FOO=1 python3 a.py",
            "sudo python3 a.py",
            "timeout 30 python3 a.py",
            "nohup python3 a.py &",
            "echo x | xargs python3 a.py",
            "python3 - <<'PY'\nprint(1)\nPY",
            "case $x in\n  a) python3 a.py ;;\nesac",
            "while python3 a.py; do :; done",
            "for f in a; do\n  python3 $f\ndone",
            "foo() {\n  python3 a.py\n}",
            '"python3" a.py',
        ],
    )
    def test_invocation_is_found(self, checker: ModuleType, source: str) -> None:
        assert _lines(checker, source) != []

    @pytest.mark.parametrize(
        "source",
        [
            "command -v python3",
            "command -v python3 >/dev/null 2>&1",
            "if ! command -v python3 &>/dev/null; then :; fi",
            "type python3",
            "which python3",
            'echo "python3 is too old"',
            "echo python3 is too old",
            "printf '%s' 'python3 -c x'",
            "# python3 a.py",
            "x=1 # python3 a.py",
            '"$interpreter" "$paths_script"',
            '"$PYTHON" -c "print(1)"',
            "python3.12 a.py",
            "python3.11 -m venv v",
            "/usr/bin/python3 a.py",
            "$HOME/venv/bin/python a.py",
            "pip install python3-foo",
            "python3_bin=1",
            "python3-config --prefix",
            "_rv_pick_ranked_scan dir python3",
            "case $x in\n  python3) y=1 ;;\nesac",
            "cat <<'EOF'\npython3 not-run.py\nEOF",
            "cat <<EOF\npython3 not-run.py\nEOF",
            "cat <<-EOF\n\tpython3 not-run.py\n\tEOF",
            "x='\npython3 inside a quoted string\n'",
            "grep -n python3 file",
            "for c in python3.14 python3; do :; done",
        ],
    )
    def test_non_invocation_is_clean(self, checker: ModuleType, source: str) -> None:
        assert _lines(checker, source) == []

    @pytest.mark.parametrize(
        "source",
        [
            'python_bin="${HOOKS_DAEMON_PYTHON:-python3}"',
            'local python_bin="${3:-python3}"',
            'ensure_venv "$d" "$v" "${HOOKS_DAEMON_PYTHON:-python3}"',
            'x="${VAR:=python3}"',
            "x=${VAR:-python}",
            "x=${VAR-python3}",
            "x=${VAR:-'python3'}",
            'x=${A:-${B:-"python3"}}',
            "PYTHON_BIN=python3",
            'PYTHON_BIN="python3"',
            "PYTHON_BIN='python3'",
            'local python_bin="python3"',
            "export PYTHON_BIN=python3",
            "declare -r PY=python",
            'if [ -z "$x" ]; then\n  PYTHON_BIN="python3"\nfi',
        ],
    )
    def test_a_bare_name_used_as_a_value_to_be_run_is_found(
        self, checker: ModuleType, source: str
    ) -> None:
        assert _lines(checker, source) != []

    @pytest.mark.parametrize(
        "source",
        [
            'x="${VAR:-python3.12}"',
            'x="${VAR:-$HOME/bin/python3}"',
            'x="${VAR:-}"',
            'x="${VAR:-python3-config}"',
            'x="${python3:-1}"',
            "x=python3.12",
            "x=/usr/bin/python3",
            'x="$(command -v python3)"',
            'x="use python3 here"',
            'x="${VAR:-use python3}"',
            "x=${VAR:+python3}",
            "echo x=python3",
            "echo ${VAR:-python3}",
            "# x=python3",
            "cat <<'EOF'\nPYTHON_BIN=python3\nEOF",
            "cat <<EOF\n${VAR:-python3}\nEOF",
        ],
    )
    def test_prose_lookups_and_pinned_values_stay_clean(
        self, checker: ModuleType, source: str
    ) -> None:
        assert _lines(checker, source) == []

    def test_a_default_reports_the_line_it_sits_on(self, checker: ModuleType) -> None:
        source = 'a=1\nb="${X:-python3}"\n'
        assert _lines(checker, source) == [2]

    def test_script_text_in_a_single_quoted_string_after_the_command_is_not_scanned(
        self, checker: ModuleType
    ) -> None:
        source = "python3 -c \"$py\"'\nimport json\npython3 -c x\n'\n"
        assert _lines(checker, source) == [1]

    def test_line_numbers_follow_continuations_and_heredocs(self, checker: ModuleType) -> None:
        source = "cat <<'EOF'\nbody\nEOF\necho a \\\n  b\npython3 x.py\n"
        assert _lines(checker, source) == [6]

    def test_a_double_quoted_substitution_is_still_a_command(self, checker: ModuleType) -> None:
        assert _lines(checker, 'echo "result: $(python3 -c "1")"') == [1]


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestScan:
    def test_finds_the_original_instance_in_a_shell_file(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "scripts/install/venv.sh", _ORIGINAL_INSTANCE)
        found = checker.scan_tree(tmp_path, allowlist=[])
        assert [(v.file, v.line, v.rule) for v in found] == [
            ("scripts/install/venv.sh", 4, "bare-python-invocation")
        ]

    def test_reads_an_extensionless_shell_script_by_shebang(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "bin/tool", "#!/usr/bin/env bash\npython3 a.py\n")
        found = checker.scan_tree(tmp_path, allowlist=[])
        assert [(v.file, v.line) for v in found] == [("bin/tool", 2)]

    def test_python_and_markdown_files_are_not_shell(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "a.py", "import os\nos.system('python3 x.py')\n")
        _write(tmp_path, "README.md", "run:\n\npython3 a.py\n")
        _write(tmp_path, "ok.sh", "echo fine\n")
        assert checker.scan_tree(tmp_path, allowlist=[]) == []

    def test_fixture_directories_are_not_project_code(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "tests/fixtures/x/bad.sh", "python3 a.py\n")
        _write(tmp_path, "ok.sh", "echo fine\n")
        assert checker.scan_tree(tmp_path, allowlist=[]) == []

    def test_plan_prototypes_are_not_scanned_but_other_claude_files_are(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "CLAUDE/Plan/00001-x/bench.sh", "python3 a.py\n")
        _write(tmp_path, "CLAUDE/Plan/Completed/00002-y/run.sh", 'P="${X:-python3}"\n')
        _write(tmp_path, "CLAUDE/UPGRADES/v2/migrate.sh", "python3 a.py\n")
        found = checker.scan_tree(tmp_path, allowlist=[])
        assert [v.file for v in found] == ["CLAUDE/UPGRADES/v2/migrate.sh"]

    def test_a_value_default_is_reported_in_a_file(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "s.sh", 'x=1\nPY="${HOOKS_DAEMON_PYTHON:-python3}"\n')
        found = checker.scan_tree(tmp_path, allowlist=[])
        assert [(v.file, v.line) for v in found] == [("s.sh", 2)]

    def test_an_allowlisted_probe_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "probe.sh", "found=\"$(python3 -c 'import sys')\"\n")
        entry = checker.AllowEntry(file="probe.sh", match="python3 -c", reason="finds the version")
        assert checker.scan_tree(tmp_path, allowlist=[entry]) == []

    def test_an_allowlist_entry_that_matches_nothing_is_a_violation(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "probe.sh", "echo fine\n")
        entry = checker.AllowEntry(file="probe.sh", match="python3 -c", reason="finds the version")
        found = checker.scan_tree(tmp_path, allowlist=[entry])
        assert [v.rule for v in found] == ["bare-python-allowlist-stale"]

    def test_an_allowlist_entry_without_a_reason_is_refused(self, checker: ModuleType) -> None:
        with pytest.raises(ValueError, match="reason"):
            checker.load_allowlist_entries([{"file": "a.sh", "match": "python3", "reason": " "}])


class TestCommandLine:
    def test_json_run_over_a_path_fails_and_names_the_rule(self, tmp_path: Path) -> None:
        _write(tmp_path, "venv.sh", _ORIGINAL_INSTANCE)
        result = subprocess.run(
            [sys.executable, str(_CHECKER), "--json", "--path", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "bare-python-invocation" in result.stdout
        report = json.loads((tmp_path / "bare_python_invocation.json").read_text("utf-8"))
        assert report["summary"]["total_violations"] == 1
        assert report["violations"][0]["line"] == 4

    def test_json_report_carries_the_examined_file_count(self, tmp_path: Path) -> None:
        _write(tmp_path, "clean.sh", "#!/bin/bash\necho fine\n")
        result = subprocess.run(
            [sys.executable, str(_CHECKER), "--json", "--path", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        report = json.loads((tmp_path / "bare_python_invocation.json").read_text("utf-8"))
        assert report["summary"]["files_scanned"] == 1

    def test_the_repository_registers_the_rule_with_documentation(self) -> None:
        rules = json.loads((_REPO_ROOT / "scripts" / "qa" / "qa-rules.json").read_text("utf-8"))
        entry = rules["rules"]["bare-python-invocation"]
        assert entry["checks"] == ["check_bare_python_invocation.py"]
        assert entry["statement"] and entry["fix"]

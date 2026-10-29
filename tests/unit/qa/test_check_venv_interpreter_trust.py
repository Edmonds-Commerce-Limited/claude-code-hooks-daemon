"""The `venv-interpreter-trust` Detector (Plan 00555, Defence Before Fix, RED first).

The class: **code that judges a Python venv or interpreter usable, or selects
it, without checking that the interpreter which will run it has the major.minor
the venv was built for** (``pyvenv.cfg`` ``version_info``/``version``).

When the system Python moved from 3.11 to 3.13, a venv's ``bin/python`` symlink
ran 3.13 and could not see ``lib/python3.11/site-packages``. Every check that
asked "does it exist / is it executable / does ``import sys`` work" still said
yes, so the daemon could not import itself and the self-heal never fired.

Everything here is source text fed to the Detector; nothing runs an interpreter.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_venv_interpreter_trust.py"

EXEC = "venv-exec-bit-trust"
PROBE = "venv-weak-liveness-probe"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_venv_interpreter_trust", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _py(
    checker: ModuleType, source: str, gates: frozenset[str] = frozenset()
) -> list[tuple[int, str]]:
    violations = checker.scan_python_source(textwrap.dedent(source), "fixture.py", gates)
    return [(v.line, v.rule) for v in violations]


def _sh(
    checker: ModuleType, source: str, gates: frozenset[str] = frozenset()
) -> list[tuple[int, str]]:
    violations = checker.scan_shell_source(textwrap.dedent(source), "fixture.sh", gates)
    return [(v.line, v.rule) for v in violations]


class TestPythonExecBitTrust:
    @pytest.mark.parametrize(
        "expression",
        [
            '(venv / "bin" / "python").is_file()',
            '(venv / "bin" / "python3").exists()',
            'Path(venv, "bin", "python").is_file()',
            'venv.joinpath("bin", "python").exists()',
            'os.path.isfile(os.path.join(venv, "bin", "python"))',
            'os.path.exists(f"{venv}/bin/python3")',
            'os.access(venv / "bin" / "python", os.X_OK)',
            '(venv / "bin/python").is_file()',
            '(venv / "bin" / "python3.11").is_file()',
        ],
    )
    def test_existence_or_exec_test_on_a_venv_interpreter_path(
        self, checker: ModuleType, expression: str
    ) -> None:
        source = f"""
            import os
            from pathlib import Path

            def usable(venv):
                return {expression}
        """
        assert _py(checker, source) == [(6, EXEC)]

    def test_variable_bound_from_an_interpreter_path(self, checker: ModuleType) -> None:
        source = """
            import os

            def usable(venv):
                python = venv / "bin" / "python"
                if not python.is_file():
                    return False
                return os.access(python, os.X_OK)
        """
        assert _py(checker, source) == [(6, EXEC), (8, EXEC)]

    def test_loop_variable_over_python_names(self, checker: ModuleType) -> None:
        source = """
            import os

            def pick(venv_dir):
                for name in ("python", "python3"):
                    candidate = venv_dir / "bin" / name
                    if candidate.is_file() and os.access(candidate, os.X_OK):
                        return candidate
        """
        assert _py(checker, source) == [(7, EXEC)]

    def test_loop_variable_over_interpreter_paths(self, checker: ModuleType) -> None:
        source = """
            def pick(a, b):
                for candidate in (a / "bin" / "python", b / "bin" / "python"):
                    if candidate.exists():
                        return candidate
        """
        assert _py(checker, source) == [(4, EXEC)]

    def test_variable_bound_from_the_venv_resolver(self, checker: ModuleType) -> None:
        source = """
            def installed(daemon_dir):
                python = resolve_existing_venv_python(daemon_dir)
                return python.is_file()
        """
        assert _py(checker, source) == [(4, EXEC)]

    def test_variable_copied_from_an_interpreter_variable(self, checker: ModuleType) -> None:
        source = """
            def usable(venv):
                first = venv / "bin" / "python"
                again = first
                return again.exists()
        """
        assert _py(checker, source) == [(5, EXEC)]

    @pytest.mark.parametrize(
        "expression",
        [
            "path.is_file()",
            '(venv / "bin" / "pytest").exists()',
            '(venv / "lib" / "python").exists()',
            '(venv / "python").is_file()',
            'os.access(venv / "bin" / "ruff", os.X_OK)',
            'os.path.exists(venv / "pyvenv.cfg")',
        ],
    )
    def test_other_paths_are_not_reported(self, checker: ModuleType, expression: str) -> None:
        source = f"""
            import os

            def usable(venv, path):
                return {expression}
        """
        assert _py(checker, source) == []

    def test_a_parameter_is_not_known_to_be_an_interpreter(self, checker: ModuleType) -> None:
        source = """
            def usable(candidate):
                return candidate.is_file()
        """
        assert _py(checker, source) == []

    def test_a_rebinding_scope_is_per_function(self, checker: ModuleType) -> None:
        source = """
            def one(venv):
                python = venv / "bin" / "python"
                return python

            def two(python):
                return python.is_file()
        """
        assert _py(checker, source) == []


class TestPythonWeakLivenessProbe:
    @pytest.mark.parametrize(
        "argv",
        [
            '[str(candidate), "-c", "import sys"]',
            '[candidate, "-c", "import sys"]',
            '[str(python), "--version"]',
            '[str(candidate), "-V"]',
            '[str(venv / "bin" / "python"), "--version"]',
        ],
    )
    def test_import_sys_or_version_only(self, checker: ModuleType, argv: str) -> None:
        source = f"""
            import subprocess

            def runs(candidate, python, venv):
                return subprocess.run({argv}, capture_output=True).returncode == 0
        """
        assert _py(checker, source) == [(5, PROBE)]

    @pytest.mark.parametrize(
        "argv",
        [
            '[sys.executable, "-c", "import sys"]',
            '["git", "--version"]',
            '["python3", "-c", "import sys"]',
            '[str(candidate), "-c", "import sys; print(sys.version_info[:2])"]',
            '[str(candidate), "-c", "import claude_code_hooks_daemon"]',
            '[str(candidate), "-m", "pytest"]',
        ],
    )
    def test_a_probe_that_reads_more_or_probes_something_else(
        self, checker: ModuleType, argv: str
    ) -> None:
        source = f"""
            import subprocess
            import sys

            def runs(candidate):
                return subprocess.run({argv}, capture_output=True).returncode == 0
        """
        assert _py(checker, source) == []


class TestPythonProof:
    def test_reading_pyvenv_cfg_and_comparing_a_version_exempts_the_function(
        self, checker: ModuleType
    ) -> None:
        source = """
            import subprocess, sys

            def runs(venv, candidate):
                cfg = (venv / "pyvenv.cfg").read_text()
                built = tuple(int(p) for p in cfg.split("version = ")[1].split(".")[:2])
                if built != sys.version_info[:2]:
                    return False
                python = venv / "bin" / "python"
                return python.is_file()
        """
        assert _py(checker, source) == []

    def test_pyvenv_cfg_without_a_comparison_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            import sys

            def runs(venv):
                cfg = (venv / "pyvenv.cfg").read_text()
                print(cfg, sys.version_info)
                return (venv / "bin" / "python").is_file()
        """
        assert _py(checker, source) == [(7, EXEC)]

    def test_a_version_comparison_without_pyvenv_cfg_does_not_exempt(
        self, checker: ModuleType
    ) -> None:
        source = """
            import sys

            def runs(venv):
                if sys.version_info < (3, 11):
                    return False
                return (venv / "bin" / "python").is_file()
        """
        assert _py(checker, source) == [(7, EXEC)]

    def test_a_docstring_mentioning_pyvenv_cfg_does_not_exempt(self, checker: ModuleType) -> None:
        source = '''
            import sys

            def runs(venv):
                """Would read pyvenv.cfg and compare version_info, but does not."""
                if sys.version_info < (3, 11):
                    return False
                return (venv / "bin" / "python").is_file()
        '''
        assert _py(checker, source) == [(8, EXEC)]

    def test_proof_in_another_function_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            import sys

            def proves(venv):
                cfg = (venv / "pyvenv.cfg").read_text()
                return "version" in cfg and sys.version_info[:2] == (3, 11)

            def trusts(venv):
                return (venv / "bin" / "python").is_file()
        """
        assert _py(checker, source) == [(9, EXEC)]

    def test_calling_a_proven_gate_exempts(self, checker: ModuleType) -> None:
        source = """
            def pick(venv):
                python = venv / "bin" / "python"
                if python.is_file() and _venv_interpreter_runs(python):
                    return python
        """
        gates = frozenset({"_venv_interpreter_runs"})
        assert _py(checker, source, gates) == []

    def test_calling_a_gate_that_is_not_proven_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            def pick(venv):
                python = venv / "bin" / "python"
                if python.is_file() and _venv_interpreter_runs(python):
                    return python
        """
        assert _py(checker, source, frozenset()) == [(4, EXEC)]

    def test_a_method_call_to_a_proven_gate_exempts(self, checker: ModuleType) -> None:
        source = """
            def pick(venv, paths):
                python = venv / "bin" / "python"
                if python.is_file() and paths._venv_interpreter_runs(python):
                    return python
        """
        assert _py(checker, source, frozenset({"_venv_interpreter_runs"})) == []

    def test_the_weak_probe_is_reported_even_when_nothing_proves_it(
        self, checker: ModuleType
    ) -> None:
        source = """
            import subprocess

            def runs(candidate):
                return subprocess.run([str(candidate), "-c", "import sys"]).returncode == 0
        """
        assert _py(checker, source) == [(5, PROBE)]


class TestShellExecBitTrust:
    @pytest.mark.parametrize(
        "test",
        [
            '[ -x "$venv/bin/python" ]',
            '[ -f "$VENV_DIR/bin/python3" ]',
            '[[ -e "${venv}/bin/python" ]]',
            'test -x "$d/bin/python"',
            '[ ! -x "$d/bin/python" ]',
            "[ -x $d/bin/python ]",
            '[ -x "$d"/bin/python ]',
        ],
    )
    def test_existence_or_exec_test_on_a_venv_interpreter_path(
        self, checker: ModuleType, test: str
    ) -> None:
        source = f"""
            usable() {{
                {test} && return 0
                return 1
            }}
        """
        assert _sh(checker, source) == [(3, EXEC)]

    def test_variable_bound_from_an_interpreter_path(self, checker: ModuleType) -> None:
        source = """
            usable() {
                local python="$1/bin/python"
                [ -x "$python" ] || return 1
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_loop_variable_over_interpreter_paths(self, checker: ModuleType) -> None:
        source = """
            pick() {
                for candidate in "$1/bin/python" "$1/bin/python3"; do
                    [ -x "$candidate" ] && echo "$candidate"
                done
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_variable_bound_from_the_venv_resolver(self, checker: ModuleType) -> None:
        source = """
            PYTHON_CMD="$(resolve_venv_python "$dir")"
            [[ -f "$PYTHON_CMD" ]] || exit 1
        """
        assert _sh(checker, source) == [(3, EXEC)]

    @pytest.mark.parametrize(
        "test",
        [
            '[ -x "$venv/bin/pytest" ]',
            '[ -d "$venv/bin/python" ]',
            '[ -x "$other" ]',
            '[ -f "$venv/pyvenv.cfg" ]',
            '[ -n "$venv/bin/python" ]',
        ],
    )
    def test_other_tests_are_not_reported(self, checker: ModuleType, test: str) -> None:
        source = f"""
            usable() {{
                {test} && return 0
            }}
        """
        assert _sh(checker, source) == []

    def test_a_comment_or_string_is_not_a_test(self, checker: ModuleType) -> None:
        source = """
            # [ -x "$venv/bin/python" ] is what the old code did
            echo '[ -x "$venv/bin/python" ]'
        """
        assert _sh(checker, source) == []


class TestShellWeakLivenessProbe:
    @pytest.mark.parametrize(
        "command",
        [
            """"$candidate" -c 'import sys'""",
            """"$candidate" -c "import sys" > /dev/null 2>&1""",
            '"$PYTHON_CMD" --version',
            '"$venv/bin/python" -V',
            """timeout 5 "$candidate" -c 'import sys'""",
        ],
    )
    def test_import_sys_or_version_only(self, checker: ModuleType, command: str) -> None:
        source = f"""
            runs() {{
                if {command}; then
                    return 0
                fi
            }}
        """
        assert _sh(checker, source) == [(3, PROBE)]

    @pytest.mark.parametrize(
        "command",
        [
            """python3 -c 'import sys'""",
            """"$candidate" -c 'import sys; print(sys.version_info[:2])'""",
            """"$candidate" -c 'import claude_code_hooks_daemon'""",
            "git --version",
            """echo '"$candidate" -c "import sys"'""",
        ],
    )
    def test_a_probe_that_reads_more_or_probes_something_else(
        self, checker: ModuleType, command: str
    ) -> None:
        source = f"""
            runs() {{
                if {command}; then
                    return 0
                fi
            }}
        """
        assert _sh(checker, source) == []


class TestShellProof:
    def test_reading_pyvenv_cfg_and_comparing_a_version_exempts_the_function(
        self, checker: ModuleType
    ) -> None:
        source = """
            runs() {
                local built
                built="$(grep '^version' "$1/pyvenv.cfg")"
                [ "${built}" = "${want_version}" ] || return 1
                [ -x "$1/bin/python" ]
            }
        """
        assert _sh(checker, source) == []

    def test_pyvenv_cfg_alone_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            runs() {
                [ -f "$1/pyvenv.cfg" ] || return 1
                [ -x "$1/bin/python" ]
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_a_comment_mentioning_the_proof_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            runs() {
                # should read pyvenv.cfg and compare the version
                [ -x "$1/bin/python" ]
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_proof_in_another_function_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            proves() {
                grep version "$1/pyvenv.cfg"
            }
            trusts() {
                [ -x "$1/bin/python" ]
            }
        """
        assert _sh(checker, source) == [(6, EXEC)]

    def test_top_level_proof_covers_the_whole_script(self, checker: ModuleType) -> None:
        source = """
            built="$(grep '^version' "$1/pyvenv.cfg")"
            [ "$built" = "$want_version" ] || exit 1
            [ -x "$1/bin/python" ] || exit 1
        """
        assert _sh(checker, source) == []

    def test_a_top_level_proof_does_not_cover_a_function(self, checker: ModuleType) -> None:
        source = """
            built="$(grep '^version' "$1/pyvenv.cfg")"
            [ "$built" = "$want_version" ] || exit 1
            trusts() {
                [ -x "$1/bin/python" ]
            }
        """
        assert _sh(checker, source) == [(5, EXEC)]

    def test_calling_a_proven_gate_exempts(self, checker: ModuleType) -> None:
        source = """
            pick() {
                [ -x "$1/bin/python" ] && _rv_candidate_runs "$1/bin/python"
            }
        """
        assert _sh(checker, source, frozenset({"_rv_candidate_runs"})) == []

    def test_calling_a_gate_that_is_not_proven_does_not_exempt(self, checker: ModuleType) -> None:
        source = """
            pick() {
                [ -x "$1/bin/python" ] && _rv_candidate_runs "$1/bin/python"
            }
        """
        assert _sh(checker, source) == [(3, EXEC)]


_PY_WEAK = """
    def _venv_interpreter_runs(candidate):
        return subprocess.run([str(candidate), "-c", "import sys"]).returncode == 0
"""
_PY_STRONG = """
    def _venv_interpreter_runs(candidate):
        cfg = (candidate.parent.parent / "pyvenv.cfg").read_text()
        if parse_version(cfg) != sys.version_info[:2]:
            return False
        return subprocess.run([str(candidate), "-c", "import sys"]).returncode == 0
"""
_SH_WEAK = """
    _rv_candidate_runs() {
        "$1" -c 'import sys'
    }
"""
_SH_STRONG = """
    _rv_candidate_runs() {
        local built
        built="$(grep '^version' "$(dirname "$(dirname "$1")")/pyvenv.cfg")"
        [ "$built" = "$_rv_want_version" ] || return 1
        "$1" -c 'import sys'
    }
"""


class TestGatesAreProvenFromTheirOwnBody:
    """A gate counts as proof only if its own body compares the version."""

    def _gates(self, checker: ModuleType, py: str, sh: str) -> frozenset[str]:
        files = {"paths.py": py, "resolve_venv.sh": sh}
        gates = {
            "_venv_interpreter_runs": "paths.py",
            "_rv_candidate_runs": "resolve_venv.sh",
            "_rv_cached_venv_current": "resolve_venv.sh",
        }

        def read(path: str) -> str:
            return textwrap.dedent(files[path])

        proven: frozenset[str] = checker.proven_gates(gates, read)
        return proven

    def test_gates_that_only_probe_are_not_proof(self, checker: ModuleType) -> None:
        assert self._gates(checker, _PY_WEAK, _SH_WEAK) == frozenset()

    def test_gates_that_compare_the_version_are_proof(self, checker: ModuleType) -> None:
        assert self._gates(checker, _PY_STRONG, _SH_STRONG) == frozenset(
            {"_venv_interpreter_runs", "_rv_candidate_runs"}
        )

    def test_each_gate_is_judged_on_its_own(self, checker: ModuleType) -> None:
        assert self._gates(checker, _PY_STRONG, _SH_WEAK) == frozenset({"_venv_interpreter_runs"})

    def test_a_gate_with_no_body_is_not_proof(self, checker: ModuleType) -> None:
        assert self._gates(checker, "x = 1\n", "echo hi\n") == frozenset()

    def test_the_gate_list_names_the_intended_gates(self, checker: ModuleType) -> None:
        assert dict(checker.GATES) == {
            "venv_interpreter_usable": "src/claude_code_hooks_daemon/daemon/paths.py",
            "venv_python_usable": "scripts/lib/resolve_venv.sh",
            "_rv_cached_venv_current": "scripts/lib/resolve_venv.sh",
        }
        for path in checker.GATES.values():
            assert (_REPO_ROOT / path).is_file()


class TestWidenedToMatchTheIndependentSearch:
    """Shapes the independent search (Plan 00555) found that the first rules missed."""

    def test_existence_test_inside_a_compound_double_bracket(self, checker: ModuleType) -> None:
        source = """
            validate() {
                PYTHON_CMD="$(resolve_venv_python "$dir")"
                if [[ -z "$PYTHON_CMD" || ! -f "$PYTHON_CMD" ]]; then
                    return 1
                fi
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_a_compound_double_bracket_about_something_else_is_not_reported(
        self, checker: ModuleType
    ) -> None:
        source = """
            validate() {
                if [[ -z "$name" || ! -f "$config" ]]; then
                    return 1
                fi
            }
        """
        assert _sh(checker, source) == []

    def test_a_scan_variable_named_bin_entry_under_a_venv_glob(self, checker: ModuleType) -> None:
        source = """
            pick() {
                for candidate in "${daemon_dir}"/untracked/venv-*/bin/"$name"; do
                    [ -x "$candidate" ] || continue
                    echo "$candidate"
                done
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_a_tool_path_built_from_the_venv_dir_and_a_variable(self, checker: ModuleType) -> None:
        source = """
            venv_tool() {
                local tool_path="${VENV_DIR}/bin/${tool}"
                if [[ ! -f "${tool_path}" ]]; then
                    return 1
                fi
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_a_bin_entry_variable_outside_a_venv_is_not_reported(self, checker: ModuleType) -> None:
        source = """
            find_tool() {
                local tool_path="${PREFIX}/bin/${tool}"
                [ -x "${tool_path}" ]
            }
        """
        assert _sh(checker, source) == []

    @pytest.mark.parametrize(
        "binding",
        [
            'python_path = Path(metadata["python_path"])',
            'python_path = Path(metadata.get("python_path", ""))',
            'python_path = metadata["python_path"]',
        ],
    )
    def test_interpreter_path_read_from_venv_metadata(
        self, checker: ModuleType, binding: str
    ) -> None:
        source = f"""
            import os
            from pathlib import Path

            def usable(metadata):
                {binding}
                return python_path.is_file() and os.access(python_path, os.X_OK)
        """
        assert _py(checker, source) == [(7, EXEC)]

    def test_another_metadata_key_is_not_an_interpreter(self, checker: ModuleType) -> None:
        source = """
            from pathlib import Path

            def usable(metadata):
                config = Path(metadata["config_path"])
                return config.is_file()
        """
        assert _py(checker, source) == []


class TestImportingThePackageIsTheVersionCheck:
    """Running ``import <package>`` under the interpreter fails on a minor mismatch.

    A venv built for another minor cannot see its own site-packages, so the
    import is a stronger test than any version comparison -- provided the source
    tree is not put on ``sys.path`` first.
    """

    def test_shell_exec_test_followed_by_a_package_import_probe(self, checker: ModuleType) -> None:
        source = """
            healthy() {
                local py="$1/bin/python"
                [ -x "$py" ] && "$py" -c "import claude_code_hooks_daemon" 2>/dev/null
            }
        """
        assert _sh(checker, source) == []

    def test_shell_import_probe_that_prepends_the_source_tree_is_not_proof(
        self, checker: ModuleType
    ) -> None:
        source = """
            healthy() {
                local py="$1/bin/python"
                [ -x "$py" ] || return 1
                "$py" -c "import sys; sys.path.insert(0, 'src'); import claude_code_hooks_daemon"
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_shell_import_of_another_module_is_not_proof(self, checker: ModuleType) -> None:
        source = """
            healthy() {
                local py="$1/bin/python"
                [ -x "$py" ] && "$py" -c "import json"
            }
        """
        assert _sh(checker, source) == [(4, EXEC)]

    def test_python_exists_followed_by_a_package_import_probe(self, checker: ModuleType) -> None:
        source = """
            import subprocess

            def validate(venv_python):
                python = venv_python / "bin" / "python"
                if not python.exists():
                    return False
                result = subprocess.run([str(python), "-c", "import claude_code_hooks_daemon"])
                return result.returncode == 0
        """
        assert _py(checker, source) == []

    def test_python_import_probe_that_edits_sys_path_is_not_proof(
        self, checker: ModuleType
    ) -> None:
        source = """
            import subprocess

            def validate(venv):
                python = venv / "bin" / "python"
                if not python.exists():
                    return False
                code = "import sys; sys.path.insert(0, 'src'); import claude_code_hooks_daemon"
                return subprocess.run([str(python), "-c", code]).returncode == 0
        """
        assert _py(checker, source) == [(6, EXEC)]


class TestScope:
    @pytest.mark.parametrize(
        "path",
        [
            "bin/hooks-daemon",
            "init.sh",
            ".claude/init.sh",
            ".claude/hooks/pre-tool-use",
            "src/claude_code_hooks_daemon/install/templates/hooks-daemon",
            "src/claude_code_hooks_daemon/daemon/paths.py",
            "scripts/lib/resolve_venv.sh",
            "CLAUDE/UPGRADES/v3/upgrade.sh",
        ],
    )
    def test_first_party_paths_are_in_scope(self, checker: ModuleType, path: str) -> None:
        assert checker.in_scope(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "tests/unit/test_x.py",
            "tests/helpers/venv.sh",
            "src/pkg/fixtures/broken.py",
            "src/pkg/assets/thing.sh",
            ".claude/worktrees/agent-1/init.sh",
            "untracked/venv-x/bin/python",
            "vendor/thing/setup.py",
            "web/node_modules/pkg/index.sh",
        ],
    )
    def test_tests_fixtures_worktrees_untracked_and_vendored_are_out(
        self, checker: ModuleType, path: str
    ) -> None:
        assert checker.in_scope(path) is False


class TestReporting:
    def test_violation_message_is_terse_and_ends_with_the_doc_path(
        self, checker: ModuleType
    ) -> None:
        violation = checker.Violation(file="a.py", line=3, rule=EXEC, call="x.is_file()")
        message = violation.to_dict()["message"]
        assert isinstance(message, str)
        assert message.endswith("CLAUDE/Security/UntrustedVenvInterpreter.md")
        assert len(message) < 220

    def test_every_rule_has_a_message(self, checker: ModuleType) -> None:
        for rule in (EXEC, PROBE):
            violation = checker.Violation(file="a.py", line=1, rule=rule, call="c")
            assert violation.to_dict()["rule"] == rule

    def test_one_finding_per_line_and_rule(self, checker: ModuleType) -> None:
        source = """
            import os

            def usable(venv):
                python = venv / "bin" / "python"
                return python.is_file() and python.exists()
        """
        assert _py(checker, source) == [(6, EXEC)]

    def test_findings_are_sorted_by_line(self, checker: ModuleType) -> None:
        source = """
            def b(venv):
                return (venv / "bin" / "python").exists()

            def a(venv):
                return (venv / "bin" / "python").is_file()
        """
        assert [line for line, _ in _py(checker, source)] == [3, 6]

    def test_json_output_names_the_tool(
        self, checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(checker, "_OUTPUT_FILE", tmp_path / "out.json")
        monkeypatch.setattr(checker, "scanned_files", lambda: ([], []))
        monkeypatch.setattr(sys, "argv", ["check", "--json"])
        assert checker.main() == 0
        data = json.loads((tmp_path / "out.json").read_text())
        assert data["tool"] == "venv_interpreter_trust"
        assert data["summary"]["passed"] is True
        assert data["violations"] == []

    def test_main_fails_when_a_file_has_a_finding(
        self, checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = tmp_path / "bad.sh"
        script.write_text('usable() {\n    [ -x "$1/bin/python" ]\n}\n')
        monkeypatch.setattr(checker, "_OUTPUT_FILE", tmp_path / "out.json")
        monkeypatch.setattr(checker, "scanned_files", lambda: ([], [script]))
        monkeypatch.setattr(sys, "argv", ["check", "--json"])
        assert checker.main() == 1
        data = json.loads((tmp_path / "out.json").read_text())
        assert data["summary"]["total_violations"] == 1
        assert data["violations"][0]["rule"] == EXEC

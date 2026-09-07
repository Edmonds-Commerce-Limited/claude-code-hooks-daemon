"""Integration test: ``merge_custom_config`` must write the merged config for
ANY value the user's config can legally hold — including a backslash.

Field defect from the v3.62.0 upgrade. ``merge_custom_config`` handed the
merge CLI's JSON result to Python by INTERPOLATING it into a triple-quoted
source literal::

    data = json.loads('''$merge_output''')

Two decoders then run over the same bytes. Python's tokenizer unescapes the
literal first, so a JSON-encoded backslash (``"^pip\\\\b"`` on the wire) reaches
``json.loads`` already halved to ``"^pip\\b"``. ``\\b`` happens to be a valid
JSON escape, so that one silently decodes to a backspace; ``\\.`` and ``\\d``
are not, and the upgrade dies with ``JSONDecodeError: Invalid \\escape``.

A regex is the ordinary way to write an ``exclude_paths`` or a command
pattern, so this is not an exotic input — it aborted a real upgrade.

The fix removes the second decoder: the JSON travels on stdin and the output
path on argv, so no user byte is ever parsed as Python source. These tests
pin the observable behaviour (the merged file is written, and holds the
user's value verbatim) rather than the mechanism, so they keep their meaning
if the implementation changes again.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PRESERVE_SH = REPO_ROOT / "scripts" / "install" / "config_preserve.sh"
BASH = shutil.which("bash") or "/bin/bash"

# A default config in the shape the differ expects: the sections it has a
# dedicated pass for, and nothing the tests below want to see preserved.
_DEFAULT_CONFIG: dict[str, object] = {
    "version": "3.0",
    "daemon": {"log_level": "INFO"},
    "handlers": {"pre_tool_use": {}},
}


def _write_yaml(path: Path, data: object) -> None:
    """Serialise ``data`` to ``path`` as YAML."""
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _run_merge(tmp_path: Path, user_config: dict[str, object]) -> tuple[int, str, Path]:
    """Source the helper and run ``merge_custom_config`` with an output file.

    Returns the exit code, the combined output, and the path the merged YAML
    was requested at (which may not exist if the merge failed).
    """
    user_path = tmp_path / "user.yaml"
    old_default_path = tmp_path / "old-default.yaml"
    new_default_path = tmp_path / "new-default.yaml"
    merged_path = tmp_path / "merged.yaml"

    _write_yaml(user_path, user_config)
    _write_yaml(old_default_path, _DEFAULT_CONFIG)
    _write_yaml(new_default_path, _DEFAULT_CONFIG)

    script = textwrap.dedent(f"""
        set -uo pipefail
        source "{CONFIG_PRESERVE_SH}"
        merge_custom_config \\
            "{sys.executable}" \\
            "{user_path}" \\
            "{old_default_path}" \\
            "{new_default_path}" \\
            "{merged_path}"
        """)
    result = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr, merged_path


class TestMergeSurvivesEveryLegalConfigValue:
    """``merge_custom_config`` must not re-parse user bytes as Python source."""

    def test_a_backslash_regex_does_not_abort_the_merge(self, tmp_path: Path) -> None:
        """``^pip\\b`` in a user option must not raise ``Invalid \\escape``.

        This is the field failure verbatim: a command-pattern regex in an
        ordinary handler option aborted the whole upgrade.
        """
        user_config = {
            **_DEFAULT_CONFIG,
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {
                        "enabled": True,
                        "options": {"patterns": ["^pip\\b", "^poetry\\s"]},
                    }
                }
            },
        }

        exit_code, output, merged_path = _run_merge(tmp_path, user_config)

        assert exit_code == 0, f"merge failed: {output}"
        assert merged_path.exists(), f"merged config was never written: {output}"

    def test_a_backslash_regex_survives_verbatim(self, tmp_path: Path) -> None:
        """The written YAML must hold the user's regex byte-for-byte.

        Not aborting is not enough. ``\\b`` is a legal JSON escape, so the old
        double-decode turned it into a BACKSPACE character and wrote a config
        that was silently wrong rather than loudly broken.
        """
        user_config = {
            **_DEFAULT_CONFIG,
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {
                        "enabled": True,
                        "options": {"patterns": ["^pip\\b"]},
                    }
                }
            },
        }

        exit_code, output, merged_path = _run_merge(tmp_path, user_config)

        assert exit_code == 0, f"merge failed: {output}"
        merged = yaml.safe_load(merged_path.read_text())
        patterns = merged["handlers"]["pre_tool_use"]["my_handler"]["options"]["patterns"]
        assert patterns == ["^pip\\b"], f"regex was mangled in transit: {patterns!r}"

    def test_an_invalid_python_escape_survives_verbatim(self, tmp_path: Path) -> None:
        """``\\d`` and ``\\.`` are the escapes that produced the hard abort."""
        user_config = {
            **_DEFAULT_CONFIG,
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {
                        "enabled": True,
                        "options": {"patterns": ["v\\d+\\.\\d+"]},
                    }
                }
            },
        }

        exit_code, output, merged_path = _run_merge(tmp_path, user_config)

        assert exit_code == 0, f"merge failed: {output}"
        merged = yaml.safe_load(merged_path.read_text())
        patterns = merged["handlers"]["pre_tool_use"]["my_handler"]["options"]["patterns"]
        assert patterns == ["v\\d+\\.\\d+"], f"regex was mangled in transit: {patterns!r}"

    def test_a_triple_quote_in_a_config_value_does_not_break_the_writer(
        self, tmp_path: Path
    ) -> None:
        """A value containing ``'''`` used to terminate the Python literal.

        The same interpolation that mis-decoded backslashes let a user value
        close the string it was embedded in — a config value should never be
        able to reach the interpreter as code.
        """
        user_config = {
            **_DEFAULT_CONFIG,
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {
                        "enabled": True,
                        "options": {"docstring_marker": "'''"},
                    }
                }
            },
        }

        exit_code, output, merged_path = _run_merge(tmp_path, user_config)

        assert exit_code == 0, f"merge failed: {output}"
        merged = yaml.safe_load(merged_path.read_text())
        options = merged["handlers"]["pre_tool_use"]["my_handler"]["options"]
        assert options["docstring_marker"] == "'''"

    def test_a_plain_config_still_merges(self, tmp_path: Path) -> None:
        """The ordinary path keeps working — this is a regression guard."""
        user_config = {
            **_DEFAULT_CONFIG,
            "daemon": {"log_level": "DEBUG"},
        }

        exit_code, output, merged_path = _run_merge(tmp_path, user_config)

        assert exit_code == 0, f"merge failed: {output}"
        merged = yaml.safe_load(merged_path.read_text())
        assert merged["daemon"]["log_level"] == "DEBUG"


def _run_report(merge_json: str) -> tuple[int, str]:
    """Source the helper and run ``report_incompatibilities`` on ``merge_json``."""
    script = textwrap.dedent(f"""
        set -uo pipefail
        source "{CONFIG_PRESERVE_SH}"
        report_incompatibilities "{sys.executable}" {shlex.quote(merge_json)}
        """)
    result = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


class TestConflictReportingSurvivesEveryLegalConfigValue:
    """``report_incompatibilities`` decodes the same JSON and had the same flaw.

    A conflict record carries ``user_value`` — the user's own config value —
    so a regex option that reaches the conflict report hits the identical
    double-decode. This path is what TELLS the user their customization could
    not be applied, so losing it loses the warning as well as the value.
    """

    def test_a_clean_merge_reports_no_conflicts(self) -> None:
        """The ordinary path keeps working — regression guard."""
        merge_json = json.dumps({"is_clean": True, "conflicts": []})

        exit_code, output = _run_report(merge_json)

        assert exit_code == 0, output
        assert "No conflicts found" in output

    def test_a_backslash_in_a_conflict_value_still_reports(self) -> None:
        """A regex ``user_value`` must not abort the conflict report.

        A scalar is used rather than a nested dict so the assertion reads the
        value itself: the report renders ``user_value`` with an f-string, and a
        dict would arrive via ``repr`` with its backslashes doubled for
        display, which says nothing about whether they survived transit.
        """
        merge_json = json.dumps(
            {
                "is_clean": False,
                "conflicts": [
                    {
                        "path": "handlers.pre_tool_use.my_handler",
                        "conflict_type": "missing_handler",
                        "description": "Handler no longer exists",
                        "user_value": "v\\d+\\.\\d+",
                        "default_value": None,
                    }
                ],
            }
        )

        exit_code, output = _run_report(merge_json)

        assert exit_code == 1, f"expected the conflict exit code, got {exit_code}: {output}"
        assert "Found 1 conflict(s)" in output
        assert "my_handler" in output
        assert "Your value: v\\d+\\.\\d+" in output, f"the user's value was mangled: {output}"


class TestNoInstallScriptRebuildsPythonSourceFromShellVariables:
    """Static guard: a shell variable must never land inside a Python literal.

    The three sites this test was written for were all the same shape —
    ``json.loads('''$var''')`` — and all three were reachable from a normal
    upgrade. The behavioural tests above cover two of them; the third lives
    inside ``preserve_config_for_upgrade`` behind a ``try/except`` and a
    sanctioned ``|| true``, so its failure mode is a SILENTLY skipped
    breaking-changes report rather than a visible abort. That is precisely the
    case a behavioural test is worst at catching and a static guard is best
    at, and it is why this class exists alongside them.

    The rule is the general one, not a patch for three known lines: user text
    goes in on stdin or argv, never through the tokenizer.
    """

    # A quoted Python string literal containing a shell expansion. Matches
    # '''$x''' / \"\"\"$x\"\"\" / '$x' / \"$x\" and the ${x} brace form.
    _INTERPOLATION_IN_LITERAL = re.compile(
        r"""(?P<quote>'{3}|"{3}|'|")\s*\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\s*(?P=quote)"""
    )

    def _python_heredoc_spans(self, text: str) -> list[tuple[int, str]]:
        """Return ``(line_number, line)`` for lines inside a ``python -c "..."`` block.

        The embedded Python starts at a ``-c "`` that ends the line (the
        opening quote of a multi-line source string) and runs to the line
        whose first character closes it.
        """
        spans: list[tuple[int, str]] = []
        inside = False
        for number, line in enumerate(text.splitlines(), start=1):
            if not inside:
                if re.search(r"-c\s+\"\s*$", line):
                    inside = True
                continue
            if line.startswith('"'):
                inside = False
                continue
            spans.append((number, line))
        return spans

    def test_no_install_script_interpolates_a_variable_into_a_python_literal(self) -> None:
        """Every ``scripts/install/*.sh`` embedded-Python block must be clean."""
        offenders: list[str] = []
        for script in sorted((REPO_ROOT / "scripts" / "install").glob("*.sh")):
            for number, line in self._python_heredoc_spans(script.read_text()):
                if self._INTERPOLATION_IN_LITERAL.search(line):
                    offenders.append(f"{script.relative_to(REPO_ROOT)}:{number}: {line.strip()}")

        assert not offenders, (
            "Shell variables are being interpolated into Python string literals. "
            "Python's tokenizer decodes the literal before the program runs, so a "
            "backslash or a quote in the value is reinterpreted as source. Pass the "
            "value on stdin (sys.stdin.read()) or argv (sys.argv[1]) instead:\n  "
            + "\n  ".join(offenders)
        )

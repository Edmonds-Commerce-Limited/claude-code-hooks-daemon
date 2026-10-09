"""Every inline QA suppression must carry its reasoning (Plan 00484 G1, owner ruling B2).

Owner ruling B2: suppressions stay inline, co-located with the code they excuse,
and each MUST carry its reasoning. There is no central exceptions file and no
baseline. This detector is what makes "MUST carry" true: a suppression with no
reason on its line, in the same comment, or in the comment block directly above
fails the gate.

Python comments are found with ``tokenize``, so the text of a directive inside a
string or docstring (the ``qa_suppression`` handler's own fixtures, prose that
names the directives) is never judged.

The directive names are assembled from parts below: the ``qa_suppression``
handler blocks a write that carries one as literal text, even inside a string.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
    PythonQaSuppressionStrategy,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_inline_suppressions.py"

NOQA: Final[str] = "# no" + "qa"
NOSEC: Final[str] = "# no" + "sec"
NOSEMGREP: Final[str] = "# no" + "semgrep"
TYPE_IGNORE: Final[str] = "# type: " + "ignore"
NO_COVER: Final[str] = "# pragma: " + "no cover"
SHELLCHECK: Final[str] = "# shellcheck " + "disable"

#: Directives the qa_suppression write-time list names, plus the file-wide forms of
#: tools the project gates on. Assembled from parts for the same reason as above.
PROJECT_FORM_SAMPLES: Final[tuple[str, ...]] = (
    "# py" + "right: ignore",
    "# py" + "right: ignore[reportAssignmentType]",
    "# py" + "right: reportMissingImports=false",
    "# my" + "py: ignore-errors",
    "# pyl" + "int: disable=C0114",
    "# ru" + "ff: no" + "qa",
    "# ru" + "ff: no" + "qa: E501",
    "# fla" + "ke8: no" + "qa",
    "# my" + "py: disable-error-code=attr-defined",
)

#: The ten suppressions in the tree whose reason is the comment block above them, not
#: their own line. Each names a code of the directive, or a tool, or opens with SECURITY:.
GENUINE_REASON_ABOVE: Final[tuple[tuple[str, int], ...]] = (
    (".claude/ccy/claude-supervise.py", 9336),
    ("init.sh", 1215),
    ("init.sh", 2566),
    ("init.sh", 2676),
    ("scripts/install/venv.sh", 356),
    ("scripts/install/venv.sh", 532),
    ("src/claude_code_hooks_daemon/constants/paths.py", 91),
    ("src/claude_code_hooks_daemon/install/transport_toggle.py", 31),
    ("src/claude_code_hooks_daemon/install/transport_verify.py", 37),
    ("src/claude_code_hooks_daemon/install/transport_verify.py", 158),
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_inline_suppressions", _CHECKER)
    assert spec is not None and spec.loader is not None, f"cannot load {_CHECKER}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _findings(root: Path) -> list[dict[str, object]]:
    return list(checker.find_violations(root))


class TestAPythonSuppressionWithNoReasonFails:
    """One case per directive family the ruling names."""

    @pytest.mark.parametrize(
        "line",
        [
            f"import subprocess  {NOSEC} B404\n",
            f"import subprocess  {NOSEC}\n",
            f"value: int = 'x'  {TYPE_IGNORE}\n",
            f"value: int = 'x'  {TYPE_IGNORE}[assignment]\n",
            f"import os, sys  {NOQA}\n",
            f"import os, sys  {NOQA}: E401\n",
            f"import os, sys  {NOQA}: E401, F401\n",
            f"call()  {NOSEMGREP}\n",
            f"call()  {NOSEMGREP}: rules.some-rule\n",
            f"if x:  {NO_COVER}\n",
            f"if x:  {NO_COVER} -\n",
        ],
    )
    def test_a_bare_directive_is_a_finding(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line}")
        found = _findings(tmp_path)
        assert [f["rule"] for f in found] == ["inline-suppression-without-reason"]
        assert found[0]["file"] == "mod.py"
        assert found[0]["line"] == 2

    @pytest.mark.parametrize(
        "line",
        [
            f"import subprocess  {NOSEC} B404 - only the CompletedProcess type is named\n",
            f"import subprocess  {NOSEC} B404 — trusted system git, fixed argv\n",
            f"value: int = 'x'  {TYPE_IGNORE}[assignment] - the stub is wrong upstream\n",
            f"import os, sys  {NOQA}: E401 - a tuple import reads clearer here\n",
            f"call()  {NOSEMGREP}: rules.some-rule - bounded by the caller\n",
            f"if x:  {NO_COVER} - matches() gates this branch\n",
        ],
    )
    def test_a_reason_on_the_line_passes(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line}")
        assert _findings(tmp_path) == []

    def test_a_placeholder_reason_is_a_finding(self, tmp_path: Path) -> None:
        """The same generic-reason check the MUST_*_BECAUSE hatches use."""
        _write(tmp_path, "mod.py", f"import subprocess  {NOSEC} B404 - needed\n")
        assert [f["rule"] for f in _findings(tmp_path)] == ["inline-suppression-without-reason"]

    def test_a_second_comment_segment_is_the_reason(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f"x = f()  {NOQA}: E501  # the URL cannot be wrapped\n")
        assert _findings(tmp_path) == []

    def test_a_comment_block_directly_above_is_the_reason(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "mod.py",
            "# SECURITY: runs this package's own CLI via sys.executable,\n"
            "# fixed argv and no shell.\n"
            f"import subprocess  {NOSEC} B404\n",
        )
        assert _findings(tmp_path) == []

    def test_a_blank_line_between_breaks_the_block(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "mod.py",
            f"# Fixed argv and no shell.\n\nimport subprocess  {NOSEC} B404\n",
        )
        assert [f["line"] for f in _findings(tmp_path)] == [3]

    def test_code_above_is_not_a_reason(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f"total = 1  # sum of the parts\nimport os  {NOQA}\n")
        assert [f["line"] for f in _findings(tmp_path)] == [2]

    def test_another_directive_above_is_not_a_reason(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f"import os  {NOQA}\nimport sys  {NOQA}\n")
        assert [f["line"] for f in _findings(tmp_path)] == [1, 2]

    def test_a_reason_above_covers_only_the_line_it_touches(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "mod.py",
            "# F401 is expected: re-exported so callers import them from here.\n"
            f"from a import b  {NOQA}: F401\n"
            f"from a import c  {NOQA}: F401\n",
        )
        assert [f["line"] for f in _findings(tmp_path)] == [3]


class TestTheProjectsOwnDirectiveListIsJudged:
    """B2: pyright, mypy, pylint and the file-wide ruff/flake8 forms are suppressions too."""

    @pytest.mark.parametrize("line", PROJECT_FORM_SAMPLES)
    def test_a_bare_directive_is_a_finding(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line}\n")
        found = _findings(tmp_path)
        assert [f["line"] for f in found] == [2]

    @pytest.mark.parametrize("line", PROJECT_FORM_SAMPLES)
    def test_a_reason_on_the_line_passes(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line} - the stub is wrong upstream\n")
        assert _findings(tmp_path) == []

    @pytest.mark.parametrize("line", PROJECT_FORM_SAMPLES)
    def test_a_directive_counts_towards_the_denominator(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line} - the stub is wrong upstream\n")
        assert checker.scan(tmp_path).suppressions_found == 1

    def test_every_pattern_of_the_write_time_list_has_a_sample(self) -> None:
        """The detector reads the strategy's list, so a pattern added there needs a sample here."""
        samples = (NOQA, TYPE_IGNORE, *PROJECT_FORM_SAMPLES)
        for pattern in PythonQaSuppressionStrategy().forbidden_patterns:
            assert any(re.search(pattern, sample) for sample in samples), pattern

    def test_the_detector_reads_the_strategy_list_not_a_copy(self) -> None:
        assert (
            checker.PROJECT_FORBIDDEN_PATTERNS == PythonQaSuppressionStrategy().forbidden_patterns
        )


class TestNosecReasonsAreReasons:
    """S6: an ID with a colon, or Bandit's test name, names the check and not the reason."""

    @pytest.mark.parametrize(
        "line",
        [
            f"import subprocess  {NOSEC}: B603\n",
            f"import subprocess  {NOSEC}:B603\n",
            f"import subprocess  {NOSEC} subprocess_without_shell_equals_true\n",
            f"import subprocess  {NOSEC}: B404, B603\n",
            f"import subprocess  {NOSEC} B404 import_subprocess\n",
        ],
    )
    def test_codes_and_test_names_alone_are_findings(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line}")
        assert [f["line"] for f in _findings(tmp_path)] == [2]

    @pytest.mark.parametrize(
        "line",
        [
            f"import subprocess  {NOSEC}: B603 - fixed argv, no shell\n",
            f"import subprocess  {NOSEC} subprocess_without_shell_equals_true - fixed argv\n",
        ],
    )
    def test_a_reason_after_them_passes(self, tmp_path: Path, line: str) -> None:
        _write(tmp_path, "mod.py", f"x = 1\n{line}")
        assert _findings(tmp_path) == []


class TestTheBlockAboveMustBeAboutTheSuppression:
    """S2: an adjacent comment about something else is not the reason."""

    def test_an_unrelated_comment_above_is_a_finding(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "run.sh",
            "#!/usr/bin/env bash\n"
            "# First call: return one-time advisory context so the agent sees it once.\n"
            f"{SHELLCHECK}=SC2317\n",
        )
        assert [f["line"] for f in _findings(tmp_path)] == [3]

    def test_a_comment_naming_the_code_is_a_reason(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "run.sh",
            "#!/usr/bin/env bash\n# SC2317 fires here: the body is only reached via export -f.\n"
            f"{SHELLCHECK}=SC2317\n",
        )
        assert _findings(tmp_path) == []

    def test_a_comment_naming_the_tool_is_a_reason(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "run.sh",
            "#!/usr/bin/env bash\n# Called by the forwarder, so shellcheck sees dead code.\n"
            f"{SHELLCHECK}=SC2317\n",
        )
        assert _findings(tmp_path) == []

    @pytest.mark.parametrize(
        ("above", "directive"),
        [
            ("# There is no config file here.", NO_COVER),
            ("# Return type of the handler.", TYPE_IGNORE),
            ("# Ignore empty lines.", TYPE_IGNORE),
            ("# Disable the cache when pragma is set.", NO_COVER),
            ("# Nonsecurity data only.", NOSEC + " B404"),
            ("# A SECURITY-minded reader skips this.", NOSEC + " B404"),
            ("# The b4040 constant.", NOSEC + " B404"),
        ],
    )
    def test_the_directives_own_words_and_substrings_are_not_a_reason(
        self, tmp_path: Path, above: str, directive: str
    ) -> None:
        """SHOULD 1: `no`, `cover`, `type`, `ignore` prove nothing, and neither do substrings."""
        _write(tmp_path, "mod.py", f"{above}\nx = 1  {directive}\n")
        assert [f["line"] for f in _findings(tmp_path)] == [2]

    @pytest.mark.parametrize(
        ("above", "directive"),
        [
            ("# B404 is raised by the bare import.", NOSEC + " B404"),
            ("# bandit flags the import only.", NOSEC + " B404"),
            ("# mypy cannot see the stub.", TYPE_IGNORE),
            ("# The stub lacks it: attr-defined.", TYPE_IGNORE + "[attr-defined]"),
            ("# SECURITY: fixed argv, no shell.", NOSEC + " B603"),
        ],
    )
    def test_a_code_a_tool_or_the_security_marker_is_a_reason(
        self, tmp_path: Path, above: str, directive: str
    ) -> None:
        _write(tmp_path, "mod.py", f"{above}\nx = 1  {directive}\n")
        assert _findings(tmp_path) == []

    @pytest.mark.parametrize(("relative", "line"), GENUINE_REASON_ABOVE)
    def test_the_genuine_reason_above_in_this_tree_still_passes(
        self, relative: str, line: int
    ) -> None:
        path = _REPO_ROOT / relative
        text = path.read_text(encoding="utf-8")
        shell = checker._is_shell(path, text.split("\n", 1)[0])
        comments = checker._shell_comments(text) if shell else checker._python_comments(text)
        parsed = checker.parse_comment(comments[line].text)
        assert parsed.directives, f"{relative}:{line} is not a suppression"
        assert not checker.is_acceptable_reason(parsed.reason_text), "reason is on the line itself"
        assert checker.judge_comments(comments)[1] == []

    def test_an_unrelated_comment_above_a_python_directive_is_a_finding(
        self, tmp_path: Path
    ) -> None:
        _write(tmp_path, "mod.py", f"# Parse the config file.\nimport os  {NOQA}: F401\n")
        assert [f["line"] for f in _findings(tmp_path)] == [2]


class TestOnlyRealCommentsAreJudged:
    def test_a_directive_in_a_string_is_not_a_comment(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f'SAMPLE = "x = 1  {NOQA}"\n')
        assert _findings(tmp_path) == []

    def test_a_directive_in_a_docstring_is_not_a_comment(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f'"""Blocks `{TYPE_IGNORE}` and `{NOSEC}`."""\n')
        assert _findings(tmp_path) == []

    def test_prose_that_merely_mentions_a_directive_is_not_one(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", "# the noqa marker is handled by the formatter\n")
        assert _findings(tmp_path) == []

    def test_a_formatter_marker_is_not_a_qa_suppression(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", "TABLE = (\n    1,\n)  # fmt: skip\n")
        assert _findings(tmp_path) == []

    def test_markdown_is_not_scanned(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", "VALUE = 1\n")
        _write(tmp_path, "notes.md", f"import os  {NOQA}\n")
        assert _findings(tmp_path) == []


class TestShellSuppressions:
    def test_a_bare_shellcheck_disable_is_a_finding(self, tmp_path: Path) -> None:
        _write(tmp_path, "run.sh", f"#!/usr/bin/env bash\n{SHELLCHECK}=SC2317\nf() {{ :; }}\n")
        found = _findings(tmp_path)
        assert [(f["file"], f["line"]) for f in found] == [("run.sh", 2)]

    def test_a_reason_after_the_codes_passes(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "run.sh",
            f"#!/usr/bin/env bash\n{SHELLCHECK}=SC1090  # path is computed at runtime\n",
        )
        assert _findings(tmp_path) == []

    def test_a_comment_line_above_passes(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "run.sh",
            "#!/usr/bin/env bash\n# Invoked only by the EXIT trap, so shellcheck sees the body as dead.\n"
            f"{SHELLCHECK}=SC2317\n",
        )
        assert _findings(tmp_path) == []

    def test_an_extensionless_shell_script_is_scanned(self, tmp_path: Path) -> None:
        _write(tmp_path, "bin/tool", f'#!/bin/bash\n{SHELLCHECK}=SC1090\n. "$X"\n')
        assert [f["file"] for f in _findings(tmp_path)] == ["bin/tool"]

    def test_an_extensionless_non_shell_file_is_not_scanned(self, tmp_path: Path) -> None:
        _write(tmp_path, "LICENSE", f"{SHELLCHECK}=SC1090\n")
        _write(tmp_path, "mod.py", "VALUE = 1\n")
        assert _findings(tmp_path) == []

    def test_a_multiple_code_directive_is_one_finding(self, tmp_path: Path) -> None:
        _write(tmp_path, "run.sh", f"#!/bin/sh\n{SHELLCHECK}=SC2034,SC2154\n")
        assert len(_findings(tmp_path)) == 1


class TestTheScanRefusesToPassVacuously:
    def test_unreadable_python_is_a_finding_not_a_skip(self, tmp_path: Path) -> None:
        _write(tmp_path, "bad.py", f"x = 1  {NOQA} - kept\n'''unterminated\n")
        rules = [f["rule"] for f in _findings(tmp_path)]
        assert rules == ["unreadable-file"]

    def test_the_skipped_directories_are_not_scanned(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", "VALUE = 1\n")
        _write(tmp_path, "untracked/scratch/x.py", f"import os  {NOQA}\n")
        _write(tmp_path, "node_modules/p/x.py", f"import os  {NOQA}\n")
        assert _findings(tmp_path) == []

    def test_a_checkout_under_a_skipped_name_is_still_scanned(self, tmp_path: Path) -> None:
        """Directory names are judged below the root, never on the absolute path (N26)."""
        root = tmp_path / "untracked" / "worktrees" / "wt"
        _write(root, "mod.py", f"import os  {NOQA}\n")
        assert [f["file"] for f in _findings(root)] == ["mod.py"]


class TestTheCommandLine:
    def _run(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_CHECKER), "--json", "--path", str(root), *extra],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )

    def test_a_clean_tree_passes_and_reports_its_denominator(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f"import subprocess  {NOSEC} B404 - fixed argv, no shell\n")
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stderr
        data = json.loads((tmp_path / "inline_suppressions.json").read_text())
        assert data["summary"]["passed"] is True
        assert data["summary"]["files_scanned"] == 1
        assert data["summary"]["suppressions_found"] == 1
        assert data["summary"]["total_violations"] == 0

    def test_a_reasonless_suppression_fails_with_its_location(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f"import os  {NOQA}\n")
        result = self._run(tmp_path)
        assert result.returncode == 1
        data = json.loads((tmp_path / "inline_suppressions.json").read_text())
        assert data["summary"]["passed"] is False
        violation = data["violations"][0]
        assert (violation["file"], violation["line"]) == ("mod.py", 1)
        assert violation["directive"] == "noqa"
        assert "reason" in violation["message"]

    def test_an_empty_root_fails(self, tmp_path: Path) -> None:
        assert self._run(tmp_path).returncode == 1

    def test_the_text_mode_names_each_finding(self, tmp_path: Path) -> None:
        _write(tmp_path, "mod.py", f"import os  {NOQA}\n")
        result = subprocess.run(
            [sys.executable, str(_CHECKER), "--path", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )
        assert result.returncode == 1
        assert "mod.py:1" in result.stdout


class TestTheRepositoryItself:
    def test_this_repository_carries_a_reason_on_every_suppression(self) -> None:
        """The detector's verdict on the tracked tree, so a reasonless one fails the suite."""
        found = _findings(_REPO_ROOT)
        assert [(f["file"], f["line"]) for f in found] == []

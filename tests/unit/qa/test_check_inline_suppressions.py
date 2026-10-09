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
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_inline_suppressions.py"

NOQA: Final[str] = "# no" + "qa"
NOSEC: Final[str] = "# no" + "sec"
NOSEMGREP: Final[str] = "# no" + "semgrep"
TYPE_IGNORE: Final[str] = "# type: " + "ignore"
NO_COVER: Final[str] = "# pragma: " + "no cover"
SHELLCHECK: Final[str] = "# shellcheck " + "disable"


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
            "# Re-exported on purpose so callers import them from here.\n"
            f"from a import b  {NOQA}: F401\n"
            f"from a import c  {NOQA}: F401\n",
        )
        assert [f["line"] for f in _findings(tmp_path)] == [3]


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
            f"#!/usr/bin/env bash\n# Invoked indirectly by the EXIT trap.\n{SHELLCHECK}=SC2317\n",
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

"""The gate that stops Plan 00347's defect class coming back.

Fourteen call sites under ``handlers/`` judged a caller-supplied path with a raw
``Path.exists()`` / ``is_file()`` / ``is_dir()``. Every one raised
``PermissionError`` when an ancestor directory lacked ``+x``, because EACCES is
not among the stat failures ``pathlib`` swallows. Converting those fourteen
fixes the instances; the fifteenth call site would reintroduce the bug with
nothing to catch it.

So the gate is the deliverable, not the conversions. It is modelled on
``check_canonical_callers.sh``: go through the canonical helper, or carry an
inline marker recording WHY this site does not need it.

**Scope is the interesting decision.** Only some handler families can receive a
path the daemon did not choose. A ``PreToolUse``/``PostToolUse`` handler reads
``tool_input.file_path``; a worktree handler reads a path from its event
payload. A ``SessionStart`` or ``status_line`` handler has no such input at all
— its paths are built from the project root and config — so requiring markers
there would be 38 comments asserting something already true by construction,
and noise is how a real marker stops being read.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_CHECKER: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "check_eacces_safe_predicates.py"

_RAW_PREDICATE = "        if Path(file_path).is_file():\n            return False\n"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKER), *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def _handler_file(root: Path, family: str, name: str, body: str) -> Path:
    directory = root / "handlers" / family
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        "from pathlib import Path\n\n\nclass H:\n    def matches(self, file_path: str) -> bool:\n"
        + body,
        encoding="utf-8",
    )
    return path


class TestTheCheckerExists:
    def test_it_is_executable_as_a_script(self) -> None:
        """Guards the whole file: every assertion below would pass vacuously
        against a checker that cannot run, since a crash and a clean scan both
        produce no violations list."""
        result = _run("--help")

        assert result.returncode in (0, 1), result.stderr


class TestTheLiveRepoIsClean:
    def test_the_repository_has_no_unmarked_violations(self) -> None:
        """The gate must pass on the tree that ships it. A gate committed red
        gets disabled rather than obeyed."""
        result = _run()

        assert result.returncode == 0, result.stdout + result.stderr


class TestANewRawPredicateFails:
    def test_a_raw_is_file_in_pre_tool_use_is_a_violation(self, tmp_path: Path) -> None:
        _handler_file(tmp_path, "pre_tool_use", "new_guard.py", _RAW_PREDICATE)

        result = _run("--path", str(tmp_path))

        assert result.returncode == 1, result.stdout
        assert "new_guard.py" in result.stdout

    def test_a_raw_predicate_in_post_tool_use_is_a_violation(self, tmp_path: Path) -> None:
        _handler_file(tmp_path, "post_tool_use", "new_formatter.py", _RAW_PREDICATE)

        result = _run("--path", str(tmp_path))

        assert result.returncode == 1, result.stdout

    def test_a_raw_predicate_in_a_worktree_family_is_a_violation(self, tmp_path: Path) -> None:
        """Not hypothetical: ``worktree_remove_handler`` read its path straight
        from the event payload with no containment check, and the classification
        pass found it only because it looked at every family that takes one."""
        _handler_file(tmp_path, "worktree_remove", "new_remove.py", _RAW_PREDICATE)

        result = _run("--path", str(tmp_path))

        assert result.returncode == 1, result.stdout

    def test_every_predicate_name_is_caught(self, tmp_path: Path) -> None:
        for index, predicate in enumerate(("exists", "is_file", "is_dir")):
            _handler_file(
                tmp_path,
                "pre_tool_use",
                f"guard_{index}.py",
                f"        return Path(file_path).{predicate}()\n",
            )

        result = _run("--path", str(tmp_path))

        assert result.returncode == 1
        for index in range(3):
            assert f"guard_{index}.py" in result.stdout


class TestTheEscapeHatches:
    def test_the_canonical_helper_is_not_a_violation(self, tmp_path: Path) -> None:
        _handler_file(
            tmp_path,
            "pre_tool_use",
            "converted.py",
            "        return path_is_file(file_path, unreadable_means=True)\n",
        )

        result = _run("--path", str(tmp_path))

        assert result.returncode == 0, result.stdout

    def test_an_inline_marker_exempts_the_site(self, tmp_path: Path) -> None:
        _handler_file(
            tmp_path,
            "pre_tool_use",
            "exempted.py",
            "        # eacces-safe-exempt: the daemon builds this path itself\n"
            "        return Path(file_path).is_file()\n",
        )

        result = _run("--path", str(tmp_path))

        assert result.returncode == 0, result.stdout

    def test_a_marker_without_a_reason_does_not_exempt(self, tmp_path: Path) -> None:
        """An empty marker is a silencer, not a record. The point of the inline
        form is that the person who added the exception is recorded in place."""
        _handler_file(
            tmp_path,
            "pre_tool_use",
            "bare_marker.py",
            "        # eacces-safe-exempt:\n        return Path(file_path).is_file()\n",
        )

        result = _run("--path", str(tmp_path))

        assert result.returncode == 1, result.stdout


class TestScopeIsFamilyBased:
    def test_a_family_with_no_caller_supplied_path_is_not_scanned(self, tmp_path: Path) -> None:
        """A SessionStart handler receives no ``tool_input``, so its paths come
        from the project root and config by construction."""
        _handler_file(tmp_path, "session_start", "checker.py", _RAW_PREDICATE)

        result = _run("--path", str(tmp_path))

        assert result.returncode == 0, result.stdout

    def test_a_new_family_defaults_to_scanned(self, tmp_path: Path) -> None:
        """Fail CLOSED on an unrecognised family. A gate whose default is
        'skip' silently stops covering anything added after it was written --
        which is the failure mode this whole plan is about."""
        _handler_file(tmp_path, "some_future_event", "handler.py", _RAW_PREDICATE)

        result = _run("--path", str(tmp_path))

        assert result.returncode == 1, result.stdout


class TestTheJsonContract:
    def test_json_mode_writes_the_qa_report(self) -> None:
        """``llm_qa.py`` reads this file, so its shape is part of the gate."""
        _run("--json")

        report = json.loads((_REPO_ROOT / "untracked" / "qa" / "eacces_safe.json").read_text())

        assert report["tool"] == "eacces_safe"
        assert report["summary"]["passed"] is True
        assert report["summary"]["total_violations"] == 0
        assert report["violations"] == []

"""The batch half of the ``british_english`` handler.

DBF (``CLAUDE.md`` Core Standard 15). The daemon ships a handler that flags
``behavior``/``organize``/``analyze``/``color`` when an agent WRITES a doc — and
the project's own tracked docs carried 85 of them across 28 files, including
``CLAUDE/CodeLifecycle/General.md`` ("Update tests when changing behavior") and
the generated ``.claude/HOOKS-DAEMON.md``. The handler could never have caught
them: it fires on a write, and these predate it.

Per that standard's corollary, every write-time rule needs a batch equivalent.
This is it, and the word list is IMPORTED from the handler rather than copied,
so the two can never disagree about what the rule is.

Exemptions are by LOCATION, and each earns its place:

- ``CLAUDE/Plan/``, ``RELEASES/``, ``CHANGELOG.md``, ``CLAUDE/UPGRADES/`` are
  historical records. Rewriting them to change a spelling would falsify an
  account of what was written at the time.
- fixture directories hold DELIBERATE specimens --
  ``CLAUDE/AcceptanceTests/fixtures/test-files/sample.md`` exists precisely to
  make the handler fire, and "fixing" it would destroy the test.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import BritishEnglishHandler

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "qa" / "check_british_english.py"
_TIMEOUT_SECONDS = 120


def _load_checker_module() -> ModuleType:
    """Import the checker by path -- ``scripts/`` is not an installed package."""
    spec = importlib.util.spec_from_file_location("_check_british_english", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves string annotations via
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_checker(root: Path) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), "--report-stdout"],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.stdout, f"checker produced no report. stderr: {result.stderr[:500]}"
    return result.returncode, json.loads(result.stdout)


def _make_repo(tmp_path: Path, tracked: dict[str, str]) -> Path:
    repo = tmp_path / "fixture"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=_TIMEOUT_SECONDS)
    for rel, content in tracked.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-f", rel], cwd=repo, check=True, timeout=_TIMEOUT_SECONDS)
    return repo


def _paths(report: dict) -> set[str]:
    return {v["file"] for v in report["violations"]}


def test_flags_american_spelling_in_a_tracked_doc(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, {"docs/guide.md": "Update tests when changing behavior.\n"})

    exit_code, report = _run_checker(repo)

    assert exit_code == 1
    assert "docs/guide.md" in _paths(report)
    assert report["violations"][0]["american"] == "behavior"
    assert report["violations"][0]["british"] == "behaviour"


def test_reports_line_number_and_suggestion(tmp_path: Path) -> None:
    """A finding a human cannot act on is a finding that gets ignored."""
    repo = _make_repo(tmp_path, {"docs/g.md": "ok\nok\nWe analyze the output.\n"})

    _, report = _run_checker(repo)

    violation = report["violations"][0]
    assert violation["line"] == 3
    assert violation["american"] == "analyze"
    assert violation["british"] == "analyse"


def test_does_not_flag_fenced_code_blocks(tmp_path: Path) -> None:
    """NEGATIVE CONTROL -- code is code. `color: red` is CSS, not a misspelling."""
    repo = _make_repo(
        tmp_path,
        {"docs/g.md": "Styling:\n\n```css\n.a { color: red; }\n```\n\nDone.\n"},
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"code block flagged: {report['violations']}"


def test_does_not_flag_inline_code_spans(tmp_path: Path) -> None:
    """NEGATIVE CONTROL -- a doc that NAMES the rule must not trip it.

    ``british_english.py``'s own reference documentation lists the mappings it
    enforces (`behavior` -> `behaviour`). Flagging that would make the rule
    impossible to document, which is how a gate earns a blanket exemption and
    then dies.
    """
    repo = _make_repo(
        tmp_path,
        {"docs/g.md": "The handler maps `behavior` to `behaviour` and `color` to `colour`.\n"},
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"inline code flagged: {report['violations']}"


def test_does_not_flag_historical_records(tmp_path: Path) -> None:
    """NEGATIVE CONTROL -- rewriting an archive falsifies it."""
    repo = _make_repo(
        tmp_path,
        {
            "CLAUDE/Plan/00001-x/PLAN.md": "Document the behavior.\n",
            "RELEASES/v1.0.0.md": "Changed the behavior.\n",
            "CHANGELOG.md": "Fixed color handling.\n",
            "CLAUDE/UPGRADES/v1/guide.md": "The old behavior was wrong.\n",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"historical record flagged: {report['violations']}"


def test_does_not_flag_deliberate_fixtures(tmp_path: Path) -> None:
    """NEGATIVE CONTROL -- the specimen that makes the HANDLER fire.

    ``CLAUDE/AcceptanceTests/fixtures/test-files/sample.md`` contains American
    spellings on purpose. A batch check that demanded they be corrected would
    delete the only evidence the handler works.
    """
    repo = _make_repo(
        tmp_path,
        {
            "CLAUDE/AcceptanceTests/fixtures/test-files/sample.md": "- color\n- behavior\n",
            "tests/fixtures/thing.md": "organize this\n",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"fixture flagged: {report['violations']}"


def test_word_list_is_imported_from_the_handler_not_copied() -> None:
    """The rule has ONE definition. A copy would drift the day either changed."""
    checker = _load_checker_module()

    assert checker.spelling_checks() is BritishEnglishHandler.SPELLING_CHECKS


def test_real_repository_is_clean() -> None:
    """The tracked tree must stay free of American spellings.

    Not vacuous: the synthesised cases above prove the checker fires, so a pass
    here means the repo is clean rather than the checker being blind.
    """
    exit_code, report = _run_checker(REPO_ROOT)

    assert exit_code == 0, "American spellings found:\n" + "\n".join(
        f"  {v['file']}:{v['line']}  {v['american']} -> {v['british']}"
        for v in report["violations"]
    )

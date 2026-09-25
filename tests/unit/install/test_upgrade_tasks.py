"""The shared upgrade-task schema and loader (Plan 00376 Tasks 2.2 and 4.1).

Pre-upgrade and post-upgrade tasks share one schema and one loader. A
pre-upgrade task must declare how to find the call sites it cares about
(``**Detect**:``), which is what lets the gate stay silent for a project it
does not affect. A post-upgrade task may declare one, and the post-upgrade
report then says whether the task applies.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import upgrade_tasks
from claude_code_hooks_daemon.install.upgrade_tasks import (
    Detection,
    TaskKind,
    detect,
    evaluate,
    format_findings_line,
    load_task,
    run_check_upgrade_tasks,
    schema_errors,
    tasks_for_range,
)

_VALID = """# Task: {title}

**Type**: {task_type}
**Severity**: {severity}
**Applies to**: all
**Idempotent**: yes
{detect}
## Why

Because.

## How to detect if this applies to you

Look.

## How to handle

Do it.

## How to confirm

Check it.
"""


def _task(
    path: Path,
    *,
    title: str = "a task",
    task_type: str = "audit",
    severity: str = "recommended",
    detect_block: str = "",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _VALID.format(title=title, task_type=task_type, severity=severity, detect=detect_block)
    )
    return path


_DETECT = "**Detect**: `plan-qa[^\\n]*--json`\n**Detect in**: `*.py`, `*.sh`\n"


class TestSchema:
    def test_a_well_formed_post_task_has_no_errors(self, tmp_path: Path) -> None:
        assert schema_errors(_task(tmp_path / "01-ok.md"), TaskKind.POST) == []

    def test_a_pre_task_must_declare_detection(self, tmp_path: Path) -> None:
        errors = schema_errors(_task(tmp_path / "01-no-detect.md"), TaskKind.PRE)
        assert any("Detect" in error for error in errors)

    def test_a_pre_task_with_detection_is_well_formed(self, tmp_path: Path) -> None:
        path = _task(tmp_path / "01-detect.md", detect_block=_DETECT)
        assert schema_errors(path, TaskKind.PRE) == []

    def test_an_uncompilable_pattern_is_an_error(self, tmp_path: Path) -> None:
        path = _task(tmp_path / "01-bad.md", detect_block="**Detect**: `(unclosed`\n")
        assert any("pattern" in error for error in schema_errors(path, TaskKind.PRE))

    def test_a_detect_pattern_without_backticks_is_an_error(self, tmp_path: Path) -> None:
        path = _task(tmp_path / "01-bare.md", detect_block="**Detect**: plan-qa --json\n")
        assert any("backticks" in error for error in schema_errors(path, TaskKind.PRE))

    @pytest.mark.parametrize("pattern", ["(x+x+)+y", "(a*)*b", "(?:\\w+\\s?)+$", "(a+){2,}"])
    def test_a_nested_quantifier_is_an_error(self, tmp_path: Path, pattern: str) -> None:
        path = _task(tmp_path / "01-redos.md", detect_block=f"**Detect**: `{pattern}`\n")
        assert any("nested quantifier" in error for error in schema_errors(path, TaskKind.PRE))

    @pytest.mark.parametrize(
        ("field", "value"),
        [("task_type", "chore"), ("severity", "urgent")],
    )
    def test_values_outside_the_vocabulary_are_errors(
        self, tmp_path: Path, field: str, value: str
    ) -> None:
        path = _task(tmp_path / "01-vocab.md", **{field: value})
        assert any(value in error for error in schema_errors(path, TaskKind.POST))

    def test_missing_sections_and_title_are_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "01-thin.md"
        path.write_text("**Type**: audit\n**Severity**: optional\n\n## Why\n\nx\n")
        errors = schema_errors(path, TaskKind.POST)
        assert any("# Task:" in error for error in errors)
        assert any("How to handle" in error for error in errors)
        assert any("Idempotent" in error for error in errors)

    def test_a_badly_named_file_is_an_error(self, tmp_path: Path) -> None:
        path = _task(tmp_path / "remove-vendor.md")
        assert any("NN-" in error for error in schema_errors(path, TaskKind.POST))


class TestLoad:
    def test_fields_are_read(self, tmp_path: Path) -> None:
        task = load_task(
            _task(tmp_path / "01-x.md", title="rewrite callers", detect_block=_DETECT),
            "v3.63.0-to-v3.64.0",
            TaskKind.PRE,
        )
        assert task.title == "rewrite callers"
        assert task.severity == "recommended"
        assert task.detection == Detection(pattern="plan-qa[^\\n]*--json", paths=("*.py", "*.sh"))

    def test_detection_paths_default_to_every_file(self, tmp_path: Path) -> None:
        path = _task(tmp_path / "01-x.md", detect_block="**Detect**: `level`\n")
        assert load_task(path, "UNRELEASED", TaskKind.PRE).detection == Detection(
            pattern="level", paths=("*",)
        )

    def test_a_malformed_task_still_loads_for_reporting(self, tmp_path: Path) -> None:
        path = tmp_path / "01-thin.md"
        path.write_text("# Task: thin\n")
        task = load_task(path, "UNRELEASED", TaskKind.POST)
        assert task.severity == "unknown"
        assert task.detection is None


class TestDetect:
    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        root = tmp_path / "project"
        (root / "tools").mkdir(parents=True)
        (root / "tools" / "qa.sh").write_text("x\nhooks-daemon plan-qa --json | jq .level\n")
        (root / "tools" / "notes.md").write_text("plan-qa --json is documented here\n")
        (root / ".claude" / "hooks-daemon").mkdir(parents=True)
        (root / ".claude" / "hooks-daemon" / "vendored.sh").write_text("plan-qa --json\n")
        (root / ".git").mkdir()
        (root / ".git" / "config.sh").write_text("plan-qa --json\n")
        return root

    def test_hits_are_named_at_file_and_line(self, project: Path) -> None:
        hits, total = detect(Detection(pattern="plan-qa[^\\n]*--json", paths=("*.sh",)), project)
        assert [(h.path, h.line) for h in hits] == [("tools/qa.sh", 2)]
        assert total == 1

    def test_the_daemon_clone_and_git_dir_are_never_scanned(self, project: Path) -> None:
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*",)), project)
        assert {h.path for h in hits} == {"tools/qa.sh", "tools/notes.md"}

    def test_no_hits_is_silence(self, project: Path) -> None:
        assert detect(Detection(pattern="nothing-matches-this", paths=("*",)), project) == ([], 0)

    def test_binary_files_are_skipped_and_non_utf8_text_is_still_scanned(
        self, project: Path
    ) -> None:
        (project / "blob.bin").write_bytes(b"plan-qa --json\x00\x01")
        (project / "latin.sh").write_bytes("caf\xe9 plan-qa --json\n".encode("latin-1"))
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*.bin", "latin.sh")), project)
        assert [h.path for h in hits] == ["latin.sh"]

    def test_hits_are_capped_but_counted(self, project: Path) -> None:
        (project / "many.txt").write_text("hit\n" * 50)
        hits, total = detect(Detection(pattern="hit", paths=("many.txt",)), project, limit=5)
        assert len(hits) == 5
        assert total == 50

    def test_only_the_start_of_a_very_long_line_is_scanned(self, project: Path) -> None:
        width = upgrade_tasks.MAX_SCANNED_LINE_CHARS
        (project / "min.js").write_text("a" * width + "needle\n" + "needle" + "a" * width + "\n")
        hits, _total = detect(Detection(pattern="needle", paths=("*.js",)), project)
        assert [h.line for h in hits] == [2]

    def test_venv_and_untracked_are_skipped_only_at_the_root(self, project: Path) -> None:
        for rel in ("venv/x.sh", "untracked/x.sh", "src/venv/x.sh", "src/untracked/x.sh"):
            (project / rel).parent.mkdir(parents=True, exist_ok=True)
            (project / rel).write_text("plan-qa --json\n")
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*/x.sh",)), project)
        assert {h.path for h in hits} == {"src/venv/x.sh", "src/untracked/x.sh"}

    @pytest.mark.parametrize("root", ["vendor", "dist", "build", "target", "node_modules"])
    def test_vendored_and_build_roots_are_skipped(self, project: Path, root: str) -> None:
        (project / root / "lib").mkdir(parents=True)
        (project / root / "lib" / "copy.sh").write_text("plan-qa --json\n")
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*.sh",)), project)
        assert {h.path for h in hits} == {"tools/qa.sh"}

    def test_a_git_work_tree_is_scanned_through_its_ignore_rules(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".gitignore").write_text("generated/\n")
        (root / "generated").mkdir()
        (root / "generated" / "out.sh").write_text("plan-qa --json\n")
        (root / "new.sh").write_text("plan-qa --json\n")
        (root / ".claude" / "hooks-daemon").mkdir(parents=True)
        (root / ".claude" / "hooks-daemon" / "vendored.sh").write_text("plan-qa --json\n")
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*.sh",)), root)
        assert {h.path for h in hits} == {"new.sh"}

    def test_only_the_projects_own_gitignore_can_exclude_a_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An environment variable or local git state must not hide a call site."""
        root = tmp_path / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "caller.sh").write_text("plan-qa --json\n")
        (root / ".git" / "info" / "exclude").write_text("*\n")
        everything = tmp_path / "exclude-everything"
        everything.write_text("*\n")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(everything))
        monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "other-index"))
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*.sh",)), root)
        assert [h.path for h in hits] == ["caller.sh"]

    def test_a_git_planted_on_path_does_not_list_the_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fresh review BLOCKER 1: `shutil.which` took the caller's PATH for git."""
        root = tmp_path / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "caller.sh").write_text("plan-qa --json\n")
        (root / "decoy.txt").write_text("nothing\n")
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        fake_git = fakebin / "git"
        fake_git.write_text("#!/bin/sh\nprintf 'decoy.txt\\0'\n")
        fake_git.chmod(0o755)
        monkeypatch.setenv("PATH", f"{fakebin}:{os.environ['PATH']}")
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*.sh",)), root)
        assert [h.path for h in hits] == ["caller.sh"]

    def test_a_git_planted_in_a_writable_trusted_tool_path_entry_does_not_answer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review2 MAJOR 2: a fixed system location is not trusted unless it is
        root-owned and neither group- nor world-writable -- a directory this
        same process could itself write to (Homebrew's default layout on
        macOS) must not answer for the scan just for being listed."""
        root = tmp_path / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "caller.sh").write_text("plan-qa --json\n")
        (root / "decoy.txt").write_text("nothing\n")
        writable_bin = tmp_path / "writable-bin"
        writable_bin.mkdir()
        writable_bin.chmod(0o777)
        fake_git = writable_bin / "git"
        fake_git.write_text("#!/bin/sh\nprintf 'decoy.txt\\0'\n")
        fake_git.chmod(0o755)
        monkeypatch.setattr(
            upgrade_tasks,
            "TRUSTED_TOOL_PATH",
            f"{writable_bin}{os.pathsep}{upgrade_tasks.TRUSTED_TOOL_PATH}",
        )
        hits, _total = detect(Detection(pattern="plan-qa", paths=("*.sh",)), root)
        assert [h.path for h in hits] == ["caller.sh"]


class TestTrustedDirs:
    """review2 MAJOR 2: only a root-owned, non-group/world-writable directory
    from a fixed tool-path list is trusted to answer for a planted tool."""

    def test_a_root_owned_unwritable_directory_is_trusted(self, tmp_path: Path) -> None:
        safe = tmp_path / "safe"
        safe.mkdir()
        safe.chmod(0o755)
        assert upgrade_tasks._trusted_dirs([str(safe)]) == [str(safe)]

    def test_a_world_writable_directory_is_not_trusted(self, tmp_path: Path) -> None:
        unsafe = tmp_path / "world-writable"
        unsafe.mkdir()
        unsafe.chmod(0o777)
        assert upgrade_tasks._trusted_dirs([str(unsafe)]) == []

    def test_a_group_writable_directory_is_not_trusted(self, tmp_path: Path) -> None:
        unsafe = tmp_path / "group-writable"
        unsafe.mkdir()
        unsafe.chmod(0o775)
        assert upgrade_tasks._trusted_dirs([str(unsafe)]) == []

    def test_a_directory_not_owned_by_root_is_not_trusted(self) -> None:
        """Homebrew's /opt/homebrew/bin and /usr/local/bin are user-owned by
        default on macOS: listed in GATE_SAFE_PATH/TRUSTED_TOOL_PATH, but not
        trusted merely for being named there. The policy is pure over a
        ``stat`` result (:func:`_dir_trust_from_stat`), so this is checked
        without needing a directory of a uid this process does not have."""
        user_owned = os.stat_result((0o40755, 1, 1, 1, 501, 501, 0, 0, 0, 0))
        assert upgrade_tasks._dir_trust_from_stat(user_owned) is False

    def test_a_root_owned_writable_directory_is_not_trusted(self) -> None:
        world_writable = os.stat_result((0o40777, 1, 1, 1, 0, 0, 0, 0, 0, 0))
        assert upgrade_tasks._dir_trust_from_stat(world_writable) is False

    def test_a_root_owned_unwritable_stat_result_is_trusted(self) -> None:
        safe = os.stat_result((0o40755, 1, 1, 1, 0, 0, 0, 0, 0, 0))
        assert upgrade_tasks._dir_trust_from_stat(safe) is True

    def test_a_missing_directory_is_skipped(self, tmp_path: Path) -> None:
        assert upgrade_tasks._trusted_dirs([str(tmp_path / "absent")]) == []

    def test_the_default_candidates_are_trusted_tool_path(self) -> None:
        assert upgrade_tasks._trusted_tool_path() != ""
        for directory in upgrade_tasks._trusted_tool_path().split(os.pathsep):
            assert directory in upgrade_tasks.TRUSTED_TOOL_PATH.split(os.pathsep)


class TestShippedPlanQaTask:
    """The shipped 00375 task is critical, so a false positive costs an owner approval."""

    _PATH = (
        Path(__file__).resolve().parents[3]
        / "CLAUDE/UPGRADES/v3/v3.63.0-to-v3.64.0/pre-upgrade-tasks"
        / "01-rewrite-plan-qa-json-level-to-severity.md"
    )

    def _pattern(self) -> str:
        detection = load_task(self._PATH, "v3.63.0-to-v3.64.0", TaskKind.PRE).detection
        assert detection is not None
        return detection.pattern

    @pytest.mark.parametrize(
        "line",
        [
            "hooks-daemon plan-qa --json | jq '.findings[].level'",
            "subprocess.run(['bin/hooks-daemon', 'plan_qa', '--json'])",
        ],
    )
    def test_it_finds_an_invocation(self, line: str) -> None:
        assert re.search(self._pattern(), line)

    @pytest.mark.parametrize(
        "line",
        ['report = cache_dir / "plan_qa.json"', "see untracked/qa/plan-qa.json for details"],
    )
    def test_it_ignores_a_file_name(self, line: str) -> None:
        assert re.search(self._pattern(), line) is None

    @pytest.mark.parametrize(
        "line",
        [
            "hooks-daemon plan-qa --json | jq '.findings[].severity'",
            'sev = [f["severity"] for f in json.loads(run(["hooks-daemon", "plan-qa", "--json"]))]',
        ],
    )
    def test_it_ignores_a_call_site_already_reading_severity(self, line: str) -> None:
        """Fresh review D6: a migrated site cost the owner an approval on every crossing."""
        assert re.search(self._pattern(), line) is None

    def test_it_never_tells_the_reader_a_critical_hit_can_be_acknowledged(self) -> None:
        """Fresh review D6: any hit of a critical task needs the owner, even a false one."""
        text = self._PATH.read_text(encoding="utf-8")
        assert "and acknowledge" not in text
        assert "even" in text.split("## How to detect if this applies to you")[1].split("##")[0]


class TestRange:
    @pytest.fixture
    def upgrades(self, tmp_path: Path) -> Path:
        root = tmp_path / "UPGRADES"
        guide = root / "v3" / "v3.63.0-to-v3.64.0"
        _task(guide / "pre-upgrade-tasks" / "01-pre.md", detect_block="**Detect**: `x`\n")
        _task(guide / "post-upgrade-tasks" / "01-post.md")
        _task(
            root / "UNRELEASED" / "pre-upgrade-tasks" / "01-staged.md",
            detect_block="**Detect**: `y`\n",
        )
        return root

    def test_each_kind_reads_its_own_directory(self, upgrades: Path) -> None:
        pre = tasks_for_range(TaskKind.PRE, "3.63.0", "3.64.0", upgrades, include_unreleased=False)
        post = tasks_for_range(
            TaskKind.POST, "3.63.0", "3.64.0", upgrades, include_unreleased=False
        )
        assert [t.path.name for t in pre] == ["01-pre.md"]
        assert [t.path.name for t in post] == ["01-post.md"]

    def test_staged_tasks_join_for_a_branch_install(self, upgrades: Path) -> None:
        pre = tasks_for_range(TaskKind.PRE, "3.64.0", "3.64.0", upgrades, include_unreleased=True)
        assert [(t.path.name, t.source) for t in pre] == [("01-staged.md", "UNRELEASED")]

    def test_default_asks_the_install_stamp(
        self, upgrades: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(upgrade_tasks, "is_branch_install", lambda: True)
        pre = tasks_for_range(TaskKind.PRE, "3.64.0", "3.64.0", upgrades)
        assert [t.source for t in pre] == ["UNRELEASED"]

    def test_oldest_guide_first_and_file_order_within(self, upgrades: Path) -> None:
        older = upgrades / "v3" / "v3.57-to-v3.58" / "post-upgrade-tasks"
        _task(older / "02-second.md")
        _task(older / "01-first.md")
        post = tasks_for_range(
            TaskKind.POST, "3.57.0", "3.64.0", upgrades, include_unreleased=False
        )
        assert [(t.source, t.path.name) for t in post] == [
            ("v3.57-to-v3.58", "01-first.md"),
            ("v3.57-to-v3.58", "02-second.md"),
            ("v3.63.0-to-v3.64.0", "01-post.md"),
        ]

    def test_the_template_is_never_a_guide(self, upgrades: Path) -> None:
        _task(upgrades / "upgrade-template" / "post-upgrade-tasks" / "00-EXAMPLE-task.md")
        post = tasks_for_range(TaskKind.POST, "0.0.1", "99.0.0", upgrades, include_unreleased=True)
        assert "00-EXAMPLE-task.md" not in {t.path.name for t in post}

    def test_a_backwards_range_is_refused(self, upgrades: Path) -> None:
        with pytest.raises(ValueError, match="from_version"):
            tasks_for_range(TaskKind.POST, "3.65.0", "3.64.0", upgrades)


class TestReport:
    def test_a_post_task_with_detection_says_whether_it_applies(self, tmp_path: Path) -> None:
        upgrades = tmp_path / "UPGRADES"
        guide = upgrades / "v3" / "v3.63.0-to-v3.64.0" / "post-upgrade-tasks"
        _task(guide / "01-applies.md", detect_block="**Detect**: `needle`\n")
        _task(guide / "02-clear.md", detect_block="**Detect**: `absent-token`\n")
        _task(guide / "03-plain.md")
        project = tmp_path / "project"
        project.mkdir()
        (project / "a.txt").write_text("the needle\n")

        result = run_check_upgrade_tasks(
            TaskKind.POST,
            "3.63.0",
            "3.64.0",
            upgrades_dir=upgrades,
            include_unreleased=False,
            project_root=project,
        )
        by_name = {Path(t["path"]).name: t for t in result["tasks"]}
        assert by_name["01-applies.md"]["applies"] is True
        assert by_name["01-applies.md"]["hits"] == [
            {"path": "a.txt", "line": 1, "text": "the needle"}
        ]
        assert by_name["02-clear.md"]["applies"] is False
        assert by_name["03-plain.md"]["applies"] is None
        assert "a.txt:1" in result["text"]
        assert "not detected" in result["text"]

    def test_a_task_whose_scan_could_not_run_says_so(self, tmp_path: Path) -> None:
        task = load_task(
            _task(tmp_path / "01-broken.md", detect_block="**Detect**: `(unclosed`\n"),
            "UNRELEASED",
            TaskKind.PRE,
        )
        (finding,) = evaluate([task], tmp_path)
        assert finding.applies is None
        assert any("could not run" in line for line in format_findings_line(finding))

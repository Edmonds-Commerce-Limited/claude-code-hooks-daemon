"""``llm_qa.py main-moved``: what must re-run when ``main`` moves during a batch (Plan 00463).

The coordinator's batched gate runs the full suite once on an integration
branch built from ``main``. If ``main`` moves before the fast-forward, the
green run no longer covers what would land, and re-running the whole suite
for a ledger row is the waste the owner asked to stop. The verdict decides
what must re-run instead, and it is a checked mechanism, not a judgement:

- ``docs-only``: every moved path is a document no test reads (the
  ``changed_tests`` mapper, never a second copy of it, says which tests read
  a file). Only the doc tools re-run.
- ``targeted``: moved documents that tests DO read (review 3 R1: the plan
  index, handler guide, lifecycle docs...). ``llm_qa.py changed`` re-runs
  over exactly the moved range.
- ``full-gate``: code, a symlink, anything the mapper cannot target, and the
  runtime-read set (root ``CLAUDE.md``, ``CHANGELOG.md``, ``.claude/**``,
  ``RELEASES/**``, ``CLAUDE/UPGRADES/**``), which runtime code reads.

The batch base is recorded durably in a git ref (review 3 R2: a shell
variable does not survive between Bash calls), and it advances only when the
recheck the verdict names has PASSED on the merged head, so the loop ends and
the next check sees only newer movement.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load(script: str, name: str) -> Any:
    """Import a file under ``scripts/qa/``, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / script
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load("llm_qa.py", "llm_qa_main_moved_under_test")
changed_tests = _load("run_changed_tests.py", "run_changed_tests_for_main_moved")

_DOCS = llm_qa.PATH_DOCS
_TESTED = llm_qa.PATH_TESTED
_FULL = llm_qa.PATH_FULL


def _payload(
    mapping: list[dict[str, Any]] | None = None,
    unmapped: dict[str, str] | None = None,
) -> dict[str, Any]:
    """A ``run_changed_tests --select-only`` payload."""
    reasons = {path: {"reason": reason, "detail": "d"} for path, reason in (unmapped or {}).items()}
    return {
        "range": "a..b",
        "mapping": mapping or [],
        "unmapped": list(reasons),
        "unmapped_reasons": reasons,
    }


def _judge(path: str, payload: dict[str, Any] | None = None, *, symlink: bool = False) -> str:
    moved = llm_qa.MovedPath(path=path, symlink=symlink)
    return str(llm_qa.judge_path(moved, payload or _payload()).kind)


class TestTheRuntimeReadSet:
    def test_the_set_is_defined_once_and_is_exactly_this(self) -> None:
        """Runtime code reads each: the injector, release notes, upgrade guides, agents."""
        assert llm_qa.RUNTIME_READ_FILES == frozenset({"CLAUDE.md", "CHANGELOG.md"})
        assert llm_qa.RUNTIME_READ_ROOTS == (".claude/", "RELEASES/", "CLAUDE/UPGRADES/")

    @pytest.mark.parametrize(
        "path",
        [
            "CLAUDE.md",
            "CHANGELOG.md",
            ".claude/agents/qa-runner.md",
            ".claude/skills/release/SKILL.md",
            ".claude/rules/agent-docs.md",
            ".claude/hooks-daemon.yaml",
            "RELEASES/v3.66.0.md",
            "CLAUDE/UPGRADES/UNRELEASED/release-notes/13-x.md",
        ],
    )
    def test_a_runtime_read_path_needs_the_full_gate_whatever_maps_to_it(self, path: str) -> None:
        payload = _payload(mapping=[{"file": path, "rules": [], "tests": []}])
        assert _judge(path, payload) == _FULL


class TestJudgingOnePath:
    @pytest.mark.parametrize(
        "path",
        [
            "CLAUDE/Plan/00463-x/conftest.py",
            "CLAUDE/Plan/00463-x/run_me.sh",
            "CLAUDE/Plan/mkplan.bash",
            "CLAUDE/Plan/00471-a-plan/notes.json",
            "src/CLAUDE.md",
            "tests/CLAUDE.md",
            "scripts/qa/README.md",
            "docs/diagram.svg",
            "CLAUDE/QA.MD",
            "pyproject.toml",
        ],
    )
    def test_anything_but_a_document_outside_the_code_roots_needs_the_full_gate(
        self, path: str
    ) -> None:
        assert _judge(path) == _FULL

    def test_a_symlinked_document_needs_the_full_gate(self) -> None:
        """Review 3 R12: ``docs/app.md`` pointing at ``../src/app.py`` is code."""
        payload = _payload(mapping=[{"file": "docs/app.md", "rules": [], "tests": []}])
        assert _judge("docs/app.md", payload, symlink=True) == _FULL

    def test_a_document_tests_read_is_targeted(self) -> None:
        payload = _payload(
            mapping=[{"file": "CLAUDE/Plan/README.md", "rules": ["reference"], "tests": ["t.py"]}]
        )
        assert _judge("CLAUDE/Plan/README.md", payload) == _TESTED

    def test_a_document_only_the_doc_tools_cover_is_docs_only(self) -> None:
        payload = _payload(
            mapping=[
                {"file": "docs/a.md", "rules": ["declared"], "tests": [], "tools": ["docs_qa"]}
            ]
        )
        assert _judge("docs/a.md", payload) == _DOCS

    def test_a_document_a_non_doc_tool_covers_is_targeted(self) -> None:
        payload = _payload(
            mapping=[{"file": "docs/a.md", "rules": [], "tests": [], "tools": ["shell_check"]}]
        )
        assert _judge("docs/a.md", payload) == _TESTED

    def test_a_document_nothing_covers_is_docs_only(self) -> None:
        assert _judge("docs/a.md", _payload(unmapped={"docs/a.md": "uncovered"})) == _DOCS

    @pytest.mark.parametrize("reason", ["too-broad", "deleted-but-referenced"])
    def test_a_document_the_mapper_cannot_target_needs_the_full_gate(self, reason: str) -> None:
        assert _judge("docs/a.md", _payload(unmapped={"docs/a.md": reason})) == _FULL

    def test_a_document_the_mapper_did_not_report_needs_the_full_gate(self) -> None:
        assert _judge("docs/a.md", _payload()) == _FULL


class TestTheVerdict:
    def _verdict(self, *kinds: str) -> str:
        judged = [llm_qa.PathVerdict(f"p{i}", kind, "why") for i, kind in enumerate(kinds)]
        return str(llm_qa.combine_verdicts(judged))

    def test_new_commits_that_change_no_file_are_docs_only_not_unmoved(self) -> None:
        """Review 3 R4: a commit and its revert, or --allow-empty. --ff-only still refuses."""
        assert self._verdict() == llm_qa.VERDICT_DOCS_ONLY

    def test_documents_only(self) -> None:
        assert self._verdict(_DOCS, _DOCS) == llm_qa.VERDICT_DOCS_ONLY

    def test_a_tested_document_makes_it_targeted(self) -> None:
        assert self._verdict(_DOCS, _TESTED) == llm_qa.VERDICT_TARGETED

    def test_one_full_path_anywhere_makes_it_the_full_gate(self) -> None:
        assert self._verdict(_DOCS, _TESTED, _FULL) == llm_qa.VERDICT_FULL_GATE


@pytest.fixture(scope="module")
def this_repository_judges() -> Any:
    """Judge paths against THIS repository's tests, through the real mapper.

    This file is left out of the corpus: it names every path below as a
    string, which the mapper would rightly read as a test that reads them.
    """
    tree, error = changed_tests.tree_files(PROJECT_ROOT)
    assert tree is not None, error
    this_file = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()
    full = changed_tests.build_corpus(PROJECT_ROOT, tree)
    corpus = dataclasses.replace(
        full, tests={test: refs for test, refs in full.tests.items() if test != this_file}
    )
    rules, problems = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
    assert problems == []

    def judge(path: str) -> str:
        selection = changed_tests.select_tests([path], corpus, PROJECT_ROOT, rules)
        payload = changed_tests.selection_payload("a..b", [path], selection)
        return str(llm_qa.judge_path(llm_qa.MovedPath(path, False), payload).kind)

    return judge


class TestTheReviewExamplesAgainstThisRepository:
    """Review 3 R1: each path it names, judged by this repository's own mapper."""

    @pytest.mark.parametrize(
        "path",
        [
            "CLAUDE/Plan/README.md",
            "CLAUDE/HANDLER_DEVELOPMENT.md",
            "CLAUDE/CodeLifecycle/General.md",
            "CLAUDE/core/PlanWorkflow.core.md",
            "BUG_REPORTING.md",
            # Review 4 N1: read by glob, so these read docs-only or missed a test.
            "docs/guides/TROUBLESHOOTING.md",
            "docs/a-page-nothing-names-yet.md",
            "CLAUDE/Worktree.md",
        ],
    )
    def test_a_document_tests_read_is_targeted_not_docs_only(
        self, path: str, this_repository_judges: Any
    ) -> None:
        assert this_repository_judges(path) == _TESTED

    @pytest.mark.parametrize(
        "path",
        [
            "CLAUDE.md",
            "CHANGELOG.md",
            ".claude/agents/qa-runner.md",
            ".claude/skills/release/SKILL.md",
            ".claude/rules/agent-docs.md",
            "CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate/conftest.py",
            "CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate/run_me.sh",
            # Read by over 40 test files, so the mapper cannot target it.
            "README.md",
        ],
    )
    def test_runtime_executable_and_untargetable_paths_need_the_full_gate(
        self, path: str, this_repository_judges: Any
    ) -> None:
        assert this_repository_judges(path) == _FULL

    @pytest.mark.parametrize(
        "path",
        [
            # A non-existent, invented plan number: the corpus does not need
            # the file to exist to judge it, and a real open ledger's path
            # eventually gets cited by an unrelated fix's rationale comment
            # ("see NIGGLES.md N46 for why") -- a legitimate practice this
            # project uses elsewhere -- which the mapper (rightly, for its
            # general purpose) then reads as a real dependency, pulling in
            # that citing module's own tests and flipping the verdict to
            # tested. An invented plan number no source will ever cite stays
            # docs-only regardless of what other plans' ledgers accumulate.
            "CLAUDE/Plan/00000-example-ledger-for-tests/NIGGLES.md",
            "CLAUDE/Plan/00000-example-ledger-for-tests/JOURNAL/00000-Journal-26-01-01.md",
        ],
    )
    def test_a_ledger_or_journal_entry_is_docs_only(
        self, path: str, this_repository_judges: Any
    ) -> None:
        assert this_repository_judges(path) == _DOCS


class TestTheRecheck:
    def test_the_docs_only_recheck_is_registered_doc_tools_that_rewrite_nothing(self) -> None:
        """Review 3 R10: ``format`` is black; it checks Python and REWRITES files."""
        assert set(llm_qa.DOCS_ONLY_TOOL_NAMES) <= set(llm_qa.TOOL_REGISTRY)
        assert "format" not in llm_qa.DOCS_ONLY_TOOL_NAMES

    @pytest.mark.parametrize(
        ("checker_test", "tool"),
        [
            ("tests/integration/test_repo_hygiene_check.py", "repo_hygiene"),
            ("tests/integration/test_doc_truth_check.py", "doc_truth"),
            ("tests/integration/test_handler_reference_check.py", "handler_reference"),
        ],
    )
    def test_a_whole_tree_checker_a_test_runs_on_this_repository_is_in_the_docs_recheck(
        self, checker_test: str, tool: str
    ) -> None:
        """Review 4 N1: these tests read EVERY document through a checker, naming none.

        No mapping can select them for a moved page, so the docs recheck runs
        the checker they wrap instead.
        """
        assert (PROJECT_ROOT / checker_test).is_file()
        assert tool in llm_qa.DOCS_ONLY_TOOL_NAMES

    def test_each_verdict_names_what_must_have_passed(self) -> None:
        required = llm_qa.required_tools
        assert required(llm_qa.VERDICT_DOCS_ONLY) == llm_qa.DOCS_ONLY_TOOL_NAMES
        targeted = required(llm_qa.VERDICT_TARGETED)
        assert "changed_tests" in targeted
        assert set(llm_qa.DOCS_ONLY_TOOL_NAMES) <= set(targeted)
        assert required(llm_qa.VERDICT_FULL_GATE) == llm_qa.ALL_TOOL_NAMES


# ── Against a real repository ─────────────────────────────────────────────

_BRANCH = "integ"
# Outside docs/: this repository's map declares its glob readers there, and
# select_range judges the fixture with that map.
_GUIDE = "notes/guide.md"
_LONELY = "notes/lonely.md"


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=Timeout.QA_TEST_TIMEOUT,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _on_main(repo: Path, files: dict[str, str], message: str = "on main") -> str:
    _git(repo, "checkout", "-q", "main")
    sha = _commit(repo, files, message)
    _git(repo, "checkout", "-q", _BRANCH)
    return sha


def _merge_main(repo: Path) -> None:
    _git(repo, "merge", "-q", "--no-edit", "main")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``main`` with code, two documents (one a test reads), and an integration branch."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(
        tmp_path,
        {
            ".gitignore": "untracked/\n",
            "src/app.py": "x = 1\n",
            _GUIDE: "# Guide\n",
            _LONELY: "# Lonely\n",
            "tests/unit/test_guide.py": f'GUIDE = "{_GUIDE}"\n\n\ndef test_guide() -> None:\n    pass\n',
        },
        "base",
    )
    _git(tmp_path, "checkout", "-q", "-b", _BRANCH)
    _commit(tmp_path, {"src/feature.py": "y = 1\n"}, "a ready branch, merged into the batch")
    return tmp_path


def _qa_dir(repo: Path) -> Path:
    return repo / "untracked" / "qa"


def _certify(
    repo: Path,
    tools: list[str],
    *,
    passed: bool = True,
    changed_range: str | None = None,
) -> None:
    """Record, as a run on the current tree would, that ``tools`` ran."""
    qa_dir = _qa_dir(repo)
    qa_dir.mkdir(parents=True, exist_ok=True)
    state = llm_qa.worktree_state(repo)
    assert state is not None
    records = {}
    for name in tools:
        output = qa_dir / llm_qa.TOOL_REGISTRY[name].json_file
        body: dict[str, Any] = {"tool": name}
        if name == "changed_tests" and changed_range is not None:
            body["range"] = changed_range
        output.write_text(json.dumps(body), encoding="utf-8")
        records[name] = llm_qa.run_record(
            state,
            exit_code=0 if passed else 1,
            passed=passed,
            output_sha256=llm_qa.output_digest(output),
        )
    llm_qa.record_provenance(qa_dir, records)


def _base(repo: Path) -> str:
    return _git(repo, "rev-parse", f"refs/integration/base/{_BRANCH}")


def _certified(repo: Path) -> str | None:
    ref = f"refs/integration/certified/{_BRANCH}"
    listed = _git(repo, "for-each-ref", "--format=%(objectname)", ref)
    return listed or None


def _gate(repo: Path) -> None:
    """What a passing ``llm_qa.py all`` on this clean, still tree records."""
    assert llm_qa.certify_head(repo, llm_qa.worktree_state(repo)) == _git(repo, "rev-parse", "HEAD")


def _start(repo: Path) -> None:
    llm_qa.start_batch(repo, "main")
    _gate(repo)


class TestTheBatchBase:
    def test_start_records_the_main_commit_the_batch_contains_in_a_ref(self, repo: Path) -> None:
        recorded = llm_qa.start_batch(repo, "main")
        assert recorded == _git(repo, "rev-parse", "main")
        assert _base(repo) == recorded, "a fresh process reads the same base"

    def test_start_after_main_moved_records_the_older_commit_the_batch_holds(
        self, repo: Path
    ) -> None:
        contained = _git(repo, "rev-parse", "main")
        _on_main(repo, {"src/app.py": "x = 2\n"})
        assert llm_qa.start_batch(repo, "main") == contained

    def test_a_check_with_no_recorded_base_is_an_error_not_a_verdict(self, repo: Path) -> None:
        with pytest.raises(llm_qa.MainMovedError, match="--start"):
            llm_qa.main_moved(repo, "main")

    def test_a_detached_head_has_no_batch(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "--detach")
        with pytest.raises(llm_qa.MainMovedError):
            llm_qa.start_batch(repo, "main")


class TestTheCheck:
    @pytest.fixture(autouse=True)
    def _started(self, repo: Path) -> None:
        _start(repo)

    def test_unmoved(self, repo: Path) -> None:
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_UNMOVED

    def test_a_document_nothing_reads_is_docs_only(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# Lonely 2\n"})
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_DOCS_ONLY

    def test_a_document_a_test_reads_is_targeted(self, repo: Path) -> None:
        _on_main(repo, {_GUIDE: "# Guide 2\n", _LONELY: "# Lonely 2\n"})
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_TARGETED
        kinds = {judged.path: judged.kind for judged in outcome.paths}
        assert kinds == {_GUIDE: _TESTED, _LONELY: _DOCS}

    def test_code_needs_the_full_gate(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# 2\n", "src/app.py": "x = 2\n"})
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_FULL_GATE

    def test_a_commit_and_its_revert_are_not_unmoved(self, repo: Path) -> None:
        _on_main(repo, {"src/app.py": "x = 2\n"})
        _on_main(repo, {"src/app.py": "x = 1\n"}, "revert")
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_DOCS_ONLY
        assert outcome.paths == []

    def test_a_rename_out_of_src_is_judged_by_its_old_path(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "main")
        _git(repo, "mv", "src/app.py", "notes/app.md")
        _git(repo, "commit", "-q", "-m", "move")
        _git(repo, "checkout", "-q", _BRANCH)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert "src/app.py" in [judged.path for judged in outcome.paths]

    def test_a_symlinked_document_needs_the_full_gate(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "main")
        (repo / "notes" / "app.md").symlink_to("../src/app.py")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "link")
        _git(repo, "checkout", "-q", _BRANCH)
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_FULL_GATE

    def test_a_rewritten_main_needs_the_full_gate(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "main")
        _git(repo, "checkout", "-q", "--orphan", "rewritten")
        _commit(repo, {"src/app.py": "z = 1\n"}, "rewritten")
        _git(repo, "branch", "-f", "main", "rewritten")
        _git(repo, "checkout", "-q", _BRANCH)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert "rewritten" in outcome.reason

    def test_an_unknown_main_ref_is_an_error(self, repo: Path) -> None:
        with pytest.raises(llm_qa.MainMovedError):
            llm_qa.main_moved(repo, "no-such-ref")


class TestAdvancing:
    """Review 3 R2: the base moves only when the verdict's recheck has passed."""

    @pytest.fixture(autouse=True)
    def _started(self, repo: Path) -> None:
        _start(repo)

    def test_nothing_to_advance_before_main_is_merged_in(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# 2\n"})
        with pytest.raises(llm_qa.MainMovedError, match="merge"):
            llm_qa.advance_batch(repo, "main")

    def test_a_merge_with_no_recheck_does_not_advance(self, repo: Path) -> None:
        before = _base(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        with pytest.raises(llm_qa.MainMovedError, match="docs_qa"):
            llm_qa.advance_batch(repo, "main")
        assert _base(repo) == before

    def test_a_passed_docs_recheck_advances_and_the_next_check_is_unmoved(self, repo: Path) -> None:
        moved = _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        assert llm_qa.advance_batch(repo, "main") == moved
        assert _base(repo) == moved
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_UNMOVED

    def test_after_advancing_only_newer_movement_is_seen(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        llm_qa.advance_batch(repo, "main")
        _on_main(repo, {"src/app.py": "x = 3\n"})
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert [judged.path for judged in outcome.paths] == ["src/app.py"]

    def test_a_failed_recheck_does_not_advance(self, repo: Path) -> None:
        """Review 3 R8: a recorded ``passed: false`` is never a pass."""
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES, passed=False)
        with pytest.raises(llm_qa.MainMovedError, match="did not pass"):
            llm_qa.advance_batch(repo, "main")

    def test_a_recheck_on_another_tree_does_not_advance(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# 2\n"})
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        _merge_main(repo)
        with pytest.raises(llm_qa.MainMovedError, match="re-run"):
            llm_qa.advance_batch(repo, "main")

    def test_a_targeted_move_needs_the_changed_run_over_exactly_that_range(
        self, repo: Path
    ) -> None:
        base = _base(repo)
        moved = _on_main(repo, {_GUIDE: "# Guide 2\n"})
        _merge_main(repo)
        tools = llm_qa.required_tools(llm_qa.VERDICT_TARGETED)
        _certify(repo, tools, changed_range=f"{base}..{base}")
        with pytest.raises(llm_qa.MainMovedError, match="--range"):
            llm_qa.advance_batch(repo, "main")
        _certify(repo, tools, changed_range=f"{base}..{moved}")
        assert llm_qa.advance_batch(repo, "main") == moved

    def test_a_full_gate_move_needs_every_full_tool(self, repo: Path) -> None:
        moved = _on_main(repo, {"src/app.py": "x = 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.required_tools(llm_qa.VERDICT_TARGETED))
        with pytest.raises(llm_qa.MainMovedError):
            llm_qa.advance_batch(repo, "main")
        _certify(repo, llm_qa.ALL_TOOL_NAMES)
        assert llm_qa.advance_batch(repo, "main") == moved


class TestTheCertifiedHead:
    """Review 4 N2: a verdict is about the head that lands, not only about ``main``.

    ``refs/integration/certified/<branch>`` is the head a gate passed on a
    clean tree. Only a passing ``llm_qa.py all`` and a successful ``--advance``
    write it, and ``unmoved`` needs HEAD to be it, on a clean tree.
    """

    def test_no_gate_since_start_is_head_moved_not_unmoved(self, repo: Path) -> None:
        llm_qa.start_batch(repo, "main")
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_HEAD_MOVED
        assert "llm_qa.py all" in outcome.reason

    def test_a_merge_after_the_gate_is_head_moved(self, repo: Path) -> None:
        """Review 4 N2(a): a late child merged after the gate read ``unmoved``."""
        _start(repo)
        _git(repo, "checkout", "-q", "-b", "late-child", "main")
        _commit(repo, {"src/late.py": "z = 1\n"}, "a late child")
        _git(repo, "checkout", "-q", _BRANCH)
        _git(repo, "merge", "-q", "--no-ff", "--no-edit", "late-child")
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_HEAD_MOVED

    def test_head_moved_is_checked_before_main_movement(self, repo: Path) -> None:
        _start(repo)
        _commit(repo, {"src/feature.py": "y = 2\n"}, "after the gate")
        _on_main(repo, {_LONELY: "# 2\n"})
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_HEAD_MOVED

    @pytest.mark.parametrize(
        "dirty",
        [
            {"src/feature.py": "y = 99\n"},
            {"docs/untracked-copy.md": "# not committed\n"},
        ],
        ids=["tracked-edit", "untracked-file"],
    )
    def test_an_uncommitted_change_is_head_moved(self, repo: Path, dirty: dict[str, str]) -> None:
        _start(repo)
        _write(repo, dirty)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_HEAD_MOVED
        assert "uncommitted" in outcome.reason

    def test_the_gate_again_on_the_new_head_restores_unmoved(self, repo: Path) -> None:
        _start(repo)
        _commit(repo, {"src/feature.py": "y = 2\n"}, "after the gate")
        _gate(repo)
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_UNMOVED

    def test_a_gate_is_not_certified_on_a_dirty_tree(self, repo: Path) -> None:
        llm_qa.start_batch(repo, "main")
        _write(repo, {"docs/untracked-copy.md": "# x\n"})
        with pytest.raises(llm_qa.MainMovedError, match="uncommitted"):
            llm_qa.certify_head(repo, llm_qa.worktree_state(repo))
        assert _certified(repo) is None

    def test_a_gate_is_not_certified_when_the_tree_changed_during_the_run(self, repo: Path) -> None:
        llm_qa.start_batch(repo, "main")
        judged = llm_qa.worktree_state(repo)
        _commit(repo, {"src/feature.py": "y = 3\n"}, "during the run")
        with pytest.raises(llm_qa.MainMovedError, match="changed"):
            llm_qa.certify_head(repo, judged)
        assert _certified(repo) is None

    def test_outside_a_batch_a_gate_certifies_nothing(self, repo: Path) -> None:
        assert llm_qa.certify_head(repo, llm_qa.worktree_state(repo)) is None
        assert _certified(repo) is None


class TestStartingTwice:
    """Review 4 N2(b): a second ``--start`` silently reset the base past moved code."""

    def test_a_second_start_is_refused_and_the_base_stays(self, repo: Path) -> None:
        first = llm_qa.start_batch(repo, "main")
        _on_main(repo, {"src/app.py": "x = 2\n"})
        _merge_main(repo)
        with pytest.raises(llm_qa.MainMovedError, match="--restart"):
            llm_qa.start_batch(repo, "main")
        assert _base(repo) == first

    def test_restart_records_a_new_base_and_clears_the_certified_head(self, repo: Path) -> None:
        _start(repo)
        moved = _on_main(repo, {"src/app.py": "x = 2\n"})
        _merge_main(repo)
        assert llm_qa.start_batch(repo, "main", restart=True) == moved
        assert _certified(repo) is None
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_HEAD_MOVED


class TestAdvancingNeedsTheHeadThatLands:
    """Review 4 N2(c) and the late-merge path through ``--advance``."""

    @pytest.fixture(autouse=True)
    def _started(self, repo: Path) -> None:
        _start(repo)

    def test_advance_refuses_an_uncommitted_tree(self, repo: Path) -> None:
        """N2(c): an untracked copy of a deleted doc certified a head that lacks it."""
        before = _base(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _write(repo, {"docs/untracked-copy.md": "# restored by hand\n"})
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        with pytest.raises(llm_qa.MainMovedError, match="uncommitted"):
            llm_qa.advance_batch(repo, "main")
        assert _base(repo) == before

    def test_advance_refuses_work_merged_alongside_main(self, repo: Path) -> None:
        before = _base(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _commit(repo, {"src/feature.py": "y = 5\n"}, "not from main")
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        with pytest.raises(llm_qa.MainMovedError, match="llm_qa.py all"):
            llm_qa.advance_batch(repo, "main")
        assert _base(repo) == before

    def test_advance_refuses_an_edit_made_inside_the_merge_of_main(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# 2\n"})
        _git(repo, "merge", "-q", "--no-commit", "--no-ff", "main")
        _write(repo, {"src/feature.py": "y = 6\n"})
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "--no-edit")
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        with pytest.raises(llm_qa.MainMovedError, match="src/feature.py"):
            llm_qa.advance_batch(repo, "main")

    def test_a_conflict_resolved_on_a_path_main_moved_can_advance(self, repo: Path) -> None:
        _commit(repo, {_LONELY: "# branch side\n"}, "branch edits the doc")
        _gate(repo)
        moved = _on_main(repo, {_LONELY: "# main side\n"})
        completed = subprocess.run(
            ["git", "-C", str(repo), "merge", "-q", "--no-edit", "main"],
            capture_output=True,
            timeout=Timeout.QA_TEST_TIMEOUT,
            check=False,
        )
        assert completed.returncode != 0, "the fixture must conflict"
        _write(repo, {_LONELY: "# both sides\n"})
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "--no-edit")
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        assert llm_qa.advance_batch(repo, "main") == moved

    def test_advance_certifies_the_merged_head(self, repo: Path) -> None:
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        llm_qa.advance_batch(repo, "main")
        assert _certified(repo) == _git(repo, "rev-parse", "HEAD")

    def test_the_range_check_compares_commits_not_spellings(self, repo: Path) -> None:
        """Review 4 N12: ``<sha>..main`` is the same range as ``<sha>..<sha>``."""
        base = _base(repo)
        moved = _on_main(repo, {_GUIDE: "# Guide 2\n"})
        _merge_main(repo)
        _certify(
            repo, llm_qa.required_tools(llm_qa.VERDICT_TARGETED), changed_range=f"{base}..main"
        )
        assert llm_qa.advance_batch(repo, "main") == moved


class TestTheGateRunCertifies:
    """``llm_qa.py all`` writes the certified head, and only a clean, passing run does."""

    @pytest.fixture
    def stubbed(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        qa_dir = _qa_dir(repo)
        qa_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(llm_qa, "PROJECT_ROOT", repo)
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", qa_dir)

        def run_tool(name: str, extra_args: Any = ()) -> int:
            (qa_dir / llm_qa.TOOL_REGISTRY[name].json_file).write_text("{}", encoding="utf-8")
            return 0

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        return qa_dir

    def _summaries(self, monkeypatch: pytest.MonkeyPatch, failing: str | None) -> None:
        def summarize(name: str, **_: Any) -> tuple[bool, str]:
            return name != failing, f"{name}\n"

        monkeypatch.setattr(llm_qa, "summarize_tool", summarize)

    def test_a_passing_full_run_in_a_batch_certifies_head(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llm_qa.start_batch(repo, "main")
        self._summaries(monkeypatch, failing=None)
        assert llm_qa._run_tools(list(llm_qa.ALL_TOOL_NAMES), read_only=False) == 0
        assert _certified(repo) == _git(repo, "rev-parse", "HEAD")

    def test_a_failing_full_run_certifies_nothing(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llm_qa.start_batch(repo, "main")
        self._summaries(monkeypatch, failing="lint")
        llm_qa._run_tools(list(llm_qa.ALL_TOOL_NAMES), read_only=False)
        assert _certified(repo) is None

    def test_a_partial_run_certifies_nothing(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llm_qa.start_batch(repo, "main")
        self._summaries(monkeypatch, failing=None)
        llm_qa._run_tools(["lint"], read_only=False)
        assert _certified(repo) is None


class TestFinishing:
    """Review 4 N12: the batch refs were never removed after the batch landed."""

    def test_finish_refuses_before_the_certified_head_is_on_main(self, repo: Path) -> None:
        _start(repo)
        with pytest.raises(llm_qa.MainMovedError, match="--ff-only"):
            llm_qa.finish_batch(repo, "main")
        assert _certified(repo) is not None

    def test_finish_removes_both_refs_once_the_batch_landed(self, repo: Path) -> None:
        _start(repo)
        _git(repo, "branch", "-f", "main", _BRANCH)
        llm_qa.finish_batch(repo, "main")
        assert _certified(repo) is None
        assert _git(repo, "for-each-ref", f"refs/integration/base/{_BRANCH}") == ""

    def test_the_refs_follow_the_branch_namespace(self, repo: Path) -> None:
        """A branch ``a`` and ``a/base`` collided under ``refs/integration/<branch>/base``."""
        _git(repo, "checkout", "-q", "-b", "feature/x")
        assert llm_qa.batch_base_ref(repo) == "refs/integration/base/feature/x"
        assert llm_qa.certified_ref(repo) == "refs/integration/certified/feature/x"


class TestExactlyTheCertifiedHeadLands:
    """Review 5 m5 and n2: what lands is the head the gate passed, and nothing after it."""

    def _late_child(self, repo: Path) -> str:
        """A commit on the integration branch after the gate: never certified."""
        return _commit(repo, {"src/late.py": "z = 1\n"}, "a late child")

    def test_unmoved_names_the_certified_sha_not_the_branch(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start(repo)
        certified = _git(repo, "rev-parse", "HEAD")
        assert llm_qa.main_moved_command([], root=repo) == llm_qa.EXIT_SUCCESS
        out = capsys.readouterr().out
        assert f"git merge --ff-only {certified}" in out
        assert f"--ff-only {_BRANCH}" not in out

    def test_the_verdict_carries_the_certified_head(self, repo: Path) -> None:
        _start(repo)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.head == _git(repo, "rev-parse", "HEAD")

    def test_finish_refuses_a_descendant_of_the_certified_head(self, repo: Path) -> None:
        _start(repo)
        self._late_child(repo)
        _git(repo, "branch", "-f", "main", _BRANCH)
        with pytest.raises(llm_qa.MainMovedError, match="not the certified head"):
            llm_qa.finish_batch(repo, "main")
        assert _certified(repo) is not None, "the evidence stays"

    def test_finish_accepts_a_merge_of_the_certified_head_with_its_tree(self, repo: Path) -> None:
        _start(repo)
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--no-ff", "--no-edit", _BRANCH)
        _git(repo, "checkout", "-q", _BRANCH)
        llm_qa.finish_batch(repo, "main")
        assert _certified(repo) is None

    def test_finish_refuses_a_merge_whose_tree_is_not_the_certified_tree(self, repo: Path) -> None:
        _start(repo)
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {_LONELY: "# moved on main\n"}, "main moved")
        _git(repo, "merge", "-q", "--no-ff", "--no-edit", _BRANCH)
        _git(repo, "checkout", "-q", _BRANCH)
        with pytest.raises(llm_qa.MainMovedError, match="not the certified head"):
            llm_qa.finish_batch(repo, "main")

    def test_finish_refuses_a_same_tree_child_that_is_no_merge(self, repo: Path) -> None:
        """Review 6 n3: only a real merge of the certified head is accepted."""
        _start(repo)
        certified = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "-B", "main", certified)
        _commit(repo, {}, "same tree, one parent")
        _git(repo, "checkout", "-q", _BRANCH)
        with pytest.raises(llm_qa.MainMovedError, match="not the certified head"):
            llm_qa.finish_batch(repo, "main")

    @pytest.mark.parametrize("side_branches", [["unrelated"], ["one", "two"]])
    def test_finish_refuses_a_same_tree_merge_with_another_line_of_work(
        self, repo: Path, side_branches: list[str]
    ) -> None:
        """Review 6 n3: a merge with an unrelated branch, or an octopus, is no landing."""
        _start(repo)
        certified = _git(repo, "rev-parse", "HEAD")
        for name in side_branches:
            if name == "unrelated":
                _git(repo, "checkout", "-q", "--orphan", name)
                _git(repo, "rm", "-rfq", ".")
            else:
                _git(repo, "checkout", "-q", "-b", name, "main")
            _commit(repo, {f"{name}.md": f"# {name}\n"}, name)
        _git(repo, "checkout", "-q", "-B", "main", certified)
        _git(
            repo,
            "merge",
            "-q",
            "-s",
            "ours",
            "--no-edit",
            "--allow-unrelated-histories",
            *side_branches,
        )
        _git(repo, "checkout", "-q", _BRANCH)
        with pytest.raises(llm_qa.MainMovedError, match="not the certified head"):
            llm_qa.finish_batch(repo, "main")

    def test_unmoved_needs_head_to_contain_main(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """n2 (S12): the base advanced, then the branch backed out the merge of main."""
        _start(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        llm_qa.advance_batch(repo, "main")
        _git(repo, "checkout", "-q", "-B", _BRANCH, "HEAD~1")
        _gate(repo)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_HEAD_MOVED
        assert "does not contain" in outcome.reason
        capsys.readouterr()
        assert llm_qa.main_moved_command([], root=repo) == llm_qa.EXIT_HEAD_MOVED
        assert "git merge --no-edit main" in capsys.readouterr().out


class TestTheGateIsNotRunTwiceOnOneHead:
    """Review 5 m6: after main was merged and the gate passed, only ``--advance`` is left."""

    def test_a_passed_gate_on_the_merged_head_prints_only_advance(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start(repo)
        _on_main(repo, {"src/app.py": "x = 2\n"})
        _merge_main(repo)
        _gate(repo)
        _certify(repo, llm_qa.ALL_TOOL_NAMES)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert outcome.recheck_passed
        assert llm_qa.main_moved_command([], root=repo) == llm_qa.EXIT_FULL_GATE
        out = capsys.readouterr().out
        assert "--advance" in out
        assert "llm_qa.py all" not in out
        assert "git merge --no-edit" not in out

    def test_main_not_yet_merged_still_prints_the_recheck(self, repo: Path) -> None:
        _start(repo)
        _on_main(repo, {"src/app.py": "x = 2\n"})
        _certify(repo, llm_qa.ALL_TOOL_NAMES)
        assert not llm_qa.main_moved(repo, "main").recheck_passed

    def test_a_merged_head_without_the_recheck_still_needs_it(self, repo: Path) -> None:
        _start(repo)
        _on_main(repo, {"src/app.py": "x = 2\n"})
        _merge_main(repo)
        _gate(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        assert not llm_qa.main_moved(repo, "main").recheck_passed

    def test_a_merge_of_main_after_the_gate_is_judged_as_the_movement_of_main(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Review 6 m8: main merged and its docs recheck passed, then a check said head-moved."""
        _start(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_DOCS_ONLY
        assert outcome.recheck_passed
        capsys.readouterr()
        assert llm_qa.main_moved_command([], root=repo) == llm_qa.EXIT_DOCS_ONLY
        out = capsys.readouterr().out
        assert "--advance" in out
        assert "llm_qa.py all" not in out

    def test_a_merge_of_main_whose_recheck_has_not_run_names_the_recheck(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _start(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_DOCS_ONLY
        assert not outcome.recheck_passed
        capsys.readouterr()
        llm_qa.main_moved_command([], root=repo)
        out = capsys.readouterr().out
        assert "llm_qa.py all" not in out
        assert " ".join(llm_qa.DOCS_ONLY_TOOL_NAMES) in out

    @pytest.mark.parametrize("extra", ["a commit", "an edit inside the merge"])
    def test_work_beside_the_merge_of_main_is_still_head_moved(
        self, repo: Path, extra: str
    ) -> None:
        _start(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        if extra == "a commit":
            _merge_main(repo)
            _commit(repo, {"src/feature.py": "y = 5\n"}, "not from main")
        else:
            _git(repo, "merge", "-q", "--no-commit", "--no-ff", "main")
            _write(repo, {"src/feature.py": "y = 6\n"})
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "--no-edit")
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        assert llm_qa.main_moved(repo, "main").verdict == llm_qa.VERDICT_HEAD_MOVED

    def test_the_merge_step_names_the_judged_commit_not_the_moved_ref(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Review 7 m5: main moved again before the printed merge step ran.

        The recheck range (base..judged) is only right for HEAD holding
        exactly ``judged`` merged in; printing ``git merge main`` would pull
        in the newer, unmerged commit too and waste the recheck.
        """
        _start(repo)
        judged = _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _on_main(repo, {"src/app.py": "x = 2\n"})
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_DOCS_ONLY
        assert outcome.main == judged
        capsys.readouterr()
        llm_qa.main_moved_command([], root=repo)
        out = capsys.readouterr().out
        assert f"git merge --no-edit {judged}" in out
        assert "git merge --no-edit main" not in out

    def test_a_dirty_tree_after_the_merge_of_main_is_still_head_moved(self, repo: Path) -> None:
        _start(repo)
        _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        _write(repo, {"docs/untracked-copy.md": "# x\n"})
        outcome = llm_qa.main_moved(repo, "main")
        assert outcome.verdict == llm_qa.VERDICT_HEAD_MOVED
        assert "uncommitted" in outcome.reason


class TestTheCommand:
    def _run(self, repo: Path, *args: str) -> int:
        return int(llm_qa.main_moved_command(list(args), root=repo))

    def test_start_then_the_gate_then_unmoved_exits_zero(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run(repo, "--start") == llm_qa.EXIT_SUCCESS
        _gate(repo)
        assert self._run(repo) == llm_qa.EXIT_SUCCESS
        out = capsys.readouterr().out
        assert f"VERDICT: {llm_qa.VERDICT_UNMOVED}" in out
        assert "--ff-only" in out

    @pytest.mark.parametrize(
        ("files", "verdict", "exit_code"),
        [
            ({_LONELY: "# 2\n"}, "docs-only", 5),
            ({_GUIDE: "# 2\n"}, "targeted", 6),
            ({"src/app.py": "x = 2\n"}, "full-gate", 4),
        ],
    )
    def test_each_verdict_has_its_own_exit_code_and_names_its_recheck(
        self,
        repo: Path,
        capsys: pytest.CaptureFixture[str],
        files: dict[str, str],
        verdict: str,
        exit_code: int,
    ) -> None:
        """Review 3 R11: docs-only and unmoved shared exit 0."""
        self._run(repo, "--start")
        _gate(repo)
        base = _base(repo)
        moved = _on_main(repo, files)
        capsys.readouterr()
        assert self._run(repo) == exit_code
        out = capsys.readouterr().out
        assert f"VERDICT: {verdict}" in out
        assert "--advance" in out
        assert "second line" in out
        recheck = {
            "docs-only": "llm_qa.py " + " ".join(llm_qa.DOCS_ONLY_TOOL_NAMES),
            "targeted": f"--range {base}..{moved}",
            "full-gate": "llm_qa.py all",
        }[verdict]
        assert recheck in out

    def test_advance_through_the_command(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run(repo, "--start")
        _gate(repo)
        moved = _on_main(repo, {_LONELY: "# 2\n"})
        _merge_main(repo)
        assert self._run(repo, "--advance") == llm_qa.EXIT_FAILURE
        _certify(repo, llm_qa.DOCS_ONLY_TOOL_NAMES)
        assert self._run(repo, "--advance") == llm_qa.EXIT_SUCCESS
        assert moved in capsys.readouterr().out

    def test_head_moved_has_its_own_exit_code_and_names_the_full_gate(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run(repo, "--start")
        capsys.readouterr()
        assert self._run(repo) == llm_qa.EXIT_HEAD_MOVED
        out = capsys.readouterr().out
        assert f"VERDICT: {llm_qa.VERDICT_HEAD_MOVED}" in out
        assert "llm_qa.py all" in out
        assert "--ff-only" not in out

    def test_start_twice_needs_restart_through_the_command(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run(repo, "--start") == llm_qa.EXIT_SUCCESS
        assert self._run(repo, "--start") == llm_qa.EXIT_FAILURE
        assert "--restart" in capsys.readouterr().err
        assert self._run(repo, "--start", "--restart") == llm_qa.EXIT_SUCCESS

    def test_finish_through_the_command(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run(repo, "--start")
        _gate(repo)
        assert self._run(repo, "--finish") == llm_qa.EXIT_FAILURE
        _git(repo, "branch", "-f", "main", _BRANCH)
        assert self._run(repo, "--finish") == llm_qa.EXIT_SUCCESS
        assert _certified(repo) is None

    def test_an_error_prints_no_verdict(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run(repo) == llm_qa.EXIT_FAILURE
        assert "VERDICT" not in capsys.readouterr().out

    @pytest.mark.parametrize(
        "args",
        [
            ["a", "b"],
            ["--start", "--advance"],
            ["--bogus"],
            ["--start", "main", "extra"],
            ["--restart"],
            ["--advance", "--restart"],
            ["--finish", "--start"],
        ],
    )
    def test_wrong_arguments_are_a_usage_error(
        self, repo: Path, args: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run(repo, *args) == llm_qa.EXIT_FAILURE
        assert "Usage" in capsys.readouterr().err


class TestTheCliDispatch:
    @pytest.mark.parametrize(
        "argv",
        [["main-moved", "--bogus"], ["--read-only", "main-moved", "--bogus"]],
    )
    def test_main_dispatches_the_subcommand_before_tool_resolution(
        self,
        argv: list[str],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Review 3 R11: ``--read-only main-moved`` printed "Unknown tool: main-moved"."""
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", *argv])
        assert llm_qa.main() == llm_qa.EXIT_FAILURE
        err = capsys.readouterr()
        assert "Usage" in err.err
        assert "Unknown tool" not in err.out

    def test_main_moved_after_a_tool_name_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", "lint", "main-moved"])
        assert llm_qa.main() == llm_qa.EXIT_FAILURE
        assert "main-moved" in capsys.readouterr().err

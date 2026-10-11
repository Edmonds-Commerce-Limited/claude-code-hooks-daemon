"""N260: CI and the local runner start the project-handler tests the same way.

The local runner (``cmd_test_project_handlers``) passes ``--import-mode=importlib``
and unloads the full-QA gate plugin. CI used to pass only the first flag, so
the gate plugin ran there and not locally: a run could be green locally and red
on CI. The workflow step is the CI half; ``cli.py`` is the local half. Both are
read from their source files, so neither can drift on its own.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "qa.yml"
CLI = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "cli.py"

_STEP = re.compile(r"- name: Project handler tests\n(?P<body>(?:[ ]{8}.*\n)+)")


def _ci_command() -> str:
    match = _STEP.search(WORKFLOW.read_text())
    assert match is not None, "the 'Project handler tests' step is missing from qa.yml"
    run = re.search(r"run: (?P<cmd>pytest .*)", match.group("body"))
    assert run is not None, "the step has no single-line pytest command"
    return run.group("cmd")


def _gate_plugin_name() -> str:
    match = re.search(r'^_FULL_QA_GATE_PLUGIN = "(?P<name>[^"]+)"', CLI.read_text(), re.M)
    assert match is not None
    return match.group("name")


class TestCiMatchesTheLocalRunner:
    def test_ci_passes_the_import_mode_flag(self) -> None:
        assert "--import-mode=importlib" in _ci_command()

    def test_ci_unloads_the_full_qa_gate_plugin_like_the_local_run(self) -> None:
        assert f"-p no:{_gate_plugin_name()}" in _ci_command()

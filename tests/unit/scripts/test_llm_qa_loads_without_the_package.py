"""``llm_qa.py`` loads under a python3 that cannot import the daemon package.

``./scripts/qa/llm_qa.py`` runs through its ``#!/usr/bin/env python3`` shebang,
so it starts under whatever python3 is first on PATH, before any venv. A
top-level import of ``claude_code_hooks_daemon`` therefore crashes the
documented full-QA entry point there, which is how a whole gate run failed
at its first line.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LLM_QA = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "llm_qa.py"

_LOAD_WITHOUT_EXECUTING_MAIN = (
    "import importlib.util as u, sys\n"
    "spec = u.spec_from_file_location('llm_qa_under_test', sys.argv[1])\n"
    "module = u.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
)


def test_llm_qa_loads_with_no_site_packages() -> None:
    # -I drops the working directory and PYTHONPATH; -S drops site-packages,
    # where the venv's editable install of the package lives.
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", _LOAD_WITHOUT_EXECUTING_MAIN, str(LLM_QA)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr

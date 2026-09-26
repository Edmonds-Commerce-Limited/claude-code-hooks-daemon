"""Tests for ``python_program_reach.analyse_python_program`` (Plan 00466 N101).

``shell_expansion.brace_expansion_view`` stops enumerating the brace
spellings of a Python program handed to ``python3`` on the command line.
That is sound only while the program's own text cannot reach anything that
brace-expands it or runs it later. This module answers that question: a
program that may spawn a process, write a file, execute code dynamically or
load code from outside a small stdlib allowlist "reaches beyond stdout", and
its string literals are then still enumerated by the caller.

Fixture sources that name a process or code-execution call are split into
adjacent string literals, so this file's own text does not read as a call.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.python_program_reach import analyse_python_program


def _reaches(source: str) -> bool:
    program = analyse_python_program(source)
    assert program is not None
    return program.reaches_beyond_stdout


class TestUnparseableSourceIsNotAnalysed:
    @pytest.mark.parametrize("source", ["print(", "def f(:\n  pass", "x = 1\0"])
    def test_unparseable_source_returns_none(self, source: str) -> None:
        assert analyse_python_program(source) is None


class TestProgramsThatOnlyPrint:
    @pytest.mark.parametrize(
        "source",
        [
            "print('{a,b}{c,d}')",
            "import json\nprint(json.dumps({'a': 1, 'b': [1, 2]}))",
            "from pathlib import Path\nprint(Path('x').read_text())",
            "import re, sys\nprint(re.sub('a', 'b', sys.argv[0]))",
            "with open('x') as f:\n    print(f.read())",
            "with open('x', 'rb') as f:\n    print(f.read())",
            "with open('x', mode='rt') as f:\n    print(f.read())",
            "if __name__ == '__main__':\n    print(1)",
            "x = f'{1}-{2}'\nprint(x, file=None)",
        ],
    )
    def test_does_not_reach_beyond_stdout(self, source: str) -> None:
        assert not _reaches(source)


class TestProgramsThatReachBeyondStdout:
    @pytest.mark.parametrize(
        "source",
        [
            # Spawning a process, any spelling.
            "import os\nos." "system('x')",
            "import os\nos." "popen('x')",
            "import os\nos.execvp('bash', ['bash'])",
            "import os\nos.spawnlp(0, 'bash', 'bash')",
            "import os\nos.posix_spawn('/bin/sh', ['sh'], {})",
            "from os import system\nsys" "tem('x')",
            "from os import *\nsys" "tem('x')",
            "import subprocess\nsubprocess.run(['env', 'bash', '-c', 'x'])",
            "from subprocess import run as r\nr('x')",
            "import pty\npty." "spawn('bash')",
            "import commands\ncommands.getoutput('x')",
            "import asyncio\nasyncio.create_subprocess_exec('bash')",
            # Writing a file a later command can run.
            "open('g.sh', 'w').write('x')",
            "open('g.sh', mode='a').write('x')",
            "f = open\nf('g.sh', 'w')",
            "from pathlib import Path\nPath('g.sh').write_text('x')",
            "from pathlib import Path\nPath('g.sh').open('w')",
            "import os\nfd = os.open('g.sh', 1)",
            "import sys\nsys.stdout.write('x')",
            # Running text as code, or reaching a name dynamically.
            "ex" "ec('x = 1')",
            "ev" "al('1')",
            "compile('x', 'f', 'exec')",
            "__imp" "ort__('subprocess')",
            "import os\ngetattr(os, 'system')('x')",
            "().__class__.__base__.__subclasses__()",
            "import sys\nsys.modules['subprocess']",
            "help('x')",
            # Code from outside the allowlist.
            "import braceexpand",
            "from wcmatch import glob",
            "import shutil",
            "import logging",
            "from . import local",
            "import local_module",
        ],
    )
    def test_reaches_beyond_stdout(self, source: str) -> None:
        assert _reaches(source)


class TestStringLiterals:
    def test_every_string_literal_is_reported(self) -> None:
        program = analyse_python_program("a = 'x{a,b}'\nb = \"y\" 'z'\nc = b'w{1,2}'\n")
        assert program is not None
        assert program.string_literals == ("x{a,b}", "yz", "w{1,2}")

    def test_an_f_string_reports_its_literal_text(self) -> None:
        program = analyse_python_program("d = 1\nx = f'cat {d}/.p{{a,x}}ss'\n")
        assert program is not None
        assert "/.p{a,x}ss" in program.string_literals

    def test_code_braces_are_not_literals(self) -> None:
        program = analyse_python_program("x = {'a': 1, 'b': {2, 3}}\n")
        assert program is not None
        assert program.string_literals == ("a", "b")

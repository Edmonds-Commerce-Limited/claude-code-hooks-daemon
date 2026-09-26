"""Can a Python program's text reach anything but its own stdout? (Plan 00466 N101)

``shell_expansion.brace_expansion_view`` stops enumerating the brace
spellings of a Python program handed to ``python3`` on the command line,
because Python never brace-expands its source and nothing in the standard
library's file APIs expands braces either. That is sound only while the
program cannot hand its own text on to something that does: a spawned
process (a shell brace-expands its argument), a file a later command runs,
text executed as code, or a library the analysis cannot see into.

:func:`analyse_python_program` answers with an ALLOWLIST. A program
"reaches beyond stdout" unless every module it imports is on
:data:`_STDOUT_ONLY_MODULES`, it names nothing on
:data:`_REACHING_NAMES` (not even as a string, which is how ``getattr``
spells an attribute), it touches no dunder outside
:data:`_ORDINARY_DUNDERS`, and every ``open`` it makes is read-only. An
unknown name costs a false positive -- the caller enumerates the program's
string literals as it would enumerate shell text -- never a bypass.

A value assembled at runtime (``"id_" + "rsa"``) is outside every
spelling-based scan, on this route as on any other; that residual is the
guard's, not this module's.
"""

from __future__ import annotations

import ast
import logging
from typing import Final, NamedTuple

logger = logging.getLogger(__name__)

#: Top-level modules a program may import and still only print. None of them
#: spawns a process, and none expands braces in a path. Their file-writing
#: entry points are caught by name (:data:`_REACHING_NAMES`) or by the
#: ``open`` mode rule.
_STDOUT_ONLY_MODULES: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "abc",
        "argparse",
        "ast",
        "base64",
        "binascii",
        "bisect",
        "calendar",
        "collections",
        "colorsys",
        "contextlib",
        "copy",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "difflib",
        "enum",
        "fnmatch",
        "fractions",
        "functools",
        "glob",
        "graphlib",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "math",
        "numbers",
        "operator",
        "os",
        "pathlib",
        "pprint",
        "random",
        "re",
        "secrets",
        "shlex",
        "statistics",
        "string",
        "struct",
        "sys",
        "textwrap",
        "time",
        "token",
        "tokenize",
        "tomllib",
        "types",
        "typing",
        "unicodedata",
        "uuid",
        "zlib",
    }
)

#: Names that spawn a process, write or re-route a file descriptor, run text
#: as code, or reach an attribute or module dynamically. Matched against
#: every name, attribute, imported name and string constant in the program,
#: whatever object it hangs off: ``x.system`` is judged like ``os.system``.
_REACHING_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Processes
        "system",
        "popen",
        "Popen",
        "fork",
        "forkpty",
        "startfile",
        "getoutput",
        "getstatusoutput",
        "create_subprocess_shell",
        "create_subprocess_exec",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "posix_spawn",
        "posix_spawnp",
        # Files and descriptors
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "writestr",
        "fdopen",
        "dup",
        "dup2",
        "FileIO",
        # Code and dynamic reach
        "exec",
        "eval",
        "compile",
        "__import__",
        "breakpoint",
        "help",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "modules",
    }
)

#: Dunders an ordinary program touches. Any other (``__class__``,
#: ``__subclasses__``, ``__builtins__``, ``__globals__`` ...) is the route
#: from any object to ``subprocess`` without naming it.
_ORDINARY_DUNDERS: Final[frozenset[str]] = frozenset(
    {
        "__name__",
        "__main__",
        "__file__",
        "__doc__",
        "__all__",
        "__version__",
        "__init__",
        "__post_init__",
        "__repr__",
        "__str__",
        "__eq__",
        "__ne__",
        "__lt__",
        "__le__",
        "__gt__",
        "__ge__",
        "__hash__",
        "__bool__",
        "__len__",
        "__iter__",
        "__next__",
        "__contains__",
        "__getitem__",
        "__enter__",
        "__exit__",
        "__slots__",
    }
)

#: ``open`` modes that only read.
_READ_MODE_CHARS: Final[frozenset[str]] = frozenset("rbtU")

#: Modules whose ``open`` takes the mode as its SECOND argument, like the
#: builtin. Any other ``x.open`` (``Path.open``) takes it first; ``os.open``
#: takes flags, and is never read-only as far as this analysis knows.
_OPEN_MODE_SECOND: Final[frozenset[str]] = frozenset({"io", "codecs"})


class PythonProgram(NamedTuple):
    """``reaches_beyond_stdout``: the program may hand its text to something
    other than its own stdout. ``string_literals``: every string (and
    decoded bytes) constant, f-string literal parts included."""

    reaches_beyond_stdout: bool
    string_literals: tuple[str, ...]


def analyse_python_program(source: str) -> PythonProgram | None:
    """Analyse ``source`` as a whole Python program; ``None`` when it does
    not parse, which the caller must treat as "cannot be exempted"."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        logger.debug("python_program_reach: program does not parse: %s", exc)
        return None
    read_only_opens = _read_only_open_callees(tree)
    literals: list[str] = []
    reaches = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            text = node.value if isinstance(node.value, str) else node.value.decode("latin-1")
            literals.append(text)
            reaches = reaches or _is_reaching_name(text)
        elif not reaches:
            reaches = _node_reaches(node, read_only_opens)
    return PythonProgram(reaches, tuple(literals))


def _node_reaches(node: ast.AST, read_only_opens: set[int]) -> bool:
    if isinstance(node, ast.Import):
        return any(not _module_is_stdout_only(alias.name) for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        if node.level or node.module is None or not _module_is_stdout_only(node.module):
            return True
        return any(alias.name == "*" or _is_reaching_name(alias.name) for alias in node.names)
    if isinstance(node, ast.Name):
        return _is_reaching_name(node.id) or (node.id == "open" and id(node) not in read_only_opens)
    if isinstance(node, ast.Attribute):
        return _is_reaching_name(node.attr) or (
            node.attr == "open" and id(node) not in read_only_opens
        )
    return False


def _module_is_stdout_only(dotted: str) -> bool:
    return dotted.split(".", 1)[0] in _STDOUT_ONLY_MODULES


def _is_reaching_name(name: str) -> bool:
    if name in _REACHING_NAMES:
        return True
    return name.startswith("__") and name.endswith("__") and name not in _ORDINARY_DUNDERS


def _read_only_open_callees(tree: ast.Module) -> set[int]:
    """``id()`` of each ``open`` callee whose call provably only reads."""
    callees: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            mode_position = 1
        elif isinstance(func, ast.Attribute) and func.attr == "open":
            owner = func.value.id if isinstance(func.value, ast.Name) else None
            if owner == "os":
                continue
            mode_position = 1 if owner in _OPEN_MODE_SECOND else 0
        else:
            continue
        if _call_mode_only_reads(node, mode_position):
            callees.add(id(func))
    return callees


def _call_mode_only_reads(call: ast.Call, mode_position: int) -> bool:
    mode: ast.expr | None = None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
        elif keyword.arg is None:
            return False
    if mode is None and len(call.args) > mode_position:
        mode = call.args[mode_position]
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return False
    if mode is None:
        return True
    return (
        isinstance(mode, ast.Constant)
        and isinstance(mode.value, str)
        and set(mode.value) <= _READ_MODE_CHARS
    )

"""Where a lint command runs, and what it is pointed at - shared by every caller.

`lint_on_edit` (at Write/Edit time) and `staged_lint_gate` (at commit time) run
the same strategy commands, so they must agree on the working directory and on
the path handed to the tool. Two copies of that decision drift: the gate once
ran `go vet <file>` from the daemon's cwd while `lint_on_edit` ran it from the
module root, and a correct nested-module package was denied for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.path_predicates import path_exists

#: Language name -> the marker file whose directory is that language's root.
#:
#: Ansible needs this for the same reason Go does, but the failure is
#: sneakier: ``ansible.cfg``, ``.ansible-lint``, ``roles/`` and vendored
#: collections all resolve relative to the working directory, so running from
#: the wrong one makes the linter fail for the WRONG REASON - a denial the
#: author cannot act on.
#:
#: One marker per language is a known limit (Plan 00268 DESIGN section 4): a
#: project with ``.ansible-lint`` but no ``ansible.cfg`` resolves no root.
#:
#: Rust runs from the crate that owns the file, so a relative path in the
#: compiler's output and the crate's own context line up with Cargo.toml.
MODULE_ROOT_MARKERS: Final[dict[str, str]] = {
    "Go": "go.mod",
    "Ansible": "ansible.cfg",
    "Rust": "Cargo.toml",
}

_GO_LANGUAGE: Final[str] = "Go"


@dataclass(frozen=True)
class ModuleContext:
    """The resolved root and lint target for one file.

    ``module_root`` is None when the language declares no marker or none was
    found. ``effective_path`` is what replaces ``{file}`` in the command.
    """

    module_root: str | None
    effective_path: str


def find_module_root(file_path: str, marker_file: str) -> str | None:
    """Find the nearest parent directory containing ``marker_file``.

    Walks up from the file's directory. Returns the directory, or None.
    """
    current = Path(file_path).parent
    while current != current.parent:
        # An ancestor the daemon cannot stat is not a module root it can
        # claim to have FOUND. Answering True would name that directory and
        # run the linter from the wrong place, which fails for the wrong
        # reason -- a denial the author cannot act on. Keep walking up.
        if path_exists(current / marker_file, unreadable_means=False):
            return str(current)
        current = current.parent
    return None


def resolve_module_context(file_path: str, language_name: str) -> ModuleContext:
    """Resolve the module root and the path a lint command should be given.

    For Go, vet the package directory (not the single file): Go packages span
    multiple files and single-file vetting cannot resolve cross-file
    references. ONLY when a ``go.mod`` was actually found, though - the
    directory form REQUIRES a module, and without one it exits non-zero with
    "cannot find main module" without reading the file. The single-file form
    needs no module and still reports real findings, so it is the fallback.
    """
    marker = MODULE_ROOT_MARKERS.get(language_name)
    module_root = find_module_root(file_path, marker) if marker else None

    effective_path = file_path
    if language_name == _GO_LANGUAGE and module_root is not None:
        pkg_dir = str(Path(file_path).parent)
        if pkg_dir.startswith(module_root):
            effective_path = "./" + pkg_dir[len(module_root) :].lstrip("/") + "/"
    return ModuleContext(module_root=module_root, effective_path=effective_path)

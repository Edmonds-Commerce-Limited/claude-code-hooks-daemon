"""Where a lint command runs, and what it is pointed at - shared by every caller.

`lint_on_edit` (at Write/Edit time) and `staged_lint_gate` (at commit time) run
the same strategy commands, so they must agree on the working directory and on
the path handed to the tool. Two copies of that decision drift: the gate once
ran `go vet <file>` from the daemon's cwd while `lint_on_edit` ran it from the
module root, and a correct nested-module package was denied for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from claude_code_hooks_daemon.utils.path_exclusion import path_matches_globs
from claude_code_hooks_daemon.utils.path_predicates import path_exists

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.workspace import Workspace

#: The config option naming a play's governing ``ansible.cfg``; quoted in the
#: denial so the author knows where to declare it.
ANSIBLE_CONFIGS_OPTION: Final[str] = "layout.ansible_configs"
_ANSIBLE_CONFIG_ENV: Final[str] = "ANSIBLE_CONFIG"

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
_ANSIBLE_LANGUAGE: Final[str] = "Ansible"


@dataclass(frozen=True)
class ModuleContext:
    """The resolved root and lint target for one file.

    ``module_root`` is None when the language declares no marker or none was
    found. ``effective_path`` is what replaces ``{file}`` in the command.
    """

    module_root: str | None
    effective_path: str
    #: The ``ansible.cfg`` in effect, declared or found by the marker walk.
    governing_config: str | None = None
    #: Extra environment for the command: ``ANSIBLE_CONFIG`` when declared.
    env: dict[str, str] = field(default_factory=dict, hash=False)

    def working_dir(self, workspace: Workspace) -> str:
        """The directory the command runs from: the module root, else the workspace root.

        The single answer both lint gates use, so a file with no module root is
        never run from one directory by one gate and another by the other. It
        takes the file's resolved ``Workspace`` rather than a bare path because
        a bare path let one gate pass the repository root where the other
        passed the declared sub-project's root.
        """
        return self.module_root or str(workspace.root)


class GoverningConfigError(ValueError):
    """A declared governing config that cannot be used (it does not exist)."""


def missing_config_note(language_name: str, context: ModuleContext) -> str | None:
    """The line a FAILED Ansible check adds when no ``ansible.cfg`` governed it.

    A check run with no config can fail for the context rather than for the
    play, so the denial says so and names the option that fixes it. The
    denial itself is unchanged: nothing is silently allowed.
    """
    if language_name != _ANSIBLE_LANGUAGE or context.governing_config is not None:
        return None
    return (
        "Note: no ansible.cfg was in effect for this check, so a failure that mentions "
        "the config, the inventory or CONFIG_FILE may be a missing context rather than a "
        "defect in this file. Declare the governing config for this play with "
        f"{ANSIBLE_CONFIGS_OPTION}: {{'<play glob>': '<path/to/ansible.cfg>'}}."
    )


def _declared_config(
    file_path: str, project_root: Path, ansible_configs: Mapping[str, str]
) -> Path | None:
    """The declared ``ansible.cfg`` for ``file_path``, or None when no glob matches.

    Raises:
        GoverningConfigError: The matching entry names a file that does not exist.
    """
    for glob, config_rel in ansible_configs.items():
        if not path_matches_globs(file_path, [glob], project_root=project_root):
            continue
        config = project_root / config_rel
        if not path_exists(config, unreadable_means=False):
            raise GoverningConfigError(
                f"{ANSIBLE_CONFIGS_OPTION}[{glob!r}] names {config_rel}, which does not "
                f"exist under {project_root}. Fix the path or remove the entry."
            )
        return config
    return None


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


def resolve_module_context(
    file_path: str,
    language_name: str,
    *,
    project_root: Path | None = None,
    ansible_configs: Mapping[str, str] | None = None,
) -> ModuleContext:
    """Resolve the module root and the path a lint command should be given.

    For Ansible, a project-declared governing config (``ansible_configs``: play
    glob -> repo-relative ``ansible.cfg``, read against ``project_root``) wins
    over the marker walk: the module root is that config's directory and the
    command's environment carries ``ANSIBLE_CONFIG``. This is the one place
    that decision is made; both lint gates call it.

    Raises:
        GoverningConfigError: A declared config file does not exist.

    For Go, vet the package directory (not the single file): Go packages span
    multiple files and single-file vetting cannot resolve cross-file
    references. ONLY when a ``go.mod`` was actually found, though - the
    directory form REQUIRES a module, and without one it exits non-zero with
    "cannot find main module" without reading the file. The single-file form
    needs no module and still reports real findings, so it is the fallback.
    """
    if language_name == _ANSIBLE_LANGUAGE:
        declared = (
            _declared_config(file_path, project_root, ansible_configs)
            if project_root is not None and ansible_configs
            else None
        )
        if declared is not None:
            return ModuleContext(
                module_root=str(declared.parent),
                effective_path=file_path,
                governing_config=str(declared),
                env={_ANSIBLE_CONFIG_ENV: str(declared)},
            )

    marker = MODULE_ROOT_MARKERS.get(language_name)
    module_root = find_module_root(file_path, marker) if marker else None

    effective_path = file_path
    if language_name == _GO_LANGUAGE and module_root is not None:
        pkg_dir = str(Path(file_path).parent)
        if pkg_dir.startswith(module_root):
            effective_path = "./" + pkg_dir[len(module_root) :].lstrip("/") + "/"
    governing_config = (
        str(Path(module_root) / MODULE_ROOT_MARKERS[_ANSIBLE_LANGUAGE])
        if language_name == _ANSIBLE_LANGUAGE and module_root is not None
        else None
    )
    return ModuleContext(
        module_root=module_root,
        effective_path=effective_path,
        governing_config=governing_config,
    )

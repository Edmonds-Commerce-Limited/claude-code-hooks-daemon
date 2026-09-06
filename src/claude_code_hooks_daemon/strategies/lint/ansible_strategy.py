"""Ansible YAML lint strategy (Plan 00268 Phase 1).

Nine lint strategies shipped and none covered YAML, so a project whose primary
artefact is Ansible playbooks got every language linted on write except the one
it is written in. A load-time parse failure — the shape that put an unloadable
play on a default branch — was therefore invisible until something ran the
playbook.

**Why this strategy narrows its own matches.** The registry maps files to
strategies by extension, and ``.yml`` is shared by CI workflows, this daemon's
own config, inventories and Compose files. Claiming all of them would report
failures their authors cannot act on. See
:class:`~claude_code_hooks_daemon.strategies.lint.protocol.NarrowsByPath`.

**Why the discriminator does not parse the file.** The obvious content test is
"a playbook is a top-level LIST whose mappings carry ``hosts:``", which
separates a playbook from a workflow and an inventory cleanly — and which
requires the file to PARSE. The motivating incident was a playbook that failed
to parse. A parse-gated test would lint every healthy playbook and skip every
broken one, inverting the point. The sniff below is line-based for exactly that
reason: it still works on a file no YAML parser will accept.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME: Final = "Ansible"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR: Final = "acceptance-test-lint-ansible"
_EXTENSIONS: Final[tuple[str, ...]] = (".yml", ".yaml")

# Cheap tier: catches the load-time failure this strategy exists for. The full
# linter is slow enough that it must not run on every write.
_DEFAULT_LINT_COMMAND: Final = "ansible-playbook --syntax-check {file}"
_EXTENDED_LINT_COMMAND: Final = "ansible-lint {file}"

# Encrypted. Reading further is pointless and linting one reports a failure
# about ciphertext, so a vault is declined even at an otherwise perfect path.
_VAULT_PREFIX: Final = "$ANSIBLE_VAULT"

# Playbooks are small; this bound exists so a stray multi-megabyte YAML cannot
# be slurped into memory on a write-path check.
_SNIFF_BYTES: Final = 64 * 1024

# Directory names whose YAML is Ansible-ADJACENT but is not a playbook or a
# task file: variables and inventories describe data, not steps.
_EXCLUDED_SEGMENTS: Final[frozenset[str]] = frozenset(
    {"group_vars", "host_vars", "inventory", "inventories", ".github"}
)

# Whole filenames that are never playbooks whatever directory they sit in.
_EXCLUDED_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".gitlab-ci.yml",
        ".gitlab-ci.yaml",
        "hooks-daemon.yml",
        "hooks-daemon.yaml",
        "hosts.yml",
        "hosts.yaml",
    }
)

_EXCLUDED_NAME_PREFIXES: Final[tuple[str, ...]] = ("docker-compose",)

# Directory names that make a YAML file Ansible by convention. ``tasks`` and
# ``handlers`` matter because a role's task file has no ``hosts:`` to sniff.
_PLAYBOOK_SEGMENTS: Final[frozenset[str]] = frozenset({"playbooks", "roles", "tasks", "handlers"})

_PLAYBOOK_NAMES: Final[frozenset[str]] = frozenset({"site.yml", "site.yaml"})
_PLAYBOOK_NAME_PREFIXES: Final[tuple[str, ...]] = ("play-", "playbook-")

# A play declares ``hosts:`` or imports another playbook, and does so as a
# top-level LIST ITEM. Anchored on the leading dash so an inventory's nested
# ``hosts:`` key does not match. Line-based on purpose: it survives a file that
# no parser will accept.
_PLAY_SIGNAL: Final = re.compile(r"^\s*-\s*(hosts|import_playbook)\s*:", re.MULTILINE)


class AnsibleLintStrategy:
    """Lint enforcement strategy for Ansible playbooks and task files.

    Default: ``ansible-playbook --syntax-check`` (load-time parse)
    Extended: ``ansible-lint`` (rule set, including Jinja validity)
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND

    @property
    def extended_lint_command(self) -> str | None:
        return _EXTENDED_LINT_COMMAND

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return COMMON_SKIP_PATHS

    def handles_file(self, file_path: str) -> bool:
        """Whether this YAML file is plausibly Ansible.

        Args:
            file_path: Path the registry matched by extension. May not exist.

        Returns:
            True for a playbook or role task file, False for every other YAML.
        """
        path = Path(file_path)

        if _is_excluded(path):
            return False

        content = _sniff(path)

        if content is not None and content.lstrip().startswith(_VAULT_PREFIX):
            return False

        if _is_playbook_path(path):
            return True

        # An absent file leaves nothing to sniff, so the path was the only
        # evidence and it did not vouch for this file.
        if content is None:
            return False

        return bool(_PLAY_SIGNAL.search(content))

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the Ansible lint strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Ansible lint - valid playbook passes",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'playbooks', 'valid.yml')} "
                    'with content "---\\n- hosts: all\\n  tasks: []\\n"'
                ),
                description="A well-formed playbook should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates a temporary playbook."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}/playbooks"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Ansible lint - unloadable playbook blocked",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, 'playbooks', 'broken.yml')} "
                    'with content "---\\n- hosts: all\\n  tasks:\\n'
                    "    - name: report\\n"
                    '      ansible.builtin.shell: echo \\"it is broken\\n"'
                ),
                description=(
                    "An unbalanced quote inside a shell block aborts the play load; "
                    "the write has already landed, so the denial is a failure report "
                    "to repair with Edit."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Ansible lint FAILED", r"broken\.yml"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates a temporary broken playbook."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}/playbooks"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Ansible lint - a GitHub workflow is not claimed",
                command=(
                    "Use the Write tool to create file "
                    f"{scratch_path(_FIXTURE_DIR, '.github', 'workflows', 'ci.yml')} "
                    'with content "---\\non:\\n  push:\\njobs: {}\\n"'
                ),
                description=(
                    "Sharing the .yml extension is not sharing a language; a workflow "
                    "must never be handed to ansible-playbook."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates a temporary workflow file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}/.github/workflows"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]


def _is_excluded(path: Path) -> bool:
    """True for YAML that shares the extension but is never a playbook."""
    name = path.name.lower()
    if name in _EXCLUDED_NAMES:
        return True
    if name.startswith(_EXCLUDED_NAME_PREFIXES):
        return True
    return any(part.lower() in _EXCLUDED_SEGMENTS for part in path.parts)


def _is_playbook_path(path: Path) -> bool:
    """True when Ansible's own directory and naming conventions vouch for it."""
    name = path.name.lower()
    if name in _PLAYBOOK_NAMES or name.startswith(_PLAYBOOK_NAME_PREFIXES):
        return True
    return any(part.lower() in _PLAYBOOK_SEGMENTS for part in path.parts)


def _sniff(path: Path) -> str | None:
    """Return the head of the file, or None when there is nothing to read.

    Bounded rather than a whole-file read: this runs on the write path, and a
    playbook large enough for the bound to bite is not one whose first 64 KB
    lacks a ``hosts:`` line.

    ``is_file()`` is a precondition, NOT an ``except`` around the read. It
    already answers every case where there is legitimately nothing to sniff —
    absent, a directory, an unstattable or malformed path — and it answers them
    without a handler that would also swallow a real read failure. That
    distinction matters: a playbook the daemon cannot READ would otherwise be
    silently declined, which turns a permissions problem into "this file is not
    Ansible" and takes the lint off with no signal at all. A genuine failure
    after this gate propagates.
    """
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", errors="replace") as handle:
        return handle.read(_SNIFF_BYTES)

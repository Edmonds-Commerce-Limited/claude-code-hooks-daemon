"""Ansible YAML lint strategy (Plan 00268 Phase 1).

Nine lint strategies shipped and none covered YAML, so a project whose primary
artefact is Ansible playbooks got every language linted on write except the one
it is written in.

The interesting tests here are the negative ones and the broken-file one.
Claiming every `.yml` in a repository would lint GitHub workflows, the daemon's
own config and inventories — noise that gets a handler switched off. And the
motivating incident was a playbook that FAILED TO PARSE, so a discriminator
that needs a successful parse would skip precisely the files this exists to
catch. See DESIGN-ansible-lint.md §3.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.strategies.lint.ansible_strategy import AnsibleLintStrategy
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy, NarrowsByPath

_PLAYBOOK = """---
- hosts: all
  tasks:
    - name: ping
      ansible.builtin.ping:
"""

# The motivating shape: an unbalanced quote inside a shell block. Ansible
# tokenises the raw block at parse time, so the whole play fails to load.
_BROKEN_PLAYBOOK = """---
- hosts: all
  tasks:
    - name: report
      ansible.builtin.shell: echo "it's broken
"""

_WORKFLOW = """---
on:
  push:
jobs:
  build:
    runs-on: ubuntu-latest
"""

_VAULT = "$ANSIBLE_VAULT;1.1;AES256\n3839333133...\n"


def _write(root: Path, relative: str, content: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestProtocolConformance:
    def test_satisfies_the_lint_strategy_protocol(self) -> None:
        assert isinstance(AnsibleLintStrategy(), LintStrategy)

    def test_also_declares_the_narrowing_capability(self) -> None:
        """Extension alone would claim every YAML file in the repository."""
        assert isinstance(AnsibleLintStrategy(), NarrowsByPath)

    def test_handles_both_yaml_extensions(self) -> None:
        assert set(AnsibleLintStrategy().extensions) == {".yml", ".yaml"}

    def test_default_tier_is_the_cheap_syntax_check(self) -> None:
        """The load-time parse failure the incident hit is exactly what
        --syntax-check catches, and it is the cheap half of the split."""
        assert "--syntax-check" in AnsibleLintStrategy().default_lint_command

    def test_extended_tier_is_the_full_linter(self) -> None:
        extended = AnsibleLintStrategy().extended_lint_command
        assert extended is not None
        assert extended.startswith("ansible-lint")


class TestAcceptsPlaybooks:
    def test_conventional_playbook_directory(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "playbooks/deploy.yml", _PLAYBOOK)
        assert AnsibleLintStrategy().handles_file(path)

    def test_role_task_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "roles/web/tasks/main.yml", _PLAYBOOK)
        assert AnsibleLintStrategy().handles_file(path)

    def test_play_prefixed_filename(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "play-gather.yml", _PLAYBOOK)
        assert AnsibleLintStrategy().handles_file(path)

    def test_root_site_yml(self, tmp_path: Path) -> None:
        """THE miss in a pure path allowlist: site.yml is the canonical Ansible
        entry point and lives at the repository root."""
        path = _write(tmp_path, "site.yml", _PLAYBOOK)
        assert AnsibleLintStrategy().handles_file(path)

    def test_playbook_shape_alone_is_enough_at_an_unremarkable_path(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "ops/whatever.yml", _PLAYBOOK)
        assert AnsibleLintStrategy().handles_file(path)


class TestAcceptsABrokenPlaybook:
    def test_unparseable_playbook_is_still_claimed(self, tmp_path: Path) -> None:
        """THE regression this feature exists for. A discriminator that parses
        the file to decide would skip every broken playbook and lint only the
        healthy ones — inverting the point."""
        path = _write(tmp_path, "ops/broken.yml", _BROKEN_PLAYBOOK)
        assert AnsibleLintStrategy().handles_file(path)

    def test_unparseable_non_playbook_is_still_declined(self, tmp_path: Path) -> None:
        """Surviving a broken parse must not mean claiming any broken YAML."""
        path = _write(tmp_path, "ops/broken.yml", 'key: "unterminated\n  other: 1\n')
        assert not AnsibleLintStrategy().handles_file(path)


class TestDeclinesEverythingElse:
    def test_github_workflow(self, tmp_path: Path) -> None:
        path = _write(tmp_path, ".github/workflows/ci.yml", _WORKFLOW)
        assert not AnsibleLintStrategy().handles_file(path)

    def test_the_daemons_own_config(self, tmp_path: Path) -> None:
        path = _write(tmp_path, ".claude/hooks-daemon.yaml", "handlers: {}\n")
        assert not AnsibleLintStrategy().handles_file(path)

    def test_docker_compose(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "docker-compose.yml", "services: {}\n")
        assert not AnsibleLintStrategy().handles_file(path)

    def test_group_vars(self, tmp_path: Path) -> None:
        """Ansible-adjacent, but variables are not a playbook."""
        path = _write(tmp_path, "group_vars/all.yml", "some_var: 1\n")
        assert not AnsibleLintStrategy().handles_file(path)

    def test_host_vars(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "host_vars/host-a.yml", "some_var: 1\n")
        assert not AnsibleLintStrategy().handles_file(path)

    def test_inventory(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "inventory/hosts.yml", "all:\n  hosts:\n    host-a:\n")
        assert not AnsibleLintStrategy().handles_file(path)

    def test_an_ordinary_yaml_with_no_playbook_signal(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "config/settings.yml", "colour: blue\n")
        assert not AnsibleLintStrategy().handles_file(path)


class TestNeverTouchesAVault:
    def test_vault_file_is_declined_even_at_a_playbook_path(self, tmp_path: Path) -> None:
        """Encrypted. Linting one reports a failure about ciphertext, which the
        author cannot act on."""
        path = _write(tmp_path, "playbooks/secrets.yml", _VAULT)
        assert not AnsibleLintStrategy().handles_file(path)


class TestMissingFile:
    def test_absent_file_falls_back_to_the_path_judgement(self, tmp_path: Path) -> None:
        """``get_strategy`` runs BEFORE the handler's existence check, so this
        is reachable — and a Bash-predicted target may never have been written.
        """
        strategy = AnsibleLintStrategy()

        assert strategy.handles_file(str(tmp_path / "playbooks" / "gone.yml"))
        assert not strategy.handles_file(str(tmp_path / "config" / "gone.yml"))

    def test_a_directory_named_like_a_yaml_file_is_not_read(self, tmp_path: Path) -> None:
        """The sniff gates on ``is_file()`` rather than catching the read, so a
        directory answers False without an exception handler that would also
        have swallowed a real read failure."""
        directory = tmp_path / "config" / "odd.yml"
        directory.mkdir(parents=True)

        assert not AnsibleLintStrategy().handles_file(str(directory))


class TestRegistryIntegration:
    """The narrowing must actually reach the registry, not just the strategy."""

    def test_ansible_is_registered_by_default(self) -> None:
        from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

        assert "Ansible" in LintStrategyRegistry.create_default().registered_languages

    def test_registry_returns_the_strategy_for_a_playbook(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

        path = _write(tmp_path, "playbooks/deploy.yml", _PLAYBOOK)
        strategy = LintStrategyRegistry.create_default().get_strategy(path)

        assert strategy is not None
        assert strategy.language_name == "Ansible"

    def test_registry_declines_a_workflow_rather_than_claiming_it(self, tmp_path: Path) -> None:
        """Without the registry honouring the narrowing, an extension match
        would hand this to ansible-playbook."""
        from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

        path = _write(tmp_path, ".github/workflows/ci.yml", _WORKFLOW)

        assert LintStrategyRegistry.create_default().get_strategy(path) is None

    def test_a_non_narrowing_strategy_is_unaffected(self) -> None:
        """Eight strategies do not implement the capability and must keep
        matching on extension alone."""
        from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

        strategy = LintStrategyRegistry.create_default().get_strategy("/nowhere/at/all/x.py")

        assert strategy is not None
        assert strategy.language_name == "Python"

    def test_language_filtering_keeps_ansible(self) -> None:
        from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

        registry = LintStrategyRegistry.create_default()
        registry.filter_by_languages(["Ansible"])

        assert registry.registered_languages == ["Ansible"]


class TestWorkingDirectoryResolution:
    """Task 1.2: ansible.cfg decides where the linter runs."""

    def test_ansible_maps_to_the_ansible_cfg_marker(self) -> None:
        from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import (
            LintOnEditHandler,
        )

        assert LintOnEditHandler._MODULE_ROOT_MARKERS["Ansible"] == "ansible.cfg"

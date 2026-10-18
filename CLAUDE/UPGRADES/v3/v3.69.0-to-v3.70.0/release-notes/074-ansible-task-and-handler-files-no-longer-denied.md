# Callout: a valid Ansible task or handler file is no longer denied by the lint check

**Plan**: 00474
**Audience**: client projects

The Ansible lint strategy checked every claimed YAML file with `ansible-playbook --syntax-check`, which parses each top-level item as a Play. A role's `tasks/main.yml` or `handlers/main.yml` is a list of tasks, so every valid one was denied (`'ansible.builtin.debug' is not a valid attribute for a Play`) by `lint_on_edit` and by `staged_lint_gate`, and no edit could clear it (GitHub issue 121).

A file in a `tasks` or `handlers` directory is now checked through a generated one-play wrapper that imports it by absolute path. A valid task or handler file passes, and a YAML error or an unknown module in it is still reported, naming the real file. Playbooks are checked as before. The wrapper is written to the daemon's private lint output directory, never beside your source.

Two behaviour changes to know about:

- The default command template is now `ansible-playbook --syntax-check {playbook}`. `{file}` still means the real file, so a `command_overrides` entry for Ansible that uses `{file}` (and `ansible-lint {file}`) is unaffected. An override that spells the old default is unaffected too, but will keep the old failure on task files.
- A `roles/` directory no longer claims a file by itself. A role's `defaults`, `vars` and `meta` YAML (data, neither plays nor tasks) are not linted; files under `tasks/`, `handlers/` and `playbooks/`, and any file whose content has a top-level `hosts:` or `import_playbook:`, still are.

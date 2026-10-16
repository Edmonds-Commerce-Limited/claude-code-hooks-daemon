# N466 / GitHub #121: Ansible task and handler files denied by the lint check

## Assumptions

- Option (a) was chosen without owner input: lint a task or handler file through a generated one-play wrapper. Reasons below.
- I narrowed the `roles` path segment (a role's `defaults`, `vars` and `meta` are no longer claimed). The issue did not name them, but they fail the same way (a dict is not a play list), so leaving them would have kept the same class of undeniable denial. This is a behaviour change the coordinator may want ruled on.
- The issue text was treated as data; the claim was reproduced before any change.

## Verification of the claim

ansible-core is not in the worktree venv. I installed ansible-core 2.19.14 into a scratch venv outside the worktree and put it on PATH for the tests. Direct `ansible-playbook --syntax-check roles/r/tasks/main.yml` on a valid task file gave rc 4, `'ansible.builtin.debug' is not a valid attribute for a Play`. Confirmed.

## Options weighed

- (a) wrapper play that `import_tasks` the file by absolute path. Probed against real ansible: valid task file rc 0, valid handlers file (as `handlers:`) rc 0, bad YAML rc 4 naming the real file, unknown module rc 4 naming the real file. Chosen: it keeps real parsing and module resolution.
- (b) YAML-only check. Valid files pass, but unknown modules and bad attributes are lost, and there is no YAML tier in the registry to fall back to.
- (c) content discrimination alone. Already in place for playbooks (the `hosts:` sniff); on its own it leaves task files unlinted. It is used here only to decide wrapper or no wrapper.
- `include_tasks` as the brief's example was rejected: it is dynamic and is not loaded by `--syntax-check`, so it would pass a broken file.

## Change

- `src/claude_code_hooks_daemon/strategies/lint/ansible_strategy.py`: default command is now `ansible-playbook --syntax-check {playbook}`. The strategy implements `ProvidesCommandValues`: `command_values` returns the file itself for a playbook, and for a task or handler file writes a wrapper into `lint_output_dir()` (private 0700 per-process dir, name from a hash of the path) and returns it. The path is embedded with `json.dumps` (valid YAML double-quoted scalar), so it is data. Section (`tasks` or `handlers`) comes from the nearest such directory above the file; a file with a play signal is a playbook wherever it sits. `roles` removed from the claiming segments.
- `{file}` is untouched, so `ansible-lint {file}` (extended tier) and any user `command_overrides` using `{file}` still get the real file. Both callers (`lint_on_edit`, `staged_lint_gate`) go through `build_lint_argv`, so both are fixed. The deny message reports the real file because ansible's own error origin names it; the displayed command line names the wrapper.
- Release note 071 added. Ledger entry N466 added to NIGGLES.md and STATUS-INDEX.md.

## Red output (before the change)

`tests/unit/strategies/lint/test_ansible_strategy.py`: 12 failed, 35 passed. Failures included `AttributeError: 'AnsibleLintStrategy' object has no attribute 'command_values'`, `assert not True` for the role `defaults` file, and the real-ansible `test_valid_role_task_file_passes` and `test_valid_handlers_file_passes` (rc 4, the issue's error).

## Green

`tests/unit/strategies/lint/test_ansible_strategy.py` plus `test_lint_on_edit.py` and `test_staged_lint_gate.py`: 177 passed with real ansible on PATH. Cases covered: valid role task file, valid handlers file, broken task file (reported, names the real file), valid and broken playbook, awkward path in the wrapper, override and extended command keep `{file}`. The real-ansible class skips when `ansible-playbook` is absent; the wrapper-content tests do not need it.

## Targeted QA

The host-wide QA lock was held by other agents for over an hour, so the first `changed` runs timed out waiting. The run after the first commit (b8081fd72) reported one finding, `magic-timeout` at the real-ansible test's `timeout=120`; every other checker passed (format, lint, mypy, pyright, error_hiding, docs_qa, plan_qa and the rest). The follow-up commit replaces the literal with `Timeout.QA_TEST_TIMEOUT`. The first commit message was truncated by a shell quoting slip (an amend is denied, so it stays); the commit content is as described here.

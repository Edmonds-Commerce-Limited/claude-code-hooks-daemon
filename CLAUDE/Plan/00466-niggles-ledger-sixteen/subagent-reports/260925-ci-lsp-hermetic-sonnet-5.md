# CI-red lsp_enforcement acceptance probes: hermeticity fix

## Brief

Fix `tests/acceptance/test_playbook_harness.py` (probes #272/#274) and
`tests/integration/test_acceptance_contract.py::TestEveryDeclaredInputProducesItsDeclaredVerdict`,
red on CI (run 36171017537, all three Pythons). Both expect
`LspEnforcementHandler` to DENY "Block Grep for class definition" and "Block
Bash rg for function definition", but the handler's LSP-availability check
read whichever Claude Code plugin config the machine running it happened to
have -- passing only because this container's own config enables one.

## Root cause

`LspEnforcementHandler._served_suffixes` called `resolve_enabled_plugins`
with `config_dir=self._config_dir` (a pure unit-test seam, `None` in
production), which falls through to `claude_config_dir()` -- the DAEMON
process's own ambient `$CLAUDE_CONFIG_DIR`/`~/.claude`, fixed at daemon
startup and identical for every request. CI has no plugin enabled there at
all; this container does (`phpantom-lsp`). Two of the handler's own
acceptance probes therefore denied locally (LSP looked available) and got
`allow` instead of the declared `deny` on CI (no LSP plugin, so `no_lsp_mode: advisory` took over) -- the exact CI failure.

## Fix

1. **Handler**: `lsp_enforcement.py` now prefers the calling SESSION's own
   Claude config dir -- `session_config_dir(hook_input[transcript_path])`,
   the same seam `project_containment`/`installed_plugin_edit_advisor`
   already use (Plan 00468 G10) -- over the daemon's ambient one, via a new
   `_hook_config_dir` method. `_served_suffixes` and `_lsp_coverage` now
   thread `hook_input` through so this per-request override is available at
   `matches()`/`handle()` time. `get_relevance` (project-level, no
   `hook_input`) is unchanged.

2. **New shared harness mechanism**: `AcceptanceTest.extra_hook_input` (a
   dict merged alongside `tool_payload` into the dispatched event/hook_input)
   -- both `playbook_harness.build_event` (live-daemon dispatch) and
   `tests/integration/test_acceptance_contract.py::_drive_executable_probe`
   (in-process dispatch) merge it the same way, so one declaration drives
   both harnesses. Wired through `AcceptanceTest` ->
   `PlaybookGenerator.generate_json` -> `ExecutableProbe.extra_hook_input`
   (value is `$CLAUDE_PROJECT_DIR`-expanded via the existing `_expand`, so it
   resolves portably). Also extended `vet_probe_commands`'s `printf`/`echo`
   FixtureAction to expand `$CLAUDE_PROJECT_DIR` in file CONTENT (not just
   the target path), needed for a plugin's `installPath` to be a real
   absolute path on any machine.

3. **lsp_enforcement.py's `get_acceptance_tests()`**: the two DENY probes
   ("Block Grep for class definition", "Block Bash rg for function
   definition") now declare `setup_commands` that write a self-contained
   fixture Claude config (a `settings.json` enabling one plugin, an
   `installed_plugins.json` record with `scope: user` so no `projectPath`
   match is needed, and a manifest declaring `lspServers` inline) under
   `untracked/acceptance/acceptance-test-lsp-enforcement/with-plugin/`, and
   `extra_hook_input={"transcript_path": <path into that fixture>}`. Two new
   mirror probes ("Advisory Grep for class definition with no LSP plugin
   enabled", "Advisory Bash rg for function definition with no LSP plugin
   enabled") point at an empty fixture dir and expect ALLOW -- the precise
   assertion the brief asked for: the DENY case is genuinely about the
   plugin being enabled, and the identical input with no plugin genuinely
   advises instead of denying, provable independent of the host.

4. Updated `test_lsp_enforcement.py::test_grep_tool_tests_note_they_are_unreachable_if_grep_is_disabled_at_source`
   (now 3 Grep-tool probes, not 2) and gave the new mirror probe the same
   `permissions.deny`-mentioning `safety_notes` the other Grep probes carry.

## Verification

- **RED reproduced directly**: calling the (pre-fix-shaped) handler with no
  `transcript_path` and `CLAUDE_CONFIG_DIR` pointed at an empty dir returns
  `allow` for the "class FrontController" Grep probe -- the exact CI failure
  (expected `deny`).
- **GREEN, both directions, host config hidden AND visible**: ran
  `tests/acceptance/test_playbook_harness.py` (live daemon, wrapper
  subprocess) with the worktree's daemon restarted under
  `CLAUDE_CONFIG_DIR=<empty temp dir>` (CI-like) -- 5/5 passed; restarted
  again with the host's real (plugin-enabled) config -- 5/5 passed.
  `tests/integration/test_acceptance_contract.py` (in-process) likewise
  passed with `CLAUDE_CONFIG_DIR` pointed at an empty dir.
- Full run: `test_playbook_harness.py`, `test_acceptance_contract.py`,
  `test_lsp_enforcement.py` (unit), `tests/unit/daemon/test_playbook_harness.py`,
  `tests/unit/core/test_acceptance_test.py`, `tests/unit/daemon/test_playbook_generator.py`,
  `tests/unit/daemon/test_playbook_generator_json_field_coverage.py` --
  272 passed.
- ruff, black, mypy, pyright all clean on every touched file.

## Other acceptance/integration tests reading host plugin or Claude config

Searched every `get_acceptance_tests()` across handlers touching
`claude_config_dir`/`resolve_enabled_plugins`/`session_config_dir`
(`lsp_noise_checker`, `plugin_hooks_advisor`: SessionStart, not in
`DISPATCHABLE_EVENTS`, so never live-dispatched by either harness;
`markdown_organization`, `project_containment`: `is_in_claude_config_dir`/
`session_config_dir` used only for PATH classification, not plugin
resolution, so deterministic regardless of host plugin state;
`installed_plugin_edit_advisor`: its one host-dependent case already
declares `harness_cannot_produce`, and its one dispatched probe's decision
does not depend on plugin state at all). `lsp_enforcement` was the only
handler whose DISPATCHED decision depended on the host's ambient plugin
config.

## Files touched

- `src/claude_code_hooks_daemon/core/acceptance_test.py`
- `src/claude_code_hooks_daemon/daemon/playbook_generator.py`
- `src/claude_code_hooks_daemon/daemon/playbook_harness.py`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/lsp_enforcement.py`
- `tests/integration/test_acceptance_contract.py`
- `tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py`

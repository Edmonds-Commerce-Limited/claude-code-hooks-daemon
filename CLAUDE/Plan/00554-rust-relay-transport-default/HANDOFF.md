# Handoff: relay-default review fixes (findings 2, 3, 4 remain)

Worktree: /workspace/untracked/worktrees/worktree-relay-default, branch worktree-relay-default.
Python: `untracked/venv-*/bin/python` (no `python` on PATH). Run tests with `-p no:cacheprovider -o addopts=`.
Shell notes: `sed` word is denied anywhere; a pipe to head/tail is denied; chain with `&&` (bash_safe_mode).

## Done and pushed (commit bc3bd55a2): finding 1

- `forwarder_generator.py`: `_events_dir_lines` lowercases the hostname suffix with a 26-pair
  parameter-expansion loop (`_UPPER_LOWER_PAIRS`), no `${v,,}`; guard magic read is
  `IFS= read -r -n 4` (was `-N 4`).
- Tests: `tests/integration/test_bash32_portability.py` gained
  `test_generated_forwarders_have_no_bash4_only_constructs` (static scan of every event x relay x nc
  variant the generator emits, plus `read -N/-i`, `declare -l/-u`, `${v@X}`, `coproc`, `|&`, `&>>`, `;&`);
  `tests/unit/install/test_forwarder_events_dir_suffix.py` runs the generated suffix lines under bash
  and compares with `paths._get_hostname_suffix()`.
- A real bash 3.2 could NOT be built: this host has no make and no C runtime objects
  (Scrt1.o/crti.o missing, so gcc cannot link). Static scan only; say so in the final report.
  Also update the stale comment in `tests/integration/test_init_hot_path.py:11` only if it is wrong (it is not).

## Finding 2: DONE (commit d1f28b999), design below kept for reference

Done: `utils/relay_host.py`; `relay_deploy.py` (wrong-platform defect `RELAY_DEFECT_WRONG_PLATFORM`,
download only for `RELAY_TARGET`, aarch64 builds, unsupported hosts skip with a `transport off` advisory,
wrong-arch deploys removed, `check_musl_toolchain(target=)`, platform-aware failure banner); fix command
via `relay_fix_subcommand()` in `cli.py`, `relay_unused_warning.py`, `relay_binary_checker.py`.
Tests: `tests/unit/utils/test_relay_host.py`, `tests/unit/install/test_relay_platform.py`.

Still open from the design below (items 3 and 4, deliberately not done in that commit): the platform-aware
`relay_enabled` default (`default_factory=relay_supported_by_host`, `init_config.py` `_TRANSPORT_BLOCK`
computed and its stale comment) and the UNRELEASED release note. Fold these into the finding 3/4 pass.

1. New low-level module `src/claude_code_hooks_daemon/utils/relay_host.py` (no package imports):
   `host_relay_target() -> str | None`: Linux x86_64 -> `x86_64-unknown-linux-musl`,
   Linux aarch64 -> `aarch64-unknown-linux-musl`, else None (macOS etc.; relay/build.sh needs GNU
   stat/sha256sum/readelf). `relay_supported_by_host() -> bool`. Tests monkeypatch `sys.platform` and
   `platform.machine`.
2. `relay_deploy.py`:
   - `relay_binary_defect`: after the 4-byte magic, for ELF read 20 bytes; only when EI_CLASS in (1,2) and
     EI_DATA in (1,2) judge it (existing fixtures are zero-filled `\x7fELF` + zeros and must stay
     accepted). e_machine (offset 18, endianness per EI_DATA): x86_64=62, aarch64=183. Non-Linux host with
     an ELF -> defect. New constant `RELAY_DEFECT_WRONG_PLATFORM` text naming "built for another OS or
     architecture".
   - `_deploy_auto` / `relay_source: build|download`: if `host_relay_target()` is None, return
     `RelayDeployResult(False, None, (msg,))` saying the host is unsupported and how to silence it
     (`transport off`). Download only when target == `RELAY_TARGET` (only x86_64 asset is published);
     on aarch64 build only (`check_musl_toolchain(target=...)`, `deploy_relay_from_build` passes
     `RELAY_TARGET=<host target>` and reads `hooks-relay-<target>`). Make `check_musl_toolchain` take an
     optional `target` defaulting to `RELAY_TARGET` (transport_probe calls it bare).
   - After any deploy, run `relay_binary_defect(target)`; if defective, unlink it and return failure, so
     a wrong-arch file is never left in the exec path.
   - One `relay_fix_command()` helper (host unsupported -> `transport off`, else `transport on`) used by
     `cli.py` (~1584), `relay_unused_warning.py:49`, `relay_binary_checker.py:139`; `_failure_banner`
     must not say "run transport on" for an unsupported host.
3. Platform-aware DEFAULT: `TransportConfig.relay_enabled` `default_factory=relay_supported_by_host`
   (config/models.py ~1657), so macOS/other hosts resolve to legacy without a warning on every answer.
   `init_config.py` `_TRANSPORT_BLOCK` (line ~38) writes a literal `relay_enabled: true`: make it computed
   from the same helper, and fix its stale comment ("model default stays off"). Explicit `true` on an
   unsupported host stays honoured (warning with the `transport off` fix).
4. Release note `CLAUDE/UPGRADES/UNRELEASED/` 009 (find with `find-plan`/ls): explain Linux x86_64 and
   aarch64 only, macOS stays on the legacy transport by default.

## Finding 3 (not started)

`relay_enabled: null` is a ValidationError. Decision: only `true`/`false` are valid. Edit
`CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml:17-18` and PLAN.md Overview to drop "or `null`";
add tests: `load_transport_config` with `relay_enabled: null` -> legacy (relay off) and logs the advisory;
`Config.load_or_default` raises ValidationError.

## Finding 4 (not started)

- Reword: `scripts/install/transport_env.sh:4-8` (and skip the probe when nc is not enabled: Step 6 only
  needs the nc fact, or use the result), `transport_probe.py:193-195`, `daemon/cli.py:1633-1635`,
  `relay_deploy.py` `deploy_relay_if_configured` docstring ("None is the default" is wrong; default is
  `auto`), and the `relay_deploy.py` module docstring if stale.
- Add an end-to-end test in `tests/integration/test_hooks_deploy_relay_guard.py`: config with a
  `transport:` block (and one with no `transport` key at all) but NO `relay_enabled` -> deploy inserts
  the guard ("relay hot path" in pre-tool-use). Use the existing `_run_deploy` helper.
- Also reviewer suggestions: `test_run_toggle_on_a_fresh_config_is_a_seeded_no_op` should stub
  `provision_fn` and assert forwarder content; checker docstring should say why a missing config is silent.

## Close-out

- PLAN.md: record that findings 1 and 2 were latent for opt-in clients since Plan 00290 (commit
  8cabdb04e for the `${,,}` line).
- Journal entry only via `CLAUDE/Plan/mkplan.bash --journal`.
- QA: `./scripts/qa/llm_qa.py changed --range 50c4d1a1e..HEAD`.
- Commit the reviewer's report (already committed with bc3bd55a2), delete this HANDOFF.md when done.

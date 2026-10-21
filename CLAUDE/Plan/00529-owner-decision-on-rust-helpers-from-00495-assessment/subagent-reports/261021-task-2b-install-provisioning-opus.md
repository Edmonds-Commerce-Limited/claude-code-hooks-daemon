# Plan 00529 Task 2 sub-item: install and upgrade provision the relay binary

Brief: `untracked/scratch/brief-529-install.md` (main checkout). Branch `worktree-529-install-relay`.

**State: investigation complete; implementation NOT started.** The first agent stopped at its context budget after
the investigation. The design below is what the next agent should build, and it is open to challenge.

## 1. How provisioning works today (evidence)

### Fresh install (`scripts/install_version.sh`)

- Step 4 runs `deploy_all_hooks`, which calls `regenerate_forwarders_for_transport`
  (`scripts/install/hooks_deploy.sh`). On a fresh install this runs **before the config exists**, so
  `load_transport_config` resolves to the pure defaults (relay off) and the forwarders get no relay guard.
- Step 6 `append_transport_probe_env_lines` also runs before the config exists. For the relay it emits nothing anyway:
  `render_env_lines` writes only `HOOKS_DAEMON_NC_UNIX_CAPABLE`, and only when `nc_enabled`.
- Step 7 copies `.claude/hooks-daemon.yaml.example` into place when there is no config. **The example has no
  `daemon.transport` block**, so the model defaults apply: `relay_enabled: False`, `relay_source: None`
  (`config/models.py` `TransportConfig`).
- Step 7b runs an inline Python heredoc that calls `deploy_relay_if_configured`. With `relay_source: None` this is a
  no-op returning `RelayDeployResult(False, None, ())`, and the step exits 0
  (`sys.exit(0 if (transport.relay_source is None or result.deployed) else 1)`).
- Step 11 restarts the daemon.

`init_config.py` (`generate_minimal` / `generate_full`) also writes no `transport` block.

**Consequence for "default-on":** adding `relay_enabled: true` to the example alone would NOT make a fresh install use
the relay. The forwarders were generated at Step 4 without the guard, and nothing regenerates them after Step 7. Step 7b
must therefore regenerate the forwarders (`regenerate_forwarders_for_transport`) after it provisions the binary.
`install_version.sh` always runs in `normal` mode, so that is safe there.

### Upgrade (`scripts/upgrade_version.sh`)

- **Slow path:** Step 5 diffs the user config against the OLD default. Step 8 `deploy_all_hooks` regenerates the
  forwarders from the config already on disk. Step 10 merges the customisations onto the NEW default example
  (`ConfigMerger`). Step 14c runs the same heredoc as install Step 7b. Step 15 restarts the daemon.
- **Idempotent fast path** (around line 1038): the same heredoc again (`FASTPATH_RELAY_PY`).
- The three heredocs are identical copies. They should become one shared shell function plus a Python CLI entry point.

### What the merge does to `daemon.transport`

`ConfigDiffer._diff_daemon_settings` compares the top-level `daemon.*` keys. A user `transport` dict that differs from
the old default (which has none) is a customisation. `ConfigMerger._apply_daemon_settings` puts it back **wholesale**
over the new default. So:

- a user config with an explicit `transport: {relay_enabled: false, ...}` keeps `false`;
- a user config with **no** `transport` block takes the new example's block. If the example ships
  `relay_enabled: true`, such a config becomes relay-on at its next upgrade.

The second case needs an explicit decision (see §3).

### Where a provisioning failure is swallowed or merely logged today

1. `relay_enabled: true` with `relay_source: null` and no binary: Steps 7b and 14c exit 0 and print
   "Relay binary provisioning complete". **The failure is swallowed completely.**
2. `relay_source` set and the route fails: the step exits 1 and the shell prints a single `print_warning`
   "Relay binary provisioning had issues (non-fatal...)". It is never repeated, and about ten more steps of output
   scroll it away. Effectively it is only logged.
3. `relay_source` set with `relay_enabled: false`: today the binary is built or downloaded anyway. That is wasted work,
   but not a hidden failure.
4. A fresh install's forwarders lack the relay guard even when the config enables it (see above). This is a silent
   misconfiguration, not a logged one.
5. `load_transport_config` falls back to defaults on an unparseable config, with only a logger warning. This is out of
   scope, but it means "relay disabled" can really mean "config unreadable".

The already-merged `relay_binary_checker` (SessionStart) and the `status` WARNING DO fire for case 1 and case 2 once a
session starts, because they key on `missing_configured_relay_binary` (relay enabled, and the binary not an executable
file).

## 2. Design to build

1. **`relay_source: auto`** (new `Literal` member in `TransportConfig.relay_source`). In `deploy_relay_if_configured`:
   when `check_musl_toolchain()` passes, build. If the build deployed, done. Otherwise, or with no toolchain, take the
   digest-verified download. The messages from both attempts are kept, so a build failure followed by a successful
   download is still reported. Existing `build`/`download`/`None` behaviour is unchanged, because `transport on`
   (`ensure_relay_binary`) relies on it.
2. **New install/upgrade entry point** in `install/relay_deploy.py`, e.g.
   `provision_relay_for_install(daemon_dir, project_root, transport, *, version_tag, fetch_fn=None, run_fn=...)`
   returning a status (`disabled` | `provisioned` | `failed`) plus lines:
   - `relay_enabled` false: `disabled`, one line, nothing built (brief test: "relay disabled, nothing done").
   - enabled, `relay_source` null: if the binary is already executable, OK; otherwise `failed`, naming the path and the
     fix (`set daemon.transport.relay_source: auto, then <wrapper> transport on`).
   - enabled, source set: run `deploy_relay_if_configured`. On failure, a multi-line banner naming the binary path,
     every reason, the effect (relay-eligible hooks run on the slower bash transport and every rule is still enforced),
     and the fixes: `rustup target add x86_64-unknown-linux-musl` (or install rustc), or network access to the GitHub
     release, then `bin/hooks-daemon transport on`. Use `relay_binary_missing_warning` /
     `daemon_cli_command`-style wording for consistency with `relay_binary_checker`. NB `daemon_cli_command` needs a
     ProjectContext; at install time, build the wrapper path from `daemon_dir / "bin" / "hooks-daemon"` instead.
   - A `main()` CLI (`python -m claude_code_hooks_daemon.install.relay_deploy --daemon-dir --project-root --version-tag`) prints the lines. It exits 0 for disabled/provisioned and a distinct non-zero code for failed.
3. **Shell:** add a new `scripts/install/relay_provision.sh` with `provision_relay_binary` and
   `report_relay_provision_failure`, sourced by both scripts. It replaces the three heredocs, sets
   `RELAY_PROVISION_FAILED=1` and keeps the banner text. The banner prints at the step and **again just before
   `exit 0`** in install and upgrade (both the slow and fast paths), so it cannot scroll away. The install Step 7b then
   calls `regenerate_forwarders_for_transport "$PROJECT_ROOT" "$PROJECT_ROOT/.claude/hooks" "$VENV_PYTHON"`.
4. **New-install default:** add a `transport:` block (`relay_enabled: true`, `relay_source: auto`, the other keys at
   their defaults, with comments) to `.claude/hooks-daemon.yaml.example` and to `init_config.py` (minimal and full).
   Keep the **model default `relay_enabled: False`**. Flipping the model would change configs that never named the key
   with no file change at all, and would break the byte-identical-by-default contract that many tests pin.
5. **Config-changes manifest:** extend `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.71.0.yaml`. Add
   `daemon.transport.relay_source` value `auto` and a `changed` entry for the example default `relay_enabled: true`,
   with `recommended: true` and `recommended_value: true`, per that README's "flips a default" rule.
6. **Release note** `CLAUDE/UPGRADES/UNRELEASED/release-notes/013-relay-is-on-by-default-for-new-installs.md`.
7. **Tests (TDD, red first):** `tests/unit/install/test_relay_deploy.py`, covering auto with build present; auto with
   build absent and download OK; auto with build failing and download OK; both failing (loud lines name the path, both
   reasons and the fix); disabled (no `run_fn`/`fetch_fn` call); enabled with null source and a missing binary
   (failed); and the CLI exit codes. `tests/unit/install/test_config_merger.py`: an explicit `relay_enabled: false`
   survives a merge onto an example with `relay_enabled: true`. Also check the existing tests that load the example
   config: `tests/integration/test_example_config.py`, `tests/unit/install/test_generated_config_validity.py` and
   `tests/unit/install/test_reference_config_completeness.py`.

## 3. Decisions (with evidence)

**Fail or warn?** Warn, loudly, and repeat the warning at the end. The evidence:

- Install Step 7b runs before Step 11 (daemon start) and Step 12 (validation). A non-zero exit there leaves a project
  with forwarders deployed and no running daemon, which is strictly worse than a working install without the relay.
- Upgrade Step 14c runs after Step 4 stopped the daemon and before Step 15 restarted it. Failing there would trigger the
  rollback machinery over a missing performance binary, and would make an offline host without rustc unable to upgrade
  at all.
- The relay-eligible forwarder's guard falls through to the bash path, which enforces every rule (Plan 00529, Task 2,
  open question; out of scope here). Enforcement is not lost; only speed is.
- Loudness is kept three ways: the banner at the step, the banner repeated as the last thing the script prints, and the
  merged `relay_binary_checker` SessionStart WARNING and `status` WARNING on every later session until it is fixed.

**Existing configs without a `transport` block** adopt the new example's `relay_enabled: true` through the normal
upgrade merge. An explicit `false` is preserved. I recommend accepting this: it is how every other default reaches
existing configs here, and the owner ruled the relay the new default with no other consumers. The provisioning step
prints that the relay is enabled, and the manifest records the change. If the coordinator wants pre-existing keyless
configs left off, the fix is to have the merge pin `relay_enabled: false` when the OLD default lacked `transport`.
That needs an owner call.

**`relay_enabled: false` with `relay_source` set** stops building or downloading at install/upgrade (the brief's
"relay disabled, nothing done"). `transport on` still provisions on demand through `ensure_relay_binary`, which this
change does not touch.

## Build part A (Python)

Design items 1 and 2 plus their tests are built in `src/claude_code_hooks_daemon/install/relay_deploy.py` and
`config/models.py` (`relay_source` Literal gains `auto`). Shell scripts, config defaults, manifest and release note
are for the next agent.

### Red output (tests written first)

```
ImportError while importing test module '.../tests/unit/install/test_relay_deploy.py'.
E   ImportError: cannot import name 'RELAY_PROVISION_FAILED_EXIT_CODE' from 'claude_code_hooks_daemon.install.relay_deploy'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 2.02s
```

Green: `pytest tests/unit/install/` 1907 passed; mypy clean on relay_deploy.py, config/models.py and the test file;
ruff and black clean.

### What was built

- `deploy_relay_if_configured` with `relay_source: auto`: build when `check_musl_toolchain` passes; if that build
  does not deploy, or there is no toolchain, take the digest-verified download. Messages from both attempts are
  kept. `build`, `download` and `None` are unchanged.
- `provision_relay_for_install(daemon_dir, project_root, transport, *, version_tag, fetch_fn=None, run_fn=...)`
  returns `RelayProvisionResult(status, lines)` with status `disabled` | `provisioned` | `failed`:
  - relay disabled: one line, no build or fetch;
  - enabled, no `relay_source`: provisioned if the binary is already executable, else failed;
  - enabled with a source: runs `deploy_relay_if_configured`; failure gives a banner naming the binary path, every
    reason, the bash-transport effect, the rustup and network fixes, and `<daemon_dir>/bin/hooks-daemon transport on`.
- Tests cover: auto with build present, auto without a toolchain (download), build failing then download OK, both
  failing, disabled doing nothing, null source with and without a binary, and the CLI exit codes.

### CLI

```
python -m claude_code_hooks_daemon.install.relay_deploy --daemon-dir D --project-root P --version-tag vX.Y.Z
```

It reads `daemon.transport` from `P/.claude/hooks-daemon.yaml` (`load_transport_config`) and prints the lines.

| Exit | Meaning                                                                                  |
| ---- | ---------------------------------------------------------------------------------------- |
| 0    | relay disabled, or binary provisioned                                                    |
| 2    | missing or bad arguments (argparse)                                                      |
| 3    | relay enabled but not provisioned (`RELAY_PROVISION_FAILED_EXIT_CODE`); banner on stdout |

The shell caller should treat 3 as warn-loudly-and-continue (per section 3), and repeat the banner before `exit 0`.
Not built here (outside items 1 and 2): the "upgrade preserving an explicit relay_enabled false" test in
`tests/unit/install/test_config_merger.py`.

# Code Review: worktree-relay-default (Plan 00554, relay on by default)

## Summary

The flip itself is clean: every reader of `relay_enabled` resolves the default the same way, so there is no split-brain. The problem is what the flip exposes. Two latent defects in the relay guard and in provisioning used to reach only clients who opted in. With the relay as the default, every macOS and non-x86_64 client hits them on upgrade, and one of them can make PreToolUse hooks fail open.

Reviewed: 26 files, +309/-153 (`git diff main...worktree-relay-default`).
Issues: 1 critical, 1 important-blocking, 2 important, 1 suggestion.

Probe scripts, kept as evidence (worktree `untracked/scratch/review554/`):

- `probe_defaults.py`: resolves `relay_enabled` for 8 config shapes through `load_transport_config` and through `Config.load_or_default`.
- `probe_foreign_elf.py`: builds a real guard block and runs it against an ELF this host cannot execute.

## Upgrade-path matrix (verified with probe_defaults.py)

| Config shape                        | forwarder_generator / relay_deploy CLI / transport_env.sh | Config.load_or_default (daemon, status, checker) |
| ----------------------------------- | --------------------------------------------------------- | ------------------------------------------------ |
| missing file                        | relay on, source auto                                     | relay on (checker: silent by design)             |
| no `daemon` block / no `transport`  | relay on                                                  | relay on                                         |
| `transport:` with only `nc_enabled` | relay on                                                  | relay on                                         |
| `relay_enabled: false`              | off                                                       | off                                              |
| `relay_enabled: null`               | off (validation fallback)                                 | RAISES ValidationError                           |
| `transport: null`                   | off (validation fallback)                                 | raises ValidationError                           |
| malformed YAML                      | off (legacy fallback, logged)                             | raises ValueError (checker and status report it) |

No bash script parses the YAML itself. `hooks_deploy.sh`, `relay_provision.sh` and `transport_env.sh` all go through `load_transport_config`, and `init.sh` never reads `relay_enabled`. So there is no "absent = off in bash, absent = on in Python" split.

## Critical issues

### 1. On macOS /bin/bash 3.2 the relay guard aborts the forwarder before the legacy body runs, so hooks fail open (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/install/forwarder_generator.py:326` (`_events_dir_lines`). The relay guard uses these lines, and so does the status fast path (gated at `:997`).

**Problem:** The generated guard contains `_rl_sfx="${_rl_sfx,,}"`. Case-modifying expansion arrived in bash 4.0. Deployed forwarders start with `#!/bin/bash`, which is bash 3.2 on macOS, and the README lists macOS as supported (`README.md:5`, `:562`). In bash 3.2 that line is a "bad substitution", and an expansion error makes a non-interactive bash exit with rc 1 on the spot. On bash 5 here, `bash -c 'if true; then y="${1x}"; echo in; fi; echo after'` prints only the error and exits 1. The forwarder therefore never reaches init.sh or its fail-closed PreToolUse deny. Exit 1 is a non-blocking hook error, so Claude Code runs the tool call unjudged.

The project already knows about this trap. `init.sh:1486-1489` says: "the lowercase pass stays on tr for bash 3.2 compatibility (macOS ships no ${var,,})". The guard also uses `read -r -N 4` (bash 4+, `:437`). On 3.2 that would fall through rather than abort, but every call would then carry the relay-unused warning.

**Failure scenario:** A macOS client with no `relay_enabled` key upgrades. Step 14c regenerates the forwarders with the guard. The daemon is running, so the per-event socket exists. Every guarded hook then exits 1 at the `${,,}` line, and no PreToolUse rule is enforced. Before this branch only clients who opted in could reach this; now it is the default.

**Caveat:** I could not run bash 3.2 here. The abort-on-bad-substitution behaviour was confirmed on bash 5.2, and `${v,,}` is documented as a 4.0 addition. Confirm on a macOS host or in a `bash:3.2` container before release.

**Suggested fix:**

1. Replace `${_rl_sfx,,}` with a 3.2-safe form that matches init.sh, for example lowercasing via `tr` only when `[[ $_rl_sfx == *[A-Z]* ]]` so the common case stays spawn-free.
2. Replace `read -N 4` with a 3.2-safe magic check.
3. Add a test that runs the generated guard under a bash 3.2 interpreter when one is available, or a static test that rejects `,,}`, `^^}`, `read -N` and `declare -l` in generated guard text.
4. Until that is fixed, keep the default off on Darwin, for example by gating the guard insertion on `sys.platform`.

## Important issues

### 2. Provisioning ignores the host platform: a foreign-architecture binary counts as "provisioned", every hook answer gets a warning, and the suggested fix does nothing (Confidence: 90%)

**Location:**

- `src/claude_code_hooks_daemon/install/relay_deploy.py:37`: `RELAY_TARGET = "x86_64-unknown-linux-musl"` is the only target.
- `:467-501`: `_deploy_auto` downloads the asset with no host check.
- `:123-146`: `relay_binary_defect` accepts any `\x7fELF`.
- `src/claude_code_hooks_daemon/daemon/relay_unused_warning.py:69-95`: adds the warning line.

**Problem:** With `relay_source` now `auto` by default, a macOS host, or a Linux host on aarch64 such as Graviton, an Apple-silicon container or a Raspberry Pi, has no musl rustc, so `auto` downloads the x86_64-linux ELF. That passes the digest check and `relay_binary_defect` (ELF magic). The results:

- The installer prints "provisioned".
- `relay_binary_checker` stays silent.
- `status` stays silent.
- At hook time `exec` fails with "cannot execute binary file: Exec format error", the guard falls through with `HOOKS_DAEMON_RELAY_UNUSED` set, and every relay-eligible answer gets "WARNING: relay is enabled but its binary is missing or cannot run ... Fix: hooks-daemon transport on" injected into its context.
- `transport on` -> `ensure_relay_binary` sees `defect is None` and provisions nothing, so the advised fix cannot clear the warning.

**Evidence (`probe_foreign_elf.py`, run on this host):**

```
relay_binary_defect: None
stdout: FELL THROUGH relay_unused=/tmp/.../untracked/bin/hooks-relay
stderr: .../pre-tool-use: line 18: .../hooks-relay: cannot execute binary file: Exec format error
```

**Related (Linux x86_64, offline, no rustc):** Provisioning fails with the banner and the install continues, which is correct. Every relay-eligible answer then carries the warning until someone acts, and the warning names only `transport on`, not the opt-out. That is an acceptable "loud" fallback, but every offline client now gets it by default.

**Suggested fix:**

1. Make `relay_binary_defect` verify the ELF class and `e_machine` against the host (`platform.machine()`), returning a new defect such as "built for another architecture".
2. In `_deploy_auto` and the `download` route, refuse when the host is not Linux x86_64, with a reason naming the platform.
3. Resolve the default to legacy on unsupported hosts, or at least have the generator skip the guard there.
4. Have the warning text name `transport off` as the remedy when the platform is unsupported.

Add unit tests for the arm64-ELF and Mach-O cases.

### 3. The manifest and plan say an explicit relay_enabled: null is "kept"; it is a validation error (Confidence: 85%)

**Location:**

- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml:17-18` ("An explicit `false` or `null` is kept").
- `CLAUDE/Plan/00554-rust-relay-transport-default/PLAN.md` Overview ("An explicit `false` or `null` is respected").

**Problem:** `relay_enabled` is a plain `bool`. `null` fails pydantic validation, so `load_transport_config` treats the whole config as unusable and resolves to legacy. `Config.load_or_default` raises, which means the daemon, `status` and the checker all see an unreadable config, not an opt-out (see the matrix above). A client who follows the manifest literally ends up with a config the daemon rejects.

**Suggested fix:** Drop "or `null`" from both texts. Only `relay_source: null` is a valid null. If null is meant to be accepted, add a `field_validator` mapping `None` to `False`, with a test.

### 4. Comments and docstrings still describe the old "off by default" contract (Confidence: 80%)

**Locations:**

- `scripts/install/transport_env.sh:4-8`: "for a genuine fresh install the probe below resolves the pure defaults (both rungs off) and appends nothing". A missing config now resolves relay on, so Step 6 of a fresh install now runs `probe_transport`, which spawns `rustc --print target-list` and `nc -h`, and then emits nothing for relay-only. The spawns are wasted, and the comment is wrong.
- `src/claude_code_hooks_daemon/install/transport_probe.py:193-195`: "keeps hooks-daemon.env untouched for the default config, matching the byte-identical-by-default contract".
- `src/claude_code_hooks_daemon/daemon/cli.py:1633-1635`: "Silent when the transport is disabled (default) - matches today's status output byte-for-byte".
- `src/claude_code_hooks_daemon/install/relay_deploy.py:429-432`: `deploy_relay_if_configured` docstring, "`None` (the default) is a genuine no-op".

**Why it matters:** Each of these tells the next maintainer the opposite of the code. The `transport_env.sh` one also hides a behaviour change at install Step 6.

**Suggested fix:** Reword each one to the new default. Optionally, in `transport_env.sh`, skip the probe when `nc_enabled` is false, since `render_env_lines` emits only the nc fact.

## Suggestions

- `src/claude_code_hooks_daemon/handlers/session_start/relay_binary_checker.py:122-123`: with no config file the checker is now silent, while `load_transport_config` and the daemon's `Config()` treat a missing file as relay on. That is defensible, since a missing config means the project is not set up, but the two now disagree. State in the docstring why silence is right there (the generator does not run without a config in a real install).
- `tests/unit/install/test_transport_toggle.py`, `test_run_toggle_on_a_fresh_config_is_a_seeded_no_op`: it asserts only `changed is False` and the seeded value. It does not stub `provision_fn`, so it calls the real `ensure_relay_binary` with `relay_source: auto`, which is fine only while the fixture binary exists. It also does not check that legacy forwarders are converged to carry the guard, which is the case an upgraded client with no key actually hits. Pass a stub `provision_fn` and assert on the forwarder content.
- `tests/integration/test_hooks_deploy_relay_guard.py`: the former default test was moved to an explicit `false`, which is correct. Nothing replaces it for the new default path, an end-to-end deploy with a config that has a `transport` block without `relay_enabled` asserting the guard IS inserted. Add one.

## Positive observations

- A single loader (`load_transport_config`) serves the generator, the provisioning CLI and `transport_env.sh`, so the default is decided in one place.
- Treating a malformed config as legacy is the safe choice and is documented and tested.
- Provisioning still never aborts install or upgrade (`relay_provision.sh` always returns 0), and the banner is repeated at the end.
- The seed and flip logic in `transport_toggle` handles the absent-key case correctly in both directions.
- The test changes that add `relay_enabled=False` keep their original intent: they are legacy- and nc-path tests, not tests of the default.

## Verdict

[x] REQUEST CHANGES: findings 1 and 2 must be fixed, or the default gated to Linux x86_64 with bash >= 4, before this ships as "everyone" in the release note. Findings 3 and 4 are doc and comment corrections.

# Handoff: rust-relay-transport-default (Plan 00554)

Worktree: /workspace/untracked/worktrees/worktree-relay-default, branch `worktree-relay-default`.
Python: `PYTHONPATH=$PWD/src /workspace/.venv/bin/python -m pytest <literal paths>` (no `-n`).

## Design decisions (made)

- `TransportConfig.relay_enabled` default True and `relay_source` default `"auto"` (models.py). Explicit `false` / explicit `null` are respected; an absent key follows the new default (so upgraded configs with no key get the relay).
- Fallback ladder intact: install/upgrade provisioning never aborts on failure (scripts/install/relay_provision.sh, Plan 00529); `relay_binary_checker` warns and starts a detached repair; the forwarder guard falls through to nc/bash when the binary is unusable.
- `load_transport_config` (forwarder_generator.py): missing config file -> defaults (relay on); unusable/malformed config -> legacy (`relay_enabled=False`), since the opt-out cannot be read.
- `transport_toggle` seeds `relay_enabled: true` (the shipped default) when the key is absent.
- `relay_binary_checker` stays silent when there is no config file.
- No blocker found for flipping the default (no GitHub ticket needed so far).

## Done and green (unit)

tests/unit/install, tests/unit/config, tests/unit/daemon, tests/unit/handlers/session_start all pass after the edits (legacy-path tests now pass `relay_enabled=False` explicitly).

## Left

1. Four integration failures to fix by making the legacy/nc scenarios explicit (`relay_enabled: false` in their config):
   - tests/integration/test_hooks_deploy_relay_guard.py::test_default_config_deploy_is_byte_identical (rename: default now carries the guard; add a `relay_enabled: false` byte-identical variant)
   - tests/integration/test_hooks_deploy_relay_guard.py::test_f1_contaminated_source_deploy_strips_foreign_guard_by_default (use explicit false)
   - tests/integration/test_relay_guard_fail_open.py::test_nc_rung_round_trip_completes_promptly and ::test_nc_rung_honours_events_dir_env_override (nc-only needs `relay_enabled: false`)
2. Other tests using the default `Config()`; run literal paths for tests/unit/handlers, tests/unit/core, tests/unit/install already done; spot-check tests/unit/qa and scripts tests touching transport.
3. Docs describing the relay as opt-in: scripts/install/hooks_deploy.sh:527 comment, install/relay_deploy.py docstring (lines ~12, 430, 569), transport_probe/transport_verify docstrings, `.claude/hooks-daemon.yaml.example` comment line 17, init_config.py comment, CLAUDE/Architecture/StatusLine.md:395, CLAUDE/UPGRADES/config-changes (add a v-next entry per README there), search CLAUDE/ and docs/ for "opt-in" near relay.
4. Release note CLAUDE/UPGRADES/UNRELEASED/release-notes/009-rust-relay-transport-default.md (follow the README.md in that folder; explain default flip, absent-key behaviour, how to opt out: `relay_enabled: false` or `bin/hooks-daemon transport off`).
5. CHANGELOG.md entry under Unreleased/Changed; add the README index row in CLAUDE/Plan/README.md; fill PLAN.md.
6. Targeted QA: `./scripts/qa/llm_qa.py changed --range <base>..HEAD` where base is 50c4d1a1e.
7. Push: `git push -u origin worktree-relay-default`; report branch and final commit to team-lead.

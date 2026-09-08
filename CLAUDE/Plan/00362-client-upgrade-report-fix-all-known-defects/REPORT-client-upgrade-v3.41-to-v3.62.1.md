# Client report: hooks daemon issues on a v3.41.0 to v3.62.1 upgrade

Imported from a client PHP project's `untracked/hooks-daemon-issues.md`
(reporter identifiers stripped). Collected during `/hooks-daemon upgrade`
v3.41.0 → v3.62.1 and the follow-up config-optimisation pass. Environment:
ccy/Podman container, Python 3.11 venv, project root `/workspace`, YOLO
(bypassPermissions) mode.

## 1. `health-check.sh` self-bootstrap fails with a 404

`/hooks-daemon health` (`.claude/skills/hooks-daemon/scripts/health-check.sh`)
now self-bootstraps by downloading a checksum manifest from the GitHub
"latest" release before doing anything:

```
curl: (22) The requested URL returned error: 404
Error: failed to download bootstrap-checksums.txt from
    https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/latest/download/bootstrap-checksums.txt
Self-bootstrap aborted. Check network connectivity and retry.
```

The asset is not attached to the latest release, so the health check is
unusable on every install (network is fine — the upgrade itself fetched tags
OK). `bin/hooks-daemon status` works, so the daemon is healthy; only the
skill wrapper is broken. Suggest: attach the asset to the release, and make
the bootstrap fall back to the already-installed local wrapper when it is
present rather than hard-failing.

## 2. Upgrade reported "no config changes" while leaving dead handler config

`config_diff_summary=no config changes` was printed, yet the project's
`hooks-daemon.yaml` still carried:

```yaml
stop:
  hedging_language_detector:   {enabled: true, priority: 30}
  dismissive_language_detector: {enabled: true, priority: 58}
```

In 3.62.1 those handlers live only under `pseudo_events.nitpick.handlers`
and `bin/hooks-daemon handlers` showed the Stop event with just
`auto-continue-stop` — the two detectors were silently not running, with no
warning at upgrade or session start. `config-validate` also passes the
stale keys as `valid: true` with no warnings. Suggest: `check-config-migrations`
/ the upgrade diff should flag handler keys that no longer exist for that
event (and ideally auto-migrate the two detectors into the nitpick block).

Same class of problem: the following keys in the client config are not in the
daemon's own reference config and got no warning either —
`notification.notification_logger`, `post_tool_use.bash_error_detector`,
`pre_compact.transcript_archiver`, `pre_tool_use.plan_completion_advisor`,
`pre_tool_use.task_tdd_advisor`, `pre_tool_use.validate_instruction_content`,
`pre_tool_use.validate_plan_number`, `session_end.cleanup`,
`session_start.yolo_container_detection`, `status_line.usage_tracking`,
`stop.task_completion_checker`, `subagent_stop.remind_prompt_library`,
`subagent_stop.subagent_completion_logger`. Some of these are clearly still
live handlers (e.g. `validate_instruction_content` is in the loaded list), so
the reference config itself may be incomplete — either way an "unknown
handler key" warning would make this discoverable.

## 3. `pipe_blocker` guidance references `echd-capture`, which is not installed

The injected CLAUDE.md guidance says to use `... 2>&1 | echd-capture 20`
instead of `| tail`. The binary does not exist in the client container:

```
/bin/bash: line 1: echd-capture: command not found
```

Either the daemon should deploy/provision it (as it does the relay binary)
or the guidance should not name it as the preferred path.

## 4. `project_containment` blocks the harness's own scratchpad directory

Claude Code's system prompt tells the agent to use a per-session scratchpad
under `/tmp/claude-0/-workspace/<session>/scratchpad` for ALL temp files.
`project_containment` (new, default-on) denies every write there with
`R-WRITE-OUTSIDE-PROJECT-ROOT` and redirects to `untracked/scratch/`. The two
instructions contradict each other on every session; the agent burns a
blocked call before learning which one wins. Suggest: whitelist the
harness-provided scratchpad path (it is discoverable — it is the parent of
`CLAUDE_*` session dirs), or document that this handler overrides the
harness instruction.

## 5. `sed_blocker` blocks read-only `sed -n 'N,Mp' file`

Handler doc says read-only pipelines (`cat file | sed ... | grep`) are
allowed and only in-place/mass modification is blocked. A plain
`sed -n 600,640p file` (print a line range, no `-i`, no `-e`, no redirect)
was denied with `R-SED-FILE-MODIFICATION`. `awk 'NR>=600 && NR<=640'` had to
be used instead. The rule should not fire when there is no `-i`/`-e`/`s///`
write path and the target is not redirected.

## 6. `tdd_enforcement` cannot express a nested mirror test root (PHP size suites)

The client repo (and its QA tooling's default `phpunit.xml` for consumers)
lays tests out as `tests/Small/<mirror of src>/FooTest.php` and
`tests/Large/<mirror>/FooTest.php`. The enforcement:

- `_map_src_to_tests_mirror` hardcodes `tests/<mirror>`;
- `_map_src_to_test_path` hardcodes `tests/unit/`;
- `options.test_path_map` is documented as FLAT ("the test filename is
  placed directly in this directory, not mirrored under it");
- `layout.test_dirs` only classifies paths, it does not add mirror roots.

Real deny output for `src/PackageType/OptimiseProbe.php`:

```
Searched locations:
  - /workspace/tests/PackageType/OptimiseProbeTest.php
  - /workspace/tests/unit/OptimiseProbeTest.php
  - /workspace/tests/OptimiseProbeTest.php
  - /workspace/src/PackageType/OptimiseProbeTest.php
  - /workspace/src/PackageType/__tests__/OptimiseProbeTest.php
```

None can ever match, so the gate would block every new source file; it has
been left disabled with a comment. Suggest: allow `test_path_map` entries (or
`layout.test_dirs`) to be declared as MIRROR roots, e.g.
`{source_glob: "src/**", test_dir: "tests/Small", mirror: true}`, checking
all declared roots.

## 7. Skill docs / CLI verb mismatch: `validate-config` vs `config-validate`

The skill's SKILL.md routes a `validate-config` subcommand to the daemon CLI,
but the CLI verb is `config-validate` (and it requires a positional
`config_path`). `bin/hooks-daemon validate-config` fails with "invalid
choice". Align the names (or accept both) and default `config_path` to the
project config.

## 8. Minor

- The `optimise-invoke.sh` procedure says to read
  `CLAUDE/UPGRADES/config-changes/v*.yaml` manifests; that tree is not
  deployed to consumer projects (only exists in the daemon's own repo), so
  Step 0 always silently skips — the "new since vX" recommendations never
  surface in a consumer install.
- `daemon_stats` (status line) is still `enabled: true` in older consumer
  configs from before v3.40; the release notes ask such projects to turn it
  off now that `upgrade_notifier` carries the arrow. The upgrader could flag
  this as it knows both facts.

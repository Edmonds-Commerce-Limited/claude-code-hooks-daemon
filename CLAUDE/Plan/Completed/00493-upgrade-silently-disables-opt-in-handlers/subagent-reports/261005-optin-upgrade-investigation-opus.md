# Investigation: the v3.67.0 to v3.68.0 upgrade switches off opt-in handlers a client config does not name

Plan 00493. Read-only investigation in worktree `agent-aed3ffd967613ded7-fc8425d8`
at `4019dd3b3`. No code was changed.

## The report

A client agent, after upgrading the daemon from v3.67.0 to v3.68.0, said:

> "Hooks daemon: upgraded from v3.67.0 to v3.68.0 and running. The upgrade had
> silently switched off 11 opt-in handlers this project relied on"

The owner sees this kind of message across client projects.

The client agent later answered the owner's questions (relayed by the coordinator):

- The line was the agent's own conclusion, not daemon output. The upgrade
  metadata said `config_diff_summary=no config changes`.
- Its evidence was the upgrade's truth-change report (`check-truth-changes --from 3.67.0 --to 3.68.0`), entry `absent-handler-block-default`, quoted
  verbatim.
- After the upgrade, `optimise-checklist` showed 11 handlers as
  `✗ … [default off]`.
- The client's config had NO block for any of them, before or after the
  upgrade.
- 10 of the 11 existed in v3.67.0. `plan_fact_check_feed` is new in v3.68.0
  and never ran there.
- Six (`goal_injection`, `idle_housekeeping_advisory`,
  `model_fallback_detector`, `routine_qa_sweep`, `session_actions_directive`,
  `tool_disable_advisor`) were in the v3.67.0-generated CLAUDE.md handler
  guidance and vanished from it after the upgrade.
- The client has since added explicit `enabled: true` blocks.

## Question 2: is the line ours?

No. `git grep -i -E "opt-in handlers|switched off|silently (switch|disabl|turn)"`
over `v3.68.0` and `HEAD` (excluding `tests/fixtures/cyber-flag` and
`CLAUDE/Plan`) finds 187 and 190 hits. None of them is runtime or upgrade
output with that wording. Every hit is a comment, docstring, test, or
release-note prose. The nearest daemon-shipped text is:

- the truth change `CLAUDE/UPGRADES/truth-changes/v3.68.0.yaml:40-60`
  (`id: absent-handler-block-default`), which `scripts/upgrade.sh:1039-1066`
  prints under "Project-doc reconciliation needed";
- release note
  `CLAUDE/UPGRADES/v3/v3.67.0-to-v3.68.0/release-notes/216-an-opt-in-handler-with-no-config-block-no-longer-runs.md`;
- config-changes `CLAUDE/UPGRADES/config-changes/v3.68.0.yaml:570-…`, sixteen
  documentation-only `changed:` entries (`handlers.<event>.<opt-in key>`).

The client agent compared the generic truth-change list with its own config
and with `optimise-checklist`, and wrote the line itself. Its conclusion is
correct in substance.

## Question 1: are we switching off opt-in handlers on upgrade? Yes. This is how

### The change

| Item                   | Reference                                                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Owner-delegated ruling | Plan 00483 `RULINGS-owner-delegated-fable.md:17,319` (N55: "an absent config block defers to the handler's declared default; the 11 opt-in handlers stay off until named"). Triage: `TRIAGE-ledger-466.md:49` |
| Implementation commit  | `02c702ea2`, merged by `ae62d27d1` (branch `worktree-p483-n55-default-enabled`), recorded by `4e58dcb21`                                                                                                      |
| Implementer's report   | `CLAUDE/Plan/00483-threat-model-conformance-audit/subagent-reports/261002-n55-default-enabled-sonnet.md`                                                                                                      |
| Truth change           | `CLAUDE/UPGRADES/truth-changes/v3.68.0.yaml:40` `absent-handler-block-default`                                                                                                                                |
| Config changes         | `CLAUDE/UPGRADES/config-changes/v3.68.0.yaml:570-575` and on (16 entries sharing the `*opt_in_description` anchor, no `recommended_value`)                                                                    |
| Release note           | `release-notes/216-…-no-longer-runs.md` (v3.67.0-to-v3.68.0)                                                                                                                                                  |

The change was intended. N55 was a real defect: at v3.67.0, `init minimal`
(which emits `pre_tool_use: {}` for every event) ran every opt-in handler,
including four that deny tool calls. `get_default_enabled()` existed from
v3.24.0 (Plan 00133) but the registry never consulted it.

### Resolution logic, v3.67.0 against v3.68.0

v3.67.0 `src/claude_code_hooks_daemon/handlers/registry.py`:

- `:216` `config_skip_reason(handler_config, *, registry_disabled)`.
- `:237` `if not block.get(ConfigKey.ENABLED, True)`. An absent block is `{}`,
  so it is ENABLED for every handler, opt-in or not.
- `:291` `handler_is_enabled` and `:652` `register_all` Pass 2 both go through
  it.

v3.68.0 (identical at HEAD, same line numbers in the function):

- `:216` `config_skip_reason(..., default_enabled=True, present=True)`.
- `:248-249` `if not present and not default_enabled: return "off by default and not configured"`.
- `:679` `present = config_key in event_config` (Pass 2), and `:690`
  `default_enabled=attr.default_enabled`.
- `:694` the only record of the skip is `logger.debug("Handler %s skipped - %s", ...)`.
  DEBUG is below the daemon's default level, so nothing reaches the operator.
- `core/handler.py:91` `default_enabled: ClassVar[bool] = True`. The 17 opt-in
  classes set `default_enabled = False`.

A present block, even a bare `key:` or an options-only block with no
`enabled`, stays enabled. The reproduction confirms this (fixture
`hand-written-options-only`: `lsp_enforcement` with only `options`, a bare
`flaggable_work_advisor:`, and `daemon_stats` with only `priority` all still
register at v3.68.0).

### Why it is silent

1. **No per-project report.** `install/config_migrations.py:659-660` (v3.68.0):
   a `changed` entry with no `recommended_value` is skipped (`continue`). The
   16 N55 entries deliberately have none (comment at
   `config-changes/v3.68.0.yaml:570-574`: "promoting every one would tell
   every project to enable all sixteen"). So `check-config-migrations`, which
   the upgrade prints as "Newly-available / recommended config options", says
   nothing about the handlers THIS project is about to lose.
2. **Only a generic notice.** The truth change prints the full list of 16. It
   does not say which of them this project's config omits, and the agent
   reads it as "project docs to reconcile" (step 4), not as "your running
   handler set just shrank".
3. **The count is wrong.** v3.68.0 has 17 opt-in handlers. The truth change,
   release note 216 and the config-changes entries list 16 and omit
   `plan_fact_check_feed` (`handlers/post_tool_use/plan_fact_check_feed.py:64`
   `default_enabled = False`, new in v3.68.0). The ruling itself said eleven.
4. **`config_diff_summary` cannot see it, and is broken anyway.**
   `scripts/upgrade.sh:954-958` reads `$PROJECT_ROOT/.claude/hooks-daemon.yaml.backup`.
   Nothing writes that path: `scripts/install/config_preserve.sh:75-77`
   writes `hooks-daemon.yaml.backup-${timestamp}`. So the summary is ALWAYS
   "no config changes", at v3.68.0 and at HEAD. Even if it worked, it diffs
   config FILES, and in this incident the file did not change. The behaviour
   changed under an unchanged file.
5. **Runtime.** The daemon logs the skip at DEBUG only (`registry.py:694`).
   The generated CLAUDE.md guidance just drops the handlers. That is how the
   client noticed six disappear.

### Hypotheses

| #   | Hypothesis                                                                      | Verdict                                                                                             | Evidence                                                                                                                                              |
| --- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| a   | Handler renamed or event moved, so `enabled: true` under the old key is ignored | **Refuted** for this incident                                                                       | All 11 keys and events are unchanged between v3.67.0 and v3.68.0. The client had no blocks at all, and the repro shows the losses with keys untouched |
| b   | Stricter validation drops a block with a stale option                           | **Refuted**                                                                                         | `Config.load` accepted all four fixtures under v3.67.0, v3.68.0 and HEAD (`ok: true`). The client had no blocks to drop                               |
| c   | Upgrade regenerates the config from the template                                | **Not the cause here**, but a latent sibling, see below                                             | The client config was unchanged. The merge path would write `enabled: false` blocks if it ran                                                         |
| d   | Change in `enabled` resolution                                                  | **CONFIRMED, root cause**                                                                           | `registry.py:248-249` at v3.68.0, against `:237` at v3.67.0. An absent block now defers to `default_enabled`                                          |
| e   | Other                                                                           | Found the broken `config_diff_summary` backup path, the 16/17 count, and the doc-only manifest skip | See "Why it is silent"                                                                                                                                |

### Hypothesis (c) detail: a latent second route to the same loss

`scripts/upgrade_version.sh:1320-1340` (v3.68.0, Step 10) runs
`preserve_config_for_upgrade` when an old-default baseline is available. That
diffs the user config against the OLD default and overlays the result onto
the NEW default (`install/config_cli.py:112-152`). A probe of the v3.68.0
`run_config_merge` (old default = v3.67.0 `.claude/hooks-daemon.yaml.example`,
new default = v3.68.0 example) gives:

- `init-minimal-v3.50.0`: 0 opt-in blocks before. After: 17 blocks, 16 of them
  `enabled: false` (daemon_stats came out `true`). 145 conflicts.
- `init-full-v3.50.0`: 5 blocks before, 17 after, all `enabled: false`.
- options-only fixture: the 3 present blocks keep their values. The other 14
  are written as `enabled: false`.

When that merge runs, it turns absent opt-in blocks into EXPLICIT
`enabled: false`. That is the same loss, and older than v3.68.0, because the
example already carried `enabled: false` for each. The client's config was
unchanged, so this path did not run for them (baseline missing, or Layer 1
did not hand one over). It has to be covered by the same before/after check.
Whether the merge normally runs on a client upgrade is an open item for the
fix phase, not established here.

## Reproduction

Scripts are under `untracked/scratch/optin/` in the investigating worktree,
which is gitignored. Results are summarised here.

- Source trees were extracted with `git archive` at v3.50.0, v3.67.0, v3.68.0
  and HEAD.
- `repro_one.py` mirrors the controller: `Config.load` →
  `build_handler_config_mapping` → `HandlerRegistry.discover()` →
  `register_all(EventRouter(), …)` → registered classes per event.
- `drive.py` builds fixtures and diffs the sets.
- No daemon was started and no upgrade was run.

| Fixture                                              | Lost v3.67.0 → v3.68.0 (and HEAD, identical)                                                                                                                                                                                                              |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `init full` generated by v3.50.0                     | **11**: GoalInjection, FlaggableContentChannelGuard, FlaggableWorkAdvisor, QuarantineArtefactReadGuard, SubagentFullQaBlocker, ModelFallbackDetector, RoutineQaSweep, SessionActionsDirective, SkillOpportunityDetector, ToolDisableAdvisor, HostHostname |
| `init minimal` generated by v3.50.0                  | **16**, all opt-in handlers that existed at v3.67.0                                                                                                                                                                                                       |
| hand-written, options-only/bare blocks for 3 opt-ins | 13 (the 3 named ones survive)                                                                                                                                                                                                                             |
| `init full` generated by v3.67.0                     | 0                                                                                                                                                                                                                                                         |

In every fixture no default-on handler was lost, and no config was refused.
(The "gained" side is new v3.68.0 handlers.) In this harness a handful of
handlers fail to construct with "ProjectContext not initialized". That
happens identically in every version and does not affect the diff.

### Template history: which client configs lack which blocks

`template_history.py` scans `daemon/init_config.py` at every v3 tag for the
16 keys:

| `init full` generated at | Opt-in blocks absent                                                                     |
| ------------------------ | ---------------------------------------------------------------------------------------- |
| v3.0.0 - v3.32.0         | 14                                                                                       |
| v3.33.0 - v3.39.0        | 12                                                                                       |
| **v3.40.0 - v3.54.0**    | **11** (the 11 in the first row of the reproduction)                                     |
| v3.55.0                  | 9                                                                                        |
| v3.56.0                  | 5                                                                                        |
| v3.57.0 - v3.64.0        | 4 (subagent_full_qa_blocker, routine_qa_sweep, session_actions_directive, host_hostname) |
| v3.65.0 - v3.66.0        | 1 (subagent_full_qa_blocker)                                                             |
| v3.67.0                  | 0                                                                                        |

Plus `plan_fact_check_feed`, which no pre-v3.68.0 config names.

The client's 11 (10 existing + `plan_fact_check_feed`) is a different set from
the v3.40-v3.54 row's 11. The client config is partial: hand-edited or
`init minimal` plus some blocks. The mechanism is the same.

## Blast radius

- **Affected:** every client config with no block for an opt-in handler that
  existed at v3.67.0. That is every `init minimal` config (16 lost), every
  `init full` config generated before v3.67.0 and not re-synced (1-14 lost,
  per the table above), and every hand-written or partial config.
- **Not affected:** v3.67.0-generated full configs, a config that names a
  handler even as a bare key or options-only, and every default-on handler.
- **What is lost** spans three kinds of handler:
  - Four PreToolUse DENY guards: `flaggable_content_channel_guard`,
    `quarantine_artefact_read_guard`, `subagent_full_qa_blocker`,
    `lsp_enforcement`.
  - Advisories: `flaggable_work_advisor`, `goal_injection`,
    `model_fallback_detector`, `routine_qa_sweep`,
    `session_actions_directive`, `skill_opportunity_detector`,
    `tool_disable_advisor`, `idle_housekeeping_advisory`,
    `compaction_signal`.
  - Status-line segments: `context_sidecar`, `daemon_stats`, `host_hostname`.
- **Upside the owner should weigh:** for a client that never chose these
  handlers, v3.68.0 is the INTENDED behaviour (N55). Most of them ran only
  because of the defect. The loud failure is not "they turned off". It is
  "they turned off without the project being told which ones". It is also a
  security regression for a client that depended on one of the four deny
  guards.

## HEAD (main, `4019dd3b3`)

Still affected. `config_skip_reason` is unchanged
(`registry.py:248-249` at HEAD). Since v3.68.0 the only commits touching
`registry.py` are `c76950b63` (Plan 00470: option-failure handling) and
`fbab59fe1` (WIP). Neither touches resolution.
`config_migrations.py` and the `upgrade.sh` backup path are unchanged.
`upgrade.sh:958` still reads `hooks-daemon.yaml.backup`. 17 opt-in classes
at HEAD.

## Is the daemon version git-visible in a project? (owner idea 3)

Yes, from v3.68.0 on. Plan 00477 added `daemon.expected_version` to the
tracked `.claude/hooks-daemon.yaml`. `install/expected_version.py` (new in
v3.68.0) writes it as a text edit that preserves comments, and the upgrade
runs it at `scripts/upgrade_version.sh:1046,1636`. The tracked
`.claude/HOOKS-DAEMON.md` header also names the version. `init.sh`
`_resolve_expected_version` (`:2274`) reads the key first and the header
second, and drives the VERSION MISMATCH branch (`:823`). The config's
`version: "2.0"` is the schema version.

Consequences:

- The v3.68.0 upgrade DID change the client's config file (the new
  `expected_version` line), which is more evidence that the
  "no config changes" summary is broken.
- The remaining gap is the summary naming `from → to`, and a
  commit-message convention.

## Client remedy (already-upgraded)

Run from the project root:

```
.claude/hooks-daemon/bin/hooks-daemon optimise-checklist
```

For each row marked `[default off]` that the project wants back, add a block
under the handler's event in `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  session_start:
    session_actions_directive:
      enabled: true
```

Then restart (`.claude/hooks-daemon/bin/hooks-daemon restart`). Prefer naming
only the handlers the project actually wants, not all of them: N55 exists
because several are noisy or deny-capable.

## Questions for the client agent

None are needed. The client already answered the deciding questions, and
the mechanism reproduces without client data.

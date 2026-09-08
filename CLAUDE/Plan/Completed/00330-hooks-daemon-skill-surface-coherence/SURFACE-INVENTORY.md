# Plan 00330 — Surface Inventory (Phase 1)

The measured state of the `hooks-daemon` skill surface, produced for Tasks
1.1–1.3. Every number here was taken from the tree at the commit that adds
this file, not from the plan's overview (which was written from an earlier
count). Where the two disagree the measurement wins and the disagreement is
called out.

Sources used:

- Skill source: `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md`
  (the deployed `.claude/skills/hooks-daemon/SKILL.md` is byte-identical;
  `tests/unit/scripts/test_skill_subcommands_are_dispatchable.py` pins that).
- Checklist: `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/optimise-invoke.sh`
  (Step 3, "Analyse Five Areas").
- Registry: `HandlerRegistry.discover()` over
  `claude_code_hooks_daemon.handlers`, cross-checked against
  `constants/handlers.py` (`HandlerID`, `RETIRED_HANDLERS`) and each
  handler's `get_default_enabled()` and `tags`.
- CLI: `python -m claude_code_hooks_daemon.daemon.cli --help` (59 verbs).
- Human-use evidence: this workspace's Claude Code session transcripts
  (`~/.claude/projects/-workspace/*.jsonl`, 25 files, 16 of which mention
  `hooks-daemon`), plus every `*.md` under the repo outside the skill trees.

---

## Task 1.1 — Routed subcommands against evidence of human use

### What the router accepts

The `case` statement in SKILL.md has 17 arms: 16 subcommands plus `help`.
Three arms carry an alias (`optimise|optimize`,
`regen-docs|regenerate-docs`, `config-validate|validate-config`), so 19
spellings route. The frontmatter `argument-hint` names only 11 of the 16, so
five routed subcommands (`status`, `handlers`, `config-validate`,
`bug-report`, `report`) are invisible at the point where Claude Code shows a
human what the skill takes.

### The evidence

Claude Code records a typed slash command in the transcript as
`<command-name>/x</command-name><command-args>…`. Across the 25 transcripts
the human typed `/compact` 129 times, `/effort` 18, `/model` 16, `/goal` 13,
`/release` 9 and `/clear` 1 — and **`/hooks-daemon` zero times, with any
subcommand**. Every one of the 14,641 transcript lines that mention
`hooks-daemon` is an AGENT running `bin/hooks-daemon <verb>` in Bash, or
prose about it.

So the "human types it" column is empty for the whole surface, in this
repository. Two caveats bound that claim: (a) these are the daemon
maintainer's own sessions, and a client's transcripts are not available; (b)
the owner reports never using several subcommands, which is consistent with
the data but is not itself a count. The usable evidence is therefore
indirect: how often docs tell a human to type it, and how often the CLI verb
behind it is actually run.

| Subcommand        | Routes to                                  | `/hooks-daemon x` in docs (files) | in PLAN docs / journals | CLI verb behind it → agent runs in transcripts  | Classification                                                                                                                                                                                                                                                                      |
| ----------------- | ------------------------------------------ | --------------------------------- | ----------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `install`         | `scripts/install.sh`                       | 3                                 | 4 / 1                   | (installer, not a CLI verb)                     | **Routed**. Fresh-clone bootstrap; there is no daemon CLI to fall back to, so the skill is the only entry point.                                                                                                                                                                    |
| `upgrade`         | `scripts/upgrade.sh`                       | 46                                | 13 / 2                  | `upgrade` → 65                                  | **Routed**. The most-documented subcommand after `restart`; drives config-migration, truth-changes and the optimise closing step.                                                                                                                                                   |
| `optimise`        | `scripts/optimise-invoke.sh`               | 6                                 | 4 / 0                   | `record-config-optimisation-run` → 52           | **Routed**. A confirmation-driven procedure with no CLI equivalent; mandatory closing step of `upgrade`. (`optimize` alias: keep.)                                                                                                                                                  |
| `restart`         | `daemon-cli.sh restart`                    | 42                                | 17 / 18                 | `restart` → 1,578                               | **Routed**. The single most-used verb, and the one every config edit ends with; a human-facing name for it is justified even though agents reach the CLI directly.                                                                                                                  |
| `health`          | `scripts/health-check.sh`                  | 14                                | 6 / 0                   | `health` → 45, `status` → 1,344                 | **Routed**. The script does more than the CLI verb (venv resolution, bootstrap); it is the "is it working?" entry point the troubleshooting guidance starts from.                                                                                                                   |
| `bug-report`      | `daemon-cli.sh bug-report`                 | 3                                 | 3 / 0                   | `bug-report` → 12                               | **Routed** (candidate to absorb `report`). Human-initiated by nature: it produces a file for maintainers, and `BUG_REPORTING.md` points at it.                                                                                                                                      |
| `report`          | `cat report.md` (LLM investigation prompt) | 2                                 | 0 / 0                   | none (prompt only)                              | **Documented-only or merge**. Zero plan/journal use; overlaps `bug-report` ("full investigation" vs "quick diagnostics"). Suggest one `bug-report` with the investigation prompt as its documented deep mode.                                                                       |
| `logs`            | `daemon-cli.sh logs`                       | 18                                | 2 / 2                   | `logs` → 318                                    | **Documented-only**. Pure CLI passthrough; agents already call `bin/hooks-daemon logs`. Document as `bin/hooks-daemon logs [--follow]` under the health section.                                                                                                                    |
| `status`          | `daemon-cli.sh status`                     | 37                                | 9 / 4                   | `status` → 1,344                                | **Documented-only**. Same: passthrough of the second-most-used CLI verb. Not in `argument-hint`, so the skill never advertised it anyway.                                                                                                                                           |
| `handlers`        | `daemon-cli.sh handlers`                   | 5                                 | 2 / 1                   | `handlers` → 65                                 | **Documented-only**. Passthrough. Not in `argument-hint`.                                                                                                                                                                                                                           |
| `config-validate` | `daemon-cli.sh config-validate`            | 5                                 | 0 / 0                   | `config-validate` → 38                          | **Documented-only**. Passthrough; the daemon validates on restart anyway. Not in `argument-hint`. (`validate-config` alias goes with it.)                                                                                                                                           |
| `check`           | `daemon-cli.sh check`                      | 2                                 | 2 / 0                   | `check` → 0 (absent from the transcript top-45) | **Documented-only**. Introduced as the verbose twin of the quiet SessionStart audit; no recorded run. Document under `health`.                                                                                                                                                      |
| `regen-docs`      | `daemon-cli.sh regenerate-docs`            | 2                                 | 0 / 0                   | `regenerate-docs` → 24                          | **Documented-only**. A recovery verb for merge-conflicted generated files; the CLI name is the one agents use. (`regenerate-docs` alias goes with it.)                                                                                                                              |
| `rule-explain`    | `daemon-cli.sh explain-rule`               | 2                                 | 2 / 1                   | `explain-rule` → 24, `explain-handler` → 20     | **Documented-only**. Every block message already prints the CLI form (`bin/hooks-daemon explain-rule <ID>`); the skill spelling is a second name for the same thing. `SkillCommand.RULE_EXPLAIN` in `constants/skill_commands.py` is the only code reference and must move with it. |
| `dev-handlers`    | `scripts/init-handlers.sh`                 | 1                                 | 2 / 0                   | `init-project-handlers` → 149                   | **Documented-only**. Agents scaffold via the CLI verb; the interactive script has one doc mention. Point `dev-handlers.md` at `init-project-handlers`.                                                                                                                              |
| `release-notes`   | `daemon-cli.sh release-notes`              | 3                                 | 1 / 0                   | `release-notes` → 0 (1 doc mention of the CLI)  | **Documented-only**. Passthrough; a human reading release notes is plausible, but nothing shows it happening. Keep the CLI, drop the routing arm.                                                                                                                                   |

Routed after the cut: **6** (`install`, `upgrade`, `optimise`, `restart`,
`health`, `bug-report`) — or 5 if `bug-report` and `report` are merged and
the merged command is what routes. Documented-only: **10** (`report`,
`logs`, `status`, `handlers`, `config-validate`, `check`, `regen-docs`,
`rule-explain`, `dev-handlers`, `release-notes`). Retire outright: **none** —
each has a live CLI verb or prompt, and the Non-Goals forbid deleting a
capability.

Two further findings from the same pass:

- SKILL.md already documents `plan-qa` as a CLI command rather than a
  subcommand, and the dispatchability test carves out that exact shape. The
  "documented-only" class therefore already exists in the skill; Phase 2–4
  generalise it rather than invent it.
- Nothing in the routed surface runs the housekeeping verbs that exist
  today: `docs-qa --sweep`, `plan-qa --sweep`, `skill-scan`, `worktree-reap`,
  `format-markdown`, `remote-docs check|refresh`, `check-permissions`,
  `disk-usage`/`prune-venvs`, `audit-handler-keys`, `check-worktree-seed`,
  `harvest-background`, `verdicts`/`block-report`/`tool-report`. That is the
  raw material for Phase 3 (see the decisions at the end).

---

## Task 1.2 — What `optimise` covers against the registry

### The measured numbers

| Quantity                                | Count | Note                                                                                                                                                       |
| --------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `HandlerID` constants                   | 117   | includes `TEST_SERVER`, which `discover()` does not register                                                                                               |
| Handlers the registry discovers         | 116   | across 11 event dirs: pre_tool_use 57, session_start 21, status_line 14, post_tool_use 10, user_prompt_submit 5, nitpick 2, pre_compact 2, four singletons |
| Retired names still accepted in config  | 31    | `RETIRED_HANDLERS`; the Plan 00323 test keeps them out of the checklist                                                                                    |
| Items the checklist scores              | 25    | 20 handler keys + 2 nitpick handlers + `pseudo_events.nitpick.enabled` + `plan_workflow` config section + "plans in use" (filesystem)                      |
| Registered handlers the checklist names | 22    | 20 + the 2 nitpick handlers                                                                                                                                |
| Registered handlers it does not name    | 94    | 81 % of the registry                                                                                                                                       |

The plan's overview says 21 of 110. The registry has grown since it was
written, and the overview counted the nitpick pair once; 22 of 116 is the
figure at this commit, and the proportion is the same.

### The fair denominator

Not every uncovered handler is a gap. Removing what `optimise` should not
score:

| Exclusion                                                                                         | Handlers | Names                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status-line components — display preferences, not project fit                                     | 14       | the whole `status_line` event dir                                                                                                                                                   |
| Daemon-integrity plumbing — disabling one blinds the daemon, no project profile makes it optional | 6        | `disclosure_reset_session_start`, `disclosure_reset_pre_compact`, `project_handler_load_checker`, `hook_registration_checker`, `config_optimisation_reminder`, `contract_staleness` |
| **Scorable**                                                                                      | **96**   |                                                                                                                                                                                     |
| of which the checklist covers                                                                     | 22       |                                                                                                                                                                                     |
| **Uncovered, scorable — the real gap**                                                            | **74**   |                                                                                                                                                                                     |

Within the 74, one further split matters for Phase 2, because the
checklist's rule is "only recommend enabling, never disabling":

- **13 handlers are off by default on purpose** (`get_default_enabled()` is
  `False`): `bash_safe_mode`, `flaggable_content_channel_guard`,
  `flaggable_work_advisor`, `quarantine_artefact_read_guard`,
  `goal_injection`, `compaction_signal`, `model_fallback_detector`,
  `skill_opportunity_detector`, `tool_disable_advisor`,
  `idle_housekeeping_advisory`, `lsp_enforcement`, plus two status-line
  ones already excluded (`context_sidecar`, `daemon_stats`). For these
  "enable it" is not a safe blanket recommendation — the template comment on
  `model_fallback_detector` literally says "Probably leave OFF". **The
  checklist already contains one of them (`lsp_enforcement`) and scores a
  client down for respecting the default**, which is direct evidence that
  the hardcoded list does not distinguish opt-in from default-on.
- The remaining 61 uncovered scorable handlers are default-on. A client on
  defaults has them on, so the blind spot bites only where a config
  explicitly disabled one or was generated from an older template — which
  is exactly the population `optimise` exists for.

Coverage of the 96 scorable handlers by event, so the shape of the gap is
visible:

| Event dir              | Scorable | Covered | Uncovered (examples)                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pre_tool_use           | 57       | 14      | 43 — every content guard (`sensitive_content`, `secret_file_guard`, `project_containment`, `write_clobber_guard`, `pipe_blocker`, `root_recursion_guard`), the git-hygiene set (`git_stash`, `ancestry_preserving_merge`, `github_auto_close_keywords`, `git_message_backtick`, `worktree_file_copy`), both QA gates (`plan_qa_*`, `docs_qa_*`, `staged_lint_gate`), `comment_*`, `markdown_organization`, `remote_docs_*` |
| session_start          | 17       | 2       | 15 — `git_upstream_checker`, `gitignore_safety_checker`, `secret_file_hygiene_checker`, `plan_qa_sweep`, `docs_qa_sweep`, `monorepo_detector`, `plan_workflow_asset_checker`, …                                                                                                                                                                                                                                            |
| post_tool_use          | 10       | 1       | 9 — `validate_eslint_on_write`, `markdown_table_formatter`, `git_hooks_executable_fixer`, `background_process_tracker`, `command_hints`, …                                                                                                                                                                                                                                                                                 |
| user_prompt_submit     | 5        | 2       | 3 — `standing_authorisations`, `failsafe_cron_blockage_suppressor`, `idle_housekeeping_advisory`                                                                                                                                                                                                                                                                                                                           |
| nitpick                | 2        | 2       | 0                                                                                                                                                                                                                                                                                                                                                                                                                          |
| stop                   | 1        | 1       | 0                                                                                                                                                                                                                                                                                                                                                                                                                          |
| subagent_stop          | 1        | 0       | 1 — `subagent_report_size_blocker`                                                                                                                                                                                                                                                                                                                                                                                         |
| permission_request     | 1        | 0       | 1 — `auto_approve_reads`                                                                                                                                                                                                                                                                                                                                                                                                   |
| pre_compact            | 1        | 0       | 1 — `compaction_signal`                                                                                                                                                                                                                                                                                                                                                                                                    |
| worktree_create/remove | 2        | 0       | 2                                                                                                                                                                                                                                                                                                                                                                                                                          |

Three defects in the checklist itself, found while resolving it:

1. **Its nitpick names are YAML keys, not registry keys.** The checklist
   scores `pseudo_events.nitpick.handlers.hedging_language` and
   `…dismissive_language`; the registry `config_key`s are
   `hedging_language_nitpick` / `dismissive_language_nitpick`. The Plan
   00323 resolver test only matches the `handlers.<event>.<name>` shape, so
   these two are not checked at all — a rename would go unnoticed.
2. **`daemon_restart_verifier` is filed under Code Quality** but the
   registry gives it the safety band (priority 10, tag `safety`,
   `advisory`). Only a hand-placed item can sit in the wrong area.
3. **The overall total is a literal `25`** in three places of the heredoc
   (score line, percentage, "if score = 25/25"). Any registry-derived list
   must compute it.

---

## Task 1.3 — Are the five areas still the right taxonomy?

The five areas are Safety; Stop & Message Quality; Plan Workflow; Code
Quality; Daemon Settings. As a reading order for a human they are fine. As a
partition for a derived list they fail the plan's own test — "a rule that
assigns any new handler to an area without human judgement" — because
nothing in the registry names them. What the registry DOES carry:

- **Event type** (11 dirs). Mechanical and total, but useless as a taxonomy:
  57 of 96 scorable handlers are `pre_tool_use`.
- **Priority bands** (`constants/priority.py`: safety 10–20, workflow, QA,
  advisory 56–60…). Ordinal, overlapping across events, documented only in
  comments — not machine-readable as a category.
- **Tags** (`constants/tags.py`, `HandlerTag`). The closest thing to a
  category system, and the one a derived list should use — but today it
  cannot be used as-is:
  - **11 handlers carry no tags at all**, three of them on the current
    checklist's Safety list: `curl_pipe_shell`, `dangerous_permissions`,
    `pip_break_system`, `sudo_pip`, `lock_file_edit_blocker`,
    `artifact_publish_blocker`, `global_npm_advisor`,
    `validate_instruction_content`, `tool_disable_advisor`,
    `worktree_create`, `worktree_remove`.
  - Tags are multi-valued and the vocabulary is mixed-purpose: `workflow`
    is on 40 handlers, `advisory` on 40, `non-terminal` on 64 (a verdict
    property, not a category), `safety` on 23, `planning` on 11,
    `qa-enforcement` on 7, `environment` on 11, `documentation` on 3.
  - No handler is tagged with anything resembling "stop quality" or
    "daemon settings".

### Recommendation: keep five areas, derive membership from a precedence rule over tags, fail closed

A derived checklist needs a single-valued area per handler. The least
invasive way to get one is a precedence list evaluated over the existing
tags, with the first match winning and **no match failing the Phase 4 gate**
(so a new handler cannot ship unclassified — the same shape as the
dispatchability test). The rule below was run against the registry
(`untracked/scratch/area_rule.py`, not committed); the populations are
measured, not estimated:

| Order | Rule                                                                                     | Area (proposed name)               | Measured population (of 96) |
| ----- | ---------------------------------------------------------------------------------------- | ---------------------------------- | --------------------------- |
| 0     | event dir `status_line`, or the 6 daemon-integrity handlers (declared opt-out, Task 2.2) | excluded                           | 20 (not in the 96)          |
| 1     | tag `safety`                                                                             | Safety                             | 21                          |
| 2     | tag `planning` or `documentation`                                                        | Plan & documentation workflow      | 14                          |
| 3     | tag `qa-enforcement`, `validation`, `content-quality` or `tdd`                           | Code & content quality             | 12                          |
| 4     | event `stop`/`subagent_stop`/`nitpick`, or tag `context-injection`                       | Agent behaviour & message quality  | 2                           |
| 5     | tag `environment`, `daemon`, `health`, or event `session_start`                          | Session & environment              | 14                          |
| 6     | anything else                                                                            | gate failure: tag it or opt it out | 33                          |

Two things the measurement shows that a paper design would not have:

- **Event rules must run before tag rules.** `auto_continue_stop` and
  `failsafe_cron_blockage_suppressor` carry the `planning` tag and land in
  "Plan & documentation workflow" under the order above, leaving "Agent
  behaviour" with only `git_context_injector` and
  `subagent_report_size_blocker`. The nitpick pair land in "Code & content
  quality" through `content-quality` for the same reason. Rule 4 belongs
  ahead of rule 2.
- **The remainder is 33 handlers, a third of the scorable set**, not a
  handful. It is the 11 untagged handlers plus 22 whose only tags are
  `workflow`/`advisory`/verdict-properties: `agent_isolation_advisor`,
  `ask_user_question_blocker`, `auto_approve_reads`,
  `background_process_tracker`, `budget_exhaustion_detector`,
  `command_hints`, `compaction_signal`, `critical_thinking_advisory`,
  `dispatch_declaration`, `flaggable_work_advisor`, `gh_issue_comments`,
  `gh_pr_comments`, `git_hooks_executable_fixer`, `goal_injection`,
  `idle_housekeeping_advisory`, `lsp_enforcement`,
  `markdown_table_formatter`, `npm_command`, `remote_docs_commit_gate`,
  `remote_docs_provenance`, `remote_docs_routing`,
  `standing_authorisations`, `web_search_year`. Four of the current
  checklist's own items (`critical_thinking_advisory`, `lsp_enforcement`,
  `curl_pipe_shell`, `dangerous_permissions`) are in it.

Why tags and not a new `area=` attribute on every handler: the tags are
already the declared categorisation, are already validated as a vocabulary,
and already drive `enable_tags`/`disable_tags`. Adding a second parallel
attribute would create the next drift. The cost is a one-off tagging pass —
larger than the untagged 11, because the 22 `workflow`-only handlers need a
category tag too — and a decision on whether a sixth area ("Workflow
guidance") absorbs the remainder instead.

Which five (or six) names the areas carry is an owner call; the load-bearing
change is that membership is computed, and the report's per-area
denominators and total are computed with it.

---

## Decisions the owner must make for Phases 2–4

1. **Opt-out mechanism at the handler (Task 2.2).** Options measured here:
   (a) a `HandlerTag` such as `optimise-exempt`, using the existing tag
   vocabulary; (b) a boolean on `Handler` beside `get_default_enabled()`;
   (c) event-dir exclusion for `status_line` plus one of (a)/(b) for the six
   integrity handlers. Recommendation: (c), because 14 of the 20 exclusions
   fall out of the event dir with no per-handler declaration.
2. **What `optimise` says about default-off handlers.** Today it recommends
   enabling `lsp_enforcement` although its default is off. Choose: never
   recommend a default-off handler (report it as "available, opt-in"), or
   recommend it only when the project profile says so (which needs a
   profile rule per handler and is Phase 2 scope creep).
3. **Area names and count (Task 1.3).** Accept the five proposed derived
   areas, or add a sixth for the rule-6 remainder rather than tagging each
   of those handlers into an existing area.
4. **Which subcommands become documentation (Task 1.1).** The table above
   proposes routing 6 and documenting 10. The one genuine judgement call is
   `report` versus `bug-report`: merge, or keep both routed.
5. **The full-housekeeping step list and order (Task 3.1).** Candidate
   steps, grouped by whether they mutate: report-only —
   `plan-qa --sweep`, `docs-qa --sweep`, `check-worktree-seed`,
   `audit-handler-keys`, `check-permissions`, `disk-usage`, `remote-docs check`, `verdicts`, `block-report`, `harvest-background`, `worktree-reap`
   (no `--reap`), `skill-scan`; mutating — `optimise` (edits config,
   restarts daemon), `format-markdown`, `regenerate-docs`,
   `reconcile-settings`, `remote-docs refresh`, `prune-venvs`,
   `check-permissions --fix`, `worktree-reap --reap`. The order question is
   whether `optimise` (which restarts the daemon) runs first or last.
6. **Which steps may act without confirmation (Task 3.2).** The plan's own
   default is report-everything, act-on-request. The candidates for
   unconfirmed action are the idempotent, reversible formatters
   (`format-markdown`, `regenerate-docs`); everything else in the mutating
   list above changes config, settings, or deletes files.
7. **Whether the existing `idle_housekeeping_advisory` (opt-in, beta,
   report-first, sub-agent-per-audit) is the vehicle for Phase 3 or a
   separate thing.** It already encodes the "subagents return what they
   changed, not what they read" shape from Task 3.3, but names only two
   audits and is off by default.

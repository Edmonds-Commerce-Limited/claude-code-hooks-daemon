# Plan 00560: code facts behind GitHub #155

Each claim the issue makes about the code, checked against this repository at the commit the plan was written on (`e4841e27d`). Paths are under `src/claude_code_hooks_daemon/` unless stated. The issue text is a hypothesis; this file is what the code says.

## F1. `project_containment` steers durable work into the scratch directory (CONFIRMED)

The scratch directory is `untracked/scratch` (`constants/paths.py:67`, `SCRATCH_DIR`), shared with `pipe_blocker`.

- `handlers/pre_tool_use/project_containment.py:116-117`: the source comment says "Durable work still belongs in `untracked/scratch/` and the guidance says so."
- `:175` (rule `fix`): "`untracked/scratch/` is the scratch location".
- `:183-190` (rule `verbose`): "WRITE IT HERE INSTEAD: untracked/scratch/ - inside the working tree, so it survives container restarts - gitignored, so it never reaches review", then "nothing is lost by writing it somewhere durable".
- `:994-996` (deny message suffix): the session scratchpad is "THROWAWAY ONLY ... anything durable goes in untracked/scratch/".
- `:1037-1042` and `:1069-1070` (handler guidance): "Write scratch to `untracked/scratch/`: inside the working tree so it survives a container restart", and "keep anything you or a teammate might need again in `untracked/scratch/`, which is durable".

So the handler presents "survives a container restart" as "durable". It never says that git does not carry the directory to the remote, which is the property that matters for an asset. The issue's claim is accurate.

## F2. `markdown_organization` allows markdown anywhere under `untracked/` (CONFIRMED, wider than the issue says)

- `handlers/pre_tool_use/markdown_organization.py:1366-1368`: any normalised path starting `untracked/` is allowed, with no narrowing to `untracked/scratch/` or to any file shape.
- `:58` lists "./untracked/ - Ad-hoc temporary docs" among the allowed locations, and `:73` routes "Is this temporary/ad-hoc? -> untracked/".
- `:348` includes `untracked/` among the project-root markers, so `untracked/scratch/x/.claude/NOTE.md` is rooted at `untracked/` and allowed (Plan 00390 N1).

The allowance covers the whole ignored root, not just the scratch directory. A review written to `untracked/briefs/` or `untracked/reports/` passes as well.

## F3. `dispatch_declaration` accepts any path, ignored or not, as a non-plan destination (CONFIRMED, wider than the issue says)

- `handlers/pre_tool_use/dispatch_declaration.py:248-252` (`_has_declaration`): a dispatch counts as declared if it names a plan folder, or if it says "not plan work" AND `_prompt_declares_destination` is true.
- `:131-152` (`_prompt_declares_destination`): true when a destination keyword (`:92-96`: write/save/report/output/store/file) and ANY path-shaped token (`:105`, `\S*/\S+`) appear in the same clause. Nothing checks whether that path is tracked, ignored or even inside the repository: `/tmp/x.md` and `untracked/scratch/x.md` both count.
- The default fallback is `DEFAULT_REPORT_DIR` = `untracked/agent-reports/` (`:64`, `utils/subagent_report_paths.py:44`). The contract text (`:262-267`) offers it as the plan-less destination and says it is gitignored.
- The only push-back on an ignored destination is the N5 advisory (`:280-297`). It fires only when the prompt names a plan folder AND the fallback directory.
- Strict mode (`:115-126`) requires a declaration but applies the same test, so an ignored destination satisfies it.

## F4. `subagent_report_persistence` saves every reply to an ignored store and prunes it (CONFIRMED)

- `handlers/subagent_stop/subagent_report_persistence.py:119-133`: runs on every non-synthetic SubagentStop, re-entries included.
- `:157-207`: writes `last_assistant_message` to a new file under `report_dir`, which defaults to `DEFAULT_PERSISTED_REPORT_DIR` = `untracked/agent-reports/auto/` (`:110`, `utils/subagent_report_paths.py:56`). It always allows the stop.
- `:80-81`, `:190-205`: after each write it prunes `*.md` in that directory to 500 files and 30 days (`max_kept_reports`, `max_report_age_days`).
- Nothing compares a saved reply with a tracked counterpart: not at save, and not before pruning. A reply whose only copy is this store is deleted once it is old enough or pushed out by newer replies.

## F5. The report-path verifier checks claims, not declarations (CONFIRMED)

- `handlers/subagent_stop/subagent_report_path_verifier.py:53-59`: it judges only a `.md` path that a past-tense write verb ("written", "wrote", "saved", "created") governs in the agent's FINAL MESSAGE. Paths outside the project root are skipped (module docstring).
- It does not know the destination the dispatch declared. An agent that was told to write `CLAUDE/Plan/NNNNN-x/subagent-reports/r.md`, wrote nothing there and never claimed the path is not caught. Item 5 needs the declared destination recorded at dispatch and read at SubagentStop. `untracked/agent-dispatch-registry/` exists but is NOT keyed per dispatch: it holds one file per `(session_id, name)`, records named dispatches only, and a repeated name overwrites the earlier row. It cannot carry a per-dispatch declared destination as it stands; Phase 1 decides whether to extend it or record the destination elsewhere.

## F6. The Plan 00470 stale-scratch report is not a SessionStart sweep, and it suggests deleting (CONFIRMED, relevant to item 7)

- The report is built by `utils/stale_litter.py:148-196` (`collect_scratch_report`) over `untracked/scratch` (`:35`), with a 14-day default (`:38`, `DEFAULT_SCRATCH_DAYS`).
- Its only caller is `handlers/user_prompt_submit/idle_housekeeping_advisor.py:302`, a **UserPromptSubmit** handler that fires on repeated no-op recovery ticks. It is off by default (`:159`, `default_enabled = False`) and gated on the project's `autonomy:` config (`:163`).
- The command the report offers is `find <scratch> -type f -mmin +<N> -delete` (`stale_litter.py:193`). That is the opposite of item 7's three choices: it deletes every old file, assets included, without asking which ones held something worth keeping. Judged only by age, it cannot tell a consumed commit body from an unconsumed review.

## F7. Nothing judges scratch at Stop or SubagentStop (CONFIRMED)

- The Stop handlers are `auto_continue_stop`, `background_task_recorder`, `branch_stop_guard` (Plan 00558, built since), `cron_stop_enforcer`, `goal_loop_detector`, `idle_workable_issue_stop_gate`, `teammate_reap_advisor` and `usage_pause_stop_gate` (`handlers/stop/`). None reads the files a session created.
- Relevant priorities (`constants/priority.py`): `USAGE_PAUSE_STOP_GATE = 6` (`:154`), `BRANCH_STOP_GUARD = 9` (`:218`), `SUBAGENT_HANDOFF_GATE = 11` (`:213`), `BRANCH_SUBAGENT_STOP_GUARD = 12` (`:216`), `AUTO_CONTINUE_STOP = 15` (`:231`; this project overrides it to 10, `:128-129`). The owner has since dropped this plan's stop gate (DESIGN.md section 0), so no slot is needed.

## F8. Reusable pieces

- `core/utils.py:670` `get_written_file_paths(hook_input)`: the accessor `lint_on_edit` and `sed_blocker` already use to find the files a Bash command AUTHORS (redirect, `tee`, heredoc). The ledger and the allowlist deny can use it for Bash-authored writes.
- Plan 00558 DESIGN.md section 13 (now `CLAUDE/Plan/Completed/00558-git-branch-hygiene-sweep/`) records evacuations in the session's spend-ledger state keyed by turn. The scratch ledger has the same keying problem (main thread vs sub-agent) and should share that storage decision.

## F9. Other ignored homes the daemon itself writes to

These are registered stores, not scratch, and the allowlist must name them:

- `bin/echd-capture:72`: captures go to `untracked/captures/`, not the scratch directory.
- `issue_report/upstream.py:13`: issue bodies go to `untracked/issue-reports/<report>.md`.
- `utils/subagent_report_paths.py:44,56`: `untracked/agent-reports/` and `.../auto/`.
- `issue_report/reproduction.py:55`: reproductions use fixtures under `untracked/scratch/`.
- `CLAUDE/Plan/mkplan.bash:447-448` and `CLAUDE/PlanJournalling.md:200-202` document journal bodies under `untracked/scratch/` with no fixed name pattern (examples `entry.md`, `fix.md`; live bodies are named like `j558-standin.md`). A name-pattern allowlist cannot recognise them; consumption by `mkplan.bash --journal` must.

## F10. This repository's own practice (measured at plan time)

- `untracked/scratch/`: 90,346 files, 1.4 GB, 97 subdirectories. 2,057 files sit at the top level, 1,846 of them older than 24 hours, and 547 of them are `.md`.
- The most common top-level name prefixes are `brief` (136), `issue` (130), `wt` (79), `journal` (78), `ci` (78), `merge` (64), `qa` (62), `setup` (61), `restart` (52), `triage` (33), `close` (33). Most are consumed shapes: briefs read by a dispatched agent, issue bodies passed to `gh --body-file`, journal bodies passed to `mkplan.bash --journal`, and QA or CI captures read back.
- `untracked/agent-reports/` holds 575 files. `untracked/briefs/` holds `*-report.md` files (for example `ci-tiers-report.md`, `land-worktree-n466-lifecycle-report.md`). Those are sub-agent reports in an ignored directory: the asset class this plan is about.
- `untracked/worktrees/` holds this repository's linked worktrees (Plan 00558's territory). `untracked/` also holds `worktree-archive/` and `deleted-branches.bundle`, which are rescue copies of the kind the issue's creation path 3 describes.
- 32 files in `CLAUDE/`, `.claude/agents/`, `.claude/skills/` and `CLAUDE.md` (plans excluded) mention `untracked/scratch`. So do 11 shipped source files under `src/` (skills, install templates, `src/CLAUDE.md`), `README.md` and two `docs/guides/` files. The `.claude/skills/` copies are deployed from `src/`, so the sweep must edit the `src/` originals or an upgrade undoes it.

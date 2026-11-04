# Plan 00560: design (Phase 1, Tasks 1.1, 1.2 and 1.5)

This settles the design questions in [DESIGN-QUESTIONS.md](DESIGN-QUESTIONS.md) against the rulings made so far. Paths are under `src/claude_code_hooks_daemon/` unless stated. Code claims were re-checked at the commit this file was written on; see the Task 1.5 journal entry for the list.

## 0. Rulings this design rests on

| Ruling                                                                                                                                              | Source                                                                                                   | Standing                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Q1: no fallback report store. A dispatched agent with a durable report and no plan folder stops and asks for one.                                   | Owner, [JOURNAL/2026-11-04/094151Z-decision-b2519a.md](JOURNAL/2026-11-04/094151Z-decision-b2519a.md)    | Final                                      |
| Drop the consumption ledger and the unused-scratch stop gate (Goals 4, 5; Phase 4; the consumption parts of Phase 6). Q2 and Q7 are moot.           | Owner, same entry                                                                                        | Final                                      |
| New: a command that consumes a scratch file must chain `&& rm <file>`; the unchained form is blocked; the consuming commands are listed explicitly. | Owner, same entry                                                                                        | Final                                      |
| Scratch file-name whitelist: yes, starting from the D4 shapes plus a `journal-*.md` convention; `*.patch`/`*.diff` excluded.                        | Stand-in, [JOURNAL/2026-11-04/223017Z-decision-ba17c1.md](JOURNAL/2026-11-04/223017Z-decision-ba17c1.md) | **Provisional**: the owner may overturn it |
| Q3: configured roots, default `untracked/`.                                                                                                         | Stand-in, same entry                                                                                     | **Provisional**                            |
| Q4: baseline; judge only files after it.                                                                                                            | Stand-in, same entry                                                                                     | **Provisional**                            |
| Q6: 24 hours; the 14-day key is mapped onto the new one by a config-changes entry.                                                                  | Stand-in, same entry                                                                                     | **Provisional**                            |
| Q5: rollout mode (advise one release, then block; or block at once).                                                                                | Declined by the stand-in                                                                                 | **Open, owner only**                       |

Every section below that rests on a provisional ruling says so. If the owner overturns one, only that section changes.

## D1. What counts as consumption: DROPPED (owner ruling)

The owner dropped usage tracking as over-engineering (094151Z entry). Nothing records whether a scratch file was used. Its replacement is narrower and stateless: the consume-then-remove rule in section 7, which judges one Bash command at a time and needs no memory between tool calls.

What is lost, deliberately: a brief read by a dispatched agent, or a capture read back, is never "cleared". Such files fall to the SessionStart age sweep (section 6) instead.

## D2. Where the ledger lives: DROPPED (owner ruling)

No ledger, so no storage or keying decision. Nothing in this plan adds per-session scratch state.

## D3. How earlier sessions' files are judged: REDUCED (owner ruling)

With no ledger there is no "earlier session's unconsumed file". The SessionStart sweep (section 6) judges every file under the scratch directory by age alone, against the baseline (section 6, provisional Q4).

## D4. The scratch-shape whitelist and registered stores (provisional: stand-in whitelist ruling)

### Where it applies

Only to a **new** file: a `Write` whose `file_path` does not exist yet, or a path a Bash command authors (`core/utils.py:670` `get_written_file_paths`: redirect, `tee`, heredoc) that does not exist yet. `Edit`, and overwriting or appending to an existing file, are never judged, so the existing backlog never blocks work (Q4).

A file a command merely relocates (`cp`, `mv`) is not seen by `get_written_file_paths`; that gap is accepted and documented in the guidance, as `lint_on_edit` already does.

### The verdict

For a new file under a configured ignored root (D5):

1. Inside a linked worktree (`untracked/worktrees/<name>/...`, and Claude Code's `.claude/worktrees/` if a project adds `.claude/` as a root): **not judged**. That is another checkout's working tree, and its paths are judged relative to that checkout's own root.
2. Inside the scratch directory (`ProjectPath.SCRATCH_DIR`, `constants/paths.py:67`) at any depth: **allowed if the basename matches a shape**, else denied.
3. Anywhere else under the root (including `untracked/briefs/`, `untracked/reports/`, `untracked/qa/`): **denied**. Registered stores are written by the daemon's own code or tooling, never by an agent's tool call, so they need no exemption in this deny (see "Registered stores").

Content never decides the verdict. It only picks the suggested home in the deny text: a file whose name or first heading says report, review, design, findings or decision is pointed at a plan folder (`<plan>/subagent-reports/` or a supporting doc); anything else at "rename it to a scratch shape if it is consumed this session, otherwise a plan folder, a journal entry, a pushed commit or an issue".

### Default shapes (basename globs, case-sensitive)

| Kind                                                      | Globs                                                                                                                                                        |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Message and body files, consumed by a command (section 7) | `commit-*.txt`, `commit-*.md`, `merge-*.txt`, `merge-*.md`, `tag-*.txt`, `pr-*.md`, `issue-*.md`, `issue-*.json`, `comment-*.md`, `close-*.md`, `gh-*.md`    |
| Journal bodies                                            | `journal-*.md` (the convention `CLAUDE/PlanJournalling.md` already shows; `mkplan.bash`'s own usage examples `entry.md` and `fix.md` move to it in Task 2.3) |
| Briefs                                                    | `brief-*.md`                                                                                                                                                 |
| Captures                                                  | `*.txt`, `*.log`, `*.out`, `*.json`, `*.jsonl`, `*.tsv`                                                                                                      |

Not shapes, so denied by default: any other `*.md`; `*.patch` and `*.diff` (Plan 00558 Goal 12, evacuation); scripts (`*.py`, `*.sh`, `*.bash`), because a diagnostic script worth keeping belongs in a commit. A project adds globs through `scratch.shapes.extra` (section 8) rather than by editing the defaults.

Known limit: `*.txt` admits a report written as plain text. The whitelist is a speed bump that makes the agent choose a name, and the deny text is where the teaching happens; the stand-in's ruling accepts that trade.

Measured against this repository's scratch directory while writing this design, the top-level `.md` prefixes `brief` and `journal` already conform; ad-hoc names (`p555-*`, `501-*`, `j558-*`, `stand*`, `triage-*`) do not, and would be denied at creation. That is the intended friction, and the reason Q5's rollout mode matters.

### Registered stores

Directories under the root that the daemon or its tooling writes by its own code. They are named in config so the SessionStart sweep (section 6) leaves them alone and the guidance can list them; the PreToolUse deny does not need them, because an agent writing into one by hand is exactly the case to deny. This answers DESIGN-QUESTIONS.md D4's open point: a store admits only the files its owning tool writes, so `untracked/qa/00552-full-gate-report.md`, written by hand, would be denied today.

Defaults: `untracked/captures/` (`bin/echd-capture:72`), `untracked/issue-reports/` (`issue_report/upstream.py:13`), `untracked/agent-reports/` and its `auto/` (`utils/subagent_report_paths.py:44,56`), `untracked/agent-dispatch-registry/` (`utils/agent_dispatch_registry.py`), `untracked/worktrees/`, `untracked/qa/`, and the daemon's runtime files (venvs, sockets, logs, caches).

### One predicate, two handlers

`markdown_organization` (Task 2.2) and the new deny (Phase 5) both judge `.md` under `untracked/`. Both call one shared predicate (a new `utils/scratch_shapes.py`, `is_allowed_new_scratch_path(path, config)`), so they cannot disagree. `markdown_organization` stops treating `untracked/` as a general home (`markdown_organization.py:1366-1368`) and defers to the predicate; it keeps its migration-safe option from Task 2.2.

## D5. Scope of the ignored root (provisional: stand-in Q3)

`scratch.roots`, default `["untracked/"]`, repository-root-relative. No `git check-ignore` subprocess per write. Widened only on a field report.

## D6. A saved reply's tracked counterpart: REDUCED (owner Q1)

Under Q1 a declared destination is always a plan folder, which is tracked by definition. So:

- **Task 3.1** (`dispatch_declaration`): "not plan work" stays a valid declaration only for a dispatch with no durable output (a reply that fits inline). A destination under a configured root or outside the repository never counts as a declaration (`_prompt_declares_destination`, `dispatch_declaration.py:131`). The contract text drops the gitignored fallback (`:263-267`) and says: an agent with a durable report and no plan folder stops and asks the coordinator for one. The N5 advisory (`:280-297`) loses its purpose and is removed with the fallback.
- **Task 3.2** (declared destination must exist): no dispatch-time record. At SubagentStop the verifier reads the dispatch prompt from the sub-agent's own transcript (`agent_transcript_path`, `constants/protocol.py:98`, already read by `subagent_cache_aggregator.py:311`) and re-applies the same plan-folder parser. If the prompt named a concrete file path inside a plan folder and that file does not exist, the stop is refused (the `MAX_STOP_BLOCKS` = 3 never-strand pattern, `subagent_handoff_gate.py:43`). `untracked/agent-dispatch-registry/` is not extended: it is keyed by `(session_id, name)` and records named dispatches only (CODE-FACTS.md F5). That the first user record of a sub-agent transcript is its dispatch prompt is to be confirmed on a live payload (`scripts/debug_hooks.sh`) as the first step of Task 3.2.
- **Task 6.2** (saved replies with no counterpart): reduced to the replies Task 3.2 refused and then let go under the never-strand rule. The verifier appends such a reply's path to a small list in the daemon's untracked state; the SessionStart sweep reports it before `subagent_report_persistence` prunes it (500 files / 30 days, `subagent_report_persistence.py:80-81`). Reporting every saved reply without a counterpart would list almost every dispatch, since most never owe a file.

## 6. SessionStart sweep (provisional: stand-in Q4, Q6)

- A new SessionStart handler, `scratch_sweep`, printing directly after `branch_sweep` (`Priority.BRANCH_SWEEP` = 56, `constants/priority.py:558`) so the two read as one housekeeping block. It reuses `stale_litter`'s scan budget (`SCRATCH_MAX_ENTRIES`, `SCRATCH_BUDGET_SECONDS`, `utils/stale_litter.py:41,44`), is silent on a clean tree, and lists at most a configured number of entries with a total.
- Reports files under the scratch directory older than `scratch.sweep.max_age_hours` (default 24, Q6), and any file under a root that is neither in the scratch directory nor in a registered store. Each line gets the three choices: use it now (then remove it), move it to a tracked home, or delete it. No bulk-delete command is ever printed.
- **Baseline (Q4):** `scratch.sweep.baseline_before`, an ISO-8601 timestamp, default unset. Files whose mtime is older are counted ("N files predate the baseline"), never listed. The stand-in's ruling says "a baseline listing in this plan's folder"; this design records the baseline as a cutoff time instead, because a tracked listing of this repository's backlog would put tens of thousands of paths into git for the same verdict. The mechanism the stand-in chose (judge only new files) is unchanged. This repository sets the cutoff to the time Task 7.3 runs.
- **Task 6.3:** `stale_litter.collect_scratch_report` (`:148`) loses its `find ... -delete` suggestion (`:193`) and prints the three choices; `idle_housekeeping_advisor`'s `stale_scratch_days` option (`idle_housekeeping_advisor.py:72`, default `DEFAULT_SCRATCH_DAYS` = 14 at `stale_litter.py:38`) is renamed to `scratch.sweep.max_age_hours` with a config-changes `renamed` entry, read as a fallback for one release (the 00558 `branch_count_advisor` precedent).

## 7. Consume-then-remove (owner's new requirement)

A new PreToolUse Bash rule, `R-SCRATCH-CONSUME-UNCHAINED`, in a new handler `scratch_consume_chain`.

- **Consumers (explicit list, config `scratch.consume_chain.consumers`):** `git commit -F/--file`, `git merge -F/--file`, `git tag -F/--file`, `gh issue|pr create|comment|edit|close` with `--body-file`/`-F`, `gh release create|edit --notes-file/-F`, and `mkplan.bash --journal <plan> <category> <body-file>`. `gh api` is excluded (its `-F` is a field), as `sensitive_content` already does.
- **Judged file:** the consumer's file operand, only when it resolves inside the scratch directory. A tracked file passed to `-F` is never required to be removed. `-` (stdin) is not a file.
- **Satisfied when** a later step of the same command is `rm` (with or without `-f`, `--`) naming that file, and every list operator between the consumer and that `rm` is `&&`. So `git commit -F commit-1.txt && git push && rm commit-1.txt` passes; `; rm`, `|| rm`, a separate tool call, or no `rm` is denied. Parsed with `utils/git_commit_parsing.py` `simple_commands` (`:966`), whose `SimpleCommand.operator` carries the list operator per step (`:942`).
- **Deny text:** the exact corrected command (the original plus `&& rm -- <file>`), and why: the file is gone only when the command it fed succeeded, so a failure leaves it for a retry, and a success leaves nothing for the sweep.
- **Docs:** `CLAUDE/PlanJournalling.md:199-209` currently says the body file "stays behind after the append"; Task 2.3 rewrites that and the `mkplan.bash` usage examples to the chained form.
- **Not covered:** a body read through `-m "$(cat file)"`, a brief named in an Agent dispatch, and a capture read back. Those age out through the sweep.

## 8. Config surface: one top-level `scratch:` block

Decision: one top-level block, a new `ScratchConfig` in `config/models.py` beside `BranchesConfig` (`config/models.py:2393`), for the same reason Plan 00558 chose `branches:` (its DESIGN.md section 1): the PreToolUse deny, `markdown_organization`, the consume-chain rule and the SessionStart sweep must read one list, and handler options are per handler. `extra="forbid"`.

```yaml
scratch:
  roots: ["untracked/"]          # D5, provisional Q3
  shapes:
    defaults: true               # D4 table; false drops the built-in list
    extra: []                    # basename globs a project adds
  stores: []                     # added to the built-in registered stores (D4)
  shape_deny:
    mode: block                  # block | advise | off; model default is Q5 (open)
  consume_chain:
    mode: block                  # block | advise | off; model default is Q5 (open)
    consumers: []                # added to the built-in list (section 7)
  sweep:
    max_age_hours: 24            # provisional Q6
    baseline_before: null        # provisional Q4; ISO-8601 cutoff
    max_listed: 50
```

The `mode` defaults shown are placeholders until Q5 is answered; this repository's own config sets `block` whichever way Q5 goes, as the plan already proposes for dogfooding. Config-changes entries (`added` for every key, `renamed` for `stale_scratch_days`) go into `CLAUDE/UPGRADES/UNRELEASED/config-changes/` in Task 7.2.

## 9. What is left to the owner or to Task 1.3

- **Q5** (rollout mode): sets the model default of `shape_deny.mode` and `consume_chain.mode`. Open.
- **Task 1.3** (shared Stop design with Plan 00558): this plan no longer adds a Stop or SubagentStop gate, so the shared registration, priority and never-strand design has nothing left to share except Task 3.2's refusal (a SubagentStop handler, which reuses the `MAX_STOP_BLOCKS` pattern on its own) and the sweep's placement beside `branch_sweep` (section 6). Plan 00558 is Complete and its guards are built (`handlers/stop/branch_stop_guard.py`, `handlers/subagent_stop/branch_subagent_stop_guard.py`). Whether to close Task 1.3 as reduced, or to extend 00558's `BRANCH_LIMIT_PRINCIPLE` (`constants/branch_guard.py:9`) with "a file in scratch is not a record", is for the coordinator to confirm.
- **Backlog triage:** whether and when the owner hand-triages the `*-report.md` files in `untracked/briefs/` and `untracked/agent-reports/` is the owner's call (stand-in entry).

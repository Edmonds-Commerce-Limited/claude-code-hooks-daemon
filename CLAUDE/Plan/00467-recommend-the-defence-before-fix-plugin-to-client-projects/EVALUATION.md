# Plan 00467: Defence Before Fix plugin dogfood evaluation (Task 1.2)

The evidence for each Task 1.2 criterion. The subject is plugin 0.1.1, pinned to the source
commit in its `SPEC-VERSION` (`754e508`), as cached at
`.claude/ccy/plugins/cache/defence-before-fix/defence-before-fix/0.1.1/`. Plugin paths below are
relative to that directory. Upstream drafts are in [upstream-drafts/](upstream-drafts/).

**Criteria status**: 1, 2, 4, 5 and 6 have evidence. Criterion 3 (auto-trigger) is judged from
the description only, and nobody has observed it live. So Task 1.2 stays open until one
logged-in session runs the probe prompts below.

## Criterion 1: does it find this project's detectors?

**No.** Here is what `skills/dbf/SKILL.md` step 1 does in this repository:

| Step (SKILL.md)                                                                                                              | What happens here                                                                                                                                                                                                                                                                                                            |
| ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Manifest declaration (`:42-46`, and `project-prompt.md:94-98`): only `composer.json` and `package.json` keys                 | `pyproject.toml` has no key, and none is defined. Nothing is found                                                                                                                                                                                                                                                           |
| Identify the toolchain from `register.json` (`:47-51`); commands exist only for `tools/php-qa-ci.md` and `tools/ts-qa-ci.md` | Python rows: pylint (detector green), bandit, flake8 (amber), mypy, pyright, ruff (red). This repo runs ruff, mypy, bandit and semgrep (`pyproject.toml:48-65`), and **no pylint**. There is **no shell row** at all; `languages` is PHP, JS/TS, Python, Go, Rust, Multi-language                                            |
| Run the listing (`:52-55`, clause 8.5)                                                                                       | This repo has no command that enumerates its defences. `CLAUDE/Security/README.md` is the nearest thing: a table of four categories. The skill would correctly report that as a toolchain gap                                                                                                                                |
| Fallback (`:56-58`): "choose a detector for the language from the register, preferring … green"                              | For a Python defect it picks pylint, which this repo does not run. For a shell defect it picks ast-grep or pre-commit (Multi-language, green). It never opens `scripts/qa/`, `llm_qa.py`, `run_all.sh`, `scripts/qa/semgrep/` (a rule directory that picks up new files, `run_semgrep_check.sh:11-12`) or `CLAUDE/Security/` |
| Searcher keep-out defaults (`agents/independent-searcher.md:15-18`)                                                          | `phpstan.neon`, `qaConfig/`, `eslint.config.*`, `tsQaConfig/`, `rules/`, `.php-qa-ci/`: all PHP and TS. The coordinator has to supply this repo's list by hand                                                                                                                                                               |

The fallback also contradicts the specification it cites. SPEC 1.0.1 section 2, last
paragraph, says the attempt is complete only once the practitioner "has checked the Detectors
the project already runs". The declaration half is upstream #2; the order half is draft
[01](upstream-drafts/01-fallback-skips-project-detectors.md).

## Criterion 2: a real run

**How it was run: by hand, following SKILL.md.** The skill was not offered to this sub-agent
session: `defence-before-fix:dbf` is not in the Skill list, and neither plugin agent is an Agent
type. A headless probe, `claude -p --plugin-dir <cache>` in a scratch repository, proves the
plugin loads. Its `init` event lists the skill `defence-before-fix:dbf` and both
`defence-before-fix:*` agents. But the probe stopped at "Not logged in", so no model turn ran.

**The defect**: `scripts/lib/resolve_venv.sh`'s runnability-probe watchdog ran `sleep` from
`PATH`. Under the hostile `PATH` the resolver exists to survive, it killed a working venv at
once. It was fixed at `766677c1`, and only the acceptance test
`tests/acceptance/test_v391_field_regression.py` caught it.

| Step                                               | What the skill asks for                                                                               | What it produced                                                                                                                                                                                                                                                                                                                                                                                               |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0. Load the spec (`:20-35`)                        | Run `refresh-spec.bash`, read `project-prompt.md` in full, read SPEC §4                               | Run with `CLAUDE_PLUGIN_DATA` set to a scratch directory and `--force`: all five documents fetched, and all byte-identical to the vendored copies. SPEC 1.0.1, DETECTOR 1.0.0, TOOLING 0.2.0. The prompt and the register print version `-` (draft [04](upstream-drafts/04-refresh-spec-cache-dir-and-versions.md))                                                                                            |
| 1. Discover the toolchain                          | Criterion 1                                                                                           | The skill's own route ends at ast-grep. A coordinator who knows this repo picks the Semgrep rule directory or a `scripts/qa/check_*.py` checker, because `CLAUDE/Security/README.md` requires every Defence to be a Detector in `scripts/qa/` wired into `run_all.sh` and `llm_qa.py`                                                                                                                          |
| 2.1 Attribute                                      | Class and hazard in one sentence each                                                                 | **Class**: a shell code path that exists to work under a hostile, stripped or wrong `PATH` (venv resolver, bootstrap or installer prelude, hook entry, diagnostic helper), yet depends on an external command looked up on `PATH`. **Hazard**: when the command is missing or wrong, the path does not fail loudly. It takes a different branch, so the environment it exists to survive gives a wrong verdict |
| 2.2 Independent searcher, before any rule          | Dispatch `defence-before-fix:independent-searcher` with the class, a keep-out list and an output file | Emulated: an `Explore` agent on sonnet (the same Read/Grep/Glob/Bash grant, no Write), given the plugin agent's body verbatim. It found **4 candidate instances** outside the fixed one, and ruled out 3. It did not write the named file (criterion 6). The reply is saved at `untracked/agent-reports/auto/260924-201850-Explore-a1022bc0a685ad3d3.md`                                                       |
| 2.3 Write the rule                                 | A rule wider than the instance, no wider than the hazard; name the next wider rule                    | **Proposed, not built** (out of scope for this task). See below                                                                                                                                                                                                                                                                                                                                                |
| 2.4–2.9, 3 (prove, sweep, fix, permanence, review) | Red commit, sweep and count, fix every instance, blocking gate, conformance review                    | Not executed. Building the defence is implementation, which this task excludes. `conformance-reviewer` was therefore not exercised                                                                                                                                                                                                                                                                             |

**The searcher's candidate instances.** None is fixed; they are handed to the coordinator for
the niggles ledger.

1. `scripts/venv_bootstrap.sh:443` (`_vb_watchdog`): `if [ "$(date +%s)" -ge "$deadline" ]`.
   With no `date`, the test is false for ever, so a hung build is never stopped. I reproduced
   the idiom under `set -euo pipefail`: it prints `integer expression expected`, takes the else
   branch, and does not abort.
2. `scripts/venv_bootstrap.sh:474` (`_vb_judge_stop`): `elapsed=$(($(date +%s) - _VB_CHILD_STARTED))`.
   The searcher reports that a missing `date` yields a negative `elapsed`, so a real timeout is
   classed as a benign stop and the failure marker is not written.
3. `scripts/install/venv.sh:427` (`_venv_detached_build_wait`): `$(date +%s)` in trailing
   arithmetic. A missing `date` makes the function return 1, so a waiter gives up on a live
   build.
4. `scripts/install/daemon_control.sh:40-43` (`_daemon_process_exists`): unguarded `pgrep`. A
   missing `pgrep` reads as "daemon absent". The existing portability test stubs a BSD `pgrep`,
   never an absent one.

It ruled out the `stat` mtime helpers (their failure is a safe cache-miss) and `init.sh:664,684`
(a bare assignment under `set -e` aborts loudly). `scripts/health_check.sh`'s git check it rated
low confidence.

Whether each of these surfaces really must survive a hostile `PATH` is a judgement nobody has
checked. Only `resolve_venv.sh` and `venv_resolver.sh` document it (the searcher's global search
for the wording).

**Detector proposed for the class** (a finding, not implemented):

- **Rule**: a declared inventory of hostile-`PATH` surfaces, in YAML like
  `scripts/qa/fail-open-boundaries.yaml`. The discriminator is a property of the surface, not of
  the code, as in `CLAUDE/Security/FailOpenBoundaries.md`.

- **Checker**: a new `scripts/qa/check_*.py` that flags, inside those files, any command-position
  word that is none of these:

  - a bash builtin or keyword;
  - a function defined in the surface's sourced set;
  - an absolute path.

  A flagged command is allowed when its function guards it with `command -v <name>`, or when its
  line carries a reasoned allow-marker, like `audit_shell.py`'s `-- <reason>` convention.

- **Next wider rule, not built**: every external command in every shell script. Rejected
  because scripts that run after resolution, under a normal `PATH`, do not carry the hazard.

- **Narrower rule, rejected because the search wins**: `sleep` in a watchdog subshell. It misses
  instances 1–4.

- **Known over-match**: a command whose absence aborts loudly under `set -e` (`init.sh`) carries
  no hazard. It needs the marker, or the rule has to learn the `if`/arithmetic contexts where
  `set -e` does not fire.

- **Detector choice is open**. Semgrep's Bash support may not express "not a builtin" (not
  checked). A Python checker with a conservative tokenizer is the surer route.

**Where the skill fell short on this run**:

- It had no route to the project's detectors, and its fallback pointed at a new tool.
- Its searcher could not honour its own output contract.
- Its token cost is well above the projection (criterion 5).

The method itself earned its keep. One independent search, by a single sonnet sub-agent, turned
one acceptance-test catch into a class with four more candidate instances in three other
scripts.

## Criterion 3: auto-trigger, and how it meets the daemon's guards and Plan 00463

**Judged from the description; not observed live.**

- **Triggers** (`SKILL.md:3`): "DBF" and similar, or "fix a bug, a defect, a failing check or a
  red QA run", or "whenever a QA tool prints 'Defence Before Fix' in its failure output".
- **The second trigger never fires here.** No QA tool or handler prints the phrase. It appears
  only in comments (`grep` over `scripts/qa/` and `src/`).
- **The first trigger is broad** in a repository where agents are told to fix red QA
  constantly: the `qa-fixer` agent, `lint_on_edit`'s "fix with Edit", and every red
  `llm_qa.py` run. A red run is usually a detector that has already fired, so the defence
  exists. Running the full method there is expensive (criterion 5). That is draft
  [02](upstream-drafts/02-trigger-on-every-red-qa-run.md), which also carries the three probe
  prompts: A fires correctly, B and C should stay quiet.
- **Daemon guards**:
  - The plugin audit (F1) found every refresh-script invocation shape allowed.
  - A red commit (step 2.4) is not blocked. No git pre-commit hook is installed, and the
    commit-time gates check syntax, sensitive content and plan QA, not test results.
  - When `/dbf` runs in a sub-agent whose brief says "do not commit" (the norm here), step 2.4's
    separate red commit has to go through the coordinator. The skill does not anticipate that.
- **Plan 00463** (full QA is main-thread only; not started):
  - `conformance-reviewer` is always a sub-agent, with `isolation: worktree`. It must run "the
    project's entry point" at the red and the green commit (`agents/conformance-reviewer.md:21-26`).
  - Once 00463 lands, `llm_qa.py all` and `run_all.sh` are denied to it. `llm_qa.py <tool>` stays
    allowed and is still the project's entry point, so the reviewer can comply if it is told the
    targeted form.
  - Each dispatch also pays for a new worktree's venv.
  - 00463 Task 1.1 should include this agent in its cases. Upstream is draft
    [03](upstream-drafts/03-reviewer-full-entry-point-cost.md).

## Criterion 4: spec duplication

| Document       | Plugin (vendored = fetched today) | `remote-docs/defence-before-fix.github.io/`                                             | Agree?                                                                                                      |
| -------------- | --------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| SPEC           | 1.0.1, published 2026-09-08 (raw) | `SPEC.md`: 1.0.1, published 2026-09-08; `fidelity: converted` from `SPEC.html`          | Version and date agree. The bytes differ because remote-docs holds an HTML conversion, not the raw markdown |
| DETECTOR-SPEC  | 1.0.0, published 2026-09-08 (raw) | `DETECTOR-SPEC.md`: 1.0.0; converted from `.html`                                       | Version and date agree; the form differs                                                                    |
| TOOLING-SPEC   | 0.2.0, published 2026-09-08       | `raw/TOOLING-SPEC.md`: `source_sha256` equals the plugin file's sha256                  | Identical                                                                                                   |
| Project prompt | method 1.0.1                      | `defence-before-fix-project-prompt.md`: `source_sha256` equals the plugin file's sha256 | Identical                                                                                                   |

- remote-docs was fetched on 2026-09-15, and is `stale_after` 2026-12-14. A `--force` fetch
  today matched every plugin copy byte for byte, so nothing has drifted.
- **Correction** to the 18:00 journal entry: the remote-docs SPEC and DETECTOR-SPEC are not
  byte-identical to the plugin's. They are HTML conversions of the same versions.
- **Daemon-side option**: re-capture both from `/raw/*.md`, so that all three copies are
  comparable by hash.

## Criterion 5: token cost

Estimates are bytes / 4, measured from the cached files.

| Cost                                                                                                                                            | Bytes   | ≈ tokens               | Projection |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ---------------------- | ---------- |
| Always-on: skill name + description (486), plus both agents' names + descriptions (313 + 338)                                                   | 1,137   | **~285**               | ~290       |
| SKILL.md body alone (7,106 with frontmatter)                                                                                                    | 6,395   | ~1.6k                  | ~1.6k      |
| **Coordinator floor per `/dbf`**: body + refresh output (753) + `project-prompt.md` in full (6,559) + SPEC §4 (5,801) + REPORT-TEMPLATE (3,230) | 22,738  | **~5.7k**              | –          |
| Plus `register.json`, which this repo needs because it has no reference toolchain                                                               | +57,074 | +14.3k → **~20k**      | –          |
| Plus SPEC §3 "whenever a step … is unclear"                                                                                                     | +43,440 | +10.9k → ~31k          | –          |
| Reviewer's own context: body + SPEC §3, 4, 7, 8                                                                                                 | ~60,900 | ~15k, plus its runs    | –          |
| Searcher's own context: body only                                                                                                               | 2,248   | ~0.6k, plus its search | –          |

The always-on projection holds. The ~1.6k invocation projection counts only the SKILL.md body.
What the skill tells the agent to read puts a real invocation at ~5.7k minimum, and ~20k in a
Python or shell project, before any work or sub-agent. Measured in this session, the emulated
searcher's reply was 9,385 bytes (~2.3k) back to the coordinator.

## Criterion 6: report conventions (Plan 00460, `subagent_report_*`)

- **The contract is unmeetable as written.** Both agents are told to "write the full … to the
  file the coordinator names" (`agents/conformance-reviewer.md:57-58`,
  `agents/independent-searcher.md:42-43`), yet declare `tools: Read, Grep, Glob, Bash`. That is
  upstream #3.
- **Observed**: the emulated searcher, which had the same grant, **did not write the named
  file**. It cited the harness's standard sub-agent note ("Do NOT Write report … files; return
  findings directly") and returned the report inline. It did not use a Bash heredoc.
  - The report survived only through the daemon's Plan 00460 auto-save
    (`untracked/agent-reports/auto/…`).
  - The path the coordinator named, which could have followed this repo's
    `<plan>/subagent-reports/` convention, was never written.
  - New evidence for #3; draft [06](upstream-drafts/06-comment-on-issue-3.md) favours "return
    inline, the skill writes it".
- **Daemon side (Plan 00468)**:
  - Plugin agents are invisible to the read-only resolver (00468 P2 and Task 2.2).
  - The Plan 00307 dispatch-declaration advisory fired on this dispatch even though the prompt
    named a report file ("File to write to: <path>"). It recognises only a plan folder or "not
    plan work".
  - After the move to local scope, `installed_plugins.json` still records the plugin as
    `scope: project` with `projectPath`, and `claude plugin list` shows "Scope: project".
    Nothing broke, but a scope-aware resolver (00468 Task 2.1) should not trust that field alone.

## Probe to close criterion 3

The probe needs a logged-in session. Run it in a scratch repository (the one under
`untracked/scratch/p467/trigger-probe/` is ready):

```
claude -p "<prompt>" --plugin-dir .claude/ccy/plugins/cache/defence-before-fix/defence-before-fix/0.1.1 \
  --permission-mode plan --max-turns 6 --output-format stream-json --verbose
```

Use the prompts A, B and C from draft 02. Then look for a `Skill` tool_use naming
`defence-before-fix:dbf`.

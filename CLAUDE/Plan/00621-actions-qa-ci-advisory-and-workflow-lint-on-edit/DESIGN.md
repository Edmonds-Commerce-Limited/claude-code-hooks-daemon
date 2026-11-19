# Plan 00621: design, as ruled

Supporting document for [PLAN.md](PLAN.md), Task 1.2.

**Provenance.** This design was settled by a fable sub-agent under the owner's delegation,
2026-11-19. It is not the owner's own words. A later owner message overturns any part of
it, and the builder then follows the owner.

## 1. What was verified about the linter, and what was not

Checked on 2026-11-19, from this repository's environment:

- No `actions-qa-ci` executable is installed here.
- A public web search for the tool name together with its four rule names returned no page
  that mentions any of them.
- A GitHub repository search for the name, a listing of the authenticated account's
  repositories, and a listing of this repository's own organisation returned no repository
  whose name contains it.

So no documentation and no release of the linter could be reached, and **every fact about
the linter in this plan's journal remains unverified**:

| Reported fact (peer notes, journal 2026-11-18)                                    | Status                                                                                                               |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| The tool exists as a Go CLI named `actions-qa-ci`                                 | Unverified                                                                                                           |
| It has the rules docsOnlyPush, pushConcurrency, workflowRunFanout, scheduleBudget | Unverified                                                                                                           |
| A v0.2.0 is published                                                             | Unverified                                                                                                           |
| `check --file <path>` works from any working directory                            | Unverified                                                                                                           |
| `--format json` prints an array of findings                                       | Unverified                                                                                                           |
| The fields of a JSON finding                                                      | Unverified, and the two peer notes disagree (the earlier lists col, severity and exceptionKey; the later omits them) |
| Exit codes are 0 clean, 1 findings, 2 fault                                       | Unverified                                                                                                           |
| Where and how the tool is installed                                               | Unknown: no note states it                                                                                           |

The design below is therefore built so that it is correct whichever of these turn out
false, and so that a false one costs a missed check, never a blocked edit.

## 2. The design is confirmed, with five changes

The plan's two pieces stand: a lint-on-edit route and a session-start advisory. The rule
set stays in the linter. The changes:

### 2.1 The route is a tenth lint strategy, and the registry must learn to share an extension

A new `GitHubWorkflowLintStrategy` (language name `GitHub Workflow`, extensions `.yml` and
`.yaml`) that implements `NarrowsByPath` and accepts only a file directly inside a
`.github/workflows/` directory.

`LintStrategyRegistry.register` stores one strategy per extension, so registering this
strategy as it stands would replace the Ansible strategy for every YAML file. The registry
must hold several strategies for one extension and return the first whose `handles_file`
accepts the path. A strategy that shares an extension must implement `NarrowsByPath`; the
registry refuses a second strategy on an owned extension that does not. The Ansible
strategy already declines anything under `.github`, so the two never both accept a file.
`filter_by_languages`, `strategies` and `registered_languages` must keep working.

### 2.2 The command, and no JSON parsing

Default command: `actions-qa-ci check --file {file}`. No extended command. The linter's
plain output is passed through as lint output, exactly as for every other strategy. The
daemon does not request or parse JSON, so the disagreement over the JSON fields cannot
break it. The existing per-language command override lets a project change the command
(for instance to the older repository-root form) without a daemon release.

### 2.3 Findings are reported as a lint failure; everything else allows

- Exit 0: silent.
- Exit 1: findings. Reported through the normal `lint_on_edit` failure path
  (R-LINT-FAILURE). The write has already landed, so this is a failure report to repair,
  the same contract as every other linter. An advisory-only report was considered and
  rejected: findings shown as a note beside a successful edit are skimmed.
- Any other non-zero exit: a fault of the tool, not a finding about the file. The edit is
  allowed, with an advisory that the file was not checked and the tool's first line of
  output. This is deliberately "anything but 1" rather than "2", so that an unverified exit
  code or an unknown flag (an older version that lacks `--file`) fails open.
- Tool not found: the existing advisory allow.
- Timeout: the existing advisory allow, budget from `options.timeouts."GitHub Workflow"`.

`_run_lint_command` currently treats every non-zero exit as a failure unless the strategy
classifies the output text. Exit codes need a new optional capability beside
`ClassifiesToolUnavailable` (a strategy that names which exit codes mean findings); the
handler treats the others as a fault. No existing strategy changes behaviour.

The linter decides what an excepted finding does to its exit code. The daemon does not
second-guess it.

### 2.4 The advisory handler ships switched off until the tool can be found

A SessionStart handler, `workflow_linter_advisor`, advisory only:

- Fires when `.github/workflows/` holds at least one `.yml` or `.yaml` file, and no file
  there mentions `actions-qa-ci`, and the executable does not resolve.
- Silent when there are no workflows, when any workflow already uses the linter, or when
  the tool is installed.
- Once per session. It never blocks and never runs the linter.
- The text names the tool, says what it checks in one line, and gives an install hint only
  from an `install_hint` option, which is empty by default.

It ships with `enabled: false`. The daemon is installed in many projects, and recommending,
by default, a tool that could not be found by any search is advice nobody can act on. It
becomes default-on in the same change that records a verified install source (Task 1.1).

### 2.5 Bash-authored and relocated files

Nothing new. `lint_on_edit` already lints a file a Bash command authors and never one it
relocates, and the new strategy inherits both.

## 3. First buildable slice

Slice 1, tests first, built against a stub linter script (the real tool is not needed):

1. Registry: several strategies per extension. Tests: an Ansible playbook path still
   resolves to Ansible; a `.github/workflows/ci.yml` path resolves to the new strategy; a
   nested `.github/workflows/sub/x.yml`, a `.github/dependabot.yml` and a plain `config.yml`
   resolve to neither wrongly; a second non-narrowing strategy on an owned extension is
   refused; `filter_by_languages` removes one of two sharing an extension and leaves the
   other.
2. The exit-code capability in the lint protocol and its handling in `_run_lint_command`.
   Tests with the stub: exit 0 silent, exit 1 denies with the output, exit 2 and exit 127
   allow with an advisory, tool missing allows, timeout allows.
3. `GitHubWorkflowLintStrategy`, registered in `create_default`, with its acceptance tests
   and the strategy-pattern documentation the project requires for a new strategy.
4. Targeted QA on the changed files; hand the commit to the coordinator.

Slice 2 is the advisory handler (off by default). Slice 3 is the handler guidance, config
documentation and the release note.

## 4. What is still open

- **Task 1.1 is not done and cannot be done from here.** Someone with the real tool must
  run it once against a sample workflow file and record the command line, the output and
  the exit codes. This gates the plan's completion and the advisory's default, not the
  build of slice 1.
- **Where the tool is published** is the one thing only the owner or the peer project can
  supply.

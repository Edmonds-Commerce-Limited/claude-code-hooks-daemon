# Plan 00621: design, as ruled

Supporting document for [PLAN.md](PLAN.md), Task 1.2.

**Provenance.** This design was settled by a fable sub-agent under the owner's delegation,
2026-11-19. It is not the owner's own words. A later owner message overturns any part of
it, and the builder then follows the owner.

## 1. What was verified about the linter, and what was not

The linter is public: the repository `LongTermSupport/actions-qa-ci` on GitHub. On
2026-11-19 its README (default branch) and its v0.2.0 release were read. The release's
`install.sh` was read and the `linux_amd64` bundle was downloaded, its sha256 compared with
the release's `checksums.txt` (equal), and its file list read. **Nothing was installed and
the tool was not run.** So each fact below is verified against the tool's own documentation
and release, not against its behaviour.

| Reported fact (peer notes, journal 2026-11-18)                         | Result                                                                                                                                                            |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The tool exists; a Go CLI                                              | Confirmed (README: Go to build from source; a released bundle needs nothing on the host)                                                                          |
| The executable is called `actions-qa-ci`                               | **Wrong.** The project and the action are `actions-qa-ci`; the executable is `actions-qa` (the bundle holds `bin/actions-qa`, and the README's commands use it)   |
| Rules docsOnlyPush, pushConcurrency, workflowRunFanout, scheduleBudget | Confirmed, as `actionsqaci.<name>` (README)                                                                                                                       |
| v0.2.0 is published                                                    | Confirmed: published 2026-11-18, with `linux_amd64` and `linux_arm64` bundles, `checksums.txt` and `install.sh`                                                   |
| `check --file <path>` works from any working directory                 | Confirmed in the README and the v0.2.0 release notes; the repository is the nearest directory above the file holding `.git`, a worktree's `.git` file included    |
| `--format json` prints a list of findings                              | Confirmed in the README                                                                                                                                           |
| The fields of a JSON finding                                           | The earlier peer note is the right one: `id`, `path`, `line`, `col`, `severity`, `message`, `excepted`, `exceptionKey`. The later note left three out             |
| Exit codes 0 clean, 1 findings, 2 fault                                | Incomplete. The README lists five: 0 nothing to report, 1 findings, 2 wrong command line or project record, 3 the toolchain failed, 4 no verdict could be reached |
| A v0.3.0 will add declared docs-only inputs and exemptions             | Not checked as a release. The README already describes `docsOnly.inputs` and `docsOnly.exempt`, so the default branch is ahead of v0.2.0                          |

Further facts the peer notes did not carry, from the same sources:

- With no `--format`, the output is `text` on a terminal and `agent` otherwise, unless
  `ACTIONS_QA_FORMAT` is set.
- `check` gives each file's actionlint lane a two-minute limit of its own and exits 4 when it
  is hit.
- The install script puts the release under `$XDG_DATA_HOME/actions-qa-ci` or
  `$HOME/.local/share/actions-qa-ci` (or `--prefix`), and tells the user to put its `bin` on
  `PATH`. It does not do so itself.
- In a workflow the tool is adopted as `uses: LongTermSupport/actions-qa-ci@<commit>`.

**Still unverified:** everything about how the tool behaves when run. The README on the
default branch may also describe more than v0.2.0 ships. Task 1.1 (run it once) stays open,
and the builder can now do it without help.

## 2. The design is confirmed, with five changes

The plan's two pieces stand: a lint-on-edit route and a session-start advisory. The rule
set stays in the linter. The changes:

### 2.1 The route is a new lint strategy, and the registry must learn to share an extension

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

Default command: `actions-qa check --file {file}`. No extended command. The executable is
resolved the way every lint tool is (workspace bin directories, the interpreter's bin,
`PATH`); the daemon does not search the linter's install directory. The linter's plain
output is passed through as lint output, exactly as for every other strategy. The daemon
does not ask for or parse JSON. The existing per-language command override lets a project
change the command without a daemon release.

### 2.3 Findings are reported as a lint failure; everything else allows

- Exit 0: silent.
- Exit 1: findings. Reported through the normal `lint_on_edit` failure path
  (R-LINT-FAILURE). The write has already landed, so this is a failure report to repair,
  the same contract as every other linter. An advisory-only report was considered and
  rejected: findings shown as a note beside a successful edit are skimmed.
- Any other non-zero exit (2, 3 and 4 as documented, and any other): a fault, not a finding
  about the file. The edit is allowed, with an advisory that the file was not checked and
  the tool's first line of output. The rule is "anything but 1" so that an older version
  without `--file`, or a behaviour the documentation does not describe, fails open.
- Tool not found: the edit is allowed and **nothing is printed**. For every other language
  the handler prints "lint tool not found, install it"; for an optional external linter that
  line would appear on every workflow edit in every project that has not adopted it. The
  session-start advisory (2.4) is the one place that suggests the tool.
- Timeout: the existing advisory allow, budget from `options.timeouts."GitHub Workflow"`.

`_run_lint_command` treats every non-zero exit as a failure unless the strategy classifies
the output text, and always prints the tool-not-found line. Two optional capabilities are
needed beside `ClassifiesToolUnavailable`: one by which a strategy names the exit codes that
mean findings, and one by which it declares its tool optional. No existing strategy changes
behaviour.

The linter decides what an excepted finding does to its exit code. The daemon does not
second-guess it.

### 2.4 The advisory handler

A SessionStart handler, `workflow_linter_advisor`, advisory only:

- Fires when `.github/workflows/` holds at least one `.yml` or `.yaml` file and none of them
  has a `uses:` line naming `actions-qa-ci`.
- Silent when there are no workflows or when any workflow already uses the linter.
- Once per session. It never blocks and never runs the linter.
- The text names the tool, says what it checks in one line, and points at the project's
  release page. It does not print an install command to paste.

It ships enabled, as the relayed direction asks ("the daemon should suggest installing
it"), and is turned off like any other handler. Whether a tool this young should be
suggested by default in every project with workflows is the one point in this design worth
the owner's glance (section 4).

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
2. The two capabilities in the lint protocol and their handling in `_run_lint_command`.
   Tests with the stub: exit 0 silent; exit 1 denies with the output; exits 2, 3, 4 and 127
   allow with an advisory; tool missing allows and prints nothing; timeout allows; an
   existing language's missing tool still prints its line.
3. `GitHubWorkflowLintStrategy`, registered in `create_default`, with its acceptance tests
   and the strategy-pattern documentation the project requires for a new strategy.
4. Targeted QA on the changed files; hand the commit to the coordinator.

Slice 2 is the advisory handler. Slice 3 is the handler guidance, config documentation and
the release note.

Task 1.1 can run beside slice 1: fetch the release bundle, check it against
`checksums.txt`, and run `actions-qa check --file` on one clean and one faulty sample
workflow inside a scratch git repository; journal the command lines, output and exit codes.
If the behaviour differs from section 1, change the strategy before the plan completes.

## 4. What is still open

- **Task 1.1**: the real tool has not been run. It gates the plan's completion, not slice 1.
- **For the owner's glance**: the advisory is on by default (2.4). Nothing in this plan is
  blocked on it.

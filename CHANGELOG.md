# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.3.1] - 2026-04-14

### Fixed

- **Shipped-broken skill and agent frontmatter restored**: v3.3.0 shipped with 6 `SKILL.md` files (`hooks-daemon`, `release`, `acceptance-test`, `configure`, `mode`, `optimise`) and 6 `.claude/agents/*.md` files still damaged by the very bug v3.3.0 announced fixing. The v3.1.0 batch-format commit (`30db070`) had run the pre-fix `mdformat` over all project markdown, collapsing each file's YAML frontmatter into a `## name: ... description: ... argument-hint: ...` heading and dropping the closing `---` delimiter. The handler fix in v3.3.0 prevents *new* corruption but does not repair files already damaged on disk — and the damaged files were still checked into the release artefact, so every upgrader re-deployed broken skill/agent metadata. All 12 files have now been restored to their pre-corruption frontmatter from git history (`30db070^`), and a round-trip through the fixed `format-markdown` CLI confirms frontmatter is preserved byte-for-byte on subsequent edits. **This is exactly the scenario the v3.3.0 post-upgrade task `01-audit-markdown-frontmatter.md` documents for client projects.**

## [3.3.0] - 2026-04-14

### Added

- **`post-upgrade-tasks/` convention**: New generic mechanism for giving upgrading LLMs/humans formal post-upgrade instructions (audits of prior-version bugs, config migrations, workflow changes, notifications). Tasks are drafted in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` during the release cycle, then moved into the versioned upgrade guide at release time. Each task is a self-contained markdown file with mandatory header (`Type`/`Severity`/`Applies to`/`Idempotent`) and sections `Why`/`How to detect`/`How to handle`/`How to confirm`/`Rollback`. Advisory only — nothing runs them automatically.
- **Release pipeline BLOCKING gate for UNRELEASED tasks (Step 6)**: `RELEASING.md` and the `/release` skill now require moving every `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-*.md` into the versioned upgrade guide before the Opus documentation review. Release ABORTS if any task file remains in `UNRELEASED/` after this step. The Opus review checklist verifies the versioned guide's task index is populated and that release notes reference post-upgrade tasks when any are `critical` or `recommended`.
- **Per-release task index README**: `CLAUDE/UPGRADES/upgrade-template/post-upgrade-tasks/README.md` template with the task-index table schema, populated per release with one row per moved task (ordered by filename).

### Fixed

- **`markdown_table_formatter` YAML frontmatter mangling**: The PostToolUse handler (`markdown_table_formatter`) and the `format-markdown` CLI subcommand previously passed entire markdown files to `mdformat`, which does not understand YAML frontmatter. Any `.md` file whose first line was `---` — notably Claude Code `SKILL.md` files, Jekyll/Hugo/MkDocs pages, and any frontmatter-using documentation — was silently rewritten so that the opening `---` became a 70-underscore thematic break, the YAML body was collapsed onto a single line prefixed with `##`, and the closing `---` was lost. Frontmatter is now stripped before formatting and re-attached byte-for-byte afterwards. **Files already damaged on disk before this release remain damaged** — see the post-upgrade task `01-audit-markdown-frontmatter.md` in the v3.2-to-v3.3 upgrade guide for detection and remediation guidance.

## [3.2.1] - 2026-04-10

### Changed

- **Markdown organization allowed paths**: Uncommented and activated the `allowed_markdown_paths` configuration in `hooks-daemon.yaml`, adding `.github/` as a new allowed path for markdown files. This enables markdown files in the `.github/` directory (e.g. issue templates, PR templates, workflows documentation) to pass the `markdown_organization` handler without being blocked.

## [3.2.0] - 2026-04-10

### Added

- **Universal continuation instruction for PreToolUse deny responses**: All PreToolUse blocking handlers now automatically append a "Do not stop working. Modify your approach" suffix to deny reasons, preventing agents from interpreting a blocked tool call as a signal to stop. This is a single-point-of-change in `HookResult` that covers all blocking handlers without requiring individual handler modifications.
- **CLAUDE.md hooksdaemon section continuation guidance**: The auto-generated `<hooksdaemon>` section in `CLAUDE.md` now includes a universal note instructing agents to read block reasons and continue working, reinforcing the continuation instruction from deny responses.

### Fixed

- **QA check count in documentation**: Updated CLAUDE.md and RELEASING.md to reference 10 QA checks (was incorrectly stating 8, missing Error Hiding, Skill References, and Smoke Test)

## [3.1.1] - 2026-04-10

### Fixed

- **Venv not recreated on idempotent upgrade path**: When upgrading between versions, the upgrade script now detects stale venvs via a `.daemon-version` stamp file and recreates the venv when the version changes, ensuring new dependencies (e.g. `mdformat`, `mdformat-gfm`) are correctly installed rather than silently missing.
- **Upgrade post-install verification fails fast on broken venv**: Post-install verification now detects broken venv states (missing packages, import errors) and fails immediately with a clear diagnostic instead of silently passing, preventing a broken install from appearing successful.
- **Venv version stamping**: The venv creation and upgrade scripts now write a `.daemon-version` file into the venv to track which daemon version the venv was built for, enabling reliable stale-venv detection on future upgrades.
- **Shellcheck issues in install/upgrade scripts**: All shellcheck warnings across install/upgrade scripts resolved (zero tolerance policy), including bash array handling for the Python interpreter flag in `venv.sh` (SC2086).

## [3.1.0] - 2026-04-10

### Added

- **`markdown_table_formatter` PostToolUse handler**: New handler (priority 26, non-terminal) that auto-formats markdown tables after every `Write` or `Edit` of a `.md` or `.markdown` file using `mdformat` + `mdformat-gfm`. Aligns table pipes vertically, widens delimiter rows to match cell widths, preserves thematic breaks, and escapes asterisks in table cells as required by GFM. Non-blocking — never denies, only reformats on disk.

- **`format-markdown` CLI subcommand**: New `$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown <path>` command for ad-hoc markdown formatting. Supports single file, directory (recursive), and `--check` mode for CI validation without modifying files.

### Fixed

- **`.CLAUDE.md.pre-inject` gitignore safety**: The installer and `gitignore_safety_checker` SessionStart handler now ensure `.CLAUDE.md.pre-inject` is present in client project `.gitignore` entries, preventing the pre-inject backup file from being accidentally committed.

- **Integration test coverage for `markdown_table_formatter`**: Added missing integration test cases for the handler's response validation and FrontController dispatch path.

### Changed

- **257 project markdown files batch-formatted**: All existing `.md` files in the project were reformatted via `mdformat + mdformat-gfm` to align table pipes and normalise formatting, establishing a consistent baseline for the new auto-formatter.

- **Daemon-generated `CLAUDE.md` `<hooksdaemon>` section restored**: The auto-generated hooks daemon guidance section in `CLAUDE.md` was restored after batch markdown formatting altered its structure.

## [3.0.1] - 2026-04-07

### Fixed

- **ClaudeMdInjector content loss protection**: Added safety checks that detect and abort writes that would lose user content outside the `<hooksdaemon>` block, plus a `.CLAUDE.md.pre-inject` backup file is written before every modification.
- **Install/upgrade gitignore management**: The `.CLAUDE.md.pre-inject` backup file is now included in generated `.gitignore` entries so it is never accidentally committed.

## [3.0.0] - 2026-04-07

### Removed

- **BREAKING: `command_redirection` feature removed entirely.** The `command_redirection` option on `pipe_blocker`, `npm_command`, and `gh_issue_comments` handlers has been removed. The shared `core/command_redirection.py` module has been deleted along with all associated tests, config options, documentation, and QA exclusions. The feature stripped blocked command parts, executed the remainder, and saved output to files — but it caused unpredictable behaviour, could not handle output redirection, and added significant complexity for marginal benefit.

### Changed

- **BREAKING: Affected handlers now simply deny with educational guidance.** `pipe_blocker`, `npm_command`, and `gh_issue_comments` no longer attempt to execute a corrected version of the blocked command. They return a `deny` decision with a clear explanation, leaving Claude to construct the corrected command itself. This is the same behaviour these handlers had with `command_redirection: false` (the default since v2.31.0).

- **Daemon stale-file cleanup no longer cleans command redirection files.** The `cleanup_stale_command_redirection_files()` function has been removed from `daemon/paths.py`. Daemon startup cleanup now only removes stale daemon runtime files (sockets, PID files, logs).

## [2.32.0] - 2026-04-06

### Added

- **`hook_registration_checker` handler**: New SessionStart handler (priority 51) that validates hook registrations in Claude Code settings on session start, alerting when expected hooks are missing or misconfigured.

- **`/hooks-daemon report` subcommand**: New CLI subcommand for generating investigation reports, providing structured diagnostic output to assist in debugging daemon and handler issues.

- **Skill-reference QA checker**: New `skill_refs` QA check that enforces the pattern of using skill-based references (e.g. `/hooks-daemon`) rather than bare Python module invocations or slash syntax in agent-facing messages, ensuring consistent and user-friendly guidance across all handlers.

### Fixed

- **`enforce_llm_qa` false positive on run_all.sh mentions**: The handler previously blocked git add/commit operations when the commit message contained the string `run_all.sh`, incorrectly treating it as a direct QA invocation. Fixed to correctly distinguish between mentioning `run_all.sh` in a commit message and actually running it.

- **Daemon error messages use skill-based wording**: All agent-facing error and guidance messages in the daemon core now direct agents to use `/hooks-daemon` skill syntax instead of bare Python module invocations (`python -m ...`) or raw slash syntax, ensuring consistent skill-first messaging.

- **Ruff warnings resolved across codebase**: Resolved all pre-existing ruff linting warnings in both source files and test files, achieving zero lint violations across the entire codebase.

- **`hook_registration_checker` included in default config**: Added `hook_registration_checker` to `init_config.py` default configuration so new installations automatically include the handler without requiring manual config edits.

- **LLM-INSTALL.md restructured to prevent install/update confusion**: The install guide front-loaded "already installed?" messaging so heavily that LLM agents would conclude they should update instead of install. Restructured to lead with prerequisites and install steps. The "already installed?" check is now a brief Step 0 guard that correctly distinguishes fresh clones (config files exist but daemon repo is gitignored) from actual existing installations.

## [2.31.1] - 2026-04-03

### Fixed

- **`auto_continue_stop` Branch 3 stale reader race condition**: The confirmation-question auto-continue branch (Branch 3) never fired because it used the original transcript reader captured at `handle()` entry, which could be stale after Branch 2's retry loop had reloaded the transcript. Branch 2 did not propagate the refreshed reader back, so Branch 3 always evaluated stale data. Fixed by reloading the transcript reader immediately before the Branch 3 check.

- **`auto_continue_stop` question evaluation guidance**: Added `get_claude_md()` guidance teaching Claude to distinguish tautological confirmation questions (rhetorical — just proceed) from genuine choice questions (require user input — use `STOPPING BECAUSE: need user input`). Prevents unnecessary stops on questions that don't need human decision-making.

## [2.31.0] - 2026-04-03

### Added

- **Handler ABC version registry accuracy**: Updated `_ABSTRACT_METHOD_VERSIONS` registry in `project_loader.py` to ensure the `get_claude_md()` method version entry is accurate, preventing false positive version mismatch errors when validating project handlers.

- **Release process checklist for Handler ABC methods**: Added a detection step to the release process for new `@abstractmethod` entries on the `Handler` base class — ensuring upgrade guides document the method name, version added, and the required stub for project handlers.

- **Upgrade guide v2.29 to v2.30**: Created comprehensive upgrade guide in `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/` documenting the `get_claude_md()` breaking change introduced in v2.30.0, including before/after config examples and migration steps.

### Fixed

- **`validate-project-handlers` now returns exit 1 on load failures**: Previously, the CLI command reported handler load failures but exited with code 0, making it usable in CI scripts without detecting problems. Now correctly exits with code 1 when any project handler fails to load.

- **Quote-aware pipe splitting in pipe blocker handler**: The pipe blocker previously split commands on `|` characters inside quoted strings, causing false positives on legitimate commands that contained quoted pipe characters. Now correctly ignores `|` inside single and double quotes.

- **Project handler load failures no longer crash the daemon**: A single malformed or incompatible project handler previously caused the entire daemon startup to fail. Now failed project handlers are skipped with an error log entry, allowing the daemon to start with the remaining valid handlers.

- **Command redirection output to `/tmp/` instead of daemon dir**: The async command redirection feature (pipe blocker, gh issue comments, npm command) previously wrote output files into the daemon's runtime directory. Changed to write to `/tmp/hooks-daemon-cmd/` for consistency and to avoid cluttering the daemon directory.

- **Fresh clone install experience**: Hook scripts on freshly cloned projects now direct the LLM to use `/hooks-daemon install` instead of referencing the non-existent `CLAUDE/LLM-INSTALL.md` file. New install skill and shell script added to the deployed skills package.

- **Placeholder URLs replaced**: Fixed `your-org/hooks-daemon` references across skill files to use the correct `Edmonds-Commerce-Limited/claude-code-hooks-daemon` GitHub URL. Also fixed `curl | bash` patterns to use the safer download-then-inspect approach.

- **Command redirection disabled by default**: All three handlers with command redirection (`pipe_blocker`, `gh_issue_comments`, `npm_command`) now default to `command_redirection: false` to avoid CLAUDE.md cascade reads when output files were in the daemon directory.

- **`gh_issue_comments` publishes guidance via `get_claude_md()`**: Returns a guidance block explaining why `--comments` is required and how to use `--json` with the `comments` field as an alternative.

- **`npm_command` publishes guidance via `get_claude_md()`**: Returns a guidance block explaining the `llm:` prefix convention for npm commands and the difference between advisory and enforcement modes.

### Changed

- **RELEASING.md condensed from 1,178 to 210 lines**: Refactored the release documentation to be significantly more concise while preserving all essential steps, making it faster to read and easier to follow during releases.

## [2.30.0] - 2026-04-02

### Added

- **`get_claude_md()` abstract method on `Handler` base class**: Every handler must now explicitly implement `get_claude_md()`, returning either `None` or a guidance string describing its behaviour. This makes handler self-documentation mandatory and opt-out rather than opt-in, preventing silent omissions. All 77+ existing handlers have been updated with explicit `return None` stubs or real guidance strings.

- **`ClaudeMdInjector`**: New core component (`src/claude_code_hooks_daemon/core/claude_md_injector.py`) that collects `get_claude_md()` output from all active handlers on daemon restart and writes a `<hooksdaemon>...</hooksdaemon>` section into the project `CLAUDE.md`. The section is auto-replaced on each restart and never duplicates. Invoked from `DaemonController.initialise()` after all handlers are loaded. Includes 13 unit tests.

- **`pipe_blocker` publishes guidance via `get_claude_md()`**: Returns a guidance block explaining what commands are blocked and showing the correct redirect-to-temp-file pattern as an alternative.

- **`auto_continue_stop` publishes guidance via `get_claude_md()`**: Returns a guidance block explaining the `STOPPING BECAUSE:` prefix requirement so agents know how to signal intentional stops without triggering retry loops.

- **Step 7.6 CLAUDE.md guidance audit added to release process**: The release documentation now includes a mandatory sub-agent analysis step that verifies all impactful handlers have accurate `get_claude_md()` content before each release.

### Fixed

- **Stale transcript race condition in `_has_stop_explanation`**: A second Stop event could fire before the new assistant turn was written to the transcript. `get_last_assistant_message()` then returned the previous turn's message (which contained `STOPPING BECAUSE:`), incorrectly allowing the new stop without a fresh explanation. Fixed by also retrying when the last message in the transcript is not from the assistant, only accepting an explanation when the last message is confirmed to be an assistant message with text blocks belonging to the current turn. If retries are exhausted without a fresh message, the method returns `False`.

## [2.29.2] - 2026-04-01

### Fixed

- **`auto_continue_stop` stop explanation missed in multi-block assistant messages**: `_has_stop_explanation()` was reading the first content block only; when the assistant produced multiple text blocks (e.g. a thinking block followed by the response), the `STOPPING BECAUSE:` prefix in a later block was silently ignored, causing valid stops to be denied and triggering unnecessary retry loops. Fixed by scanning all content blocks, not just the first.

- **Race condition in `_has_stop_explanation` — retry when text not yet flushed**: Under load, the stop event sometimes arrives before the assistant's final message has been fully written to the transcript. Added a short retry loop with backoff so the handler waits for the text to appear rather than immediately treating an empty or missing message as a missing stop explanation.

### Changed

- **Error-hiding exclusion list uses function names instead of line numbers (drift-proof)**: The `error_hiding_blocker` handler's QA audit exclusion list (`error_hiding_exclusions.json`) previously matched by line number, which silently drifted out of sync whenever code was added or removed above an exclusion site. Refactored to match by enclosing function name instead, so exclusions are immune to line shifts and fail loudly if a function is renamed rather than silently matching the wrong code.

## [2.29.1] - 2026-03-31

### Fixed

- **`auto_continue_stop` stop explanation recognised on any line**: `_has_stop_explanation()` previously used `startswith()` on the entire assistant message, so `STOPPING BECAUSE:` was only recognised when it appeared at the very first character. Assistants naturally summarise completed work before stating the stop reason, placing the prefix on a later line — causing the handler to deny valid stops and force unnecessary retry loops. Fixed by scanning each line individually so the prefix is recognised wherever it appears in the message.

## [2.29.0] - 2026-03-30

### Added

- **Live daemon smoke test as QA check 9 (`run_smoke_test.sh` + `llm_qa.py` integration)**: New QA check that probes the running daemon via 3 live hook script calls — Stop without explanation (must block), Stop with `stop_hook_active=true` (must allow, loop-guard check), and PreToolUse with a destructive git command (must deny). Catches the "#1 dogfooding failure mode": daemon running stale code. Results written to `untracked/qa/smoke_test.json`. Integrated as check 9 in `llm_qa.py` alongside the existing 8 automated checks. Includes 14 unit tests in `tests/unit/qa/test_smoke_test.py`.

- **`auto_continue_stop` redesign: 4-branch routing + JSONL stop-event logger**: The `AutoContinueStopHandler` was redesigned with a clean 4-branch routing model in `handle()`: (1) QA failure — last Bash was a QA tool and output indicates failure, respond with fix-and-continue message; (2) Explicit stop — last assistant message starts with `STOPPING BECAUSE:`, allow the stop; (3) Confirmation question (backwards compat) — text contains a continuation question, deny with auto-continue instruction; (4) Default — require `STOPPING BECAUSE:` prefix or continue, deny with explanation prompt. All stop decisions are now logged to `untracked/stop-events.jsonl` via `_log_stop_event()` for post-session debugging.

- **`/optimise` skill**: New Claude Code skill at `.claude/skills/optimise/` that analyses the hooks daemon configuration and produces a scored report across five areas: Safety, Stop Quality, Plan Workflow, Code Quality, and Daemon Settings. Each area is scored PASS / WARN / FAIL. Recommends specific handler changes and can apply them automatically (`apply all`, `apply 2,3`, or `skip`).

- **`GitignoreSafetyCheckerHandler` (SessionStart, priority 54, advisory, 39 tests)**: New SessionStart handler that warns when required `.claude/` paths are absent from `.gitignore`. Currently checks that `.claude/worktrees/` is gitignored (Claude Code managed worktrees — path is not configurable). Uses content-hash caching (MD5 of `.gitignore` + `.claude/.gitignore`) to avoid redundant filesystem reads on every session start. Only fires on new sessions (not resume). Non-blocking advisory — injects a warning context block listing missing entries with fix instructions.

- **Transcript-inspector sub-agent** (`.claude/agents/transcript-inspector.md`): New sub-agent that reads and analyses the current session transcript using `TranscriptReader` helpers. Useful for debugging stop hook behaviour, understanding conversation flow, and inspecting tool call history.

- **Stop hook debugging guide** (`CLAUDE/DEBUGGING_STOP_HOOK.md`): New documentation covering how to debug the `auto_continue_stop` handler — how to read `untracked/stop-events.jsonl`, how to probe the stop hook directly via `nc`, how to interpret the 4-branch routing decisions, and common failure patterns.

- **Daemon restart dogfooding rule added to `CLAUDE.md`**: Non-negotiable rule added to project instructions mandating daemon restart after every handler code change, with explicit commands and a description of the "daemon running stale code" failure mode as the #1 dogfooding pitfall.

### Fixed

- **Fresh-clone install guidance instead of restart advice**: When running from a fresh clone without an existing daemon socket, the hook init script now shows install guidance (directing the user to `CLAUDE/LLM-INSTALL.md`) rather than misleadingly instructing them to restart the daemon.

- **Worktree handler path fix for `.claude/worktrees/`**: The `worktree_file_copy` handler was missing `.claude/worktrees/` as a recognised worktree path. Claude Code stores managed worktrees at this path by default but the handler only matched user-configured paths, causing it to miss the most common worktree location. Fixed by adding `.claude/worktrees/` to the set of recognised worktree root patterns.

## [2.28.0] - 2026-03-25

### Added

- **`daemon_docs_guard` handler (PreToolUse, priority 57, advisory, 22 tests)**: New handler that detects when Claude Code reads from the hooks-daemon's internal `CLAUDE/` docs directory instead of the project's own authoritative `CLAUDE/` directory. When the daemon is installed at `.claude/hooks-daemon/`, it brings its own `CLAUDE/` subdirectory which can collide with the project's `CLAUDE/` naming convention. The handler injects a corrective advisory message when a Read, Write, or Edit tool targets a path containing `hooks-daemon/CLAUDE/`, explaining which file was accessed and providing the correct project-level path. The operation is always allowed (non-blocking, advisory only).

- **Stale daemon file cleanup with `startup_cleanup` statusline indicator**: Age-based cleanup on daemon startup removes runtime files (`daemon-*.*`) and `command-redirection/` output files older than a configurable threshold (default 7 days). Active daemons touch their runtime files hourly so only files from dead containers age past the cutoff — enabling safe multi-container setups where multiple containers share one codebase. New `stale_file_days` config item added to `DaemonConfig` (range 1–365, default 7). New `startup_cleanup` Status handler (priority 28) shows a cleanup icon briefly after startup and displays "N stale" count for 30 seconds when files were removed.

### Fixed

- **CI passthrough activating in non-CI environments (safety-critical)**: Passthrough mode was incorrectly triggering in non-CI developer environments (containers, local machines) whenever the daemon had a transient failure, causing all safety handlers to go permanently inactive. Fixed by restricting passthrough activation to environments where a CI environment variable is detected (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `JENKINS_URL`, `TF_BUILD`). Non-CI environments now receive a noisy `emit_hook_error` with restart instructions instead of silent passthrough. Also fixed a permanent passthrough lock bug: the cleanup `rm -f` after `start_daemon()` success was unreachable because the passthrough check returned early before `start_daemon()` was called; fixed by cleaning the flag in the `is_daemon_running()` branch so recovery after manual restart works. Also resolves SC2155 and SC1091 shellcheck violations in `init.sh`.

- **Upgrade script version prefix normalisation**: `scripts/upgrade.sh` documented both `2.14.0` and `v2.14.0` as valid inputs but the internal `git rev-parse` validation only worked with the `v` prefix (matching how tags are stored). Fixed by normalising `TARGET_VERSION` to prepend `v` if missing before the validation step.

- **ShellCheck SC1091 source directive violations in `install_version.sh` and Option A installer rename reverted**: Added proper `shellcheck source=` directives for all sourced modules in the install script, resolving pre-existing SC1091 violations. Also reverted an incorrect Option A approach (renaming `CLAUDE/` to `daemon-docs/` at install time via `mv`) that made the cloned repository dirty; the handler-based Option B (`daemon_docs_guard`) is the correct solution. Constants and upgrade compatibility code introduced for the aborted Option A were also removed.

## [2.27.0] - 2026-03-23

### Added

- **CI environment graceful degradation for hooks daemon**: Added config-based behaviour when the hooks daemon is unavailable (e.g. GitHub Actions, other CI environments). Implemented entirely in `init.sh`, the bash hook entry point layer, with zero impact on normal daemon operation.
  - **Default (fail open)**: When the daemon cannot be reached, the hook script emits a one-time warning to stderr and writes a `.hooks-passthrough` state file alongside the socket. All subsequent calls silently pass through without re-emitting the warning. This keeps CI pipelines operational without noise.
  - **`ci_enabled: true` (fail closed)**: When this option is set under `daemon:` in `hooks-daemon.yaml`, the hook script returns a hard deny with a STOP message instructing the agent that the hooks daemon must be installed before continuing. Provides strict enforcement for projects that require the daemon to be present.
  - 12 new end-to-end bash tests covering both modes in `tests/unit/test_ci_passthrough.py`.
  - Example config updated with inline documentation for the new `ci_enabled` option.

### Fixed

- **`plan_number_helper` false positive on multi-command pipelines**: The glob expansion regex used `.*` between `echo\s+` and the plan directory path, allowing it to match greedily across command separators (`&&`, `||`, `;`, `|`). This caused false positives when an unrelated `echo` (e.g. parsing `DATABASE_URL`) appeared earlier in the same pipeline as a `cat` command referencing a file stored in the plan folder. Fixed by replacing `.*` with `[^;&|]*` to prevent matching across command separator boundaries. Regression test added.

## [2.26.0] - 2026-03-23

### Added

- **Async command redirection (`launch_and_save`) for `pipe_blocker` handler**: The pipe blocker's command redirection now uses a new non-blocking `launch_and_save()` function instead of the synchronous `execute_and_save()`. When blocking a command piped to `tail`/`head`, the handler immediately spawns the base command as a detached background process and returns the deny message without waiting for it to complete. This prevents hook timeouts when the redirected command is slow (e.g. `pytest`, `npm test`). A daemon reaper thread prevents zombie process accumulation. The async wrapper script passes command arguments positionally via `$@` — no shell interpolation of user-supplied values.

### Fixed

- **Plan numbering regex matches date directories, inflating counter**: The regex `^(\d+)-` in `plan_numbering.py` and `validate_plan_number.py` matched date-formatted directories such as `2026-01-12` in legacy archives, extracting `2026` as a plan number and causing the sequential counter to jump from ~32 to ~2027. Fixed by tightening the regex to `^(\d{1,5})-[a-zA-Z]`, which requires a letter immediately after the hyphen — excluding date patterns (digit after hyphen) while correctly matching valid plan directories like `00032-svc-feature`. Regression tests added for both `plan_numbering` utility and `validate_plan_number` handler.

- **Install and upgrade docs now strongly emphasise handler enablement**: `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` previously treated handler configuration as optional, causing agents to leave most handlers disabled after install. Renamed "Configure Handlers (Optional)" to "Enable and Configure Handlers (CRITICAL)", added a full handler category table with enablement recommendations, added a comprehensive example config enabling 20+ handlers, and made the Handler Status Report section mandatory with a 30+ enabled handler target. Applied equivalent changes to the update guide.

- **QA violations in async command redirection and stale exclusion lines**: Resolved Ruff and MyPy violations introduced by the `launch_and_save` implementation and updated stale line-number references in `error_hiding_exclusions.json` that shifted after adding the new async function to `command_redirection.py`.

## [2.25.0] - 2026-03-19

### Added

- **Context-window-size-based threshold tiers for `model_context` status handler**: The status line context percentage indicator now uses tiers keyed by context window size rather than model name. Models with a 200k context window use standard thresholds (orange at 51%, red at 76%); models with a 1M context window use tighter thresholds (orange at 30%, red at 40%) because at those sizes even moderate percentages represent enormous token payloads. All thresholds are fully configurable via handler options in `.claude/hooks-daemon.yaml`. Unknown context window sizes fall back to the 200k tier. Adding a new tier (e.g. 2000k) requires only two new config options.

### Changed

- **Context thresholds keyed by window size, not model name**: Replaces the previous Opus-specific threshold implementation with a model-agnostic window-size approach. Any model (current or future) with a 1M context window automatically receives tighter thresholds; any model at 200k uses standard thresholds. This makes the feature robust to new model releases without code changes.

### Fixed

- **Error hiding exclusion line number updated for `model_context.py`**: The `try/except` block in `_read_effort_level` shifted from line 165 to line 215 after adding context-window-size tier constants and configurable threshold fields. The error-hiding exclusion comment was updated to match the current line number, keeping the security scan clean.

## [2.24.0] - 2026-03-18

### Added

- **README stats check in Opus review gate**: The Opus documentation review step now explicitly validates that README.md stats are up to date — including the test count badge, test count in body text, handler count, and event type count. Prevents stale stats from shipping in releases.

- **README stat updates in release process**: The release agent checklist and RELEASING.md documentation now include an explicit step to update README.md stats (test count badge, body test count, handler count, event type count) as part of version updates. Previously these went stale between releases.

- **Dogfooding bug fix mandate**: Added non-negotiable dogfooding rule to project CLAUDE.md — any bugs found while using the daemon's own handlers during development must be fixed immediately, not deferred.

### Fixed

- **Command redirection runs in project root**: `execute_and_save()` now accepts a `cwd` parameter, and all three callers (`gh_issue_comments`, `npm_command`, `pipe_blocker`) pass `ProjectContext.project_root()`. Previously, redirected commands ran from `/` (the daemon's cwd after daemonization) causing them to fail. Discovered via dogfooding when the pipe_blocker redirected a pytest command to a file but ran it from the wrong directory.

- **Daemon start hangs callers using `$()` command substitution**: The double-fork daemonization in `cli.py cmd_start()` redirected stdout to `/dev/null` but intentionally kept stderr open for error output. When callers like `daemon_control.sh` captured output with `$("$python" ... start 2>&1)`, the grandchild daemon process held the pipe's write-end open via inherited stderr, causing the `$()` substitution to block forever. Fixed by redirecting both stdout and stderr to `/dev/null` in the grandchild — the in-memory log system already captures all errors, so stderr is not needed for a properly daemonized process.

- **README stats corrected**: Updated README.md with accurate stats — handler count 48→68, event types 10→13, test count 6,255→7,344+. Clarified LLM-targeted sections (raw URLs at top) with collapsible `<details>` blocks labelled "LLM Quick Reference" to reduce confusion for human readers.

- **Upgrade script hangs in non-interactive mode**: `scripts/upgrade_version.sh` used `read -r -p` for an upgrade guide confirmation prompt without checking whether stdin is a terminal. In non-interactive environments (Claude Code agents, CI pipelines), `read` blocks forever waiting for input that never arrives. Fixed by adding `[ ! -t 0 ]` detection to auto-skip the interactive prompt, with an informational message directing users to review upgrade guides after the upgrade completes.

## [2.23.3] - 2026-03-16

### Fixed

- **Health check self-install false positive**: `scripts/health_check.sh` previously used the presence of a `.env` file as a proxy for self-install mode detection. This was incorrect — normal installations can also have a `hooks-daemon.env` file, causing false-positive failures. The script now reads `self_install_mode` directly from the YAML config, matching the logic already used in `upgrade.sh`.

- **Daemon start progress output**: `scripts/install/daemon_control.sh` now emits a progress message before the blocking daemon start call. Previously, callers (such as the upgrade script) would see no output during handler loading, making the script appear to hang. The new message makes it clear the daemon is starting and may take a moment.

## [2.23.2] - 2026-03-16

### Fixed

- **Git handlers use `ProjectContext.project_root()` as cwd**: `GitFilemodeCheckerHandler` and `GitContextInjectorHandler` previously ran git subprocess calls without specifying a working directory. Because the daemon process runs from `/`, all git commands failed with "not a git repository" errors. Both handlers now use `ProjectContext.project_root()` as `cwd`, with fallback to the process working directory when `ProjectContext` is not yet initialised. Tests updated to mock `ProjectContext.project_root()` alongside `subprocess.run`.

- **Shell script executable permissions**: Fixed missing executable bit on 7 shell scripts (`install/mode_guard.sh`, `install/test_helpers.sh`, `.claude/skills/mode/invoke.sh`, and four `skills/hooks-daemon/scripts/` scripts). Permissions updated in the git index via `git update-index --chmod=+x`.

## [2.23.1] - 2026-03-16

### Added

- **`GitFilemodeCheckerHandler`**: New SessionStart handler (priority 53, advisory) that warns loudly when `git config core.fileMode=false` is detected. Losing executable permissions on hook scripts after git operations (checkout, merge, rebase) is a common and silent failure mode — this handler surfaces the problem on session start for new sessions only (not resumes). 21 unit tests with full coverage.

- **`git_force_executable` install step**: New step in `scripts/install/hooks_deploy.sh` that runs `git update-index --chmod=+x` on all tracked hook scripts during install and upgrade, ensuring hooks are committed as `100755` regardless of `core.fileMode` setting. Prevents the root cause of silent permission loss.

- **`continue_on_errors` option for `auto_continue_stop` handler**: New boolean option (default: `true`) that controls whether the handler auto-continues even when Claude's stop message contains error patterns like `"error:"` or `"failed:"`. When enabled (default), sessions no longer block waiting for user intervention after a Bash command failure — the daemon auto-continues so Claude can attempt recovery. Configurable via `.claude/hooks-daemon.yaml` under `auto_continue_stop.options.continue_on_errors`.

### Changed

- **`auto_continue_stop` advisory reason improved**: The reason message now explicitly guides Claude toward truly stuck scenarios (blocked on user input, ambiguous requirements, missing credentials) rather than vague continuation prompts. Reduces unnecessary interruptions.

- **Handler reference documentation**: `docs/guides/HANDLER_REFERENCE.md` updated with `continue_on_errors` option entry for `auto_continue_stop`.

## [2.23.0] - 2026-03-15

### Added

- **Command Redirection Core Utility**: New `utils.command_redirection` module providing a reusable mechanism for blocking handlers to automatically execute corrected commands and save output to files. Eliminates wasted turns when a handler blocks a command and suggests a corrected version — Claude receives the educational deny message and the command result in a single turn. Includes `CommandRedirectionResult` dataclass, `execute_and_save()`, `format_redirection_context()`, and `cleanup_old_files()`. 24 unit tests.

- **Command Redirection for `gh_issue_comments` Handler**: When blocking a `gh issue view` command that lacks `--comments`, the handler now automatically executes the corrected command (with `--comments`) and saves the output to a file. Configurable via `command_redirection: true/false` option (default: enabled). Graceful fallback to block-only if execution fails.

- **Command Redirection for `npm_command` Handler**: When blocking raw `npm`/`npx` commands, the handler now automatically executes the corrected `llm:`-prefixed command and saves the output. Configurable via `command_redirection` option (default: enabled). Graceful fallback to block-only if execution fails.

- **Command Redirection for `pipe_blocker` Handler**: When blocking commands piped to `tail`/`head`, the handler now automatically executes the base command (without the pipe) and saves the output to a file. Configurable via `command_redirection` option (default: enabled). Graceful fallback to block-only if execution fails.

- **`ask_user_question_blocker` Handler**: New PreToolUse handler (disabled by default) that blocks `AskUserQuestion` tool calls for fully unattended autonomous workflows. Useful in CI or scheduled agent runs where interactive prompts are not acceptable.

- **Transcript-Based Debugging Guide**: Added `CLAUDE/DEBUGGING_TRANSCRIPTS.md` documenting the technique of using conversation transcripts for post-mortem debugging of hook event issues — analysing actual event payloads from real sessions to investigate handler failures.

### Fixed

- **`auto_approve_reads` Handler Dead Code Bug**: Handler was matching on `permission_type` field which does not exist in real `PermissionRequest` events, making it entirely non-functional. Rewrote to match on `tool_name` (`Read`, `Glob`, `Grep`) which is the actual field present in real events. Handler is now functional.

- **`markdown_organization` Plan Folder Write Returns DENY**: `_handle_plan_write()` previously returned `Decision.ALLOW` after creating the numbered plan folder, causing both a flat file and a folder to exist simultaneously. Now returns `Decision.DENY` with a descriptive reason explaining the redirect path and instructing the agent to rename the folder to something semantic.

## [2.22.0] - 2026-03-13

### Added

- **Plan Workflow Bootstrap**: New installer module (`install.plan_workflow`) that creates a complete `CLAUDE/Plan/` directory structure with README.md template (plan index), CLAUDE.md (lifecycle instructions), and Completed/ subdirectory. Idempotent — never overwrites existing files. Activated via `PLAN_WORKFLOW=yes` environment variable during installation (Step 14).

- **Handler Profiles**: New installer module (`install.handler_profiles`) with three configuration tiers — `minimal` (default, no extra handlers), `recommended` (16 quality/safety handlers including qa_suppression, tdd_enforcement, plan handlers, lint_on_edit), and `strict` (recommended + 8 additional handlers). Applied via `HANDLER_PROFILE=recommended|strict` environment variable during installation (Step 15). Uses text-based YAML modification to preserve comments.

- **Installer Prerequisite Checks**: `check_python_importable` validation in `scripts/install/prerequisites.sh` verifies Python can actually import the daemon package after venv creation, catching broken installs early. Also checks for `uv` availability with automatic fallback to `pip`.

- **Daemon Error Surfacing**: `restart_daemon_verified` in `scripts/install/daemon_control.sh` now captures and displays stderr from failed daemon restarts, showing the actual Python traceback instead of a generic "failed to start" message.

### Fixed

- **Version Module Mismatch**: `__init__.py` was defining `__version__` independently instead of importing from `version.py`, causing potential version drift. Now imports directly: `from claude_code_hooks_daemon.version import __version__`.

- **ModelContext Effort Error Handling**: `_read_effort_level()` in `ModelContextHandler` now uses structured try/except with logging instead of bare exception suppression. OSError and JSON decode errors are caught specifically and logged at warning level, returning `None` to fall through to daemon defaults. Updated QA exclusion to match new line numbers and rule name (`log-and-continue`).

- **Status Line Effort Default**: Corrected `_EFFORT_DEFAULT` from `"high"` to `"medium"` in an earlier release (v2.21.1), but the error handling around reading the effort level was still using bare try/except which violated security standards. Now properly structured.

### Changed

- **Installer Steps 14-15**: `install_version.sh` now includes two new optional steps: Step 14 (plan workflow bootstrap) and Step 15 (handler profile application). Both are opt-in via environment variables and use proper `if/then/else` blocks (SC2015 compliant).

- **Installer Completion Output**: Enhanced post-install summary showing active profile and plan workflow status, plus customisation instructions for re-running with different profiles.

## [2.21.1] - 2026-03-12

### Fixed

- **Statusline Effort Default Corrected**: `ModelContextHandler` was defaulting to `"high"` effort bars when `effortLevel` was absent from `~/.claude/settings.json`, disagreeing with Claude Code's actual default of `"medium"`. The constant `_EFFORT_DEFAULT` is now `"medium"`, so the status line correctly reflects what Claude Code uses when no explicit effort level is configured.

- **Auto-Set Effort Config on SessionStart**: `OptimalConfigCheckerHandler` now writes `effortLevel=high` and `alwaysThinkingEnabled=true` to `~/.claude/settings.json` at the start of each new session when those keys are absent. This keeps the status line in sync with the desired optimal configuration without requiring manual setup. The write is safe: the handler reads the file first and aborts if the read fails, preventing any risk of clobbering existing settings.

### Changed

- **Release Documentation**: Added exact `gh release view` JSON query command to the post-release verification step (Step 11) in `CLAUDE/development/RELEASING.md` for precise release status confirmation.

## [2.21.0] - 2026-03-11

### Added

- **DismissiveLanguageDetectorHandler**: New Stop event advisory handler that scans the last assistant message in the conversation transcript for dismissive language patterns — "not our problem" deflection, "out of scope" avoidance, "someone else's job" pushing, and defer/ignore phrases. When detected, injects a warning instructing the agent to acknowledge the problem and offer to fix it rather than explaining it away. Four pattern categories with 30+ compiled regexes.

- **PseudoEventDispatcher**: New core infrastructure for synthetic daemon-generated events. A pseudo-event hooks into real events via frequency-control notation (`event_type:N/D` — fire N times every D occurrences). The dispatcher maintains per-session counters, runs a shared setup function once per fire (for expensive operations like transcript reading), then dispatches through a dedicated handler chain. Results are merged back into the real event result (DENY wins, context accumulates).

- **Nitpick Pseudo-Event**: First concrete pseudo-event, triggered every 5 PreToolUse events by default. Reads conversation transcript incrementally using byte-offset tracking, extracts new assistant messages, and dispatches through nitpick handler chains. Handlers receive pre-extracted messages — no redundant transcript reads per handler.

- **NitpickDismissiveLanguageHandler**: Nitpick pseudo-event handler that audits assistant messages for dismissive language. Reuses pattern lists from `DismissiveLanguageDetectorHandler` as single source of truth. Runs periodically during sessions rather than only at Stop events.

- **NitpickHedgingLanguageHandler**: Nitpick pseudo-event handler that audits assistant messages for hedging language (guessing instead of researching). Reuses pattern lists from `HedgingLanguageDetectorHandler` as single source of truth.

- **DocsGenerator and generate-docs CLI command**: New `DocsGenerator` class and `generate-docs` CLI command that generates `.claude/HOOKS-DAEMON.md` from live config and handler metadata. Produces an accurate, auto-generated summary of active handlers (including project handlers and plugins), plan mode settings, and config reference. Integrated into the installer so new installations get an up-to-date HOOKS-DAEMON.md automatically.

- **TranscriptReader Incremental Reading**: `TranscriptReader` now supports incremental JSONL reading via `read_incremental(path, byte_offset)`, returning only messages added since the last read position. Also adds `UUID` field to parsed messages and `filter_assistant_messages()` static method. Enables efficient periodic transcript auditing without re-reading the entire file.

- **PlanWorkflowConfig Top-Level Config**: New `plan_workflow` top-level configuration block that centralises plan-related settings previously scattered across handler options. Fields: `enabled`, `directory` (default `CLAUDE/Plan`), `workflow_docs` (default `CLAUDE/PlanWorkflow.md`), `enforce_claude_code_sync`. Automatic migration reads `track_plans_in_project` from `markdown_organization` handler options and populates `plan_workflow` for backwards compatibility.

- **Plan Redirect ALLOW Flow and Numbered Folder Support**: Plan redirect handler now supports an ALLOW flow that correctly accepts writes targeting the project plan directory. Also recognises 5-digit plan folder numbers (e.g. `00085`, `00086`) alongside the existing 3-digit format.

- **plansDirectory Sync Enforcement**: When `plan_workflow.enforce_claude_code_sync` is `true`, the daemon validates that `.claude/settings.json` `plansDirectory` field matches the configured plan directory and injects a correction advisory if they diverge.

- **PostClearAutoExecuteHandler** (prototype, disabled by default): UserPromptSubmit advisory handler that detects the first prompt of a new session and injects guidance for the agent to execute the instruction immediately. Intended to address the `/clear <instruction>` idle agent pattern. Marked as prototype; behaviour may change in future releases.

- **DestructiveGitHandler: Block commit rewriting via amend flag**: Added pattern 9 to the destructive git handler, blocking all `git commit` with the `--amend` flag. Amending rewrites the previous commit and creates messy history — new commits are always preferred.

### Changed

- **DaemonController Pseudo-Event Integration**: `DaemonController.initialise()` now accepts `pseudo_events_config` and `plan_workflow` parameters. After handler registration, pseudo-events are parsed from YAML config, nitpick handlers are registered, and the `PseudoEventDispatcher` is wired into the event dispatch loop. Real event results are merged with pseudo-event results before returning.

- **PlanWorkflowConfig Migration**: `Config` model validator automatically migrates `track_plans_in_project` and `plan_workflow_docs` from `markdown_organization.options` to the new top-level `plan_workflow` block. Existing configs continue to work without changes.

- **HandlerRegistry receives plan_workflow**: Handler registration now passes the `PlanWorkflowConfig` object to the registry, allowing plan-related handlers to read their configuration from the centralised config rather than per-handler options.

### Fixed

- **Block xargs Bypass of Inplace-Edit Blocker**: The sed/inplace-edit blocker now also matches `xargs sed`, `xargs perl -pi`, and `xargs awk -i` patterns, closing a bypass where agents used `find ... | xargs sed -i` to perform in-place file edits.

- **validate_plan_number Uses Hardcoded Plan Directory**: Fixed `validate_plan_number` handler using a hardcoded `CLAUDE/Plan` path instead of reading the configured plan directory from `plan_workflow.directory`. The handler now reads the correct path from config.

- **TranscriptReader Crash on Real Transcripts**: Fixed a crash when parsing JSONL transcript files with unexpected message structures. Parser is now more defensive against missing or malformed content blocks.

- **Dismissive Language Pattern Gaps**: Extended dismissive language pattern set to cover additional deflection phrases missed in initial implementation.

- **Version Cache Flush After Upgrade**: Fixed stale version cache after daemon upgrade. The version cache is now flushed when a new version is detected, ensuring the status line shows the correct version immediately after upgrading.

- **Error Hiding Exclusions for Drifted Lines**: Updated `error_hiding_blocker` handler exclusion line numbers to match current source after upstream code changes caused the exclusions to drift out of alignment.

- **QA Violations in DocsGenerator and CLI**: Fixed ruff lint and mypy type errors introduced during initial DocsGenerator implementation.

## [2.20.0] - 2026-03-09

### Added

- **SecurityAntipatternHandler**: New PreToolUse handler that blocks hardcoded secrets (OWASP A02) and code injection patterns (OWASP A03) using the Strategy Pattern. Supports 12 language strategies via `SecurityStrategy` Protocol and `SecurityStrategyRegistry`:

  - **Secrets** (universal): API keys, tokens, passwords, private keys, connection strings
  - **Python**: `eval()`, `exec()`, `os.system()`, `subprocess` with `shell=True`, `pickle.load()`, unsafe `yaml.load()`, `__import__()`
  - **JavaScript/TypeScript**: `eval()`, `innerHTML`, `document.write()`, `Function()` constructor, `child_process.exec()`
  - **PHP**: `eval()`, `exec()`, `system()`, `shell_exec()`, `passthru()`, `include/require` with variables, `unserialize()`
  - **Go**: `template.HTML()`, `template.JS()`, `template.URL()`
  - **Ruby**: `eval()`, `system()`, `exec()`, `instance_eval()`, `class_eval()`, `Marshal.load()`, `IO.popen()`
  - **Java**: `Runtime.getRuntime().exec()`, `ObjectInputStream`, `XMLDecoder`, `ScriptEngineManager`
  - **Kotlin**: `Runtime.getRuntime().exec()`, `ObjectInputStream()`, `XMLDecoder()`, `ScriptEngineManager`
  - **C#**: `Process.Start()`, `BinaryFormatter`, `LosFormatter`, `ObjectStateFormatter`
  - **Rust**: `from_raw_parts()`, `transmute()`
  - **Swift**: `Process()`, `evaluateJavaScript()`, `NSKeyedUnarchiver.unarchiveObject()`
  - **Dart**: `Process.run()`, `Process.start()`, `innerHTML` assignment

- **ContentBlock Dataclass**: New structured data type for transcript message content blocks (`text`, `tool_use`, `tool_result`) with typed fields for `tool_name`, `tool_input`, and `tool_result_content`. Enables precise querying of transcript data.

- **TranscriptReader Query Methods**: New methods for querying parsed transcript data:

  - `last_assistant_used_tool(tool_name)` - check if assistant's last message used a specific tool
  - `get_last_tool_use_in_message()` - get the last tool_use ContentBlock
  - Real JSONL parsing with structured `ContentBlock` objects

- **Shared Stop Hook Utilities**: New `utils/stop_hook_helpers.py` module with `is_stop_hook_active()` and `get_transcript_reader()` functions, eliminating duplicated logic across stop handlers.

- **Source Guard CLAUDE.md Files**: Added `CLAUDE.md` files to `src/` and `tests/` directories that prevent project-level agents from editing daemon source code, redirecting them to project-level handlers instead.

- **Supported Languages Documentation**: Documented all supported languages across strategy domains (Security, TDD, QA Suppression) in README.md and root CLAUDE.md.

### Changed

- **SecurityAntipatternHandler Refactored to Strategy Pattern**: Migrated from monolithic handler to `SecurityStrategy` Protocol with `SecurityPattern` frozen dataclass and `SecurityStrategyRegistry`. Each language is now an independent strategy class, following the Open/Closed Principle.

- **Pipe Blocker Progressive Verbosity**: First pipe block shows full verbose explanation with alternatives. Subsequent blocks show terse message with just the block reason and suggested command, reducing noise for experienced users.

- **Stop Handlers Use Shared Utilities**: `HedgingLanguageDetector` and `AutoContinueStopHandler` refactored to use shared `stop_hook_helpers` module, removing duplicated transcript reading and stop-hook-active detection logic.

### Fixed

- **AutoContinueStopHandler No Longer Overrides AskUserQuestion**: Fixed bug where the auto-continue handler would override Claude's `AskUserQuestion` tool use, continuing automatically when the user was being asked a question. Handler now checks transcript for `AskUserQuestion` usage before triggering auto-continue.

- **Pipe Blocker Error Message Variable**: Fixed pipe blocker using hardcoded `/tmp/output.txt` path in error messages instead of the `$TEMP_FILE` variable.

## [2.19.0] - 2026-03-06

### Added

- **TDD Collocated Test Support**: TDD enforcement handler now supports collocated test file layouts in addition to the traditional separate `tests/` directory. Three new test location modes are available via the `test_locations` configuration option: `separate` (traditional `tests/` tree), `collocated` (test file next to source file, e.g. Go `_test.go` and React/Jest `*.test.ts`/`*.test.js`), and `test_subdir` (`__tests__/` subdirectory alongside source). All three modes are enabled by default, making the handler work out-of-the-box for Go, JavaScript, TypeScript, and any other language using collocated test conventions.

### Fixed

- **Go Lint Module Root and Package Vetting**: Go lint commands (`go vet`, `golangci-lint`) now run from the correct module root directory (where `go.mod` lives) rather than the file's parent directory, and vet entire package directories instead of single files. This fixes cross-file reference resolution failures in multi-file packages and multi-module repositories where types defined in sibling files were unresolvable.

## [2.18.0] - 2026-03-05

### Added

- **LspEnforcementHandler**: New PreToolUse handler that steers LLMs toward LSP tools (goToDefinition, findReferences, workspaceSymbol, hover, documentSymbol) instead of Grep/Bash grep for symbol lookups. Detects symbol-like search patterns — class/def definitions, PascalCase and snake_case identifiers, import statements — and blocks or advises the LLM to use semantic LSP operations instead of slow, imprecise text searches. Supports three modes: `block_once` (default, deny first attempt), `advisory` (always allow with guidance), and `strict` (always deny). Also supports configurable `no_lsp_mode` behaviour when `ENABLE_LSP_TOOL` env var is not set: `block` (default), `advisory` (downgrade), or `disable` (handler inactive). Priority 38 (workflow range).

### Fixed

- **Status Line Upgrade Indicator**: Fixed the upgrade-available indicator in the daemon status line showing only the target version. The indicator now displays both the current version and the target version (e.g. `v2.17.3 → v2.18.0`) so users immediately see what they are upgrading from and to. Falls back to `upgrade → vX.Y.Z` if current version is unavailable in the cache.
- **NpmCommandHandler False Positive on Logical OR**: Fixed the pipe detection regex in NpmCommandHandler matching `||` (logical OR) as a pipe operator. Commands like `npx hooks-daemon restart 2>/dev/null || npx claude-code-hooks-daemon restart` were incorrectly blocked with "Piping npm/npx commands is pointless". The regex now uses lookahead/lookbehind (`(?<!\|)\|(?!\|)`) to only match single `|` pipe operators.
- **PHP TDD Strategy Interface Skipping**: Fixed TDD enforcement handler requiring test files for PHP interface files, which have no behaviour to test. Added two detection methods: filename convention (`*Interface.php` suffix) and content inspection (files declaring `interface` without `class`). Extended the `should_skip()` protocol method to accept an optional `content` parameter across all 11 language strategies for content-aware skip decisions.
- **Silent Exception Hiding in TDD Handler Path Mapping**: Removed `try/except (ValueError, IndexError): pass` blocks that silently swallowed errors in TDD handler path mapping. Callers already guard with `if _SRC_DIR in path_parts` before calling, so these exceptions cannot occur in practice. Removing them enables fail-fast behaviour for real bugs.
- **Skill Tool Invocation Clarification**: Fixed CLAUDE.md install templates (LLM-INSTALL.md, LLM-UPDATE.md) incorrectly showing `/hooks-daemon restart` in bash code blocks, causing Claude to attempt running it as a bash command instead of using the Skill tool. Updated to clearly instruct Claude to use the Skill tool. Also changed `disable-model-invocation` from `true` to `false` so Claude can invoke the hooks-daemon skill.

## [2.17.3] - 2026-02-27

### Fixed

- **Upgrade Skill Version String Bug**: Fixed the `/hooks-daemon upgrade` skill passing the literal string `"latest"` as the target version instead of resolving the actual latest release tag. This caused the upgrade script to fail when attempting to checkout a non-existent `latest` ref.

## [2.17.2] - 2026-02-27

### Fixed

- **Plan Number Validation TOCTOU Race Condition**: Fixed false positive where the `validate_plan_number` handler incorrectly demanded the next sequential plan number when a preceding `mkdir` had already created the plan directory before the `Write` tool created `PLAN.md`. The handler now accepts `plan_number == highest` (directory already created by mkdir) in addition to `plan_number == highest + 1` (normal new-plan case).
- **Plan Number Handler False Positives on Archive Operations**: Fixed `validate_plan_number` handler incorrectly triggering when archiving plans via `git mv` to `CLAUDE/Plan/Completed/` or any organisational subfolder. Changed regex from `.*?` to `[^&;]*` to prevent matching across `&&`/`;` command boundaries into unrelated `git mv` arguments. Handler now matches only direct children of the `Plan/` root and scans all non-numbered organisational subfolders when detecting the highest existing plan number.
- **Plan Number Handler Hardcoded 3-Digit Width**: Fixed `validate_plan_number` handler silently ignoring plan numbers with more or fewer than 3 digits. The handler used `\d{3}` regex which only matched exactly 3-digit numbers (e.g. `001`), causing it to completely skip validation for 5-digit plans like `00072` used by this project. Changed all regex patterns to `\d+` to support any digit width. Removed hardcoded `:03d` zero-padding from error messages.

## [2.17.1] - 2026-02-27

### Fixed

- **Upgrade Skill Missing --project-root Argument**: Fixed the `/hooks-daemon upgrade` skill wrapper script failing with "ERR --project-root requires a path argument". The skill wrapper was not passing the required `--project-root` argument to the daemon's upgrade script, causing all skill-based upgrades to fail.

## [2.17.0] - 2026-02-27

### Added

- **Daemon Modes System**: Runtime-mutable operating modes with "unattended" mode that blocks Stop events, preventing accidental daemon shutdown during unattended operations. Includes full IPC support (`get_mode`/`set_mode` actions), controller integration, CLI commands (`get-mode`/`set-mode`), and `/mode` skill for interactive mode management.
- **Restart Mode Preservation Advisory**: New advisory that detects when daemon modes are configured and reminds users that `restart` resets modes to defaults, recommending `set_mode` after restart to restore desired modes.
- **CLI Acceptance Test System**: New `generate-playbook` CLI command and `CliAcceptanceTest` infrastructure for non-handler features (daemon modes, CLI commands), extending acceptance testing beyond handler-only coverage.
- **Priority.DEFAULT Constant**: New named constant (`Priority.DEFAULT = 50`) as single source of truth for the default handler priority value.
- **Bug Report Generator**: New `bug-report` CLI subcommand that generates comprehensive structured markdown reports with daemon version, system info, daemon status, configuration, loaded handlers, recent logs, environment variables, and health summary. Works gracefully when daemon is not running. Accessible via CLI (`bug-report "description"`) and skill (`/hooks-daemon bug-report`).

### Fixed

- **NoneType Priority Comparison Crash**: Fixed `TypeError: '<' not supported between instances of 'NoneType' and 'int'` when a handler has `priority=None`. Defence-in-depth fix across four layers: validator rejects `priority: null` in config, registry skips None priority override, chain sort applies default before sorting, and project loader validates priority post-instantiation.
- **Hedging Language Detector Misses Standalone Adverbs**: Fixed hedging language detector failing to match standalone hedging adverbs (e.g., "probably", "maybe") that weren't part of longer phrases.

### Removed

- **OrchestratorOnlyHandler**: Removed dead code handler that was never enabled in any configuration, superseded by upstream Claude Code delegate mode.

## [2.16.1] - 2026-02-22

### Fixed

- **Upgrade early-exit skips skill and slash-command deployment**: When the installed version already matched the target version, `scripts/upgrade_version.sh` would exit early after only restarting the daemon, bypassing hook script deployment, `settings.json`, `.gitignore`, slash commands, and skills deployment. Projects on v2.16.0 that had not yet received skills (introduced in Plan 00061, 17 Feb 2026) could not get skills deployed by re-running the upgrade script. Replaced the minimal early-exit path with the full idempotent deployment sequence so all deployment steps run safely regardless of whether a version change occurred.

## [2.16.0] - 2026-02-22

### Added

- **Version-aware config migration advisory system**: New PostToolUse handler (`version_aware_config_migration`) that detects when the daemon version in the active session differs from the installed daemon version and advises the user to run the config migration tool. Prevents users from running stale configurations after upgrades.
- **`blocking_mode` option for SedBlockerHandler**: SedBlockerHandler now supports a `blocking_mode` configuration option (`block` or `warn`) allowing teams to choose between hard-blocking dangerous sed patterns or issuing an advisory warning. Full docs and acceptance test included.
- **`/configure` skill**: New `/configure` skill enabling structured configuration of the daemon through a guided workflow. Provides a SSOT-aligned approach to setting daemon options.
- **Coverage tests to reach 95.1% threshold**: Additional unit tests added to bring overall test coverage from below threshold to 95.1%, satisfying the mandatory 95% coverage gate.

### Fixed

- **Plan file race condition in planning mode redirect**: `plan_completion_advisor` handler now correctly returns `DENY` after redirecting to planning mode, preventing the hook from falling through to allow when it should be blocking.
- **PipeBlocker false positives on grep alternation patterns**: `pipe_blocker` handler no longer triggers false positives on grep commands using alternation patterns (e.g. `grep "foo\|bar"`). Whitelist expanded to cover common safe pipe-including patterns.

## [2.15.2] - 2026-02-21

### Added

- **Config header restart reminder in generated hooks-daemon.yaml**: New installations now receive a restart-reminder header comment at the top of the generated `.claude/hooks-daemon.yaml` config file, showing the exact daemon restart command. Reduces friction when users edit their config and forget to restart the daemon.
- **`/hooks-daemon restart` subcommand documentation**: Added restart as a first-class documented subcommand in `skills/hooks-daemon/SKILL.md`, with a dedicated `skills/hooks-daemon/restart.md` reference doc covering syntax, examples, and when to use it.
- **Post-installation and post-update CLAUDE.md instructions**: `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` now include a "Post-Installation: Update Project CLAUDE.md" and "Post-Update: Update Project CLAUDE.md" section instructing LLM agents to add a `### Hooks Daemon` section to project CLAUDE.md files after installation or upgrade.
- **Check Config Header guidance in install/update docs**: `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` include a "Also: Check Config Header" subsection instructing agents to verify the restart-reminder header is present in `hooks-daemon.yaml` and add it if missing.

## [2.15.1] - 2026-02-20

### Added

- **Status line section in README**: New documentation section describing the status line hook, its format, and the colon-separator convention with upgrade indicator.
- **Error hiding audit exclusions file** (`scripts/qa/error_hiding_exclusions.json`): Formal exclusion list documenting 75 intentional fail-open patterns (plugin discovery, container detection, JSONL parsing loops, daemon infrastructure) with documented reasons. Distinguishes intentional error handling from genuine error hiding.

### Changed

- **README rewritten to lead with developer experience value proposition**: README restructured to open with concrete developer pain points and benefits rather than technical implementation details.
- **Error hiding audit integrated into QA pipeline**: The error-hiding audit check is now a formal step in the QA pipeline, ensuring all future code changes are validated against error-hiding patterns automatically. Includes deduplication logic and exclusion file support.
- **Status line section uses colon separators and upgrade indicator**: Status line hook output format updated to use consistent colon separators and includes an upgrade indicator when a newer daemon version is available.

### Fixed

- **Silent error hiding in monitoring handlers**: Four monitoring handlers (`notification_logger`, `transcript_archiver`, `cleanup_handler`, `subagent_completion_logger`) silently swallowed `OSError` exceptions with bare `pass`. Fixed to log at `WARNING` level so failures are visible in daemon logs without disrupting operation.
- **Silent error hiding in hook dispatchers**: All 10 hook entry points (`hooks/*.py`) silently continued past `RuntimeError` when instantiating handlers that require `ProjectContext`. Fixed to log handler name and error at `WARNING` level.
- **enforce-llm-qa priority collision** (15 to 41): `enforce_llm_qa` handler priority corrected from 15 (which collided with `error_hiding_blocker` at priority 13 in the safety range) to 41 (workflow range). Improves pipe blocker snippet in documentation.
- **Status line example replaced with actual output**: Replaced an invented/illustrative status line example in documentation with the real output produced by the daemon.

## [2.15.0] - 2026-02-19

### Added

- **ErrorHidingBlockerHandler** (PreToolUse:Write, priority 13): New safety handler that blocks error-hiding patterns before files are written to disk. Uses Strategy Pattern with 5 language strategies (Shell, Python, JavaScript/TypeScript, Go, Java). Detects patterns including `|| true`, `|| :`, `set +e`, `except: pass`, empty catch blocks, swallowed exceptions, and other silent failure constructs that mask bugs. Implements Plan 00063 Phase 3.
- **PipeBlockerHandler Strategy Pattern redesign** (Plan 00064): PipeBlocker refactored from monolithic implementation to Strategy Pattern architecture. 8 language strategies shipped: Shell, Python, JavaScript/TypeScript, Go, Java, Ruby, Rust, and Universal. Registry-based design allows adding new strategies without modifying handler logic.
- **Shellcheck QA integration** (check 8): Added `shellcheck -x` as QA pipeline check #8. All shell scripts must pass shellcheck with zero errors and zero warnings. `.shellcheckrc` configuration file added with `source-path=SCRIPTDIR` for proper source-following.
- **Color-coded git branch in status line**: Branch name in the status line now renders green for the default branch, orange for non-default branches, and grey when the branch is unknown.
- **Code review gate in release process** (Step 7.5): New blocking gate added to RELEASING.md requiring review of the code diff (`git diff LAST_TAG..HEAD -- src/`) before proceeding to acceptance testing. Ensures bugs and anti-patterns are caught before release.
- **Acceptance test scoping by bump type**: MAJOR and MINOR releases require the full acceptance test suite. PATCH releases with handler changes require targeted tests for changed handlers only. PATCH releases with no handler changes may skip acceptance testing with documented rationale in release notes.
- **`recommended_model` and `requires_main_thread` fields on `AcceptanceTest`**: New metadata fields on the `AcceptanceTest` dataclass allow test definitions to declare which model is recommended for execution and whether the test must run in the main Claude Code thread (not a sub-agent).
- **`RecommendedModel` enum**: Type-safe enum for specifying recommended model in acceptance test metadata (`OPUS`, `SONNET`, `HAIKU`).

### Fixed

- **Shellcheck warnings across all shell scripts**: Resolved all shellcheck warnings including SC2034 (unused variables), SC2155 (declare and assign separately), SC2120/SC2119 (function argument handling), and SC1091 (source file following). All scripts now pass `shellcheck -x` with zero issues.
- **ESLint PATH in validate_eslint_on_write**: Prepend `node_modules/.bin` to PATH in the subprocess call so locally-installed ESLint binaries are found without requiring global installation.
- **health-check.sh wrong command name**: Fixed health-check.sh using the incorrect `config-validate` command; updated to the correct `validate-config` command name.
- **Dockerfile GPG key dearmoring for Dart SDK**: Fixed Dart SDK apt repository setup in the CCY Dockerfile by properly dearmoring the GPG key before adding it to the apt trusted keyring.
- **CCY Dockerfile tracking**: Fixed `.gitignore` rule that prevented the CCY Dockerfile from being tracked by git; removed the blanket `ccy/` ignore pattern.
- **PipeBlocker acceptance test commands**: Fixed acceptance test commands. Original `echo`-wrapped commands were silently allowed (echo is whitelisted). Final pattern: `false && CMD | tail -N` for blacklisted commands (bash `|` binds tighter than `&&` so `false` short-circuits before CMD runs; `_extract_source_segment` splits on `&&` leaving `CMD` as source → blacklist path exercised, "expensive" message verified). Unknown-command test uses `[[ "CMD | tail" == 0 ]]` no-op (safe string comparison, no execution).

## [2.14.0] - 2026-02-18

### Added

- **NEW: /hooks-daemon User Skill** (Plan 00061, commits bd3eb72, dda0dcc, 7fc9415, d18fb50, 649d6d4, 37a0b52, ab73b82, a6222fe)

  - User-facing skill deployed to `.claude/skills/hooks-daemon/` during installation
  - Single skill with argument-driven routing (manual invocation only)
  - **Subcommands**:
    - `upgrade` - Upgrade daemon to new version (auto-detect, specific version, force reinstall)
    - `health` - Comprehensive health check (status, config, handlers, logs, DEGRADED MODE recovery)
    - `dev-handlers` - Scaffold project-level handlers with TDD workflow guidance
    - `logs` - View daemon logs
    - `status` - Check daemon status
    - `restart` - Restart daemon
    - `handlers` - List loaded handlers
  - **Documentation**: 5 markdown files (main skill + upgrade + health + dev-handlers + troubleshooting)
  - **Deployment**: Integrated with install_version.sh (Step 10) and upgrade_version.sh (Step 13)
  - **Skills packaged WITH daemon** and deployed during installation/upgrade
  - Enhanced error messages for plugin handler abstract method violations (v2.13.0 breaking change fix)

- **Breaking Changes Lifecycle Infrastructure** (Plan 00062, commits aac0f3e, d5b002b, 0454d9e, 5205851, c94af3e, d0094ce, 19f65af)

  - **Historical Upgrade Guides**: Created comprehensive guides for v2.10→v2.11, v2.11→v2.12, v2.12→v2.13
  - **Automated Breaking Changes Detection**: RELEASING.md Step 6.5 blocking gate
  - **Smart Upgrade Validation**: Pre-upgrade compatibility checks, config diff analysis, breaking changes warnings
  - **Upgrade Guide Enforcement**: Interactive reading confirmation before proceeding
  - **New Components**:
    - `breaking_changes_detector.py` - Parses CHANGELOG.md for breaking change markers (14 tests)
    - `upgrade_compatibility.py` - Validates user config against target version (13 tests)
    - `config_diff_analyzer.sh` - Compares handler names with fuzzy rename detection
  - **Upgrade Script Integration**: Three safety gates (before/during/after upgrade)
  - **Release Notes Format**: BREAKING CHANGES sections with handler removals/renames
  - Total: 5,842+ lines of code/docs, 25 new files, 27 tests

- **Test Coverage Improvements**: Increased coverage from 94.89% to 95.2% (commits b8eeb89, bb364a7)

  - Core module and handler test coverage improvements
  - Protocol and strategy test coverage enhancements
  - ImportError tests for input_schemas.py (100% coverage)
  - Edge case tests for router.py (100% coverage)
  - Unknown extension tests for tdd_enforcement.py (95.24% coverage)
  - Protocol isinstance tests for TDD, QA Suppression, and Lint strategies
  - Lazy import tests for lint module

- **Release Workflow State Management** (commit 5be1cf0)

  - Release process now uses workflow state files for compaction resilience
  - State tracking for 14 release phases
  - Enables WorkflowStatePreCompactHandler/RestorationHandler integration
  - State files: `./untracked/workflow-state/release/state-release-TIMESTAMP.json`

- **Comprehensive Plan Workflow Documentation** (commit 15e3591)

  - New `docs/PLAN_WORKFLOW.md` (1,600 lines, 41KB)
  - Complete guide to structured planning with numbered folders
  - 10 major sections covering philosophy, setup, customization, examples
  - Documents 5 handlers supporting workflow automation
  - Step-by-step setup instructions for new projects
  - Real-world examples (feature, refactoring, bug fix plans)
  - Project-agnostic design (works with any codebase)

- **Error Hiding Audit Script** (Plan 00063 Phase 2, commit 7eaf65d)

  - AST-based audit tool detecting silent error patterns
  - Detects: silent try/except/pass, silent continue, return None on errors, log-and-continue, bare except
  - Found 93 violations across 27 files (systemic problem documented)

- **Effort Level Signal Bars in Status Line** (commits 6ab6e70, 3fca72c)

  - Added effort level signal bars (▌▌▌) to status line for all models
  - Enhanced display for Claude 4+ models
  - Bars visually indicate current effort level during AI processing

### Changed

- **FAIL FAST Enforcement** (Plan 00063, commits ef650d3, 887f52c)

  - **Project Handlers (TIER 1)**: Always crash on errors (no graceful failure)
    - Changed ProjectHandlerLoader return type from `Handler | None` to `Handler`
    - All errors raise RuntimeError immediately (file not found, import errors, no Handler class, multiple classes, instantiation failure)
    - Updated 8 tests to expect RuntimeError instead of None
    - Moved error fixtures to `project_handlers_error_cases/` directory
  - **Library Handlers (TIER 2)**: Strict mode controlled (handler discovery, optional features)
    - ConfigValidator.get_available_handlers() accepts strict_mode parameter
    - In strict_mode=True: CRASH on handler discovery import errors
    - In strict_mode=False: Log and continue gracefully
  - **New DRY Utility**: `utils/strict_mode.py` with `handle_tier2_error()` and `crash_in_strict_mode()` helpers (7 tests)
  - **Plugin Loading**: Daemon CRASHES if configured handlers can't be loaded (not warns)

- **Documentation Structure** (commit 8c4c88b)

  - Separated Plans from Workflows documentation for clarity
  - **Plans**: Development work tracking (CLAUDE/Plan/, docs/PLAN_SYSTEM.md)
  - **Workflows**: Repeatable processes surviving compaction (docs/WORKFLOWS.md)
  - Clear distinction between optional vs required handlers for each system
  - Renamed `docs/PLAN_WORKFLOW.md` → `docs/PLAN_SYSTEM.md`
  - Created new `docs/WORKFLOWS.md` documenting workflow concept properly

- **MarkdownOrganizationHandler**: Allow edits to `src/claude_code_hooks_daemon/skills/` (commit dda0dcc)

  - Enables writing SKILL.md and supporting docs during skill development
  - Skills are packaged with daemon (not deployed separately)

### Fixed

- **CRITICAL: Plugin Handler Suffix Bug** (Plan 00063 Phase 1, commit ef650d3)

  - Plugin handlers with "Handler" suffix now register correctly
  - Root cause: Asymmetry between PluginLoader.load_handler() (correctly handles suffix) and DaemonController.\_load_plugins() (only checked base name)
  - **Before**: MyPluginHandler silently skipped with warning, daemon ran unprotected
  - **After**: Daemon checks both ClassName and ClassNameHandler variants, CRASHES if configured handler can't be matched
  - Added test_load_plugin_with_handler_suffix (Handler suffix now works)
  - Added test_daemon_crashes_on_unmatched_plugin_handler (FAIL FAST enforcement)
  - Updated 6 tests expecting old buggy behavior to expect CRASH

- **Documentation Organization** (commits 8c4c88b, 15e3591)

  - Fixed Plans vs Workflows documentation confusion
  - Previously conflated two separate concepts in single location
  - Now properly separated with clear purposes and lifecycles
  - Enhanced task breakdown guidance and completion checklist procedures

- **Test Bug**: Fixed test_plugin_daemon_integration.py assertion matching "NOT RUNNING" (commit 99eeee7)

  - Changed to check for "Daemon: RUNNING" specifically

- **Import Error**: Fixed test_upgrade_compatibility.py import (commit d0094ce)

  - Changed `constants.event` → `constants.events`

- **Effort Level Signal Bars Styling** (commits 95a6b4d, 0b031b1)

  - Fixed bar colours: orange (active) / grey (inactive) matching Claude Code UI
  - Fixed bar character to ▌▌▌ matching Claude Code's actual effort UI

- **Black Formatting**: Applied formatting fixes (commits 04a0125, d0094ce)

  - Fixed test_enforcement.py formatting issues
  - Fixed test_controller.py formatting issues

## [2.13.0] - 2026-02-17

### Added

- **ReleaseBlockerHandler**: New project-specific Stop event handler enforcing acceptance testing gate during releases (Plan 00060, commits 1de40fc, 1796310, 6841e8c)

  - Detects release context by checking for modified version files (pyproject.toml, version.py, README.md, CHANGELOG.md, RELEASES/\*.md)
  - Blocks Stop events during releases with clear message referencing RELEASING.md Step 8
  - Prevents infinite loops via stop_hook_active flag, fails safely on git errors
  - Priority 12 (before AutoContinueStop at 15)
  - Addresses AI acceptance test avoidance behavior
  - 22 unit tests + 4 integration tests, all passing

- **Single Daemon Process Enforcement**: New `enforce_single_daemon_process` configuration option (Plan 00057, commits fc43d03, 3b0df03, 17b3420, a491809, c07e2bb, 6c38904, 6b6adca)

  - Prevents multiple daemon instances from running simultaneously
  - In containers: Kills ALL other daemon processes system-wide on startup (SIGTERM → SIGKILL)
  - Outside containers: Only cleans up stale PID files (safe for multi-project environments)
  - Auto-detection: Configuration generation auto-enables in container environments
  - 2-second timeout for graceful shutdown before force kill
  - 40 new tests, 95.1% coverage maintained, 0 regressions

- **Plan Execution Strategy Framework**: Added execution strategy guidance to planning workflow (commit b960f23)

  - Strategy selection matrix (Simple/Medium/Complex/Critical complexity levels)
  - Three strategies: Single-Threaded, Sub-Agent Orchestration, Sub-Agent Teams
  - Model-specific guidance for optimal execution approach
  - New plan header fields: Recommended Executor, Execution Strategy

### Changed

- **Acceptance Testing Methodology**: Made acceptance testing realistic and efficient (commit 7cd9baa)

  - Categorized tests: EXECUTABLE (89 tests, 20-30 min), OBSERVABLE (10 tests, 30 sec), VERIFIED_BY_LOAD (30 tests, 0 min)
  - Updated RELEASING.md Step 8 with realistic categories and time estimates
  - Enhanced playbook generator with category annotations
  - Reduced testing burden from 127+ unrealistic tests to 89 achievable tests
  - Clear expectations about what to test vs skip

- **Plan Execution Guidance**: Clarified model capabilities for plan orchestration (commits 2983fa6, bc10236)

  - **CRITICAL**: Haiku 4.5 CANNOT orchestrate plans (only Opus/Sonnet)
  - Removed soft language and waffling about model capabilities
  - Minimum: Sonnet 4.5 for plan orchestration (hard requirement)
  - Clear guidance on when to use Opus vs Sonnet for plan execution

- **MarkdownOrganizationHandler**: Added support for plan subdirectories (Plan 00059, commits b496d68, 8f1d0df, 38b9d42)

  - Now allows edits to Completed/, Cancelled/, Archive/ subdirectories
  - Added \_PLAN_SUBDIRECTORIES constant for validation
  - Fixed validation logic to check subdirectory paths correctly
  - Updated 5 completed plans with proper status and completion dates

### Fixed

- **PHP QA Suppression Pattern Gaps**: Fixed CRITICAL bug allowing developers to bypass quality controls (Plan 00058, commits 6ae79e4, 7252bfe)

  - **SECURITY**: Handler was missing 8 suppression patterns, allowing unblocked suppressions
  - Added @phpstan-ignore, phpcs:disable/enable, phpcs:ignoreFile, @codingStandardsIgnore patterns
  - Added 8 comprehensive TDD regression tests
  - Added 3 acceptance tests for critical patterns
  - All patterns now use string concatenation to avoid self-matching

- **Black Formatting**: Fixed formatting issues in test_enforcement.py (commit 609a2ef)

- **QA Issues**: Fixed magic value violations and type errors after Phase 2 & 3 of Plan 00057 (commit c4270d3)

  - Added Timeout.PROCESS_KILL_WAIT constant (2 seconds)
  - Properly typed psutil optional import with ModuleType annotation

## [2.12.0] - 2026-02-12

### Added

- **LintOnEditHandler with Strategy Pattern**: New PostToolUse:Edit handler providing instant linting feedback for 9 languages (Plan 00054, commits 340d806, b7a7d9f, 8db361d, 9b56161)

  - Strategy-based architecture with Protocol interface for language-specific linting
  - 9 language strategies: Python (ruff), JavaScript/TypeScript (eslint), Ruby (rubocop), PHP (phpcs), Go (golangci-lint), Rust (clippy), Java (checkstyle), C/C++ (clang-tidy), Shell (shellcheck)
  - Registry pattern with config-filtered loading (only active project languages)
  - Each strategy independently TDD-able with its own test file
  - Priority 30 (code quality tier), non-terminal to allow other handlers
  - Comprehensive negative acceptance tests for all 9 strategies
  - Uses `sys.executable` for Python linting instead of hardcoded binary paths (commit 9f94158)

- **WorkingDirectoryHandler**: New SessionStart handler displaying current working directory in orange when it differs from project root (commits fe59c0c, aee79cd)

  - Helps users identify when Claude Code's cwd != project root
  - Orange color (38;2;255;165;0) for visual prominence
  - Priority 58 (workflow tier), non-terminal
  - Only displays when cwd differs from project root (reduces noise)

- **CurrentTimeHandler**: New SessionStart handler displaying current timestamp in status line (commit 4b7f7b6)

  - Shows ISO 8601 timestamp (YYYY-MM-DD HH:MM:SS) at session start
  - Priority 59 (workflow tier), non-terminal
  - Helps users track session timing and context freshness

- **DaemonLocationGuardHandler**: New PreToolUse:Bash handler enforcing daemon directory security (commits 48837e5, 0d91040, cf9c6f1, Plan 00056)

  - Blocks bash commands attempting to run daemon CLI outside `.claude/hooks-daemon/` installation directory
  - Prevents accidental execution from incorrect locations (e.g., workspace root in self-install mode)
  - Whitelisting system for allowed daemon directories via `project_root` config
  - Priority 15 (safety tier), terminal (blocks execution)
  - 100% test coverage with positive/negative cases

### Fixed

- **TDD Handler Multi-Path Detection**: Fixed bug where TDD handler only detected first test directory convention (commits b3cb0ba, 0a743fb, e5adfb5, Plan 00055)
  - Bug: Handler checked if `tests/` OR `test/` existed, but stopped after first match
  - Bug: Projects with both conventions (Python `tests/` + Node `test/`) weren't fully detected
  - Fix: Handler now detects ALL matching test directory conventions
  - Added comprehensive test coverage for single and multi-convention projects

## [2.11.0] - 2026-02-12

### Added

- **LLM-Optimized QA Script**: New `scripts/qa/llm_qa.py` wrapper producing ~16 lines of structured output instead of 200+ verbose lines (Plan 00053, commits da71c17, 5b1f1fa)

  - Unified QA runner supporting individual tools or all checks
  - JSON output with jq hints for drill-down investigation
  - Cross-checks tool exit codes against JSON to catch reporting inaccuracies
  - `--read-only` mode for non-interactive environments
  - Project-level handler enforces usage of LLM script over verbose `run_all.sh` (commit cedb3c0)

- **Per-Handler Documentation Structure**: Handler-specific documentation files in `docs/guides/handlers/` (commit 7763c05)

  - One markdown file per complex handler with full configuration options
  - First extraction: `markdown_organization.md` with monorepo interaction and custom paths
  - `HANDLER_REFERENCE.md` links to per-handler files instead of duplicating content
  - Config templates include doc links for each handler

- **Monorepo Support for Markdown Organization Handler**: Sub-project directory configuration (commits 21c0349, da7d750)

  - New `_monorepo_subproject_patterns` config option for regex patterns matching sub-project directories
  - Sub-projects can have their own `CLAUDE/`, `docs/`, `untracked/`, `RELEASES/`, `eslint-rules/` directories
  - 13 new tests covering monorepo allow/block scenarios
  - Backward compatible with existing single-project configurations

- **Configurable Allowed Markdown Paths**: Custom regex patterns for markdown organization handler (commit 10ed5dd)

  - New `allowed_markdown_paths` config option overrides ALL built-in path checks
  - `CLAUDE.md`, `README.md`, `CHANGELOG.md` remain always-allowed regardless of custom patterns
  - Documented as commented defaults in YAML config for easy customization
  - 19 tests covering interaction with monorepo configuration

- **Critical Thinking Advisory Handler**: New UserPromptSubmit handler to encourage deeper analysis (commits 2c4266d, 4a30b6e, 51e530e)

  - Triggers on complex tasks involving architecture, refactoring, or multi-file changes
  - Advises LLMs to consider edge cases, dependencies, and failure modes before implementation
  - Non-blocking advisory mode with configurable trigger patterns
  - New HandlerID.CRITICAL_THINKING_ADVISORY constant

- **LLM Command Wrapper Guide**: Comprehensive language-agnostic guide for wrapping CLI tools (commits 2c4266d, ca50a3b, 5bc354c, 8dfdcfc)

  - New `guides/` package with `llm-command-wrappers.md` documentation
  - Covers JSON output, error handling, context awareness, and LLM-optimized formatting
  - NPM and ESLint advisory handlers reference guide path
  - Markdown organization handler allows `guides/` directory
  - New `get_llm_command_guide_path()` utility function

- **Config Key Injection in DENY/ASK Responses**: Infrastructure-level feature for user-friendly handler disabling (commits b428e54, fa82460)

  - EventRouter and FrontController inject config paths into all DENY/ASK responses
  - Users see exact config path to disable blocking handler immediately
  - Zero individual handler changes needed (handled at routing layer)
  - Example: "To disable this handler, set `handlers.pre_tool_use.destructive_git.enabled: false`"

- **Force Branch Deletion Blocking**: Extended destructive git handler to catch forced branch deletions (commit f0a03b9)

  - Blocks `git branch -D` and `git branch --delete --force` patterns
  - Added to existing destructive git safety checks

- **Blocking Handler False Positives Documentation**: New CLAUDE.md section explaining intentional string matching behavior (commit 80a2f25)

  - Documents why handlers match patterns in commit messages (enables acceptance testing)
  - Explains false positives are intentional and trivial to work around
  - Provides examples and workarounds for describing fixes without triggering blocks

### Changed

- **MyPy Color Output Disabled**: Fixed false-negative error reporting in type checking (commit da71c17)

  - Bug: ANSI color codes broke mypy error parsing in JSON output
  - Bug: `run_type_check.sh` reported 0 errors when mypy found real errors
  - Fix: Added `--no-color-output` flag to mypy invocation
  - JSON results now accurately reflect actual type checking errors

- **Handler Class Attributes**: Added missing `_project_languages` to `__slots__` and type annotations (commit da71c17)

  - Fix: MyPy `attr-defined` error for handlers using project language detection
  - Ensures strict type safety for handler class attributes

- **Thinking Mode Status Priority**: Moved from priority 25 to 12 for better visibility (commit 990bb1f)

  - Displays next to model name in session start messages
  - More prominent position for critical thinking advisory context

- **NPM Handler LLM Command Detection & Advisory Mode**: NPM handler now detects `llm:` commands in package.json (commits fa82460, c5e2283, baeb7ae)

  - New shared utility `utils/npm.py` with `has_llm_commands_in_package_json()` function
  - **NpmCommandHandler**: DENY when `llm:` commands exist (blocks raw npm), ALLOW with advisory when absent
  - **ValidateEslintOnWriteHandler**: Run ESLint when `llm:` commands exist, skip with advisory when absent
  - Advisory messages reference LLM command wrapper guide for proper usage patterns
  - Encourages teams to use LLM-optimized wrappers instead of raw CLI tools

### Fixed

- **Type Check JSON Accuracy**: Cross-validation prevents false-negative QA reports (commit da71c17)

  - `llm_qa.py` now cross-checks tool exit codes against JSON results
  - Catches cases where JSON reports success but tool exited with error code
  - Prevents silent failures in CI/CD pipelines

- **Deprecated Handler Attribute**: Fixed 6 handlers using deprecated `name=` parameter instead of `handler_id=` (commit f0a03b9)

  - Updated handlers to use HandlerID constants for self-identification
  - Maintains consistency with handler registry architecture from Plan 00039
  - Affected handlers: pip_break_system, sudo_pip, curl_pipe_shell, dangerous_permissions, global_npm_advisor, lock_file_edit_blocker

- **Silent Exception Suppression**: Fixed registry.py silently hiding import errors (commit f0a03b9)

  - Bug: Bare try/except/pass suppressed handler loading failures without logging
  - Fix: Added explicit error logging before suppression
  - Maintains FAIL FAST principle - errors are now visible in daemon logs

### Removed

- **Project-Specific Hangover Handlers**: Cleaned up two handlers that belonged in project-level config (commit 990bb1f)
  - Removed `validate_sitemap` handler (PostToolUse) - project-specific validation
  - Removed `remind_validator` handler (SubagentStop) - project-specific reminder
  - Updated all constants, configs, tests, docs, and install template

## [2.10.1] - 2026-02-11

### Fixed

- **Ghost Handler Cleanup**: Removed non-existent stats_cache_reader handler from config, deduplicated handler priorities (commit adf2ae6)

  - Bug: Config referenced handler that was never implemented
  - Bug: Multiple handlers shared same priority values
  - Fix: Removed ghost handler entry from hooks-daemon.yaml
  - Fix: Adjusted handler priorities to eliminate duplicates

- **Socket Path Discovery Agreement**: Fixed init.sh and Python fallback logic to use same socket path discovery (commit 199dd00)

  - Bug: init.sh bash script and Python installer.py used different socket path logic
  - Bug: Could result in init.sh creating wrong directory structure
  - Fix: Both now use consistent socket path discovery via daemon/paths.py

- **.gitignore Auto-Creation**: Daemon now auto-creates .claude/.gitignore if missing, non-fatal if fails (commit 8285e7c)

  - Bug: Missing .gitignore caused untracked daemon runtime files to appear in git status
  - Bug: UV_LINK_MODE environment variable not set for uv package manager
  - Fix: Auto-create .gitignore on daemon startup (non-fatal if permission denied)
  - Fix: Set UV_LINK_MODE=copy in hooks-daemon.env for uv compatibility

- **Validation False Positive**: Fixed validate_instruction_content handler false positive on documentation paths (commit f7d878c)

  - Bug: Handler incorrectly flagged FILE_LISTINGS instructions in CLAUDE/ documentation paths
  - Bug: Documentation files legitimately contain instruction examples that triggered validation
  - Fix: Exclude CLAUDE/, RELEASES/, and .claude/ paths from FILE_LISTINGS validation

- **Documentation Consistency**: Fixed 10 documentation inconsistencies and broken references (commit 684ad96, dddff9a)

  - Bug: Broken internal documentation links
  - Bug: Inconsistent success criteria descriptions
  - Bug: Incorrect daemon restart command examples
  - Bug: .gitignore auto-creation not documented
  - Fix: Updated all broken references to correct paths
  - Fix: Standardized success criteria wording across docs
  - Fix: Corrected restart command format in all documentation

### Changed

- **Repository Cleanup**: Removed cruft and improved organization (Plan 00048, commit 45a45fc)
  - Deleted spurious `/workspace/=5.9` file (accidental pip output redirect)
  - Removed 4 stale worktrees (~700MB) from completed plans 00021 and 003
  - Deleted empty plan 00036, renamed auto-named plans to descriptive names
  - Moved historical `BUG_FIX_STOP_EVENT_SCHEMA.md` to completed plan directory
  - Cleaned up stale config backup file

## [2.10.0] - 2026-02-11

### Added

- **Python 3.11+ Version Detection**: Bash scripts now validate Python version meets 3.11+ requirement (Plan 00046 Phase 2, commit ae7ac25)

  - `scripts/prerequisites.sh` checks Python version before venv creation
  - `scripts/upgrade.sh` validates Python version during upgrade
  - `scripts/venv.sh` ensures compatible Python interpreter
  - Clear error messages guide users to upgrade Python if version too old
  - Prevents cryptic installation failures from unsupported Python versions

- **Installation Feedback Instructions**: Added feedback file template to LLM-INSTALL.md (commit 6f32b84)

  - Users can provide structured installation feedback
  - Helps identify common installation pain points
  - Template includes environment details, steps taken, and issue description

### Changed

- **Upgrade System Root Cause Fix**: Complete overhaul of upgrade workflow (Plan 00046 Phase 1, commit e3217ab)

  - **checkout-first-then-delegate**: Upgrade script now checks out target version BEFORE delegating to it
  - Eliminates "upgrade to broken version" failure mode where old script delegates to broken new script
  - Dropped legacy fallback mode (upgrade.sh is now single source of truth)
  - **Nested Install Protection**: Detects and prevents nested `.claude/hooks-daemon/hooks-daemon/` installations
  - More robust upgrade path with better error handling

- **Socket Path Length Validation**: AF_UNIX socket path length limits now enforced with fallback mechanism (Plan 00046 Phase 3, commit 98e6d5f, 5126237)

  - **Path Length Check**: Validates socket path ≤ 107 characters (Linux AF_UNIX limit)
  - **Fallback Hierarchy**: XDG_RUNTIME_DIR → /run/user/$(id -u) → /tmp/claude-hooks-{user}
  - Self-install mode path detection improved in `_get_untracked_dir()` (commit 964ae31)
  - Server.py catches OSError during bind and provides actionable error messages
  - Integration tests verify fallback behavior when paths exceed limits

- **Config Validation UX Improvements**: User-friendly Pydantic validation errors (Plan 00046 Phase 4, commit 2d86d5e, e27ea42)

  - **Friendly Error Formatting**: Pydantic errors transformed into readable messages
  - **Fuzzy Field Suggestions**: Suggests correct field names for typos (e.g., "enabeld" → "Did you mean: enabled?")
  - **Duplicate Priority Logging**: Duplicate handler priorities demoted from WARNING to DEBUG
  - Type annotation fixes and magic value elimination in validation_ux module

- **LLM-UPDATE.md Documentation**: Comprehensive upgrade documentation updates (Plan 00046 Phase 5, commit 38853c9)

  - Python 3.11+ requirement clearly documented
  - Socket path troubleshooting section added
  - Feedback template for upgrade issues
  - Common failure modes and solutions documented

### Fixed

- **Upgrade Script Robustness**: Fixed critical upgrade system failure modes (Plan 00046 Phase 1)

  - Bug: Old upgrade script could delegate to broken new version script
  - Bug: Nested installations created `.claude/hooks-daemon/hooks-daemon/` structure
  - Bug: Legacy fallback mode caused confusion and maintenance burden
  - Fix: Checkout target version first, then run its scripts (no more delegation trust issues)
  - Fix: Nested install detection prevents directory structure corruption

- **Socket Path Length Failures**: Fixed daemon startup failures on deep directory paths (Plan 00046 Phase 3)

  - Bug: AF_UNIX sockets limited to ~107 characters, deep project paths caused bind() failures
  - Bug: Cryptic OSError messages didn't explain root cause
  - Fix: Validate path length before bind, fallback to shorter paths (XDG_RUNTIME_DIR, /run/user, /tmp)
  - Fix: Catch OSError in server.py with actionable error message

- **Config Validation Errors**: Fixed confusing Pydantic error messages (Plan 00046 Phase 4)

  - Bug: Raw Pydantic validation errors were cryptic for end users
  - Bug: Typos in field names provided no suggestions
  - Fix: Custom formatter translates Pydantic errors to friendly messages
  - Fix: Fuzzy matching suggests correct field names

### Documentation

- **Plan 00046 Completion**: Six-phase upgrade system overhaul completed (commit 687cbac)
  - Complete implementation plan with root cause analysis
  - Technical decisions documented for all phases
  - Success criteria verified for upgrade reliability
- **Async Agent Warning**: Added critical warning to RELEASING.md about v2.9.0 incident (commit e131232)
  - Documents the importance of waiting for ALL acceptance test agents to complete
  - Prevents premature commits/pushes while tests still running

### Style

- **Black Formatting**: Auto-formatted server.py for line length compliance (commit 86b636e)

## [2.9.0] - 2026-02-11

### Added

- **Strategy Pattern Architecture for Language-Aware Handlers** (Plan 00045, commit 7adbc39)

  - **Unified QA Suppression Handler**: Single `QaSuppressionHandler` replaces 4 per-language handlers (eslint_disable, python/php/go_qa_suppression_blocker)
  - **11 Language Strategies**: Python, JavaScript/TypeScript, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#, Dart
  - **Protocol-Based Design**: Structural typing with `QaSuppressionStrategy` and `TddStrategy` protocols
  - **Extension-to-Strategy Registry**: Maps file extensions to language strategies with config-filtered loading
  - **Project Languages Config**: New `project_languages` config option to filter strategies by active languages
  - **TDD Strategy Refactoring**: TddEnforcementHandler now uses strategy registry for language-specific test detection
  - **Strategy Pattern QA Checker**: New `scripts/qa/run_strategy_pattern_check.sh` enforces pattern compliance
  - **Comprehensive Strategy Tests**: 5285 total tests (up from 4813), 95%+ coverage maintained
  - **New Strategies Module**: `src/claude_code_hooks_daemon/strategies/` with QA suppression and TDD strategies
  - **Strategy Documentation**: Complete TDD strategy documentation in `strategies/tdd/CLAUDE.md`

- **Automated Acceptance Testing Skill**: `/acceptance-test` skill for parallel handler validation (Plan 00044, commit 95e2286)

  - AcceptanceTestRunnerAgent: Haiku-based parallel test execution across batches
  - PlaybookGenerator: Converts handler definitions to structured JSON test playbooks
  - CLI integration: `generate-playbook` command for ephemeral test generation
  - Parallel batch execution: Groups tests (3-5 per batch) and runs concurrently
  - Structured JSON results: Pass/fail/skip/error counts for automated release gates
  - Reduces acceptance testing time from 30+ minutes to 4-6 minutes
  - Integration with release workflow as mandatory blocking gate (Step 8)

### Changed

- **Handler Architecture**: Transition from duplicated per-language handlers to strategy pattern
  - 4 handlers deleted (eslint_disable, python/php/go_qa_suppression_blocker)
  - 1 new unified handler added (qa_suppression)
  - Net reduction: 3 handlers, massive code deduplication
  - Language support expanded from 4 to 11 languages through strategies
- **Plugin Loader Enhancement**: Plugin paths now resolve relative to `workspace_root` instead of CWD
  - Fixes plugin loading issues when daemon started from different directories
  - More robust plugin discovery for project-level handlers
- **Config Schema**: Added `project_languages` field to daemon config for strategy filtering
- **Test Organization**: Strategy tests organized by module (qa_suppression/, tdd/)

### Fixed

- **Hook Path Robustness**: Hook paths now use `$CLAUDE_PROJECT_DIR` to handle CWD changes in Bash commands (commit cc2bd1b)
  - Bug: Relative paths like `.claude/hooks/pre-tool-use` broke when Bash tool changed CWD
  - Fix: Updated installer to generate `"$CLAUDE_PROJECT_DIR"/.claude/hooks/*` patterns
  - Tests: Added unit tests for installer hook path generation and integration tests for settings validation
  - All hooks now robust against CWD changes during command execution

### Removed

- **Deprecated Handlers**: Replaced by unified strategy-based handlers
  - `eslint_disable` - Replaced by QaSuppressionHandler with JavaScript strategy
  - `python_qa_suppression_blocker` - Replaced by QaSuppressionHandler with Python strategy
  - `php_qa_suppression_blocker` - Replaced by QaSuppressionHandler with PHP strategy
  - `go_qa_suppression_blocker` - Replaced by QaSuppressionHandler with Go strategy
- **language_config.py**: Deleted in favor of strategy implementations with direct pattern definitions

## [2.8.0] - 2026-02-10

### Added

- **Project-Level Handlers**: First-class support for per-project custom handlers (Plan 00041, PR #21)
  - New `.claude/project_handlers/` directory structure for event-specific handlers
  - Automatic loading and registration of project handlers alongside library handlers
  - Priority-based execution with project handlers integrated into handler chains
  - Full test coverage (96.33% overall project coverage)
- **Project Handler CLI Commands**: Developer experience tools for scaffolding and managing project handlers
  - `scaffold-project-handler` - Generate handler templates with proper structure
  - `list-project-handlers` - Discover and validate project handlers
  - `validate-project-handler` - Lint and test individual handlers
- **Project Handler Documentation**: Comprehensive guides for creating custom handlers
  - `CLAUDE/PROJECT_HANDLERS.md` - Complete project handler development guide
  - `examples/project-handlers/` - Handler templates and examples for all event types
- **Optimal Config Checker Handler**: SessionStart handler that validates daemon configuration (bce7fb4)
  - Checks for missing/redundant handlers
  - Suggests priority optimizations
  - Validates configuration structure
- **Hedging Language Detector Handler**: Stop hook handler that identifies uncertain language patterns (62669a7)
  - Detects hedging phrases ("maybe", "possibly", "I think")
  - Advisory handler for improving code quality communication
- **Upgrade Detection Improvements**: Robust detection for broken installations (Plan 00043)
  - Detects missing venv, broken symlinks, corrupted config
  - Handles partial upgrades and installation failures
  - Improved error messages and recovery guidance

### Changed

- **Library/Plugin Separation**: Clear architectural boundaries (Plan 00034)
  - Library handlers in `src/claude_code_hooks_daemon/handlers/`
  - Project handlers in `.claude/project_handlers/{event_type}/`
  - Plugins in `.claude/hooks-daemon/plugins/`
  - Improved modularity and maintainability
- **PHP QA CI Integration**: Enhanced handlers for PHP quality checks (PR #20)
  - PHPCS handler improvements
  - PHPStan handler enhancements
  - PHP-CS-Fixer integration
- **Documentation Improvements**: Pre-release documentation drive
  - Updated README.md with clearer project overview
  - Enhanced CLAUDE.md with project handler documentation
  - Added four new user guides in `docs/guides/` (getting started, configuration, handler reference, troubleshooting)
  - Improved code examples throughout

### Fixed

- **Project Handler Config Passing**: Critical bug where project_handlers_config wasn't passed to daemon start (28c90e2)
- **Handler Template Keys**: Use snake_case keys in scaffolded templates for consistency (a200687)
- **Nested Installation Detection**: Prevent false positives when working on hooks-daemon repo itself (075450a)
- **Dogfooding Reminder Plugin**: Restore plugin accidentally deleted in Plan 00034 (27827bd)
- **Post-Merge QA Fixes**: Resolved all QA issues from PR #20 merge (f360f87)
- **Install/Update Instructions**: Use curl-to-file pattern for more reliable downloads (2941f18)

## [2.7.0] - 2026-02-10

### Added

- **Config Preservation Engine**: Complete config migration system with differ, merger, validator, and CLI (Plan 00041)
  - `config_differ.sh` - Detects changes between old and new default configs
  - `config_merger.sh` - Merges user customizations with new defaults
  - `config_validator.sh` - Validates merged config integrity
  - `config_cli.sh` - User-facing commands for config operations
  - 82 comprehensive tests for config preservation
- **Modular Bash Install Library**: 14 reusable modules in `scripts/install/` for DRY install/upgrade architecture (Plan 00041)
  - Core modules: `common.sh`, `logging.sh`, `validation.sh`, `backup.sh`
  - Config modules: `config_differ.sh`, `config_merger.sh`, `config_validator.sh`, `config_cli.sh`
  - Install modules: `git_operations.sh`, `venv_setup.sh`, `python_setup.sh`, `hook_scripts.sh`
  - Upgrade modules: `upgrade_checks.sh`, `rollback.sh`
- **Layer 2 Orchestrators**: Simplified install/upgrade entry points that delegate to modular library (Plan 00041)
  - `install_version.sh` - Install orchestrator (116 lines, down from 307)
  - `upgrade_version.sh` - Upgrade orchestrator (134 lines, down from 612)
- **VersionCheckHandler**: SessionStart handler that displays current daemon version at session start
- **Example Config File**: `.claude/hooks-daemon.yaml.example` with comprehensive handler documentation
- **Dynamic Example Config Validation**: Test ensures all library handlers are present in example config

### Changed

- **Handler Registry Architecture**: HandlerID constants as single source of truth for config keys (Plan 00039)
  - All handlers now use `HandlerID.HANDLER_NAME` for self-identification
  - Config keys automatically derived from handler IDs
  - Eliminates config key inconsistencies and typos
- **Status Line Enhancement**: Emoticon-based context display with color-coded quarter circle icons
  - Context usage now shows with colored emoticons matching percentage scheme
  - More intuitive visual feedback for context consumption
- **Install Architecture**: Layer 1 (modular library) + Layer 2 (orchestrators) separation (Plan 00041)
  - `install.sh` simplified from 307 to 116 lines (delegates to `install_version.sh`)
  - `upgrade.sh` simplified from 612 to 134 lines (delegates to `upgrade_version.sh`)
  - All logic now in reusable, testable Bash modules
- **Release Workflow Documentation**: Added mandatory QA and acceptance testing gates to release process
  - QA verification gate after Opus review (all checks must pass)
  - Acceptance testing gate after QA (all tests must pass)
  - FAIL-FAST cycle for test failures

### Fixed

- **auto_continue_stop Handler**: Fixed camelCase `stopHookActive` field detection (Plan 00042)
  - Handler now correctly detects stop_hook_active and stopHookActive
  - Added comprehensive logging for field detection
- **Upgrade Script Critical Fixes**: 8 critical fixes in upgrade process (Plan 00041)
  - Fixed heredoc to prevent variable expansion in config
  - Fixed hook script permissions (now executable after upgrade)
  - Fixed timestamped config backups to prevent overwriting
  - Fixed validation to skip when already on target version
  - Fixed silent config validation error swallowing
  - Fixed Python version detection and restart messaging
  - Fixed config delegation to project agent
  - Fixed hook script redeployment

## [2.6.1] - 2026-02-09

### Changed

- **Architecture Documentation**: Added comprehensive documentation clarifying daemon vs agent hooks separation
  - Documented when to use daemon handlers (deterministic, fast) vs native agent hooks (complex reasoning)
  - Added "When NOT to Write a Handler" section to HANDLER_DEVELOPMENT.md
  - Updated README.md with architectural principle explanations
  - Enhanced ARCHITECTURE.md with daemon/agent hooks distinction
- **Release Workflow Documentation**: Added critical warnings to prevent manual release operations
  - Added CRITICAL section to CLAUDE.md emphasizing mandatory /release skill usage
  - Documents why manual git tag/push operations are forbidden
  - Clarifies pre-release validation, version consistency, and Opus review workflow

### Fixed

- **Upgrade Instructions Security**: Fixed v2.6.0 upgrade instructions to use fetch-review-run pattern instead of curl pipe bash
  - Removes security risk of piping curl output directly to shell
  - Aligns with project's own curl_pipe_shell blocker handler
  - Updated CHANGELOG.md and upgrade documentation

## [2.6.0] - 2026-02-09

### Added

- **Client Installation Safety Validator**: Comprehensive validation system for client project installations that prevents configuration issues
  - Pre-install validation ensures no stale configs or runtime files
  - Post-install validation verifies correct daemon directory structure
  - Lazy-load imports to avoid dependency issues during installation
  - Prevents handler_status.py path confusion in client projects
- **/hooks-daemon-update Slash Command**: Auto-deployed during install/upgrade to provide guided LLM assistance for daemon updates
  - Always fetches latest upgrade instructions from GitHub
  - Works for all versions including pre-v2.5.0 installations
  - Ensures upgrade process uses current best practices

### Changed

- **Upgrade Documentation**: Standardized upgrade process to fetch-review-run pattern (avoids curl pipe shell pattern blocked by our own security handlers)
- **Complete Dogfooding Configuration**: Enabled all handlers in daemon's own config for comprehensive self-testing
  - Enabled strict_mode at daemon level for FAIL FAST behavior
  - Activated all safety handlers (curl_pipe_shell, pipe_blocker, dangerous_permissions, etc.)
  - Activated all workflow handlers (plan_completion_advisor, task_tdd_advisor, etc.)
  - Activated all session handlers (workflow_state_restoration, remind_prompt_library, etc.)
  - Activated all status handlers (git_repo_name, account_display, thinking_mode, usage_tracking)
- **Hook Script Regeneration**: Updated all hook scripts to match current installer output
  - Fixed config handler name (hello_world_pre_tool_use)
  - Ensures consistency between generated and committed scripts

### Fixed

- **Config Detection Logic**: Fixed handler_status.py to properly distinguish self-install vs client project mode
  - Now reads config file for self_install_mode flag instead of checking directory existence
  - Prevents reading wrong config file in client projects
  - All paths dynamically detected without hardcoded assumptions

## [2.5.0] - 2026-02-09

### Added

- **Lock File Edit Blocker Handler**: Prevents editing package lock files (package-lock.json, yarn.lock, composer.lock, etc.) - Plan 00031
- **5 System Package Safety Handlers**: Block dangerous package management operations (Plan 00022)
  - `pip_break_system` - Blocks pip --break-system-packages flag
  - `sudo_pip` - Blocks sudo pip install commands
  - `curl_pipe_shell` - Blocks curl/wget piped to shell
  - `dangerous_permissions` - Blocks chmod 777 and similar unsafe permissions
  - `global_npm_advisor` - Advises against npm install -g
- **Orchestrator-Only Mode Handler**: Opt-in mode for handlers that only run in orchestrator context (Plan 00019)
- **Plan Completion Move Advisor**: Guides moving completed plans to archive folder (Plan 00027)
- **TDD Advisor Handler**: Enforces test-driven development workflow with task-based guidance
- **Hostname-Based Daemon Isolation**: Multi-environment support with hostname-suffixed runtime files (sockets, PIDs, logs)
- **Worktree CLI Flags**: Added --pid-file and --socket flags for git worktree isolation (Plan 00028)
- **Programmatic Acceptance Testing System**: Ephemeral playbook generation from handler metadata (Plan 00025)
- **Plugin Support in Playbook Generator**: Acceptance tests now include plugin handlers (Plan 00040)
- **Config Validation at Daemon Startup**: Validates configuration before daemon starts (Plan 00020)
- **Comprehensive Handler Integration Tests**: Added integration tests for all handlers (Plan 00016)
- **Deptry Dependency Checking**: Integrated deptry into QA suite for dependency validation
- **LanguageConfig Foundation**: Centralized language-specific configuration for QA suppression handlers (Plan 00021)
- **Agent Team Workflow Documentation**: Multi-role verification structure with honesty checker (Plan 00030)
- **Worktree Automation Scripts**: Parallel plan execution with git worktree support
- **Code Lifecycle Documentation**: Complete Definition of Done checklists for features, bugs, and general changes

### Changed

- **Plugin System Architecture**: Complete overhaul with event_type field and daemon integration (Plan 00024)
- **QA Suppression Handlers**: Refactored to use centralized LanguageConfig data layer (Plan 00021)
- **Strict Mode Behavior**: Unified daemon.strict_mode for all fail-fast behavior across handlers
- **Acceptance Testing**: Migrated all 59+ handlers to programmatic acceptance tests with empty array rejection
- **Magic Value Elimination**: Removed all magic strings and numbers, replaced with constants (Plan 00012)
- **Plan Workflow**: Enhanced planning system with completion checklists and archive automation
- **Status Line Display**: Added effort level display and thinking toggle logic for Opus 4.6 extended thinking
- **Markdown Handler**: Allow writes outside project root for cross-project documentation (Plan 00029)
- **LLM Upgrade Experience**: Improved upgrade documentation and verification (Plan 00023)
- **Plugin Loader**: Handle Handler suffix correctly in class name detection
- **Duplicate Handler Priorities**: Made deterministic with warning logs for conflicts

### Fixed

- **HOTFIX: Decision Import**: Fixed wrong import path in 5 new handlers (constants.decision vs core.Decision)
- **Sed Blocker False Positive**: Fixed blocking of legitimate gh CLI commands
- **Plugin Schema Validation**: Fixed plugins config integration test validation
- **PreCompact Hook Schema**: Fixed systemMessage format validation
- **Daemon Path Isolation**: Fixed worktree isolation with proper path handling (Plan 00028)
- **Handler Instantiation Test**: Fixed test suite for dynamic handler loading
- **Markdown Plan Number Validation**: Corrected plan number detection in markdown files
- **Type Hints**: Fixed MyPy violations in 5 system package safety handlers
- **Magic Value Violations**: Eliminated remaining magic values in test_models.py and paths.py
- **Import Errors**: Removed non-existent qa_suppression_base import references
- **Plan Status Accuracy**: Corrected multiple plan completion statuses after audit
- **Test Failures**: Resolved hostname isolation test failures and fixture updates

### Security

- Maintained ZERO security violations across entire codebase
- All new handlers follow security best practices (no shell=True, proper subprocess usage)

### Documentation

- Added comprehensive Code Lifecycle guides (Features.md, Bugs.md, General.md)
- Enhanced PlanWorkflow.md with completion checklist and atomic commit guidance
- Added Agent Team workflow with multi-role verification
- Updated handler development guide with acceptance testing requirements
- Documented worktree workflow and parallel plan execution

## [2.4.0] - 2026-02-01

### Added

- **Security Standards Documentation**: Comprehensive security standards section in CLAUDE.md with ZERO TOLERANCE policy
- **Acceptance Testing Playbook**: Complete acceptance testing infrastructure with 15+ critical handler tests (Plan 00017)
- **Handler Status Report**: Post-install/upgrade verification script for handler discovery
- **Installation Safety**: Pre-installation check to prevent accidental reinstalls
- **Plan Lifecycle System**: Plan archival system with hard links and lifecycle documentation
- **ProjectContext Architecture**: Singleton module for project path management eliminating CWD dependencies (Plan 00014)
- **Repo Name in Status Line**: Repository name and model color coding in status line display
- **Planning Workflow Guidance**: Adoption guidance in install/upgrade documentation
- **Triple-Layer Safety**: Enhanced acceptance testing with FAIL-FAST cycle documentation
- **Implementation Plans**: Added plans for GitHub issues 11-15
- **Comprehensive Hooks Documentation**: Integration smoke tests and hook system documentation

### Changed

- **Release Process**: Established single source of truth in CLAUDE/development/RELEASING.md
- **Documentation Links**: Use @ syntax for doc links to force reading by LLMs
- **Upgrade Documentation**: Clarified daemon restart vs Claude Code restart procedures
- **Acceptance Testing**: Improved playbook clarity and practicality with detailed test cases
- **Installation Detection**: Nested installation detection now allows .claude dir inside hooks-daemon
- **Status Line Format**: Updated after protocol format change

### Fixed

- **SECURITY: File Path Handling**: Fixed init.sh to use secure daemon untracked directory instead of /tmp (B108)
- **SECURITY: Subprocess Security**: Fixed all security violations with TDD approach (B602, B603, B607, B404)
- **SECURITY: Dangerous Git Commands**: Added handler to block dangerous commands preventing data loss
- **Critical Protocol Bug**: Fixed handlers not blocking commands due to protocol format issue
- **TDD Enforcement**: Handle directories with 'test' in name correctly
- **Sed Blocker**: Detect sed patterns in echo commands
- **Version Inconsistency**: Fixed version mismatch and updated install.py status format
- **Plan Number Helper**: Block broken plan discovery commands
- **ProjectContext Initialization**: Initialize before config validation to prevent errors
- **Git Repo Name**: Parse from remote URL instead of directory name
- **Import Errors**: Fixed git_repo_name handler import issues
- **QA Failures**: Resolved all QA issues to prepare for release
- **Test Paths**: Achieved ZERO security violations with proper nosec documentation

### Security

- **B108 Violations**: Eliminated /tmp usage in favor of secure daemon untracked directory
- **B602/B603/B607/B404**: Fixed all subprocess security issues with comprehensive TDD approach
- **Dangerous Git Commands**: Blocked commands that can cause data loss
- Complete security audit achieving ZERO violations across entire codebase (Plan 00018)

## [2.3.0] - 2026-01-29

### Added

- Daemon-based status line with 20x faster rendering performance
- Handler for GitHub issue comments (`gh_issue_comments`) with full test coverage
- Auto-continue Stop handler for workflow automation
- Pipe blocker handler to prevent risky shell command patterns
- Account display and usage tracking in status line
- Log level environment variable override (`HOOKS_DAEMON_LOG_LEVEL`)
- Comprehensive input validation system at front controller layer (Plan 002)
- Planning workflow system with formal documentation and templates
- Handler ID migration system with QA enforcement (Plan 00012)
- Dogfooding test to ensure all production handlers enabled in strict mode
- Plan archive system for completed work (CLAUDE/Plan/Completed/)

### Changed

- Handler architecture to use `handler_id` constants (320 violations fixed in Plan 00012)
- Config architecture to use explicit `options` dict instead of extra fields
- Installation hardening to prevent nested installs
- Status line script performance and reliability
- Test coverage increased to 97% (3172 tests passing)
- Documentation improvements for FAIL FAST principle and error handling
- Plan numbering pattern to support 3+ digit formats

### Fixed

- **FAIL FAST**: Comprehensive error hiding audit and remediation (Plan 00008)
- Bash error detection and input validation across all handlers
- QA failures: tests, type errors, and installer synchronization
- Status line rendering bugs and race conditions
- Config validation and test data integrity
- Tool name and timeout violations in handler implementations
- Type annotation cleanup (removed unused `type: ignore` comments)

### Removed

- Usage tracking handler (disabled due to architectural issues)
- Fake UserPromptSubmit auto-continue handler (replaced with real Stop handler)

## [2.2.1] - 2026-01-27

### Fixed

- Fixed git hook executable permissions in repositories with core.fileMode=false
- Enhanced install.py to detect and handle permission tracking settings
- Added auto-update of git index for hook executability
- Added context-specific warnings for tracked vs untracked files

## [2.2.0] - 2026-01-27

### Added

- Custom sub-agents for QA and development workflow automation
- Automated release management system with `/release` skill
- Hook event debugging tool (`scripts/debug_hooks.sh`) for handler development
- Self-install mode support to CLI and configuration system
- Debug infrastructure for troubleshooting hook flows
- `.gitignore` requirement validation in installer
- Automatic config file backup during installation

### Changed

- Release system orchestration to avoid nested agent spawning
- Installer now displays `.gitignore` template with mandatory instructions
- Documentation improvements for README config completeness and plugin events

### Fixed

- Critical QA failures achieving 95% test coverage requirement
- Stop event schema validation failure
- Critical hook response formatting bug with JSON schema validation
- 4 upstream installation and CLI bugs
- DRY violation in error response handling
- Release skill registration (SKILL.md frontmatter)
- README documentation issues with config examples

## [1.0.0-alpha] - 2025-01-15

### Added

- Initial daemon implementation with Unix socket IPC
- Front controller pattern for handler dispatch
- Multi-project support via socket namespacing
- 14+ pre_tool_use handlers for safety, code quality, and workflow
- Handlers for all 10 Claude Code hook events
- YAML/JSON configuration system
- Plugin system for custom handlers
- Comprehensive test suite (95%+ coverage)
- QA tooling (ruff, mypy, black, bandit)
- Installation automation via install.py

### Performance

- Sub-millisecond response times after daemon warmup
- 20x faster than process spawn approach
- Lazy startup with auto-shutdown on idle

### Documentation

- README.md with installation and usage guide
- DAEMON.md with architecture details
- CLAUDE/ARCHITECTURE.md with design documentation
- CLAUDE/HANDLER_DEVELOPMENT.md with handler creation guide

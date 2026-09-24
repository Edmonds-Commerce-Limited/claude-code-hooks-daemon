# Plan 00468 wave 2: Tasks 3.2, 3.3, 4.1, 4.3, 00466 N26/N27, and the worktree question

**Branch**: `worktree-p468-core` (worktree `untracked/worktrees/worktree-p468-core`)
**Author**: Opus 5.5 sub-agent, unattended
**Previous report**: [260924-p468-core-opus-5-5.md](260924-p468-core-opus-5-5.md)
(Tasks 1.2, 2.1 to 2.3)

Nothing was merged to main and nothing was pushed. Item 4 of the brief (the
config-dir exclusion in the P3 walkers) waits for batch B2 and is not done.

## Commits

| Commit     | What                                                                           | Release note |
| ---------- | ------------------------------------------------------------------------------ | ------------ |
| `0daefa88` | Merge main `3507fbfe` (00466 N26/N27 entries, 00468 T2.4)                      |              |
| `13bd2b94` | 00466 N27: one derivation of Claude Code's per-project directory               | 36           |
| `446fcd5a` | 00466 N26: QA walkers judge excluded names below the scan root                 | 37           |
| `e1cdcac8` | Worktree question: a main checkout's plugin install applies in its worktrees   | 31 (edited)  |
| `bb88b686` | Task 3.2: the Claude config dir and plugin roots are not project docs          | 38           |
| `e3d26e60` | Task 3.3: installed-plugin edit advisory; the session config dir is in bounds  | 39           |
| `4d58dd04` | Task 4.1: plugins that ship hooks, at session start and in `health`            | 41           |
| `11bf4c5e` | Task 4.3: `lsp_enforcement` judges LSP from enabled plugins; integration fixes | 42           |
| `738c4e5e` | Merge main `3104434b` (B1 archive, 00466 N28-N33); ledger conflicts, both kept |              |

Release note 40 was skipped on purpose (n466-n24 holds it).

## 00466 N27: fixed

`utils/claude_config.project_dir_name()` and `claude_project_dir()` are now
the only derivation of `<config dir>/projects/<name>/`. They are pinned to
Claude Code's own rule, read from its bundle: every UTF-16 unit outside
`[a-zA-Z0-9]` becomes `-`, and a name longer than 200 characters is cut to
200 and suffixed with `-` and the base-36 absolute Java string hash. The
path is realpath'd first. Golden values were computed with node from the
bundle's own functions. No real `projects/` entry on this machine has a `.`
or `_` in its path, so the golden values are the evidence.

Users: `skill_scan.derive_transcript_dir`, `tool_report.transcripts_root_for`,
and `cli._resolve_transcript` (cache-gaps). When the directory is missing,
`tool-report`/`block-report` say so on stderr. `cache-gaps` exits 2 naming the
directory. Tests: `tests/unit/utils/test_transcript_dir_derivations_agree.py`
and `TestProjectDirName`/`TestClaudeProjectDir` in `test_claude_config.py`,
plus one missing-directory test for each CLI. The ledger row is marked Remedied.

## 00466 N26: fixed, and the class audited

- **Discovery**: the defect was exclusions matched against absolute path
  parts. From `untracked/worktrees/...`, `untracked` excluded every file.
  `utils/scan_scope.relative_parts()` judges parts below the scan root. It is
  used by `check_skill_references`, `check_doc_truth`, `check_github_urls` and
  `check_magic_values`. `check_magic_values` matched `constants`, `fixtures`
  and `test` absolutely, which was latent.
- **Zero guard**: `vacuous_scan_failure()` fails a check that examined 0 of N
  candidates. The four checks above use it.
- **Audit of the rest**: 22 `check_*.py` were read. The three absolute-path
  exclusions were the ones above. Fourteen walkers have no zero guard but
  scan >0 from a normal checkout. Instead of a guard in each, one
  integration test, `test_qa_walkers_examine_files_from_any_checkout.py`,
  copies the tracked tree to a path made of every excluded name
  (`test/fixtures/constants/build/examples/Completed/venv/ccy/untracked/worktrees/wt`).
  It asserts each walker examines files there. `test_every_check_is_classified`
  fails for a new check that is in neither list. Eight checks read fixed
  inputs, which raise when missing, and are listed as such.
- From this worktree the checks now scan: skill_refs 699, doc_truth 1774,
  github_urls 4038, magic_values 1763.

The ledger row is marked Remedied.

## The worktree question: settled from Claude Code's bundle, resolver fixed

Claude Code's install applicability (`OS()` in its bundle) accepts a
project/local record when `projectPath` equals the cwd project, or when both
map to the same canonical repository root. That root is the main checkout
for a linked worktree: the gitdir entry's `commondir` is followed, and the
entry's `gitdir` back-pointer must resolve to the worktree's `.git`. So a DBF
install made for `/workspace` applies in its worktrees. The daemon's
resolver said it did not, so it was wrong. `canonical_repo_root()` ports that
rule, including the back-pointer check (an impostor worktree is rejected),
and `_choose_install` prefers an exact match, then same repository, then
user/managed. Live from this worktree after the fix: DBF enabled (local,
project), pyright-lsp enabled, and phpantom-lsp unresolved (its id has no
`@marketplace`).

**Limit**: this is read from the bundle's code, not observed by running Claude
Code inside a worktree session and listing its plugins.

## Task 3.2 (P4, G8): fixed

`markdown_organization` exempts the Claude config dir (unless the workspace
root is inside it) and a plugin root's `agents/`, `commands/`, `skills/` and
`output-styles/` markdown. A plugin root is a directory holding
`.claude-plugin/plugin.json` or `marketplace.json`. The memory policy is
unchanged. Tests: `TestClaudeConfigDirIsNotProjectLayout`,
`TestClaudeCodePluginSourceLayout`.

## Task 3.3 (G16, G10): fixed

- `installed_plugin_edit_advisor` (PreToolUse, priority 42, never blocks)
  covers Write/Edit/NotebookEdit and Bash write targets under `plugins/cache/`
  or `plugins/marketplaces/`, in the daemon's and the session's config dir,
  by raw or resolved path. `plugins/data/` is not covered. Tests:
  `tests/unit/handlers/pre_tool_use/test_installed_plugin_edit_advisor.py`.
- `claude_config.session_config_dir(transcript_path)` reads
  `<home>/projects/<name>/<session>.jsonl` (that exact shape only), and
  `project_containment` permits writes under it too. Tests:
  `TestSessionConfigDir` and `TestTheSessionsOwnClaudeHome`.
- **Defects I introduced, found by the integration suite, fixed in the T4.3
  commit**:
  - `e3d26e60` left the new handler untriaged in
    `test_blocking_handler_evasion.py`, with no row in
    `test_bash_write_blindness_coverage.py`, and with its acceptance probe
    under `untracked/scratch/` (now `acceptance_path()`).
  - Release notes 35 to 42 broke the holding-area header shape (only
    `**Plan**: NNNNN` and a fixed audience list are allowed).
  - T3.2 used a raw `.is_file()`, which `check_eacces_safe_predicates` flags.
    The T1.2 commit `47bfaeb8` (in `be96b623`) put its exemption marker too far
    from the predicate. My earlier report called that violation "unrelated",
    which was wrong. Both are fixed.

## Task 4.1 (G1, G2): fixed

- `plugin_hooks_advisor` (SessionStart, priority 51, never blocks) runs on new
  sessions only. It names each enabled plugin with hooks and its events, and
  singles out `PreToolUse` and its `updatedInput`. Plugin ids in
  `options.acknowledged_plugins` are left out. Shared logic is in
  `utils/plugin_hooks.py`.
- `hooks-daemon health` has a "Claude Code plugin hooks" section: every
  plugin with hooks, acknowledged ones marked, and unresolved plugins listed
  as "hooks unknown". The exit code is unchanged. Live output here: only
  phpantom-lsp (unresolved). DBF and pyright-lsp ship no hooks.
- The security note is in `CLAUDE/ARCHITECTURE.md` § Security Considerations
  and links `ClaudeCodePlugins.md`.
- Tests: `tests/unit/utils/test_plugin_hooks.py`,
  `tests/unit/handlers/session_start/test_plugin_hooks_advisor.py` (includes
  one real-resolver case), and `tests/unit/daemon/test_cli_health_plugin_hooks.py`.

## Task 4.3 (P5): fixed

The LSP tool counts as available only where an enabled plugin's language
server serves the searched file type. That is the vendored tools-reference
rule; `ENABLE_LSP_TOOL` is no longer read. The file type comes from the Grep
`glob`/`type`/`path` and a grep/rg invocation's `--include`, `-g`/`--glob`,
`-t`/`--type` and file arguments; redirect targets are ignored. A search
that names no type is covered by any enabled server. `no_lsp_mode` now
defaults to `advisory`: an uncovered search is allowed, with advice to install
a code intelligence plugin. `get_relevance` asks the same question. The
audit's `.ts` reproduction is now an ALLOW. Tests: `TestLspCoverageFromPlugins`
and the rewritten `TestLspEnforcementNoLspMode` in `test_lsp_enforcement.py`,
and `TestLspEnforcement` in `test_handler_get_relevance.py`. An autouse
fixture keeps every lsp test off the real config dir.

## Rulings (recorded in PLAN.md where they concern a task)

- T4.1: the security note goes in ARCHITECTURE.md, since `CLAUDE/Security/`
  registers defect classes with Detectors. G2's optional PostToolUse
  input comparison is not built.
- T4.3: an unknown file type counts as covered by any enabled server. The
  audit's "dominant language" fallback was not built. The cost of that gap is
  one block_once deny in a project whose only language server is for another
  language.
- T4.3: the `no_lsp_mode` default moves to `advisory`. The dogfood config and
  the example are changed to match. An explicit `block` keeps blocking.
- `health` shows unresolved plugins; the session advisory does not. Otherwise
  a plugin the daemon cannot read would raise the advisory every session.

## Known limits

- Item 4 (config-dir exclusion in the n466-docs-corpus P3 walkers) is not
  done: B2 had not landed.
- `lsp_enforcement` and the plugin hooks advisory resolve plugins on each
  call they need them. There is no cache.
- In cloud sessions Claude Code starts no plugin language servers. The daemon
  cannot tell a cloud session, so it enforces there too.
- G9 (Task 4.2) waits for Plan 00464 and was not started.

## Notes on the RED evidence

- `session_config_dir` was written with its test, extracted from the
  `project_containment` logic whose tests were RED first.
- The skill_refs worktree unit test was written after the fix; its RED is the
  hostile-checkout integration test.
- G16, T4.1 and T4.3 tests were RED on import (a module or attribute missing)
  before the code existed.

## Ready to archive

- **00468**: no. Open: Task 3.1 (walkers), 4.2 (G9, waits for 00464), 5.2
  (P8 confirmation), and brief item 4.
- **00466**: no. Other ledger entries are open; N26 and N27 are Remedied.

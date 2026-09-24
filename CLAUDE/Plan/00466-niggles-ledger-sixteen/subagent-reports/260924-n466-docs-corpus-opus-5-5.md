# Plan 00466 N9 — docs_qa gitignore fix, subagent report

**Worktree**: `worktree-n466-docs-corpus` (branch `worktree-n466-docs-corpus`, from `main` at `9f0e4fcd`)
**HEAD**: `0a30c8dcd734e24af236f94591d2d903def60986`

## Reproduction

Confirmed the defect's mechanics before touching any source:

- `.claude/ccy/.gitignore` ignores everything except a small whitelist (`*` with negations for `.gitignore`, `Dockerfile`, `ccy.env`, `claude-supervise.py`, `mounts`); `.claude/ccy/CLAUDE.md` is explicitly **not** whitelisted (its own comment: ccy's startup gate refuses to launch when it is tracked), so it is both untracked and gitignored.
- `docs_qa/corpus.py`'s `iter_markdown_paths` (`os.walk` from `project_root`, pruned only by `OWN_EXCLUDED_DIR_NAMES = {"untracked", ".git", "worktrees"}`, vendor scopes, and the vendored-daemon-install prefix) had no rule that excludes a gitignored directory by construction — `.claude/ccy/plugins/marketplaces/<repo>/...` would be walked and any nested `.md` reported, e.g. against `source-tree-markdown`'s source/test-dir scope if a vendored clone happened to contain its own `src/`-named directory.
- `iter_corpus_paths` (used for the doc inventory feeding link-graph/quote checks) is scoped to `trees.agent`/`trees.human`/`.claude/{rules,skills,agents}` — this project's config (`CLAUDE`, `docs`) never reaches `.claude/ccy`, so it was not exposed to the *specific* N9 repro, but shares the same "no gitignore awareness" defect in principle and was migrated for consistency.
- A class audit of the other five QA scripts the ledger named found a **second live instance** of the same defect: `scripts/qa/check_doc_truth.py`'s `_iter_markdown` denylists `marketplaces` by name but not its sibling `.claude/ccy/plugins/cache/` — a plugin's cached spec markdown could still reach `_check_shell_fences` as a false `slash-command-in-shell-fence`/`cli-subcommand-unknown` finding. Reproduced directly with a git-ignored fixture (see RED evidence below) before fixing.

## The fix

Added `git_visible_paths(project_root) -> frozenset[str] | None` to `utils/git_repo.py` — the daemon's existing single bounded home for git subprocess calls (`run_git`). One combined `git ls-files --cached --others --exclude-standard -z` call returns every path git would add (tracked, plus untracked-and-not-ignored); returns `None` when `project_root` is not a git repository (or git is unavailable), so callers fall back to their pre-existing unfiltered walk rather than guessing either extreme — this matters because every fixture this daemon's own test suite builds under a plain `tmp_path` is *not* a git repo unless a test opts in, and must keep scanning everything it writes.

`docs_qa/corpus.py`:

- `iter_markdown_paths` computes `git_visible` once, filters matched files against it, and additionally prunes directory descent to ancestors of git-visible paths (`_git_visible_ancestor_dirs`) so a huge ignored tree is not physically walked at all when git filtering is active.
- `iter_corpus_paths` filters its collected candidates against the same single call.
- `.claude/ccy/CLAUDE.md` is `is_module_doc_path`'s own named example of a module doc squarely in `module-doc-budget`'s scope, despite being gitignored. A blanket git filter would silently drop it. Named explicitly as `_GITIGNORED_MARKDOWN_INCLUDES = frozenset({".claude/ccy/CLAUDE.md"})`, unioned into both the file-level filter and the directory-descent ancestor set, so the walk still physically reaches it.

`scripts/qa/check_doc_truth.py`'s `_iter_markdown` now filters its `rglob` results through the same `git_visible_paths` call (imported from the package — this script already imports from `claude_code_hooks_daemon` elsewhere in the QA suite, e.g. `audit_error_hiding.py`). `_UNSCANNED_DIR_NAMES` is kept as-is (a cheap pre-prune for known-noisy directories); the git filter is now the correctness backstop, documented in an updated comment.

## Class audit

Every corpus the ledger named, classified and pinned as a ratchet test (`tests/unit/qa/test_qa_corpus_git_visibility_audit.py`, mirroring `tests/integration/test_qa_package_dependency_direction.py`'s shape):

| Corpus              | Verdict      | Evidence file                                    | Reason                                                                                                                                                                                                        |
| ------------------- | ------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs_qa`           | **MIGRATED** | `src/claude_code_hooks_daemon/docs_qa/corpus.py` | The corpus this defect was found in; both walks now filter through `git_visible_paths`.                                                                                                                       |
| `doc_truth`         | **MIGRATED** | `scripts/qa/check_doc_truth.py`                  | Second live instance of the same defect (see above); fixed the same way.                                                                                                                                      |
| `doc_snippets`      | Allowlisted  | `scripts/qa/check_doc_snippets.py`               | `_SCANNED_GLOBS` is `CLAUDE/**`, `docs/**`, `.claude/*.md` (top-level only), `.claude/agents/*.md`, `src/**`, `examples/**`, `README.md`, `CONTRIBUTING.md` — none reaches a *nested* `.claude/ccy/` subtree. |
| `repo_hygiene`      | Allowlisted  | `scripts/qa/check_repo_hygiene.py`               | Ground truth is `git ls-files` by design (its own module docstring): only a *tracked* file can be a hygiene violation. Already git-native.                                                                    |
| `sensitive_content` | Allowlisted  | `scripts/qa/check_sensitive_content.py`          | Scans `git ls-files` by design (its own module docstring: "the whole GIT-TRACKED tree ... never a filesystem walk"). Already git-native.                                                                      |
| `british_english`   | Allowlisted  | `scripts/qa/check_british_english.py`            | Already scans `git ls-files -z` directly.                                                                                                                                                                     |
| `magic_values`      | Allowlisted  | `scripts/qa/check_magic_values.py`               | `rglob` scoped to `src/claude_code_hooks_daemon` and `tests/` only — pure project-code directories, no `.gitignore` rule creates a gap in either.                                                             |
| `error_hiding`      | Allowlisted  | `scripts/qa/audit_error_hiding.py`               | `AUDITED_DIRECTORIES = ("src", "scripts")` plus named root files — same reasoning as `magic_values`.                                                                                                          |
| `handler_reference` | Allowlisted  | `scripts/qa/check_handler_reference.py`          | Does not enumerate files at all — imports and introspects the live `HandlerRegistry`. Never exposed to this defect class.                                                                                     |
| `plan_qa`           | Allowlisted  | `src/claude_code_hooks_daemon/plan_qa/model.py`  | `PlanTree.scan` descends the *configured* plan directory only, via `iterdir()` — never a project-root-wide walk. Nothing under `CLAUDE/Plan/` is gitignored in this repo.                                     |

The pinning test mechanically enforces this table, not just records it:

- Every `MIGRATED` entry's source file is AST-parsed to confirm it both imports `git_visible_paths` from `utils.git_repo` *and* calls it (an import with no call would be a stale claim).
- Every declared source path is checked to still exist on disk.
- Every `ALLOWLISTED` entry must carry a reason string of non-trivial length.
- A `TestTheDetectionWouldSeeAMigrationIfItHappened` class exercises the detector itself against synthetic source, so a broken detector that always passes cannot hide behind a green suite.

## RED evidence

Before any source change, the new tests failed against the unmodified code:

```
tests/unit/docs_qa/test_corpus.py::TestIterCorpusPathsGitIgnore::test_gitignored_markdown_is_not_returned FAILED
tests/unit/docs_qa/test_corpus.py::TestIterMarkdownPathsGitIgnore::test_gitignored_markdown_under_a_source_like_dir_is_not_returned FAILED
tests/integration/test_doc_truth_check.py::test_does_not_scan_a_gitignored_vendored_plugin_install FAILED
```

(2 failed, 7 passed for the corpus module's git-ignore test classes at that point; the doc_truth integration test failed with the actual reported violation echoed in the assertion message — `slash-command-in-shell-fence` at `.claude/ccy/plugins/cache/some-plugin/README.md`.)

After the fix, the same tests pass, plus every pre-existing test in both files (no regressions): a tracked file, an untracked-but-not-ignored file, and the not-a-git-repo fallback are all covered as negative controls alongside the positive gitignore case, for both `iter_markdown_paths`/`iter_corpus_paths` and `check_doc_truth.py`'s `_iter_markdown`. `TestGitVisiblePaths` in `tests/unit/utils/test_git_repo.py` covers the shared helper directly (tracked, untracked-not-ignored, gitignored file, gitignored directory contents, not-a-repo, git-unavailable).

## Targeted QA

- `tests/unit/docs_qa/`, `tests/unit/utils/test_git_repo.py`, `tests/unit/qa/test_qa_corpus_git_visibility_audit.py`, `tests/integration/test_doc_truth_check.py`: **576 passed**.
- `./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding docs_qa plan_qa`: format initially flagged 2 files (auto-fixed by the same run, per its `--auto-fix by default` design; re-ran `format` alone afterward to confirm 0 violations), all seven others passed clean on the first run (0 violations / 0 findings each; pyright analysed 1833 files, magic_values scanned 1745).
- Worktree daemon restarted (`./bin/hooks-daemon restart`) and verified `RUNNING` before committing.

Did not run `llm_qa.py all` or `run_all.sh`, per Plan 00463 policy.

## Commits

1. `1a100875` — the fix itself (`utils/git_repo.py`, `docs_qa/corpus.py`, `scripts/qa/check_doc_truth.py`) plus every test (new and modified).
2. `0a30c8dc` — ledger update (PLAN.md row → ✅ Remedied, NIGGLES.md Remedy paragraph), journal entry via `mkplan.bash --journal`, and release note 13.

Both commits are on `worktree-n466-docs-corpus`, not merged or pushed. No `sed`, no QA suppressions, no exclusion-path entries added.

## Note on release note numbering

`CLAUDE/UPGRADES/UNRELEASED/release-notes/13-docs-qa-and-doc-truth-now-respect-gitignore.md` uses `13`, one above the highest existing file (`12-...`) at the time this worktree branched. If another concurrent worktree also added a `13-*` file before integration, the coordinator will need to renumber one of them.

Integration B2 renumbered it to `24-docs-qa-and-doc-truth-now-respect-gitignore.md`, and the Plan 00468 T3.1 note `29-...` to `25-format-markdown-and-find-comment-blocks-now-respect-gitignore.md`.

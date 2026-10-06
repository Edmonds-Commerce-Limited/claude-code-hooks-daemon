# Inline suppression inventory (gap G1, owner ruling B2)

Ruling B2 (`../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md`): no central
exceptions file or baseline; suppressions stay inline and co-located, each MUST carry its
reasoning; delete as many as possible; review every kept one for need and why it exists.

Method: grep for `nosec`, `noqa`, `type: ignore`, `pragma: no cover`, `nosemgrep`,
`fmt: skip/off` across `src/`, `scripts/`, `tests/` and `.claude/ccy/`; then
`bandit --ignore-nosec` over the bandit scope to find directives with no finding under them.
The `qa_suppression` guard forbids adding or rewriting a directive, so deletion was by fixing
code, and the kept ones are reported here for the owner.

## Counts

| Class                                              | Count                |
| -------------------------------------------------- | -------------------- |
| Directives found (real, excluding string mentions) | about 300            |
| Deleted                                            | 228                  |
| Kept                                               | 78                   |
| Fixtures / string mentions (not directives)        | 9 files, intentional |

Deleted, by cause:

- 193 `nosec` in `tests/` and `scripts/`: bandit runs only on `src/` and
  `.claude/ccy/claude-supervise.py` (`scripts/qa/run_security_check.sh`, `qa.yml`,
  `.pre-commit-config.yaml`) and ruff selects no `S` rules, so every one was inert.
- 7 `nosec` in `src/` with no finding under them (`hashlib.md5(..., usedforsecurity=False)`
  x2, `except Exception as exc:` with a real body x4, `urllib.request.Request(` x1).
  Bandit passes without them.
- 22 `type: ignore` in `tests/` replaced by code that needs none: `patch.object`, `vars()`,
  `__setattr__`, `object.__setattr__`, and an explicit `cast("Any", ...)` for deliberate
  wrong-type calls.
- 6 `pragma: no cover`: 4 in `tests/` (omitted from coverage), `def __repr__` and
  `if TYPE_CHECKING:` in `src/` (both already in `exclude_lines`).
  (5 `attr-defined` ones in the plugin tests went in the first commit, 17 in the second.)

Reason-above-line route: ALLOWED. An `Edit` that inserts a plain comment line above a kept
suppression, leaving the suppression line byte-identical, was not blocked (tried on
`install/transport_verify.py`). The coordinator can therefore add reasons above reasonless
lines without owner involvement; only editing the suppression line itself is guarded.

## Kept: `nosec` in `src/` (live per `bandit --ignore-nosec`)

Bandit flags these on any use; they cannot be removed without removing the call or the
import. B404 is raised by the bare `import subprocess` (even for type-only use), B603 by every
`subprocess` call with a non-literal argv, B607 by a partial executable path, B108 by `/tmp`
literals, B310 by `urlopen`, B311 by `random`.

| Location (file:line)                                                                                                                                             | Directive    | Why it must stay                                                         | Reason present?                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `daemon/background_harvester.py:47,379`                                                                                                                          | B404, B603/7 | fixed-argv `ps`                                                          | yes (on line)                                                                        |
| `daemon/cli.py:38,2501,2528,3946,6337`                                                                                                                           | B404, B603/7 | systemctl, uv, venv python, pytest; fixed argv                           | yes (on line)                                                                        |
| `daemon/hook_probe.py:24,225`                                                                                                                                    | B404, B603/7 | trusted system `bash`, fixed argv                                        | yes (on line)                                                                        |
| `daemon/paths.py:386,391,656,658,720,944,947`                                                                                                                    | B404, B603   | PATH-resolved python probes, fixed argv                                  | yes (on line)                                                                        |
| `daemon/branch_safety.py:45`                                                                                                                                     | B404         | `git`, list form                                                         | yes (on line)                                                                        |
| `constants/paths.py:91`; `daemon/paths.py:1395`                                                                                                                  | B108         | `/tmp` is the subject of a deny rule / last-resort fallback              | yes (on line)                                                                        |
| `core/claude_md_injector.py:15`, `core/release_slate.py:15`                                                                                                      | B404         | import for `CompletedProcess` type only; spawns live in `utils.git_repo` | yes (on line)                                                                        |
| `utils/git_facts.py:47`, `utils/git_sync.py:29`, `utils/stale_checkouts.py:29`, `handlers/worktree_create/worktree_create_handler.py:20`                         | B404         | type-only import; `run_git` owns the spawn                               | yes (on line)                                                                        |
| `utils/git_repo.py:29,209,249`                                                                                                                                   | B404, B603/7 | the single trusted `git` spawn point                                     | yes (on line)                                                                        |
| `utils/github_issue_validity.py:43,101`                                                                                                                          | B404, B603/7 | `gh`, list form, no shell                                                | yes (on line)                                                                        |
| `handlers/post_tool_use/lint_on_edit.py:10,513`; `pre_tool_use/staged_lint_gate.py:33,337`; `post_tool_use/validate_eslint_on_write.py:8,368`                    | B404, B603   | trusted lint tools, no shell                                             | yes (on line)                                                                        |
| `handlers/status_line/git_branch.py:12`                                                                                                                          | B404         | `git` status call                                                        | yes (on line)                                                                        |
| `handlers/session_start/contract_staleness.py:32,352`                                                                                                            | B404, B603   | `claude --version`, fixed argv                                           | B603 line: reason is in the `# SECURITY:` comment on the line above                  |
| `install/transport_toggle.py:31,254`                                                                                                                             | B404, B603   | runs this package's own CLI via `sys.executable`                         | reason in the `# SECURITY:` comment block above both lines                           |
| `install/transport_verify.py:37,157`                                                                                                                             | B404, B603/7 | runs the forwarder argv under test, fixed argv                           | reason comment added above B404 in this work; B603 has a `# SECURITY:` comment above |
| `install/transport_probe.py:27,125`, `install/relay_deploy.py:22`, `install/client_validator.py:13,619`, `install/upgrade_tasks.py:32,351`, `qa/runner.py:8,141` | B404, B603   | fixed argv, no shell                                                     | yes (on line)                                                                        |
| `install/relay_deploy.py:277`, `remote_docs/fetchers.py:113`                                                                                                     | B310         | `urlopen` after https-scheme validation                                  | yes (on line)                                                                        |
| `remote_docs/fetchers.py:33`                                                                                                                                     | B404         | no shell; see `_invoke`                                                  | yes (on line)                                                                        |
| `handlers/user_prompt_submit/critical_thinking_advisory.py:63`                                                                                                   | B311         | non-cryptographic advisory sampling                                      | yes (on line)                                                                        |

Possible further reduction (not done, owner decision): route the type-only `import subprocess`
sites through one typed re-export so B404 appears once; and route `gh`/`ps`/`uv` spawns
through a `run_*` helper in `utils/` so B603 appears once per binary. That is a refactor with
its own test cost, not a suppression edit.

## Kept: `pragma: no cover` in `src/` (9)

Each is a defensive or unreachable branch with a reason on the line. Deleting the marker means
either adding a test that forces the branch, or restructuring so the branch does not exist.

| Location                                                                                                 | Why kept                                              |
| -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `handlers/pre_tool_use/gh_issue_comments.py:120`, `gh_pr_comments.py:137`                                | `segment is None` after `matches()` already succeeded |
| `handlers/session_start/docs_qa_sweep.py:85`, `plan_qa_sweep.py:76`, `plan_workflow_asset_checker.py:82` | `matches()` gates the `None`                          |
| `handlers/session_start/reference_repo_sweep.py:81`, `pre_tool_use/reference_repo_freshness.py:255`      | defensive `RuntimeError`, mirrors siblings            |
| `handlers/pre_tool_use/issue_filing_gate.py:266`                                                         | defensive `OSError`/`ValueError`                      |
| `plan_qa/model.py:689`                                                                                   | callers pre-filter on the pattern                     |

Recommended: replace the `is None` ones with a single narrowing helper that raises, and test it
once; that deletes five markers. Not done here because it changes five handlers' control flow.

## Kept: `.claude/ccy/claude-supervise.py` (6)

`:214` B404, `:8270` B603, `:8804` B603, `:9277` B606 (`os.execvp` of the wrapped executable
after fork; all carry a reason on the line, except `:9277` which has none) and `pragma: no cover`
at `:3310` (unreachable raise, reason present) and `:9272` (runs in the forked child, reason
present). The `:9277` B606 needs a reason added above it.

## Kept: formatter markers (7)

`fmt: skip` at `src/.../utils/recursive_search.py:69`, `tests/integration/test_init_sh_needs_provision.py:59`,
`tests/unit/daemon/test_work_queue_cli.py:96,112,125,140`; `fmt: off` at
`tests/unit/handlers/pre_tool_use/test_review7_false_positive_corpus.py:34`. These keep
hand-aligned tables/corpora readable; no reason is stated on any. They are not QA suppressions
(black only), so they were not deleted.

## Fixtures and string mentions (intentional, not directives)

Test data for the `qa_suppression` handler and prose that names the directives:
`tests/unit/strategies/qa_suppression/test_python_strategy.py`,
`tests/unit/handlers/pre_tool_use/test_qa_suppression.py`,
`tests/integration/handlers/test_pre_tool_use_qa.py`,
`tests/unit/qa/test_measure_instruction_footprint.py`,
`tests/unit/qa/test_audit_error_hiding.py`,
`tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`,
`tests/unit/utils/test_git_sync.py` (docstring), `tests/scaling.py` (the word "nanosecond"),
`tests/integration/test_path_mutated_execution_resolves_argv_by_name.py` (docstring quoting a
historical `nosec` comment).

## Not covered

No `nosemgrep`, `shellcheck disable` or `eslint-disable` directives exist in the scanned Python
trees. Shell scripts, `.ts` files and YAML were not enumerated for `shellcheck disable`; G1's
detector (still open) should cover them.

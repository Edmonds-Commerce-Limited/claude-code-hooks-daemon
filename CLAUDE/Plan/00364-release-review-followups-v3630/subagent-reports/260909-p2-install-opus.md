# Plan 00364 Phase 2 — install / plan_qa / docs_qa / skills

**Worktree**: `worktree-plan-00364-p2-install`
**Source**: `review-reports/260909-review-install-opus.md`, finding 3 and the
Suggestions section
**Scope**: Tasks 2.1–2.10, all ten delivered

Every task was driven by a failing test first. Where the RED number is the
evidence, it is quoted below.

## What changed, task by task

### Task 2.1 — the commit gate stops paying per plan folder

`GitFacts.staged_changes()` now holds its result in `self._staged`. The
`None`-output case is cached too: a wedged or absent git will not recover
mid-decision, so re-asking once per plan folder only multiplies the timeout
that made the fact unavailable.

`row_folder_bijection` gained `_folder_level()`, called only once a finding
exists, so the blame question is never asked for the clean folders that make
up almost the whole tree.

Measured on a 25-folder tree, as the RED assertions recorded:

| Case                    | Spawns before | After |
| ----------------------- | ------------- | ----- |
| Clean tree, no findings | 26            | 0     |
| Tree with one finding   | 27            | 1     |

A third test pins that deferring `_level` moved only the work, not any
verdict: a folder the commit did not touch still ADVISEs, one it created
still BLOCKs.

The spawn counter is a `git_diff_spawns` fixture in a new
`tests/unit/plan_qa/conftest.py`, shared by both suites rather than copied.
It wraps the real runner, so the facts under test are still a real
repository's.

### Task 2.2 — the validator looks where the deployer writes

`_verify_echd_capture_deployed` composes its path from `DaemonPath.CLAUDE_DIR`,
`DaemonPath.HOOKS_DAEMON_DIR`, `bin_wrapper.BIN_DIR_NAME` and
`bin_wrapper.ECHD_CAPTURE_NAME`, read when the check runs. The discriminating
test monkeypatches `ECHD_CAPTURE_NAME` and asserts the check follows the
rename; two more couple it to a real `deploy_echd_capture` call.

### Task 2.3 — three parts

`_DEFAULT_PSEUDO_EVENT_BLOCKS` is pinned against
`.claude/hooks-daemon.yaml.example` (the template a new project starts from),
both triggers and `enabled`. A companion test asserts every
`RELOCATED_HANDLERS` target has a default block.

`ConfigValidator._find_similar_names` became public `find_similar_names`; both
call sites updated, and a test asserts the private name is gone.

`_fill_block_defaults` raises `ValueError` naming the pseudo-event instead of
falling back to a triggerless `{enabled: True}`.

**One judgement call worth flagging.** The raise is scoped to the RELOCATION
path only. `_fill_block_defaults` has two callers, and making it raise
unconditionally would have been wrong: `scaffold_pseudo_event_blocks` walks
every pseudo-event block in a merged config, which may legitimately include
one this constant never had to scaffold, and raising there would abort an
upgrade over a user's own config. The sweep now SKIPS a block it has no
defaults for, leaving it exactly as written, since there is nothing to
complete it from. Both of the review's suggested remedies are in: the test
makes the raise unreachable in shipped code, and the raise is the backstop.

### Task 2.4 — an unreadable PLAN.md is not a crash

`except (OSError, UnicodeDecodeError)`. RED reproduced the escape exactly: a
lone `0x80` byte in `PLAN.md` raised `UnicodeDecodeError` straight out of the
commit gate. Both halves of the pair are now tested.

### Task 2.5 — the catalogue string is data, and the index is hoisted

`_METAS_BY_BASH_KEY` is built once at import instead of per render.
`daemon_down_stdout` is escaped for double-quote interpolation, backslash
first so the later escapes are not re-escaped.

The escaping test runs a generated forwarder under bash with a hostile
catalogue entry (`a "quoted" $HOME \`whoami\` \\ marker`) and `HOME`set to a sentinel; the text comes back verbatim and unexpanded. A second test pins that the shipped catalogue text is unaffected. The hoist is pinned by monkeypatching`wired_event_metas\` to raise if the renderer calls it.

### Task 2.6 — name the subsystem that is actually down

`_DAEMON_ERROR_MARKER in err` tested ahead of the exit-code-translation
branch. Both arms are pinned, so the narrowing cannot swallow the defect that
branch exists for.

### Task 2.7 — the atomicity comment is now true

`_write_atomically` (temp file in the same directory, then `Path.replace`,
temp cleaned up if the rename fails) at all three whole-file write sites,
including the escalation proposal. The comment claiming "every whole-file
writer is atomic or can be" now names the function.

The test fails the rename and asserts the original file survives byte-for-byte
— the property `write_text` lacks, because it truncates before it writes.

### Task 2.8 — the capture helper

Three changes to `install/templates/echd-capture`, mirrored byte-for-byte into
the deployed `bin/echd-capture`:

- Last-resort directory via `mktemp -d "${TMPDIR:-/tmp}/echd-captures-XXXXXX"`.
  A fixed name in a world-writable directory is a symlink-redirect target,
  since `mkdir -p` follows one that already exists. A failed `mktemp` degrades
  to the same `exec cat` pass-through the other failure paths use.
- `--help` runs an awk that exits at the first non-comment line. It also skips
  the shebang, which the old `grep '^#' | cut -c3-` was printing as a bare
  `/bin/bash`.
- The header's "tees the FULL stream" became "writes", matching `cat >`.

The review asked for `--label`, `--all` and exit-2 coverage; all three already
existed, so the new tests cover the two new behaviours instead: six for the
fallback directory (unpredictable name, distinct per run, 0700, both higher
precedence rungs still win, and the uncreatable case still passes the stream
through) and four for `--help`.

A new drift test asserts `bin/echd-capture` and the template are identical. It
caught the stale deployed copy the moment the template changed, which is the
reason to have it.

### Task 2.9 — the skill advertises what it accepts

The `description` frontmatter now lists `optimise` **and** `bug-report`. The
generalised test — every subcommand in `argument-hint` appears in
`description` — found the second omission, which the review had not.
`dev-handlers.md` uses an `[args...]` placeholder.

The `"$@"` test is deliberately scoped to reference documents and NOT to
`SKILL.md`: its blocks are the routing script's own body, executed with
arguments the skill runner passes, where forwarding `"$@"` is exactly right.
A whole-tree scan would have forced a wrong change to five correct lines. A
guard test asserts the scan never collapses to an empty file list.

Both files were updated in the source tree and in the deployed
`.claude/skills/hooks-daemon/`, which `test_deployed_skill_trees.py` pins.

### Task 2.10 — a dropped document leaves a trace

`logger.debug` → `logger.info` for an unstattable file, with a companion test
that a steady-state revalidation logs nothing at all, which is why INFO is
affordable here.

## Two things the coordinator needs to know

### The QA runner cannot resolve a worktree's venv

`scripts/qa/llm_qa.py` hardcodes `untracked/venv/bin/python`, which
`scripts/install/venv_resolver.sh` documents as the *retired* pre-v3.7.0
layout it deliberately refuses to fall back to. In a worktree the resolver
answers `untracked/venv-<hash>/bin/python`, so `llm_qa.py all` dies with
`FileNotFoundError` before running anything. Only `lint` survives, because it
does not go through `VENV_PYTHON`.

Worked around locally with a gitignored symlink `untracked/venv -> venv-<hash>`.
The canonical venv also needed `uv sync --extra dev`; it had no pytest, ruff or
mypy. **Not fixed here** — it is a QA-tooling defect outside Phase 2's scope,
and Phases 1, 3 and 4 will hit it identically in their own worktrees. It wants
its own task: `llm_qa.py` should source `venv_resolver.sh` like everything
else does.

Note also that `uv sync --active` without `--extra dev` STRIPS the dev tools
out of the venv.

### Five integration tests fail in a bare worktree, for environmental reasons

`test_daemon_smoke` (1), `test_forwarder_socket_stdin` (2) and
`test_plugin_daemon_integration` (2) fail because
`.claude/hooks-daemon/scripts/lib/resolve_venv.sh` does not exist: the
worktree's `.claude/hooks-daemon/` holds only `untracked/`, so no daemon is
deployed to answer them. None of the five touches any module Phase 2 changed.
Everything else passes.

## Release notes

One callout at
`CLAUDE/UPGRADES/UNRELEASED/release-notes/02-plan-qa-commit-gate-and-capture-helper.md`,
covering the commit-gate cost, the UTF-8 crash, the atomic settings write, the
transport-verify message, both `echd-capture` changes and the skill
description.

**Numbering caveat**: Phases 1, 3 and 4 are running concurrently and cannot see
each other's choices, so if two of them also picked `02-` the files will need
renumbering at merge. The ordinal is arrival order and nothing enforces it
across worktrees.

## Files touched

Source:

- `src/claude_code_hooks_daemon/plan_qa/gitfacts.py`
- `src/claude_code_hooks_daemon/plan_qa/checks/row_folder_bijection.py`
- `src/claude_code_hooks_daemon/plan_qa/checks/same_commit_plan_doc.py`
- `src/claude_code_hooks_daemon/install/client_validator.py`
- `src/claude_code_hooks_daemon/install/handler_key_audit.py`
- `src/claude_code_hooks_daemon/install/forwarder_generator.py`
- `src/claude_code_hooks_daemon/install/transport_verify.py`
- `src/claude_code_hooks_daemon/install/settings_merge.py`
- `src/claude_code_hooks_daemon/install/templates/echd-capture`
- `src/claude_code_hooks_daemon/config/validator.py`
- `src/claude_code_hooks_daemon/docs_qa/corpus.py`
- `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md`
- `src/claude_code_hooks_daemon/skills/hooks-daemon/dev-handlers.md`

Deployed copies kept in lockstep:

- `bin/echd-capture`
- `.claude/skills/hooks-daemon/SKILL.md`
- `.claude/skills/hooks-daemon/dev-handlers.md`

Tests:

- `tests/unit/plan_qa/conftest.py` (new)
- `tests/unit/plan_qa/test_gitfacts.py`
- `tests/unit/plan_qa/checks/test_row_folder_bijection.py`
- `tests/unit/plan_qa/checks/test_same_commit_plan_doc.py`
- `tests/unit/install/test_client_validator.py`
- `tests/unit/install/test_handler_key_audit.py`
- `tests/unit/install/test_forwarder_generator_raw_stdout.py`
- `tests/unit/install/test_transport_verify.py`
- `tests/unit/install/test_settings_merge_run.py`
- `tests/unit/docs_qa/test_corpus.py`
- `tests/integration/test_echd_capture.py`
- `tests/integration/test_skill_surface_coherence.py`

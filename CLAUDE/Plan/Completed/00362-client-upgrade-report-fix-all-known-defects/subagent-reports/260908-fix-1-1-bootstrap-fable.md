# Task 1.1 — bootstrap assets in the pipeline, local-copy fallback

Branch: `agent-a127b1018e6b52ee7-781ff01f` (worktree at
`/workspace/.claude/worktrees/agent-a127b1018e6b52ee7-781ff01f`).

## Root cause of v3.62.1 shipping without assets

Every earlier release checked (v3.40.0, v3.55.0, v3.61.0, v3.62.0) carries
the five bootstrap assets; v3.62.1 alone has none. The manifest recipe existed
only as a prose loop in `CLAUDE/development/RELEASING.md` Step 14. The
procedure a release actually follows — `.claude/skills/release/invoke.sh`
Stage 4 and `.claude/agents/release-agent.md` Stage 3 — showed
`gh release create vX.Y.Z --title ... --notes-file ... --latest` with no
artifacts and never mentioned the manifest. Nothing tested that the three
documents agreed, and nothing invoked the (already tested)
`scripts/release/build_bootstrap_checksums.sh` from the followed procedure.

## What changed

### Pipeline (part 1)

- `scripts/release/publish_bootstrap_assets.sh vX.Y.Z [--build-only]` — the
  single release step. Stages the four skill scripts from
  `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/` in a fixed
  order, builds `bootstrap-checksums.txt` via `build_bootstrap_checksums.sh`,
  refuses to build if any script in the skill tree carries a
  `SELF-BOOTSTRAP BEGIN` stanza that is not in the bundle, runs
  `gh release upload <tag> <5 assets> --clobber`, then reads the release
  back with `gh release view --json assets` and fails unless every asset is
  listed. Env overrides for tests and repairs: `HOOKS_DAEMON_GH_BIN`,
  `HOOKS_DAEMON_RELEASE_ARTIFACTS_DIR`, `HOOKS_DAEMON_SKILL_SCRIPTS_DIR`.
- `tests/integration/test_publish_bootstrap_assets.py` (10 tests): manifest
  covers every stanza-carrying script (discovered by scanning, not a list),
  determinism, `--build-only` never calls gh, upload contract incl.
  `--clobber` and read-back verification, missing-asset read-back fails,
  tag validation, the skill-scripts-dir override, and that all three
  procedure documents invoke the script AFTER `gh release create`.
- `CLAUDE/development/RELEASING.md` Step 14, `invoke.sh` Stage 4 and
  `release-agent.md` Stage 3 now run the script; the relay-asset block no
  longer offers a second `gh release create` form; RELEASING.md documents
  the tag-exact repair recipe.

### Fallback (part 2)

- The shared bootstrap stanza (byte-identical in `daemon-cli.sh`,
  `health-check.sh`, `init-handlers.sh` under `src/` and the deployed
  `.claude/skills/hooks-daemon/scripts/` copies) now falls back to the
  installed local copy when the manifest OR the fresh script cannot be
  downloaded: exactly one `Warning:` line to stderr naming the URL and curl
  exit code, the local body runs, and no cache marker is written so the next
  run retries. It still aborts on a checksum mismatch, on a manifest with no
  entry for the script, and if `$0` itself is unreadable (no local copy).
  `curl -S` was dropped so the fallback is one line, not two.
- `tests/acceptance/test_diagnostic_scripts.py`: the abort-pinning case
  `test_diagnostic_script_aborts_on_network_failure` is replaced by
  `..._falls_back_to_local_copy_when_manifest_unreachable`,
  `..._falls_back_to_local_copy_when_fresh_script_unreachable`,
  `..._still_aborts_on_checksum_mismatch` (each x3 scripts) and
  `test_bootstrap_stanza_is_identical_across_diagnostic_scripts`. These are
  bash-level: they execute the real stanza under bash with
  `HOOKS_DAEMON_BOOTSTRAP_BASE_URL` pointed at a `file://` path that does
  not exist (the repo's established pattern for shell tests — pytest driving
  bash via subprocess; there is no bats suite).

## Verification

- `pytest tests/integration/test_publish_bootstrap_assets.py tests/acceptance/test_diagnostic_scripts.py` — 37 passed.
- Neighbouring suites (`test_build_bootstrap_checksums.py`,
  `test_deployed_skill_trees.py`, `test_skill_scripts_venv_resolution.py`,
  `tests/unit/scripts`, `tests/unit/qa`, `tests/unit/docs_qa`,
  `install/test_skills.py`) — 995 passed, 1 skipped.
- `ruff check` + `ruff format`, `mypy --strict` on both test files: clean.
- `shellcheck` on the new script, all six stanza copies and
  `.claude/skills/release/invoke.sh`: clean.
- `audit_shell.py`, `audit_error_hiding.py`, `check_skill_references.py`,
  `check_doc_snippets.py`, `audit_capture_corruption.py`,
  `check_doc_truth.py`, `check_british_english.py`: all clean.
- Daemon NOT restarted (per brief). No `sed`, no stash, no destructive git.

## Command for the owner / coordinator to repair v3.62.1

Not run by me. From the main checkout after this branch merges, attach the
bytes of the v3.62.1 tag (not main HEAD) so the manifest matches what
clients already have installed:

```bash
git worktree add untracked/worktrees/tag-v3.62.1 v3.62.1
HOOKS_DAEMON_SKILL_SCRIPTS_DIR=untracked/worktrees/tag-v3.62.1/src/claude_code_hooks_daemon/skills/hooks-daemon/scripts \
  scripts/release/publish_bootstrap_assets.sh v3.62.1
git worktree remove untracked/worktrees/tag-v3.62.1
```

Verify: `gh release view v3.62.1 --json assets --jq '.assets[].name'` lists
`upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh bootstrap-checksums.txt`.

Note the fallback itself only reaches clients with the next release; until
then the asset repair above is what unbreaks v3.62.1 installs.

## Follow-ups noticed (not done)

- The relay assets (`hooks-relay-*`, `SHA256SUMS`) are still a manual
  `gh release upload` in RELEASING.md and are absent from `invoke.sh`; a
  release without them is documented as valid, so not in this task's scope.
- `scripts/qa/llm_qa.py` hard-codes `untracked/venv/bin/python` and cannot
  run in a fingerprint-keyed worktree venv; I ran the underlying audit
  scripts directly.

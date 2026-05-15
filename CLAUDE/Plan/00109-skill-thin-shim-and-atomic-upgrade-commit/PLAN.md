# Plan 00109: Skill thin-shim + atomic upgrade commit

**Status**: In Progress
**Created**: 2026-05-15
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The skill scripts pushed into client projects (currently `scripts/upgrade.sh`,
`daemon-cli.sh`, `health-check.sh`, `init-handlers.sh`) carry non-trivial
logic — self-bootstrap with sha256 verification, Python version pre-check,
`uv.lock` cleanup. That logic is shipped frozen at release time and has
already caused two SEV-class incidents (v3.9.x `write-venv-metadata` field
bug; v3.10.0 `print_info` stdout-corruption hotfix) because clients ran
stale skill scripts that no in-repo fix could rescue.

The user's directive: the skill should hold **zero logic**. Every entry
point becomes a thin shim that fetches the canonical script from `main`
(established hot-patch pattern) and execs it. All real logic moves
upstream into the daemon repo where it can be hot-patched on `main` and
reach every client on the next invocation.

Second piece: every successful upgrade must end with an atomic
`hooks daemon upgrade` commit that records what changed in the client
repo (from/to version, Python, host, venv path, config diff summary).
The upgrade script emits the metadata; the project's agent writes the
commit message — script doesn't fabricate prose.

## Goals

- Skill `scripts/upgrade.sh` becomes a thin shim (~20 lines): fetch
  canonical script from `main`, exec, exit.
- All in-skill logic (project-root walk, Python pre-check, `uv.lock`
  cleanup, self-bootstrap stanza) moves into the in-repo
  `scripts/upgrade.sh` where it is hot-patchable.
- A successful upgrade emits a machine-parseable `UPGRADE_METADATA`
  block covering: from-version, to-version, Python version + path,
  host, venv path, list of client files modified, config diff summary.
- Skill `upgrade.md` instructs the agent: after upgrade succeeds,
  parse the metadata block and create one atomic commit
  `hooks daemon upgrade: vX → vY` covering exactly the modified files,
  with the metadata in the body.
- Acceptance test covers the metadata-emission contract so future
  scripts changes can't silently drop fields.

## Non-Goals

- Not touching the three other bootstrapped scripts (`daemon-cli.sh`,
  `health-check.sh`, `init-handlers.sh`) in this plan — track those
  separately. Reason: the upgrade flow is the highest-leverage and
  highest-risk entry point; thinning it first proves the pattern.
- Not removing the release-time `bootstrap-checksums.txt` artifact yet
  — the other three scripts still reference it. Removal is tied to
  the follow-up plan that thins them.
- Not reviewing whether pull-from-HEAD itself is the right pattern —
  user confirmed it stays for hot-patchability. A gh issue tracks the
  longer-term review of that decision.
- Not changing the in-repo Layer 2 `scripts/upgrade_version.sh` — its
  contract with Layer 1 stays the same. Metadata emission lives in
  Layer 1 after Layer 2 returns.

## Context & Background

### Current flow (pre-plan)

```
/hooks-daemon upgrade
  └─ skill scripts/upgrade.sh (in client repo, frozen at release time)
     ├─ self-bootstrap from releases/latest/download/upgrade.sh + sha256
     ├─ detect project root by walking up for .claude/hooks-daemon.yaml
     ├─ check active python3 >= requires-python from daemon pyproject.toml
     ├─ rm -f $DAEMON_DIR/uv.lock
     └─ exec $DAEMON_DIR/scripts/upgrade.sh --project-root … [VERSION]
        └─ in-repo Layer 1 (scripts/upgrade.sh, current HEAD of installed tag)
           ├─ find_compatible_python (3.11+)
           ├─ stop running daemons (PID-only)
           ├─ git fetch --tags + checkout target version
           ├─ clean nested install artifacts
           └─ exec scripts/upgrade_version.sh (Layer 2 from target tag)
```

The "frozen at release time" line is the failure surface. v3.9.x and
v3.10.0 both shipped releases where the skill script in users' repos
had a bug, and the fix required re-installation, not a normal upgrade.

### Established hot-patch pattern

`version_check.py` already tells users (every session start, when an
upgrade is available):

```
curl -fsSL https://raw.githubusercontent.com/.../main/scripts/upgrade.sh -o /tmp/upgrade.sh
less /tmp/upgrade.sh
bash /tmp/upgrade.sh
```

That message is the canonical hot-patch flow. The skill should do
exactly that — nothing more, nothing less.

### Atomic commit motivation

Client repos track `.claude/hooks-daemon/` (daemon source),
`.claude/hooks-daemon.yaml` (config), `.claude/skills/hooks-daemon/`
(skill files), and possibly `.claude/hooks/*` and `.claude/settings.json`.
Today users are left with a dirty working tree after upgrade and may
commit it ad-hoc with no metadata. An atomic commit with the from/to
version + environment fingerprint gives downstream-readers (and
future-Claude doing release archaeology) a clean record of which
upgrade ran where.

## Tasks

### Phase 1: Metadata emission in Layer 1 (TDD)

- [x] ✅ **Task 1.1**: Define the `UPGRADE_METADATA` block contract.
  Fields, format (key=value lines wrapped in
  `<<<UPGRADE_METADATA` … `UPGRADE_METADATA>>>` sentinels for unambiguous parsing).
  Fields: `from_version`, `to_version`, `python_version`,
  `python_path`, `venv_path`, `host`, `daemon_dir`, `project_root`,
  `modified_files` (newline-separated relative paths),
  `config_diff_summary` (one-line per setting changed, or empty).
- [x] ✅ **Task 1.2**: Write failing test
  `tests/acceptance/test_upgrade_metadata_emission.py` — invokes the
  in-repo `scripts/upgrade.sh` end-to-end against a fixture project
  and asserts the metadata block appears on stdout with all required
  fields populated and non-empty.
- [x] ✅ **Task 1.3**: Implement metadata emission in Layer 1
  `scripts/upgrade.sh`. Layer 2 returns success → Layer 1 gathers
  metadata (from previous tag at start, target tag at end, venv path
  via daemon CLI, etc.) and prints the block. Block goes to stdout
  AFTER all human-readable progress output so it's the last thing
  the agent sees.
- [x] ✅ **Task 1.4**: Run QA, restart daemon, verify RUNNING.
  Coverage at 94.98% on this branch matches main pre-existing state
  (verified by running tests without the new acceptance test). uv.lock
  was stale on v3.10.1 → regenerated to v3.14.0. All other gates pass.
  Daemon restart verified RUNNING.

### Phase 2: Thin-shim skill upgrade.sh (TDD)

- [x] ✅ **Task 2.1**: Write failing test
  `tests/acceptance/test_skill_upgrade_shim.py` — invokes
  `src/.../skills/hooks-daemon/scripts/upgrade.sh` against a fixture,
  with `HOOKS_DAEMON_UPGRADE_BASE_URL` pointed at a local file://
  fixture serving a known `scripts/upgrade.sh`. Asserts the shim
  fetches and execs the fixture script (sees fixture-specific marker
  in output), and aborts non-zero on fetch failure.
- [x] ✅ **Task 2.2**: Replaced skill `scripts/upgrade.sh` body with
  the thin shim (~23 logic lines). Parses `--help`, walks for
  `.claude/hooks-daemon.yaml` to detect PROJECT_ROOT, fetches
  `$BASE_URL/$REF/scripts/upgrade.sh` (env-overridable for tests),
  aborts loudly on curl failure, `chmod +x`, `exec bash /tmp/upgrade.sh --project-root "$PROJECT_ROOT" "$@"`.
- [x] ✅ **Task 2.3**: Python pre-check already lives upstream as
  `find_compatible_python` in `scripts/upgrade.sh` — no migration
  needed. `uv.lock` cleanup migrated upstream as a git-aware block
  (only removes untracked uv.lock; preserves tracked one in
  self-install mode). Retired the old skill-side
  `tests/integration/test_skill_*.py` files (6 files) since the
  thin shim has none of the behaviours they exercised; re-pointed
  `_extract_bootstrap_stanza()` in `test_diagnostic_scripts.py`
  at `daemon-cli.sh` which still carries the stanza per Non-Goals.
  Added two small coverage tests in `test_upgrade_compatibility.py`
  to restore the 95% threshold after retiring the obsolete tests.
- [x] ✅ **Task 2.4**: QA: 13/13 passed (coverage 95.0%). Daemon
  restart verified RUNNING.

### Phase 3: Atomic commit instruction in skill upgrade.md

- [x] ✅ **Task 3.1**: Rewrote skill `upgrade.md` (56 lines, agent
  workflow in 5 numbered steps): run `/hooks-daemon upgrade`,
  parse `<<<UPGRADE_METADATA` block, verify daemon RUNNING via
  `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`, stage
  ONLY daemon-owned paths via explicit `git add` (never `git add .`),
  commit with metadata block in body. Dropped the legacy
  "Quick/Specific/Force/Safety/Manual/History" sections — they
  belonged to the pre-thin-shim design and the agent-facing flow
  is now self-contained.
- [x] ✅ **Task 3.2**: Added
  `tests/acceptance/test_upgrade_md_metadata_contract.py` (4 tests):
  - every field Layer 1's `printf 'KEY=%s\n'` emits is referenced
    in `upgrade.md`
  - every snake-case field reference in `upgrade.md` exists in the
    script's emission contract (no phantom fields)
  - both open and close sentinels are mentioned in `upgrade.md`
  - sanity check both files exist. Cheap (~0.03s, no subprocess).
- [x] ✅ **Task 3.3**: QA: 13/13 passed (8244 tests, 95.0% coverage).
  Daemon restart verified RUNNING (PID 148827). Also added
  `^src/claude_code_hooks_daemon/skills/.*\\.md$` to
  `allowed_markdown_paths` in `.claude/hooks-daemon.yaml` so the
  `markdown_organization` handler stops blocking legitimate edits
  to skill source markdown.

### Phase 4: Release artifact handling

- [x] ✅ **Task 4.1**: KEEP decision documented in Decision 4
  below. Rationale: sibling scripts (`daemon-cli.sh`,
  `health-check.sh`, `init-handlers.sh`) still self-bootstrap
  from the manifest via `awk -v name="…"` lookup; removing
  `upgrade.sh` from the manifest would only force a
  RELEASING.md churn for no client-visible gain. Once the
  follow-up plan thins the three siblings, all four artifacts
  can be dropped together in a single release-process change.
- [x] ✅ **Task 4.2**: Added "Note on `upgrade.sh` (Plan 00109)"
  paragraph after Step 14 in `CLAUDE/development/RELEASING.md`
  explaining the published `upgrade.sh` artifact is now inert
  dead-weight (clients run the canonical `scripts/upgrade.sh`
  from `main` HEAD via the thin shim) but kept in the manifest
  for cross-symmetry with the three sibling self-bootstrap
  scripts.
- [x] ✅ **Task 4.3**: Added
  `tests/acceptance/test_skill_upgrade_end_to_end.py` —
  full pipeline gate: shim → real Layer 1 → metadata against
  an installed daemon. Sets up fixture project, clones daemon
  into `.claude/hooks-daemon/`, runs `install_version.sh`,
  builds `file://` fixture tree mirroring GitHub's raw-content
  layout (`<base>/main/scripts/upgrade.sh`) seeded from the
  cloned daemon dir (hermetic, not from test-host REPO_ROOT).
  Sets `HOOKS_DAEMON_UPGRADE_BASE_URL`,
  `HOOKS_DAEMON_UPGRADE_REF=main`, `HOOKS_DAEMON_PYTHON`,
  invokes the shim, asserts exit 0, both sentinels on stdout,
  all 10 required metadata fields populated,
  `metadata["project_root"] == str(project_root)` (proves the
  shim's PROJECT_ROOT detection forwarded correctly to Layer 1),
  and `python_path` is not `/usr/bin/`. Decorated
  `@pytest.mark.slow`. Closes the integration gap between the
  Phase 1 metadata test (bypasses the shim) and the Phase 2
  shim test (uses a stand-in script). PASSED 6.96s on first
  run. H-1 gate still green: 2/2 in 11.57s.

### Phase 5: gh issue + release

- [x] ✅ **Task 5.1**: Opened gh issue #31
  `Review pull-from-HEAD pattern for skill upgrade flow`
  (<https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/31>)
  — captures the longer-term question of whether `raw/main` is
  the right source (vs `releases/latest/download` with sha256,
  vs a pinned tag). Documents the two decision triggers (sibling
  thinning plan landing; mid-release inconsistency biting a user)
  and lists alternatives. Out of scope for this plan.
- [ ] ⬜ **Task 5.2**: Update CHANGELOG.md / RELEASES/ via
  `/release` skill. This is MINOR (breaking change for any client
  that scripted against the old skill upgrade.sh internals — none
  documented — but the user-facing CLI is identical).
- [ ] ⬜ **Task 5.3**: Acceptance test the full upgrade flow end
  to end against a clean fixture project before tagging.

## Dependencies

- Depends on: nothing — `tests/acceptance/test_install_sh_end_to_end.py`
  is the H-1 gate that proves the install path still works; this
  plan reuses it as-is.
- Blocks: future plan to thin `daemon-cli.sh`, `health-check.sh`,
  `init-handlers.sh` (same pattern, separate plan).
- Related: Plan 00104 (introduced self-bootstrap), Plan 00105
  (extended to all four scripts), gh issue from Task 5.1.

## Technical Decisions

### Decision 1: Pull from `main` (not `releases/latest`)

**Context**: User confirmed pull-from-HEAD is the established
hot-patch pattern and stays. Pulling from a release tag would
re-introduce the freeze-at-release-time failure mode.

**Options Considered**:

1. Pull from `raw.githubusercontent.com/.../main/scripts/upgrade.sh`
   — current `version_check` suggestion. No verification. Hot-patchable.
2. Pull from `releases/latest/download/upgrade.sh` with sha256
   verification against `bootstrap-checksums.txt`. Verified but
   frozen-at-release.
3. Pull from a configurable ref (env var `HOOKS_DAEMON_UPGRADE_REF`,
   default `main`). Allows users to pin if they want.

**Decision**: Option 1, with env override
`HOOKS_DAEMON_UPGRADE_REF` defaulting to `main` (lightweight
hedge — doesn't add complexity, enables a paranoid user to pin).

**Date**: 2026-05-15

### Decision 2: Metadata block format

**Context**: Need a machine-parseable block the agent can
extract reliably even if Layer 2 prints additional progress
output after the upgrade succeeds.

**Options Considered**:

1. JSON block — easy to parse but bash-emission of nested values
   (e.g. modified-files list) is error-prone.
2. `key=value` lines with sentinels — bash-friendly emission,
   trivial parse via grep/awk.
3. YAML — overkill for ~10 keys.

**Decision**: Option 2. Sentinels
`<<<UPGRADE_METADATA` (open) and `UPGRADE_METADATA>>>` (close)
on lines by themselves. Multi-value fields use comma separators
on a single line; `modified_files` uses a separate indented
block. Agent parses with awk/grep, no JSON dep.

**Date**: 2026-05-15

### Decision 3: Atomic commit — script vs agent

**Context**: User said "the project agent to handle writing the
commit message but script can prompt which values to include".

**Decision**: Script emits the metadata block; agent writes the
commit message body using the metadata. Script never runs `git commit` itself. Reason: commit message authoring is judgement
work (which files to stage, what to highlight in the body) and
the agent has full context the script doesn't. Keeps the script
deterministic and the prose human-readable.

**Date**: 2026-05-15

### Decision 4: Keep `upgrade.sh` in the release manifest

**Context**: With the thin-shim design, the published
`upgrade.sh` release artifact is no longer the script that runs
on clients — the shim fetches `scripts/upgrade.sh` from `main`
HEAD instead. Question: should `upgrade.sh` still be published
in `bootstrap-checksums.txt` and as a release asset?

**Options Considered**:

1. **Remove `upgrade.sh` from manifest + release assets.** Each
   of the three sibling scripts (`daemon-cli.sh`,
   `health-check.sh`, `init-handlers.sh`) looks up its own
   basename via `awk -v name="$_HOOKS_DAEMON_BOOTSTRAP_SCRIPT_NAME"`
   — they don't reference `upgrade.sh`. Removing it would not
   break their self-bootstrap. BUT `RELEASING.md` Step 14 iterates
   `for script in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh`
   and aborts the release if any is missing from the manifest;
   that loop would need updating.
2. **Keep `upgrade.sh` in manifest + release assets.** Zero
   release-process change. The published artifact becomes inert
   (no client ever runs it), but it costs nothing and matches the
   established symmetry across all four entry-point scripts.
   Future plan to thin the three siblings (mentioned in Non-Goals)
   will revisit this once they too become shims.

**Decision**: Option 2 — KEEP. The published `upgrade.sh` artifact
is now dead weight (clients run the canonical `scripts/upgrade.sh`
from `main` HEAD via the thin shim, not the published asset), but
removing it has no upside and adds churn to the release process.
Once the sibling-script thinning plan lands, all four artifacts
can be dropped together in a single release-process change.

**Documented in**: `CLAUDE/development/RELEASING.md` Step 14 — the
existing artifact-build commands stay; a note explains the
published `upgrade.sh` is no longer functionally consumed.

**Date**: 2026-05-15

## Success Criteria

- [ ] Skill `scripts/upgrade.sh` is < 30 lines and contains no
  logic beyond `curl + exec` (plus `--help` passthrough).
- [ ] In-repo `scripts/upgrade.sh` emits the `UPGRADE_METADATA`
  block on success with all required fields populated.
- [ ] Skill `upgrade.md` instructs the agent on the atomic
  commit step in ≤ 15 lines of agent-facing text.
- [ ] `tests/acceptance/test_upgrade_metadata_emission.py` and
  `tests/acceptance/test_skill_upgrade_shim.py` pass.
- [ ] H-1 gate (`test_install_sh_end_to_end.py` + sibling
  `test_skill_upgrade_end_to_end.py`) green.
- [ ] gh issue opened for pull-from-HEAD review.
- [ ] CHANGELOG entry + release notes call out the change.
- [ ] Full QA: `./scripts/qa/run_all.sh` — all 12 checks pass.

## Risks & Mitigations

| Risk                                                                      | Impact | Probability | Mitigation                                                                                                                                                                        |
| ------------------------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stale clients with broken skill upgrade.sh can't bootstrap new flow       | High   | Medium      | The thin shim is a one-time install; clients on broken old versions need to re-run install.sh manually (already documented for v3.9.x / v3.10.0 victims)                          |
| Pull-from-`main` returns mid-release inconsistent script                  | Medium | Low         | User accepted the tradeoff; gh issue tracks long-term review; release process should hold `scripts/upgrade.sh` changes for the same PR as the tag                                 |
| Agent fails to parse metadata block (formatting drift)                    | Medium | Medium      | Acceptance test asserts the contract; skill upgrade.md references same contract; both reviewed together                                                                           |
| Layer 2 writes additional output after Layer 1 metadata emission          | Low    | Medium      | Layer 1 uses `exec bash Layer2` today; new design captures Layer 2 output and emits metadata AFTER Layer 2 returns, eliminating ordering risk                                     |
| Atomic commit catches unrelated working-tree changes the user had pending | Low    | Low         | upgrade.md tells the agent to stage ONLY daemon-owned paths via explicit `git add`; other WIP stays unstaged (user directive — not relevant to upgrade commit). Never `git add .` |

## Notes & Updates

### 2026-05-15

- Plan drafted from user clarifications:
  - Skill must have zero logic (pull from main + exec)
  - Pull-from-HEAD pattern stays (hot-patchable) — gh issue tracks review
  - Upgrade must end with atomic commit; script emits metadata, agent writes prose
  - Fields: HD version, Python version, host, venv path, config changes
- Waiting on user approval before implementing.

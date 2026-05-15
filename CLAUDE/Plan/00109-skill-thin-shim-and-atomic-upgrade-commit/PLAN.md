# Plan 00109: Skill thin-shim + atomic upgrade commit

**Status**: Not Started
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

- [ ] ⬜ **Task 2.1**: Write failing test
  `tests/acceptance/test_skill_upgrade_shim.py` — invokes
  `src/.../skills/hooks-daemon/scripts/upgrade.sh` against a fixture,
  with `HOOKS_DAEMON_BOOTSTRAP_BASE_URL` pointed at a local fixture
  serving a known `scripts/upgrade.sh`. Asserts the shim fetches and
  execs the fixture script (sees fixture-specific marker in output).
- [ ] ⬜ **Task 2.2**: Replace skill `scripts/upgrade.sh` body with
  the thin shim. ~20 lines: parse `--help`, fetch
  `$RAW_URL/main/scripts/upgrade.sh` (overridable for tests), abort
  loudly on curl failure, `chmod +x`, `exec bash /tmp/upgrade.sh --project-root "$PROJECT_ROOT" "$@"`. Project-root detection stays
  in the shim because the canonical script needs it as an argument
  — keep that one piece because it's the only thing the shim knows
  that the canonical script doesn't (the client's actual working
  directory at invocation time).
- [ ] ⬜ **Task 2.3**: Move the Python-version pre-check and
  `uv.lock` cleanup currently in the skill script into the canonical
  in-repo `scripts/upgrade.sh` (so they're hot-patchable). Confirm
  no duplication with the existing `find_compatible_python` /
  uv.lock-removal logic already there. If duplicate, drop the skill
  copy; if novel, port forward.
- [ ] ⬜ **Task 2.4**: Run QA + restart daemon.

### Phase 3: Atomic commit instruction in skill upgrade.md

- [ ] ⬜ **Task 3.1**: Rewrite skill `upgrade.md` to a short,
  agent-facing instruction:
  1. Run `/hooks-daemon upgrade [VERSION]`
  2. When you see `<<<UPGRADE_METADATA` block on stdout, parse it.
  3. Verify daemon is RUNNING via
     `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`.
  4. Stage ONLY daemon-owned paths with explicit `git add`:
     `.claude/hooks-daemon/`, `.claude/hooks-daemon.yaml`,
     `.claude/skills/hooks-daemon/`, `.claude/hooks/`,
     `.claude/settings.json`. **Other WIP files in the working
     tree are NOT relevant to the upgrade commit** — leave them
     unstaged (per user directive: "commit hooks daemon stuff
     only — other WIP stuff is not relevant"). Never `git add .`.
  5. Commit with title
     `hooks daemon upgrade: ${from_version} → ${to_version}` and
     the metadata block in the body.
- [ ] ⬜ **Task 3.2**: Add an acceptance test that walks the
  upgrade.md instruction text against the metadata contract — i.e.
  every field the metadata block emits is referenced somewhere in
  upgrade.md, and every reference in upgrade.md exists in the
  contract. Prevents drift.
- [ ] ⬜ **Task 3.3**: Run QA + restart daemon.

### Phase 4: Release artifact handling

- [ ] ⬜ **Task 4.1**: Decide whether to keep publishing
  `upgrade.sh` and `bootstrap-checksums.txt` as release artifacts.
  Recommendation: KEEP — the three sibling scripts still
  self-bootstrap against the manifest, and removing `upgrade.sh`
  from the manifest would break their lookup contract. Document
  the decision in PLAN.md "Technical Decisions" section.
- [ ] ⬜ **Task 4.2**: If Task 4.1 says KEEP, update
  `CLAUDE/development/RELEASING.md` Step 14 to note that the
  published `upgrade.sh` is no longer the script that runs on
  clients (it's the in-repo `scripts/upgrade.sh` from `main`
  HEAD), and the artifact exists only to satisfy the manifest
  cross-check used by the other three bootstrapped scripts.
- [ ] ⬜ **Task 4.3**: Make sure the H-1 deterministic gate
  `tests/acceptance/test_install_sh_end_to_end.py` still exercises
  the install path. Add a sibling
  `tests/acceptance/test_skill_upgrade_end_to_end.py` that
  exercises the new shim end-to-end against a fixture.

### Phase 5: gh issue + release

- [ ] ⬜ **Task 5.1**: Open gh issue
  `Review pull-from-HEAD pattern for skill upgrade flow` — captures
  the longer-term question of whether `raw/main` is the right
  source (vs `releases/latest/download` with sha256, vs a pinned
  tag). Out of scope for this plan; tracked for future review.
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

# Plan 00141: `release-notes` CLI subcommand + skill route

**Status**: Complete
**Created**: 2026-06-24
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Add a `release-notes` subcommand to the daemon CLI and expose it through the
`/hooks-daemon` skill. Users (especially after an upgrade) want to read the
daemon's release notes without leaving the terminal — "what's in the version I
have?" and "what changed between my old version and now?".

The per-version `RELEASES/vX.Y.Z.md` files are present on every install (the
daemon ships as a git checkout, not a wheel), so the command reads them
directly — no new bundling, no network dependency. This mirrors the proven
`check-config-migrations` / `check-truth-changes` range-loader pattern.

An audit confirmed release-notes discipline is good: all 91 git tags
(v2.2.0 → v3.27.0) have matching `RELEASES/*.md` files. The one gap found is
`v3.12.0` missing from `CHANGELOG.md` (its `RELEASES/v3.12.0.md` exists). That
changelog gap is fixed as part of the release commit (CHANGELOG edits are
release-flow-only).

## Goals

- New pure module `install/release_notes.py` (TDD, 95%+ coverage) that loads and
  formats release notes from `RELEASES/` by exact version, range, latest, or list.
- New `cmd_release_notes` CLI handler + `release-notes` subparser in `daemon/cli.py`.
- Route `release-notes` through the `/hooks-daemon` skill (`daemon-cli.sh` forward).
- Document the new subcommand in SKILL.md.
- All QA green, daemon restart verified, acceptance tested.

## Non-Goals

- No bundling of CHANGELOG.md/RELEASES into a wheel (not how the daemon ships).
- No network/GitHub fetching (offline-first; reads the on-disk checkout).
- No new release-notes *generation* tooling — the release flow already creates them.

## Design

Module: `src/claude_code_hooks_daemon/install/release_notes.py`

- `_parse_version(str) -> tuple[int, ...]` (reuse sibling convention).
- `_default_releases_dir() -> Path` = `Path(__file__).parents[3] / "RELEASES"`
  (install/ -> pkg/ -> src/ -> project_root), overridable for tests.
- `RELEASE_FILE_PREFIX = "v"`, `RELEASE_FILE_SUFFIX = ".md"`, `_VERSION_PATTERN`.
- `@dataclass ReleaseNote{version: str, content: str, path: str}`.
- `list_known_release_versions(releases_dir=None) -> list[str]` (sorted).
- `load_release_note(version, releases_dir=None) -> ReleaseNote | None`.
- `load_release_notes_between(from_version, to_version, releases_dir=None)`
  -> `(from, to]` semantics (from excluded, to included) — matches siblings.
- `run_release_notes(version=None, from_version=None, to_version=None, list_versions=False, latest=False, current_version=None, output_format="markdown", releases_dir=None) -> dict[str, Any]`.

CLI args on `release-notes`:

- `--version VERSION` — notes for one version
- `--from VERSION --to VERSION` — range (from excluded, to included)
- `--list` — list available versions
- `--latest` — newest available version's notes
- `--format {markdown,json}` (default markdown)
- `--releases-dir PATH` (testing override)
- no args -> installed `__version__`

Exit codes: 0 success, 1 requested version not found, 2 bad args (from>to).

## Tasks

### Phase 1: TDD module

- [x] Write `tests/unit/install/test_release_notes.py` (RED).
- [x] Implement `install/release_notes.py` (GREEN).
- [x] Refactor; module coverage 99.35%.

### Phase 2: CLI wiring

- [x] Write `tests/unit/daemon/test_cli_release_notes.py` (RED) for `cmd_release_notes`.
- [x] Add `cmd_release_notes` handler + `release-notes` subparser in `daemon/cli.py` (GREEN).

### Phase 3: Skill route + docs

- [x] Add `release-notes` to the SKILL.md `daemon-cli.sh` forward case + document it.
- [x] No separate deployed skill copy — single source of truth under `src/`.

### Phase 4: Audit loop

- [x] `./scripts/qa/llm_qa.py all` green (13/13, 8986 tests, 95.1% coverage).
- [x] Daemon restart -> RUNNING.
- [x] code-reviewer agent: APPROVE, no blockers; two minor items fixed.
- [x] Live probe: `release-notes`, `--list`, `--version`, `--from/--to`, `--latest`, `--format json` all correct.

### Phase 5: Release

- [x] Fixed `v3.12.0` CHANGELOG.md gap within the release flow.
- [x] No `config-changes` manifest needed — feature adds no config key (always-on CLI subcommand).
- [x] Ran `/release` (minor) end-to-end; all blocking gates passed; shipped as v3.28.0.

## Success Criteria

- [ ] `release-notes` works for all modes; 95%+ coverage; QA 13/13.
- [ ] Daemon restarts RUNNING with the new subcommand registered.
- [ ] Released via `/release` with all gates passed.

## Notes & Updates

### 2026-06-24

- Plan created. Recovery cron `f4bd4799` (hourly :37, non-durable) created to
  guard the implement->audit->release loop. Delete on completion.
- Audit verdict: release-notes discipline GOOD (91/91 tags have RELEASES files);
  lone gap = v3.12.0 missing from CHANGELOG.md (fix folded into release).
- **Complete.** Delivered across commits `8a044fa` (feature + tests), `a995ff7`
  (code-review fixes), `6664328` (plan/README), and released as **v3.28.0**
  (release commit `fad2e4e`, tag `v3.28.0`). Code-review APPROVED; Opus doc review
  flagged one range-semantics wording inaccuracy (fixed). All release gates passed:
  QA 13/13 (8986 tests, 95.1% cov), 0 breaking changes, 0 handler files changed,
  Step 12.0 acceptance 23/23, live CLI + handler probes correct, artifact shas
  match manifest. Recovery cron `f4bd4799` deleted on completion.

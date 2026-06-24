# Plan 00141: `release-notes` CLI subcommand + skill route

**Status**: In Progress
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

- [ ] Write `tests/unit/install/test_release_notes.py` (RED): version parse, list,
  load single (hit/miss), range (incl/excl + from>to error), latest, default
  current_version, json + markdown formatting, missing dir.
- [ ] Implement `install/release_notes.py` (GREEN).
- [ ] Refactor; verify 95%+ coverage on the new module.

### Phase 2: CLI wiring

- [ ] Write `tests/unit/daemon/test_cli_release_notes.py` (RED) for `cmd_release_notes`.
- [ ] Add `cmd_release_notes` handler + `release-notes` subparser in `daemon/cli.py` (GREEN).

### Phase 3: Skill route + docs

- [ ] Add `release-notes` to the SKILL.md `daemon-cli.sh` forward case + document it.
- [ ] Mirror to deployed skill copy if separate (`.claude/skills/hooks-daemon`).

### Phase 4: Audit loop

- [ ] `./scripts/qa/llm_qa.py all` green (13/13).
- [ ] Daemon restart -> RUNNING.
- [ ] code-reviewer agent pass; fix findings.
- [ ] Live probe: `release-notes`, `--list`, `--version`, `--from/--to`, `--latest`, `--format json`.

### Phase 5: Release

- [ ] Fix `v3.12.0` CHANGELOG.md gap (within release flow).
- [ ] `config-changes/vX.Y.Z.yaml` (new opt-in feature -> recommended) staged in UNRELEASED.
- [ ] Run `/release` (minor) end-to-end through all blocking gates.

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

# Report: Task 3.2 implemented per RULING-3.2 (Plan 00488, GitHub #72)

Worktree: worktree-488-ruling. Commit says "Addresses #72"; nothing pushed or merged.

## What changed

- `init.sh` (`.claude/init.sh` is a symlink to it): `_hd_build_window_guidance` is defined once beside the bootstrap-state `case` and appended to the `started` and `running` remedies only. Text: keep to reads and ordinary edits; do not commit, push, delete branches or touch protected files; no guard is judging these calls. The gate, both encoders and the Stop behaviour are untouched, so allow/deny is unchanged.
- Tests (written first, RED confirmed): new class `TestTheBuildWindowStaysFailOpenButTellsTheAgentHowToBehave` in `tests/integration/test_init_sh_venv_self_heal.py`. started and running carry the line and the PreToolUse output has no `permissionDecision`; failed, refused and disabled do not carry it.
- Docs: new section "The venv build window is a declared fail-open" in `CLAUDE/Security/FailOpenBoundaries.md` (the one canonical home, cites the ruling); `CLAUDE/ARCHITECTURE.md` names "a venv build under way" among the setup states.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/024-venv-build-window-tells-the-agent-what-to-avoid.md`.
- `PLAN.md` Task 3.2 ticked "implemented per RULING-3.2 (coordinator ruling, Fable-assisted)".

## Deviations from the outline

- The test went into `test_init_sh_venv_self_heal.py`, not `test_init_sh_status_down_text.py`: that file already has the PreToolUse `additionalContext` helper and the started/running drivers.
- No row added to `scripts/qa/fail-open-boundaries.yaml`: its rows are keyed on suppression constructs (`2>/dev/null`, `except Exception`) and the VENV_MISSING branch has no such construct, so there is nothing to point at the ruling.

## Verification

- pytest: the five init.sh integration modules touched or adjacent (self_heal, venv_missing_message, status_down_text, pretooluse_fail_closed, fail_open_valid_for_every_event): 254 passed.
- shellcheck init.sh: clean.

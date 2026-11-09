# Report: issue #174, hooks-screen target by host architecture

## RED (before the fix)

`pytest tests/unit/supervise/test_screen_focus_check.py`: 13 failed, 47 passed.

- `TypeError: resolve_screen_binary() got an unexpected keyword argument 'machine'` (3 resolver tests)
- `AttributeError: module 'claude_supervise_standalone' has no attribute 'screen_target_triple'` (6 mapping tests)
- `AttributeError: ... has no attribute 'platform'` (default-reads-platform test)
- `AttributeError: ... has no attribute 'screen_binary_missing_note'` (2 note tests)
- `TypeError: ScreenFocusCheck.__init__() got an unexpected keyword argument 'missing_note'`

## GREEN

Same file: 60 passed. `shellcheck screen/build.sh` clean. `build.sh` with a stubbed
`uname` returning riscv64 exits 1 with "set SCREEN_TARGET=<triple>".

## Changes

- `.claude/ccy/claude-supervise.py`: `screen_target_triple(machine=None)` (x86_64/amd64,
  aarch64/arm64, else None; defaults to `platform.machine()`), `screen_binary_missing_note`,
  `resolve_screen_binary(..., machine=None)` skips the build-output candidate on an unsupported
  arch, `ScreenFocusCheck(missing_note=...)` wired from the factory. Order and fail-open unchanged.
- `screen/build.sh`: SCREEN_TARGET defaults from `uname -m`, unknown arch exits 1.
- `screen/VENDORED.md` (mdformat also turned the indented code block into a fence), 
  `CLAUDE/development/CcySupervisor.md`, release note `003-...`.
- Test edit: the existing `test_deployed_path_then_built_path` now passes `machine="x86_64"`,
  since it stubs an x86_64 build and would otherwise fail on an aarch64 host.
- `tests/unit/screen/test_hooks_screen_binary.py` untouched (x86_64 by design).
- No worker process killed; worktree edit does not touch the live session.

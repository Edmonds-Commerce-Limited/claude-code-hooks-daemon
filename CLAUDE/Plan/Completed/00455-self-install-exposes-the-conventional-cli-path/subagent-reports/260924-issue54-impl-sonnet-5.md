# Plan 00455 / Issue #54 implementation report — Sonnet 5

**Worktree**: `worktree-issue-54-cli-path` (branch `worktree-issue-54-cli-path`)
**Scope**: Phase 1 (TDD in the worktree). Phase 2 (merge, restart the main
checkout's daemon, close #54) is explicitly out of scope for this report —
the owner's/team-lead's step.

## Summary

Every Phase 1 task is done, each change made RED-then-GREEN with its own
test. No part of the brief's design was found wrong; the audit surfaced one
additional real hazard (`install.py`'s standalone duplicate of the
parent-installation check) and one unrelated dead-parameter bug
(`ensure_normal_mode_only`), both fixed and tested. Full QA
(`./scripts/qa/llm_qa.py all`) passed 35/35 twice, `QA_EXIT=0`. The
worktree's own daemon was restarted; the conventional path
(`.claude/hooks-daemon/bin/hooks-daemon`) exists, resolves, and manages the
same running daemon as `bin/hooks-daemon` when called from a different cwd.

## T1.3 — the daemon creates the symlink at startup

`_ensure_self_install_cli_symlink(project_root)` in
`src/claude_code_hooks_daemon/core/project_context.py`, called from
`ProjectContext.initialize()`'s self-install branch. That is the single
chokepoint every daemon-adjacent process already passes through exactly
once (guarded by `ProjectContext._initialized`) — both the persistent
daemon controller's own startup (`daemon/controller.py:260`) and every CLI
invocation that resolves a project (`daemon/cli.py`'s `_validate_installation`,
called from `get_project_path`) — so no second call site was needed for
either the main checkout or a worktree.

Behaviour:

- Target: `Path("../../../bin/hooks-daemon")`, relative — correct regardless
  of where the checkout lives, survives being moved or re-cloned.
- Idempotent: `link_path.is_symlink() or link_path.exists()` short-circuits
  before ever calling `symlink_to` — a pre-existing symlink (this link from
  a prior run) or ANY real file/directory at that path is left untouched.
  Never replaces a non-symlink, as required.
- Only fires when `self_install_mode` is True (the existing
  `daemon_src_at_root` check, independent of `.claude/hooks-daemon.yaml`'s
  own `self_install_mode` config flag — a pre-existing, deliberate split I
  did not touch).
- A failure to create it (`OSError`) is caught narrowly and logged at
  WARNING, not raised — this is a best-effort convenience, not a
  precondition for the daemon to serve hooks.

Tests: `tests/unit/core/test_project_context.py::TestSelfInstallCliSymlink`
(5 cases: creates it, relative target, never fires in normal mode, idempotent
on a pre-existing symlink, never replaces a real file).

## T1.1/T1.2 — mode_guard.sh re-keyed, plus a side-finding fix

`scripts/install/mode_guard.sh`'s `detect_self_install_mode` had `! -d "$project_root/.claude/hooks-daemon"` as its third indicator — true the
moment the generated symlink's directory exists, which would flip
`get_install_mode` from `self-install` to `normal` and silence
`ensure_normal_mode_only` (the guard stopping `install.sh`/`upgrade.sh`
running inside this repo). Added `_is_real_daemon_clone()` (checks
`pyproject.toml` under the candidate dir — the same discriminator the
Python side uses) and re-keyed the third indicator on it.

**Side finding, fixed**: `ensure_normal_mode_only` accepted `$1` in its
signature comment but the body read `"${PROJECT_ROOT:-$(pwd)}"`, silently
discarding the argument. Both call sites
(`scripts/install_version.sh:316`, `scripts/upgrade_version.sh:246`) pass
`"$DAEMON_DIR"`, which happens to equal `$PROJECT_ROOT` in the one case this
function is meant to fire (self-install mode, where `get_daemon_dir`
returns `project_root` verbatim) — so this was not observably wrong, but a
dead parameter that could silently start being wrong on any future refactor.
Fixed: the function now honours `${1:-${PROJECT_ROOT:-$(pwd)}}`, and both
callers now pass `"$PROJECT_ROOT"` — the argument the question is actually
about (self-install IS the project checkout) — instead of `"$DAEMON_DIR"`.

Tests: `tests/integration/test_mode_guard_self_install_detection.py` (7
cases: the original positive case still holds, the link-only marker no
longer flips the mode, a real client clone still reports `normal`, a bare
project reports `normal`, `ensure_normal_mode_only` aborts/allows correctly
with the marker/a real clone present, and the positional-argument regression
case with no `$PROJECT_ROOT` global set at all).

## T1.2 — Python: `validate_installation_target`'s parent-installation walk

`daemon/validation.py` and its standalone duplicate `install.py` (kept
non-importing on purpose — see its own deprecation notice — so the fix is
duplicated there too, matching the existing duplication of
`is_hooks_daemon_repo`/`project_root_is_daemon_repo`) both walk
`project_root.parents` and raised whenever `(parent / ".claude" / "hooks-daemon").exists()`. A worktree or client-mode test
fixture living under this repo would trip that the moment the main
checkout's daemon (or this worktree's own) creates the generated symlink.
Fixed by requiring `project_root_is_daemon_repo(candidate)` /
`_project_root_is_daemon_repo(candidate)` in addition to existence — reusing
the existing pyproject.toml discriminator rather than inventing a new one.

`check_for_nested_installation` (the `.claude/hooks-daemon/.claude/hooks-daemon`
check) already had the right exemption (outer `pyproject.toml` present) and
needed no change — traced through why: it fires only when a REAL clone's own
dogfooded `.claude/` tree, or a link-only marker created by someone running
the self-install daemon directly inside a client clone's inner checkout,
produces that path; in both cases the outer directory has `pyproject.toml`
(a real clone) and the existing exemption already covers it.

Tests: extended `tests/unit/daemon/test_validation.py` and
`tests/unit/test_install.py`'s `TestValidateInstallationTarget` — the
existing `test_raises_for_inside_existing_installation` fixture was itself
the bug's blind spot (an empty directory, no `pyproject.toml`, which is
exactly the shape the old code treated as "installed"), fixed to create a
real clone marker, plus a new test asserting a link-only marker in a parent
does NOT raise.

## T1.2 — init.sh's nested-install check had no exemption at all

`init.sh:445` refuses when `.claude/hooks-daemon/.claude/hooks-daemon`
exists, with no exemption whatsoever — unlike `validation.py`'s equivalent.
This matters because `init.sh` runs on **every hook event for every
client**: a developer running the self-install daemon directly inside a
CLIENT clone's own inner checkout (`<client>/.claude/hooks-daemon/`, itself
a full self-install-capable checkout) would create exactly that nested
path as a link-only marker, and an unexempted `init.sh` would then refuse
every hook for that whole client project. Fixed by mirroring the Python
side's exemption: skip the refusal when
`.claude/hooks-daemon/pyproject.toml` exists (the outer directory is itself
a real clone).

Tests: `tests/integration/test_init_sh_nested_install_link_only.py` (4
cases: the link-only marker is exempt — the RED case; a genuine nested
clone with no outer `pyproject.toml` is still refused — negative direction;
the refusal still exits 0, fail-open; and the common case, nothing nested
at all, is never refused). Ran alongside the existing
`test_init_sh_repo_guard.py` to confirm no regression there.

## Sites audited and judged safe — each pinned with a regression test

- **`daemon/cli.py:333`** (`hooks_daemon_dir.is_dir()`, only reached `if not self_install`): `self_install` there is read from the CONFIG file's
  `daemon.self_install_mode` flag, never from `.claude/hooks-daemon/`
  existing — the generated symlink cannot flip it. Test:
  `tests/unit/daemon/test_cli_self_install.py::TestValidationUnaffectedByTheGeneratedCliSymlink`.
- **`scripts/install/project_detection.sh`**: `detect_project_root`'s
  fallback signal requires `.claude/hooks-daemon/.git` — a link-only marker
  has no `.git` at all. `detect_install_mode` reads
  `daemon.self_install_mode` out of the config file and never inspects
  `.claude/hooks-daemon/`. Neither needed a code change. Test:
  `tests/integration/test_project_detection_sh_link_only_marker.py` (4
  cases, including the negative direction — a real clone's `.git` still
  satisfies the fallback, and a config saying `false` still reports
  `normal` despite a real clone present).
- **`src/claude_code_hooks_daemon/install/client_validator.py`** (4 sites
  checking `.claude/hooks-daemon/` existence): this module validates a
  just-COMPLETED normal install's `project_root`, which is always the
  CLIENT's project — never a self-install checkout, because
  `ensure_normal_mode_only` already stops install/upgrade scripts running
  inside a self-install repo before this module is ever reached. Not
  reachable in the scenario this plan is about; no test added (would be
  testing an unreachable path).
- **`daemon/paths.py`'s `_get_untracked_dir`, `get_socket_path`'s callers,
  `prospective_socket_path`, and the `.claude/hooks-daemon/untracked` path
  constructions in `daemon/cli.py`/`debug_info.py`**: these build a path
  STRING inside a branch the CALLER already decided (either
  `project_path/"src"/"claude_code_hooks_daemon").is_dir()` — the same
  discriminator `ProjectContext` uses, unrelated to `.claude/hooks-daemon`
  — or an explicit `self_install: bool` parameter). None of them are
  existence-checks on `.claude/hooks-daemon/` itself.

## Behaviour change worth flagging (not a bug)

`cmd_housekeeping`'s `client_wrapper.is_file()` check
(`daemon/cli.py:7048`) will now find the generated symlink `is_file()`-true
once a self-install daemon has started at least once, so the housekeeping
procedure will print the conventional `.claude/hooks-daemon/bin/hooks-daemon`
path instead of falling back to `bin/hooks-daemon` in a self-install
checkout. This looks like the intended direction of this plan (uniform
command shown regardless of install mode) rather than a regression, but
flagging it explicitly since it is an observable output change nobody asked
for by name. `test_self_install_falls_back_to_the_repo_wrapper` is
unaffected — its `tmp_path` fixture never runs `ProjectContext.initialize`,
so no real symlink exists there.

## QA fixups (all committed separately from the real changes)

- black auto-reformatted the 7 new/edited test files (committed as-is).
- ruff `PTH115`: `Path.readlink()` instead of `os.readlink()` in the new
  symlink test; dropped the now-unused `os` import.
- `scripts/qa/error_hiding_exclusions.json`: added a function-keyed entry
  for `_ensure_self_install_cli_symlink`'s narrow `except OSError`
  log-and-continue (best-effort convenience, explicitly logged, not a
  startup precondition) — following the file's own stated preference for
  `function` over `lines` keys. Also realigned two PRE-EXISTING
  `upgrade_version.sh` exclusion entries whose line numbers drifted +3
  because of the `ensure_normal_mode_only` comment I added above them
  (reported by the audit as `stale-exclusion`) — the underlying patterns
  are unchanged, only their location moved.
- The release note's `**Audience**` field must be a single enum value
  (`operators | handler authors | client projects | everyone` in the
  schema doc is the SET of allowed values, not literal pipe-join syntax) —
  fixed to `handler authors`.
- `SELF_INSTALL.md`'s new symlink diagram needed an explicit ```` ```text ````
  fence: an untagged fence is scanned as shell by
  `test_documented_commands_are_not_self_denied`, and the diagram line
  (`.claude/hooks-daemon/bin/hooks-daemon -> ../../../bin/hooks-daemon`)
  read as a command whose target resolves outside the repo, denied by this
  project's own `project_containment` handler.

## Verification performed in this worktree

- `./scripts/qa/llm_qa.py all` run twice: 35/35 PASSED both times,
  `QA_EXIT=0` on the explicit-capture run. (The first clean run's
  35/35 was interrupted mid-run by a daemon restart taken for the second
  run's sake — the daemon warned about exactly this and the restart was
  taken anyway per the brief's instruction to verify end-to-end; the
  restart did not corrupt the SECOND run's own result, which also came
  back 35/35.)
- Restarted the worktree's own daemon (`./bin/hooks-daemon restart`);
  `health` reports HEALTHY, 144 handlers registered, hook registration OK,
  project handlers OK.
- `.claude/hooks-daemon/bin/hooks-daemon` exists, `readlink` reports
  `../../../bin/hooks-daemon`.
- Called `.claude/hooks-daemon/bin/hooks-daemon status` from `/tmp` (a
  different cwd): reported the SAME PID and the SAME socket path as
  `./bin/hooks-daemon status` run from the worktree root.

## Commits on `worktree-issue-54-cli-path`

Ten commits, each scoped to one RED/GREEN pair or one audit-pin, plus one
QA-fixup commit — `git log worktree-issue-54-cli-path` from this worktree
shows the full sequence and messages.

## Not done here (explicitly out of scope per the brief)

- Merge to `main`, verifying ancestry and CI (Task 2.1).
- Restarting the MAIN checkout's daemon.
- Commenting on and closing GitHub issue #54 (Task 2.2).

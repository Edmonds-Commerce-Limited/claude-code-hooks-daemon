# Hooks Daemon Install — Issues Found

Report from installing `claude-code-hooks-daemon` into this project
(`/workspace`, php-qa-ci, branch `php8.4`). Covers a wrong-org dead URL, a
stale hardcoded version, a real installer bug that blocks the documented
manual-install path, and a permissions bug that force-marks documentation
files as executable. Nothing here has been fixed upstream — this is a bug
report to hand to the `Edmonds-Commerce-Limited/claude-code-hooks-daemon`
maintainers (or file as GitHub issues).

## 1. Dead URL: wrong GitHub org in `scripts/deploy-skills.bash`

**File**: `scripts/deploy-skills.bash:587,591` (this repo, already fixed locally)

The fallback "how to install hooks-daemon" message pointed at:

```
https://github.com/anthropics/claude-code-hooks-daemon
```

That org/repo returns **404**. The correct repo, used correctly elsewhere in
the very same file (line 411) and confirmed reachable (**200**), is:

```
https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon
```

Same file also referenced a nonexistent installer path:

```
./scripts/install/install.bash
```

No such path exists in the daemon repo at any installed version. The real
entry point is `install.py` (manual flow) or `install.sh` (recommended
two-layer bootstrap).

**Status**: fixed locally in this repo's `scripts/deploy-skills.bash` this
session — org corrected, install command corrected to reference the venv +
`install.py` sequence.

## 2. Stale hardcoded version (v2.2.0 vs actual latest v3.41.0)

Same file hardcoded a version pin:

```
git clone -b v2.2.0 https://github.com/anthropics/claude-code-hooks-daemon.git .claude/hooks-daemon
```

`v2.2.0` was 39 releases behind the actual latest at the time of writing
(`v3.41.0`, confirmed via `gh`/GitHub API `releases/latest`, tag_name
`v3.41.0`, `draft: false`, `prerelease: false`). Following this instruction
literally installs a two-year-stale daemon with roughly a third of the
current handler count (33 handlers at v2.2.0 vs 60+ at v3.41.0) and none of
the newer safety/workflow handlers (e.g. `daemon_location_guard`,
`error_hiding_blocker`, `security_antipattern`, `qa_suppression`,
`tdd_enforcement`, the whole planning-workflow handler family).

**Root cause class**: a version number was hand-copied into a doc/script at
some point and never updated as the upstream project released. Any doc or
script that hardcodes a specific tag rather than resolving "latest" at
install time will silently rot this way.

**Recommendation**: never hardcode a tag in install instructions/scripts.
Either omit the `-b <tag>` entirely (clone default branch, which install.sh
does — `DAEMON_BRANCH="${DAEMON_BRANCH:-main}"`), or resolve latest
dynamically (`git fetch --tags && git describe --tags --abbrev=0`), which is
exactly what the daemon's own `CLAUDE/LLM-INSTALL.md` "Manual Install" step 2
already does correctly — the bug was only in this consumer repo's derived
copy of the instructions.

## 3. Real bug: `install.py` manual flow can't succeed for a normal consumer install

**File** (in the daemon repo, `Edmonds-Commerce-Limited/claude-code-hooks-daemon` at `v3.41.0`):
`src/claude_code_hooks_daemon/daemon/validation.py:120-152`, function `validate_not_nested()`

```python
hooks_daemon_marker = project_root / ".claude" / "hooks-daemon" / "src"
if hooks_daemon_marker.exists():
    ...
    raise InstallationError(
        f"Cannot install: appears to be inside an existing hooks-daemon installation.\n"
        f"Found daemon source at: {hooks_daemon_marker}\n"
        f"To develop on hooks-daemon itself, set 'self_install_mode: true' in config."
    )
```

This fires whenever `{project_root}/.claude/hooks-daemon/src` exists. But the
daemon's own documented **Manual Install** flow
(`CLAUDE/LLM-INSTALL.md`, "Manual Install (6 Steps)") is:

1. `git clone ... .claude/hooks-daemon`
2. `cd .claude/hooks-daemon && python3 -m venv untracked/venv && untracked/venv/bin/pip install -e .`
3. `untracked/venv/bin/python install.py` (optionally `--project-root /workspace`)

Step 1 unconditionally creates `.claude/hooks-daemon/src` (it's the package
source tree checked into the repo) *before* step 3 ever runs. So the marker
this check tests for is present on **every single fresh manual install**,
by construction of the documented steps — not just in some edge case. The
check cannot distinguish "consumer project that just cloned the daemon as a
dependency" (the intended, documented use) from "someone using the daemon
repo itself as project root" (the actual scenario the check is meant to
catch).

**Reproduced twice in this session**:

- `install.py` run with cwd `.claude/hooks-daemon` (no `--project-root`):
  auto-detected project root as `.claude/hooks-daemon` itself (picking up
  the daemon repo's own dogfooding `.claude/` dir), then failed a *different*
  nested-install check one level up (`project_root.parents` walk in
  `validate_installation_target`) with "is inside an existing installation
  at /workspace".
- `install.py --project-root /workspace`: hit the bug described above
  directly — "Cannot install: appears to be inside an existing hooks-daemon
  installation. Found daemon source at: /workspace/.claude/hooks-daemon/src".

**Workaround used**: abandoned the manual `install.py` flow entirely and used
the "Quick Install (Recommended)" `install.sh` two-layer bootstrap instead,
which does not hit this check (it takes a different, non-`install.py`
path — `scripts/install_version.sh` — for current-version installs). This
succeeded cleanly.

**Recommendation for upstream**: either (a) drop this check entirely now
that `install.sh`/Layer-2 is the recommended path and `install.py` is
legacy/fallback-only, or (b) scope the check to something that actually
distinguishes "project root IS the daemon repo" (e.g. check for
`project_root/pyproject.toml` naming this package, as `is_hooks_daemon_repo()`
already does elsewhere in the same file) rather than "a clone of the daemon
happens to exist under project_root/.claude/".

## 4. Permissions bug: installer force-marks non-script files executable

**Files** (daemon repo, `v3.41.0`): `scripts/install/hooks_deploy.sh`

Two functions are responsible for setting/forcing the executable bit on
files deployed to `.claude/hooks/`:

- `set_hook_permissions()` — line 177:
  ```bash
  hook_files=$(find "$hooks_dir" -maxdepth 1 -type f ! -name ".*")
  ```
- `git_force_executable()` — line 255 (same find pattern), which then runs
  `git update-index --chmod=+x` per file (line 263) and reports the count
  (line 288, `"Forced executable bit in git index for N files"`).

Both use `find "$hooks_dir" -maxdepth 1 -type f ! -name ".*"` — i.e. *every*
non-dotfile regular file directly inside `.claude/hooks/`, with no filter for
"is this actually one of the hook entrypoints this installer deploys"
(`pre-tool-use`, `post-tool-use`, `session-start`, etc.).

This project's `.claude/hooks/` already contained non-script files from an
earlier, unrelated hook deployment (php-qa-ci's own Claude Code hooks):
`.claude/hooks/CLAUDE.md`, `.claude/hooks/README.md`,
`.claude/hooks/test-all-hooks.sh` (a helper script, arguably fine to be +x,
but not one of the daemon's own hooks either).

**Observed result** (this repo, this session):

```
$ git ls-files -s .claude/hooks/CLAUDE.md .claude/hooks/README.md
100755 2376feb90745eb56af9f7fd2f723be2a5b7b0f5d 0	.claude/hooks/CLAUDE.md
100755 3d38dbe7cc24ffcfbc0dd2c67f64894cd93d759e 0	.claude/hooks/README.md
```

Both plain Markdown docs were chmod +x'd on disk *and* had the executable
bit force-written into the git index via `update-index --chmod=+x`, so `git
status` shows them as staged modifications even though their content is
byte-for-byte unchanged — purely a mode-bit diff. Harmless in effect (git
still shows them as text files, they're not actually invoked as scripts) but
sloppy: it pollutes `git diff`/`git status` with content-free noise for any
consumer project that has non-script files sitting alongside its hooks, and
will keep re-firing on every daemon reinstall/upgrade.

**Recommendation for upstream**: filter the `find` to the actual set of
hook entrypoints the installer manages (a known list, or at minimum
`! -name "*.md"` / an executable-check before force-chmod), rather than
"every regular file in the directory".

## Summary table

| # | Issue | Location | Severity | Status |
|---|-------|----------|----------|--------|
| 1 | Dead URL, wrong GitHub org | `scripts/deploy-skills.bash:587,591` (this repo) | Low (docs) | Fixed locally this session |
| 2 | Hardcoded stale version (v2.2.0 vs v3.41.0) | `scripts/deploy-skills.bash:587` (this repo) | Medium (silently installs a ~2yr-stale daemon) | Fixed locally this session (now generic, no pinned tag) |
| 3 | `install.py` nested-install false positive blocks the documented manual-install flow | `validation.py:120-152` (upstream daemon repo) | High (documented path cannot succeed) | Worked around via `install.sh`; not fixed upstream |
| 4 | Force-chmod +x on non-hook files (docs) in `.claude/hooks/` | `scripts/install/hooks_deploy.sh:177,255` (upstream daemon repo) | Low (cosmetic git noise) | Not fixed upstream |

Issues 3 and 4 live in the upstream `Edmonds-Commerce-Limited/claude-code-hooks-daemon`
repository, not this one — worth filing as GitHub issues there
(https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/new)
if the user wants them tracked/fixed upstream.

# Plan 00362 Task 1.3: echd-capture is deployed to clients

Report section 3: the injected `pipe_blocker` guidance told agents to run
`... | echd-capture 20`, but nothing had put that helper on a client's path,
so the client saw `echd-capture: command not found`.

## What was done

This picks up a previous agent's uncommitted work in the worktree and
finishes it. The resulting change:

- `scripts/echd-capture` moved (git rename) to
  `src/claude_code_hooks_daemon/install/templates/echd-capture` and is
  bundled as package data, so wheel installs carry it (verified by building
  a wheel and listing its contents).
- `install.bin_wrapper.deploy_echd_capture` copies the template to
  `{daemon_root}/bin/echd-capture` with mode 0755, sharing one private
  deployer with the CLI wrapper. `install_version.sh` step 10b and
  `upgrade_version.sh` step 13b call it, so both fresh installs and upgrades
  of older installs receive the helper. `hooks_deploy.sh` keeps its
  belt-and-braces chmod, now pointed at `bin/`.
- `utils.cli_command.echd_capture_path` (absolute, for block reasons) and
  `echd_capture_path_for_docs` (project-relative, for the tracked CLAUDE.md
  guidance) own the location; `pipe_blocker` reads both.
- `pipe_blocker.get_claude_md` renders one of two branches at render time.
  When the deployed helper exists it names it by project-relative path and
  says it is not on `PATH`. When it does not resolve, the redirect-to-file
  recipe is the only path and the helper is not mentioned at all.
- `ClientInstallValidator.validate_post_install` gains a check that warns
  (not errors) when the helper is missing or not executable.
- `bin/echd-capture` is added as this self-install repo's own deployed copy,
  beside the already-tracked `bin/hooks-daemon`, with a test that pins it
  to the template so it cannot drift.

## What was left alone

- The auto-generated hooks-daemon section of `CLAUDE.md` still shows the
  old `/…/scripts/echd-capture` example. It regenerates on daemon restart,
  which this task was told not to perform.
- Historical mentions of `scripts/echd-capture` in `CHANGELOG.md`,
  `RELEASES/v3.41.0.md` and completed plans are records, not references.
  Nothing live points at the old path, so no symlink was needed.

## Verification

- The eight touched test files pass in the worktree venv
  (`untracked/venv-wt`, built with `uv sync --frozen --extra dev`).
- ruff check and ruff format are clean on touched Python; mypy --strict is
  clean on the five touched source modules.
- shellcheck on the three touched shell scripts and the template reports only
  the pre-existing SC1091 "not following sourced file" info notes.

## Release-bound consequence

Callout `CLAUDE/UPGRADES/UNRELEASED/release-notes/17-echd-capture-is-deployed-to-clients.md`.

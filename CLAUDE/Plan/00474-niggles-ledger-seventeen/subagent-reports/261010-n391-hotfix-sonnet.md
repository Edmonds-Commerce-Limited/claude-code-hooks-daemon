# N391 hotfix: gitignored files are not scanned

- Reused `claude_code_hooks_daemon.utils.git_repo.git_visible_paths` (tracked plus not-ignored, protected paths removed;
  `None` outside a git repo, so non-git fixture trees still scan everything). `scan_scope` has no gitignore-aware walk.
- `scripts/qa/check_install_mode_marker.py::_candidate_files` now keeps only visible paths.
- Red first: `test_gitignored_files_are_not_project_code` failed with the extra item `.claude/ccy/file-history/x@v1`
  (a first draft with a Python snapshot passed vacuously, since extensionless non-shebang files are not read as Python;
  the snapshot is a shebang shell script). Green after the change; the whole file passes (86 tests).
- `--path /workspace` (read-only): 0 violations, 2509 files scanned.

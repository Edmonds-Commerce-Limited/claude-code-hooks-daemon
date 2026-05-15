# Upgrade Hooks Daemon

Upgrade the Claude Code Hooks Daemon and commit the result atomically.

## Agent Workflow

1. **Run the upgrade**:

   ```bash
   /hooks-daemon upgrade           # latest
   /hooks-daemon upgrade 3.14.0    # specific version
   /hooks-daemon upgrade --force   # reinstall current
   ```

2. **Parse the metadata block** emitted on stdout between the
   `<<<UPGRADE_METADATA` and `UPGRADE_METADATA>>>` sentinels. Fields:
   `from_version`, `to_version`, `python_version`, `python_path`,
   `venv_path`, `host`, `daemon_dir`, `project_root`, `modified_files`,
   `config_diff_summary`.

3. **Verify daemon RUNNING**:

   ```bash
   $PYTHON -m claude_code_hooks_daemon.daemon.cli status
   ```

4. **Stage daemon-owned paths ONLY** with explicit `git add` — other
   working-tree changes are not part of this commit. Never `git add .`:

   ```bash
   git add .claude/hooks-daemon/ .claude/hooks-daemon.yaml \
           .claude/skills/hooks-daemon/ .claude/hooks/ \
           .claude/settings.json
   ```

5. **Commit** with the metadata block in the body:

   ```
   hooks daemon upgrade: ${from_version} → ${to_version}

   <<<UPGRADE_METADATA
   from_version=...
   to_version=...
   python_version=...
   python_path=...
   venv_path=...
   host=...
   daemon_dir=...
   project_root=...
   modified_files=...
   config_diff_summary=...
   UPGRADE_METADATA>>>
   ```

If the daemon is not RUNNING after upgrade, do NOT commit — investigate
first (`$PYTHON -m claude_code_hooks_daemon.daemon.cli logs`).

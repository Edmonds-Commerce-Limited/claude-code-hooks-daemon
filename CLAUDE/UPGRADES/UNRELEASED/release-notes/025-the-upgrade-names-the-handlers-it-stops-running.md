# The upgrade names every handler it stops or starts running, and a remedy for projects already upgraded

**Plan**: 00493
**Audience**: operators

Since v3.68.0 a handler with no block under `handlers.<event>` runs only if it is on by default. A project whose config omits an opt-in handler lost it on that upgrade, under a config file that had not changed, and nothing said which handlers. The upgrade now resolves your actual config under the old and the new rules and prints every handler that stops or starts running, with a snippet that restores them. `config_diff_summary` also reads the backup the installer really writes, so it no longer says "no config changes" when the file or the effective handler set changed. The upgrade summary names the daemon version change (from to), and the metadata block carries a `handler_changes` field.

The seventeen opt-in handlers are counted correctly now: `plan_fact_check_feed` was missing from the earlier lists.

**If you already upgraded to v3.68.0 or later and a handler you relied on went quiet:**

1. Run `.claude/hooks-daemon/bin/hooks-daemon optimise-checklist` and read the rows marked `[default off]`.

2. For each one the project wants, add its block to `.claude/hooks-daemon.yaml`:

   ```yaml
   handlers:
     session_start:
       session_actions_directive:
         enabled: true
   ```

3. Restart: `.claude/hooks-daemon/bin/hooks-daemon restart`.

Name only the handlers you want. Several are noisy, and four deny tool calls (`flaggable_content_channel_guard`, `quarantine_artefact_read_guard`, `subagent_full_qa_blocker`, `lsp_enforcement`). To see what an upgrade would change for your config, run `.claude/hooks-daemon/bin/hooks-daemon check-effective-handlers --from <old> --to <new>`.

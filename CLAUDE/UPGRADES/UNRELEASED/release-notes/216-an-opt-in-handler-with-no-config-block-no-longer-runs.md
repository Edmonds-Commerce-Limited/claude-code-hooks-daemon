# Callout: an opt-in handler with no config block no longer runs

**Plan**: 00483
**Audience**: client projects

A handler that declares itself opt-in (`default_enabled = False`) now stays off when `.claude/hooks-daemon.yaml` has no block for it. Before, the registry treated an absent block as enabled, so a project written by `init minimal` (which emits `pre_tool_use: {}` and the same for every event) ran all of them, including three that deny tool calls. A block that is present is enabled unless it says `enabled: false`, so naming a handler, even as a bare `key:`, turns it on. An opt-out handler with no block still runs.

The sixteen opt-in handlers are `lsp_enforcement`, `flaggable_content_channel_guard`, `flaggable_work_advisor`, `quarantine_artefact_read_guard`, `subagent_full_qa_blocker`, `goal_injection`, `compaction_signal`, `model_fallback_detector`, `routine_qa_sweep`, `session_actions_directive`, `skill_opportunity_detector`, `tool_disable_advisor`, `context_sidecar`, `daemon_stats`, `host_hostname` and `idle_housekeeping_advisory`. `init full` configs already carry `enabled: false` for each, so are unaffected. If your config omitted one and you relied on it running, add its block with `enabled: true`. The generated handler docs, the playbook and the config-optimisation checklist now agree with what the daemon registers.

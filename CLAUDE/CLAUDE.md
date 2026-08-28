# CLAUDE Directory - LLM-Optimized Documentation

This directory is the **agent tree**: verbose, information-dense documentation
that owns the depth for every fact. The audience split (agent tree vs human
`docs/` tree) is defined in [DocumentationStrategy.md](DocumentationStrategy.md)
— the canonical documentation-SSoT ruleset.

## Routing Table

| File                                                                   | Route here for                                                                      |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| [DocumentationStrategy.md](DocumentationStrategy.md)                   | The documentation-SSoT rules: one canonical home per fact, satellite contracts      |
| [ARCHITECTURE.md](ARCHITECTURE.md)                                     | System architecture and design decisions                                            |
| [AgentTeam.md](AgentTeam.md)                                           | Agent team execution workflow                                                       |
| [DEBUGGING_HOOKS.md](DEBUGGING_HOOKS.md)                               | Capturing hook event flows (`scripts/debug_hooks.sh`) before writing handlers       |
| [DEBUGGING_STOP_HOOK.md](DEBUGGING_STOP_HOOK.md)                       | Diagnosing stop-hook failures to block                                              |
| [DEBUGGING_TRANSCRIPTS.md](DEBUGGING_TRANSCRIPTS.md)                   | Post-mortem debugging via session transcripts                                       |
| [HANDLER_DEVELOPMENT.md](HANDLER_DEVELOPMENT.md)                       | Creating new handlers: lifecycle, API, testing patterns                             |
| [HANDLER_GROUPING_AND_EXPANSION.md](HANDLER_GROUPING_AND_EXPANSION.md) | Handler grouping and language-specific expansion design                             |
| [LLM-INSTALL.md](LLM-INSTALL.md)                                       | Fresh installation into a project                                                   |
| [LLM-UPDATE.md](LLM-UPDATE.md)                                         | Updating an existing installation                                                   |
| [PROJECT_HANDLERS.md](PROJECT_HANDLERS.md)                             | Project-level handler developer guide                                               |
| [PlanJournalling.md](PlanJournalling.md)                               | Per-plan journalling reference                                                      |
| [PlanWorkflow.md](PlanWorkflow.md)                                     | Planning workflow, templates, and standards                                         |
| [QA.md](QA.md)                                                         | The QA pipeline — source of truth for QA workflow                                   |
| [SELF_INSTALL.md](SELF_INSTALL.md)                                     | Self-install (dogfood) mode guide                                                   |
| [Worktree.md](Worktree.md)                                             | Git worktree workflow                                                               |
| [AcceptanceTests/](AcceptanceTests/GENERATING.md)                      | Acceptance test generation and validation                                           |
| [Architecture/](Architecture/StatusLine.md)                            | Component deep-dives (status line)                                                  |
| [Code/](Code/HooksSystem.md)                                           | Hooks system internals                                                              |
| [CodeLifecycle/](CodeLifecycle/README.md)                              | Mandatory lifecycles: features, bugs, general changes                               |
| [Performance/](Performance/README.md)                                  | Performance baselines and measurements                                              |
| [Plan/](Plan/README.md)                                                | Numbered development plans (see [Plan/CLAUDE.md](Plan/CLAUDE.md) for lifecycle)     |
| [UPGRADES/](UPGRADES/README.md)                                        | Version upgrade guides, truth-changes and config-changes manifests                  |
| [development/](development/CLAUDE.md)                                  | Daemon-repo contributor docs (QA patterns, releasing, lessons, client-mode testing) |

Troubleshooting and bug reporting live at the repo root:
[../BUG_REPORTING.md](../BUG_REPORTING.md).

## What NOT to Put Here

- ❌ Human-focused guides (use README.md or docs/)
- ❌ API documentation (use docstrings)
- ❌ Configuration examples (use examples/)
- ❌ Internal development tracking

## What TO Put Here

- ✅ Architecture decisions and rationale
- ✅ Design specifications
- ✅ LLM-specific installation/development guides
- ✅ Technical deep-dives for AI context

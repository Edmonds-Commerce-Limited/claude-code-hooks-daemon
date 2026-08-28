# SSOT Rule for .claude/agents/

**Single Source of Truth**: An agent definition carries its role framing and
role-unique behavioural instruction ONLY. It must not duplicate content from
canonical docs — it links to them instead. No engineering-principle
restatements, no code skeletons, no remediation cookbooks.

| Topic                  | Canonical Source                  |
| ---------------------- | --------------------------------- |
| QA policy and commands | `CLAUDE/QA.md`                    |
| Release process        | `CLAUDE/development/RELEASING.md` |
| Handler development    | `CLAUDE/HANDLER_DEVELOPMENT.md`   |
| Plan workflow          | `CLAUDE/PlanWorkflow.md`          |
| Documentation strategy | `CLAUDE/DocumentationStrategy.md` |

**When writing an agent**: reference canonical docs with a brief pointer plus
how THIS role applies them. Do not copy tables, procedures, or config examples
into the agent file.

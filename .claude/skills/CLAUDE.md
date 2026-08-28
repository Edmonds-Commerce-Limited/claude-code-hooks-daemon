# SSOT Rule for .claude/skills/

**Single Source of Truth**: the documentation-SSoT rules live in [CLAUDE/DocumentationStrategy.md](../../CLAUDE/DocumentationStrategy.md) (R7b covers skills); each skill's own mechanics live in its `<skill>/SKILL.md`, and the table below routes shared topics to their canonical files.

| Topic                             | Canonical Source                       |
| --------------------------------- | -------------------------------------- |
| Handler options, values, defaults | `docs/guides/HANDLER_REFERENCE.md`     |
| Configuration format & structure  | `docs/guides/CONFIGURATION.md`         |
| Release process                   | `CLAUDE/development/RELEASING.md`      |
| Acceptance test process           | `CLAUDE/AcceptanceTests/GENERATING.md` |

**When writing a skill**: reference canonical docs with a brief pointer. Do not copy tables, option lists, or config examples into the skill file.

# SSOT Rule for .claude/skills/

**Single Source of Truth**: Each skill's documentation lives in its own `<skill>/SKILL.md`. Skills must not duplicate content from other canonical sources — they must link to them instead.

| Topic | Canonical Source |
|-------|-----------------|
| Handler options, values, defaults | `docs/guides/HANDLER_REFERENCE.md` |
| Configuration format & structure | `docs/guides/CONFIGURATION.md` |
| Release process | `CLAUDE/development/RELEASING.md` |
| Acceptance test process | `CLAUDE/AcceptanceTests/GENERATING.md` |

**When writing a skill**: reference canonical docs with a brief pointer. Do not copy tables, option lists, or config examples into the skill file.

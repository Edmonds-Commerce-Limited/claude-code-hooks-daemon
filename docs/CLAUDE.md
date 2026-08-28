# SSOT Rule for docs/

**Single Source of Truth**: the documentation-SSoT rules live in [CLAUDE/DocumentationStrategy.md](../CLAUDE/DocumentationStrategy.md); the table below routes each human-docs topic to its canonical file.

| Topic                                 | Canonical Source                   |
| ------------------------------------- | ---------------------------------- |
| Per-handler options, values, defaults | `docs/guides/HANDLER_REFERENCE.md` |
| Configuration format & structure      | `docs/guides/CONFIGURATION.md`     |
| Installation & first-use              | `docs/guides/GETTING_STARTED.md`   |
| Troubleshooting                       | `docs/guides/TROUBLESHOOTING.md`   |
| QA suite (human overview)             | `docs/QA.md`                       |
| Plan system (human overview)          | `docs/PLAN_SYSTEM.md`              |

**When adding new content**: put it in the canonical file and add a link from any other file that needs to mention it. Do not copy-paste the content.

# SSOT Rule for docs/

**Single Source of Truth**: Every piece of information lives in exactly one canonical file. Other files link to it — they do not summarise or duplicate it.

| Topic | Canonical Source |
|-------|-----------------|
| Per-handler options, values, defaults | `docs/guides/HANDLER_REFERENCE.md` |
| Configuration format & structure | `docs/guides/CONFIGURATION.md` |
| Installation & first-use | `docs/guides/GETTING_STARTED.md` |
| Troubleshooting | `docs/guides/TROUBLESHOOTING.md` |

**When adding new content**: put it in the canonical file and add a link from any other file that needs to mention it. Do not copy-paste the content.

# Callout: scratch is short-lived, and a tracked doc that cites it as evidence is flagged

**Plan**: 00627
**Audience**: everyone

A new docs QA check, `untracked-evidence-citation`, advises when an edit adds a markdown line that names a file under `untracked/` together with an evidence word (evidence, source, measured, findings, results, verified, proof). Untracked files expire and are never reviewed, so the citation ends up resolving to nothing: copy the figures into the document, or file the artefact into the plan folder (`subagent-reports/`) and cite that. It runs at edit time only, skips fenced code blocks, bare directories and documents that are themselves under `untracked/`, and never blocks. `project_containment` now says the same thing everywhere it points at scratch: write inside your session directory, scratch is swept after 24 hours by default, and anything worth keeping is filed where git carries it (a plan folder, a plan journal, a pushed commit or an issue).

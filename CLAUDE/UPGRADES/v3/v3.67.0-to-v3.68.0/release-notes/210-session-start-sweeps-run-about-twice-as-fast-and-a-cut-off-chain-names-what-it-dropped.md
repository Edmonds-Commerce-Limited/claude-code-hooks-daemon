# Callout: SessionStart sweeps run about twice as fast, and a cut-off chain names what it dropped

**Plan**: 00474
**Audience**: operators

In a repository of about 18,000 files the SessionStart sweeps (`docs_qa_sweep`, `gitignore_safety_checker`, `secret_file_hygiene_checker`) spent most of their time asking whether each file is protected. That check now skips a glob when a literal part of it is absent from the path, and resolves each path's symlinks once instead of twice. The answers are unchanged, including a symlink loop being treated as protected; the whole SessionStart chain measured about 13 to 17 seconds before and about 8.5 seconds after on that repository. The 20 second dispatch budget is unchanged.

When a chain still overruns that budget, its late output is discarded (it is only logged). The "Chain cut short" and "Chain skipped" notes now end with `did not finish: <handler names> (their output is dropped)`, naming the handler that was running and every handler behind it, so a dropped sweep is no longer silent.

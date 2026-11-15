# Callout: delete-branch no longer deletes unproven work, and its proof target is not caller-chosen

**Plan**: 00594
**Audience**: operators

`delete-branch` removed the `--allow-unproven` and `--reason` flags: a branch whose content no machine-checked tier proves recoverable is never deleted by the command, whatever is declared or confirmed. Finish the work (merge it) or let the human who owns the branch decide. `--protected-ref` now accepts only the default branch or a declared integration line (local or remote form); any other ref, including the branch's own tip or a sha, is a usage error, because a caller that names its own proof target proves its own deletion. A project that scripted `delete-branch ... --allow-unproven --reason ...` must drop those flags.

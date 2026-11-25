# Callout: the optimise step finds its manifests in a self-install that links its wrapper

**Plan**: 00586
**Audience**: operators

`/hooks-daemon optimise` decided it was on a client install whenever a wrapper existed at `.claude/hooks-daemon/bin/hooks-daemon`. A checkout that is the daemon's own repository can hold that path as a link back to its own wrapper, and there the step looked for the config-changes manifests and its recorded-run state under `.claude/hooks-daemon/`, a directory that does not exist, so "what is new since the last review" found nothing. It now treats a wrapper that resolves to the project's own as a self-install and reads the manifests and run state from the project root. Its reference paths also name the printed daemon directory instead of a client-only path.

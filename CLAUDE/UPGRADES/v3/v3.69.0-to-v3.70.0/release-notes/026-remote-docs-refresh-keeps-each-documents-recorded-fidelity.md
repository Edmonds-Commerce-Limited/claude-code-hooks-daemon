# Callout: `remote-docs refresh` re-fetches each document in the fidelity it recorded

**Plan**: 00504
**Audience**: operators

`remote-docs refresh` used to pick one fetcher from the command line and use it for every document, so a plain `refresh --all` turned a document captured with `add --verbatim` into an extraction, and `refresh --all --verbatim` turned converted documents into verbatim ones. Refresh now reads each document's recorded `fidelity` and re-fetches a `verbatim` document verbatim and any other document with the default fetcher, so a mixed corpus keeps every document's mode with no flag. An explicit `--verbatim` still forces verbatim for every target. A document whose provenance cannot be read is still reported unreadable and left untouched. No configuration change is needed; to deliberately change a document's fidelity, re-capture it with `add --force`.

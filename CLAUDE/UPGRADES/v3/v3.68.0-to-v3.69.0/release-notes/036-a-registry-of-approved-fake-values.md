# Callout: docs may use approved fake values, and a vendored page can carry them

**Plan**: 00492
**Audience**: everyone

A project can now keep one list of approved FAKE values for its docs, at `.claude/fake-values.yaml`, by kind (the shipped project registry lists the all-same-digit session ids). A kind is named after the `sensitive_content` public pattern it exempts. A match that is exactly a listed value of its own pattern's kind is allowed, by the write-time handler, by the commit scan and by `scripts/qa/check_sensitive_content.py`; an unlisted real-looking value is still blocked, and a registry that cannot be parsed allows nothing. A project with no registry file sees no change.

A new docs QA check, `unlisted-fake-value` (advisory, edit and sweep), reports a fake-looking value that is not on the registry, in docs and in vendored pages. Its remedy is to use a listed fake or extend the registry.

`remote-docs add` and `refresh` no longer refuse an upstream page whose only trouble is an example value that matches a public pattern. When the project has a registry, each unlisted fake of a registered kind is swapped for an unused listed fake before the content scan, and the swap is recorded in the page's provenance as an optional `value_swaps` field (kind, replacement, count and the hash of the swapped-out value, never the value). A page with any swap is recorded as `converted` and a `verbatim` document that declares swaps is rejected. `source_sha256` stays the hash of the raw upstream bytes. A page whose fakes are all listed is stored untouched. Details: `CLAUDE/RemoteDocs.md`.

"""Remote documentation vendoring (Plan 00326).

Upstream documentation is captured into a tracked, provenance-bearing tree so
it can be read locally instead of re-fetched on every use. The provenance
frontmatter -- source URL, fetch time, raw content hash and *fidelity* --
travels with each document, which is what separates a citable corpus from a
cache.
"""

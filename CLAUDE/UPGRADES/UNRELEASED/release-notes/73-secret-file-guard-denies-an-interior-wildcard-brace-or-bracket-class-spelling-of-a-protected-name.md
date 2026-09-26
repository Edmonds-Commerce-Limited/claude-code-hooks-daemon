# Callout: `secret_file_guard` denies an interior-wildcard, brace or bracket-class spelling of a protected name

**Plan**: 00466
**Audience**: client projects

Two of the six shipped protected patterns (`*.secret*`, `*vault_pass*`) — the
ones with a wildcard on BOTH edges — stayed fully open to an interior `?`/`*`
spelling of the name they protect (`cat .claude/block-words.se?ret`), a
token carrying its OWN edge wildcard plus an interior one escaped every
pattern, an unenumerable bracket class (`id_r[!x]a`, `id_r[[:alpha:]]a`) was
read as literal characters instead of a wildcard, and a brace alternation
(`.vault-pas{s,}word`) was never expanded at all. `secret_file_guard` now
runs a real glob-intersection test for an edge-open token too, treats an
unenumerable bracket expression as a wildcard, expands a brace group before
tokenising, and — for the two both-edges patterns, where a language-only
intersection test would over-fire on ordinary prose — checks what a
glob-shaped token actually expands to on disk before denying it.

# Callout: `secret_file_guard` no longer flags a Python unpacking splat as a vault-password reference

**Plan**: 00466
**Audience**: client projects

`secret_file_guard` denied writing or running ordinary Python code such as
`rest = [words[0], *words[position + 1 :]]` (or even a bare `*wordlist`),
reporting a match against the protected `*.vault-password` glob — the `*`
unpacking operator followed by an identifier starting with "word"
coincidentally overlapped the tail of "pass-**word**". The leading-wildcard
truncation heuristic now only accepts that kind of partial overlap when the
protected glob itself has a trailing wildcard too (the shape it was designed
for); a glob anchored at the end, like the shipped `*.vault-password`, now
requires the whole token to be a genuine suffix of the protected name.

Correction: an earlier version of this note claimed "a real truncation of any
protected file is still denied exactly as before". That was never true for an
INTERIOR wildcard (`cat .vault-pas?word`) — see the "secret_file_guard denies
an interior-wildcard, brace or bracket-class spelling of a protected name"
release note for the fix.

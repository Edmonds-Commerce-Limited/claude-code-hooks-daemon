# Callout: the secret-file guard now reads the path after a `rev:` or `host:` prefix

**Plan**: 00474
**Audience**: operators

`secret_file_guard` judged a Bash word whole, so a protected name in git's `<rev>:<path>` object syntax at the repository root kept its prefix and never matched an anchored pattern such as `.vault-pass*`: `git show HEAD:.vault-pass` and `git cat-file -p HEAD:.vault-pass` printed a committed protected file, while `HEAD:config/.vault-pass` was denied. The guard now also judges the part after each `:` (the first eight colons and the last), in addition to the whole word, so `HEAD:<p>`, `<sha>:<p>`, `HEAD~2:<p>`, `HEAD^{tree}:<p>`, the index forms `:<p>` and `:0:<p>`, `<rev>:./<p>` and a remote path such as `scp host:.vault-pass .` are all denied. Nothing previously denied is allowed. Expect a new denial on an ordinary word whose text after a colon names a protected file; the Read and Grep tools take filesystem paths and are unchanged.

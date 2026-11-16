# Callout: `ls -d */` is no longer denied by the secret file guard

**Issue**: #204
**Audience**: operators

`secret_file_guard` denied `ls -d */` (and any glob ending in a slash) whenever a protected file sat at that level of the tree. The glob matcher normalised the token with `os.path.normpath`, which drops the trailing slash, so the directories-only glob `*/` was judged as `*` and matched the protected file.

A trailing slash means the glob matches directories only, so it can never name a protected file directly, and the matcher now skips such a token. Nothing else is loosened: `ls *`, a literal protected file path with no slash, and every glob that reaches a protected file below a directory (`keys/*`, `*/<name>`, `**/<name>`) are denied exactly as before.

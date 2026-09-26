# Callout: self-install checkouts now get a stable lsp-venv symlink

**Plan**: 00422
**Audience**: handler authors

`pyrightconfig.json` can only name a venv by a stable path, not the
fingerprint-keyed directory name that changes across upgrades, and the
symlink it documented (`untracked/venv`) was never created by any code — the
language server's import resolution had nothing to resolve against in any
self-install checkout. `ProjectContext.initialize()` now creates (and, on
upgrade, repoints) `untracked/lsp-venv` on every self-install daemon start,
derived from the running interpreter's `sys.prefix`. `pyrightconfig.json`
points at it under its new name, chosen to avoid colliding with the
unrelated pre-v3.7.0 `LEGACY_VENV` meaning of `untracked/venv`.

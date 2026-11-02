# Callout: write_protected_paths no longer denies read-only commands under a wildcard-only glob

**Plan**: 00556
**Issue**: #141
**Audience**: operators

Three faults combined to deny read-only commands as "writes" when a `write_protected_paths` glob ended in a wildcard-only component, such as `protected/**`:

- **awk programs:** a comparison (`>=`, `>`), a regex alternation (`/a|b/`), `||` or a quoted `|` inside an awk program was read as an output redirect or pipe. Only real awk output now counts as a write:
  - `print`/`printf` to `>`, `>>` or `|`;
  - `"cmd" | getline`;
  - `system(...)`;
  - `-i inplace`.
- **Wildcard-only globs:** text the guard could not read precisely was reported as naming `protected/**` whatever it said. Such a glob now names text only when the text mentions its literal directory (`protected/x`, `./protected/x`, or an absolute path under it). A glob with no literal directory at all, such as a bare `**` or `*`, stays fail-closed.
- **Heredoc bodies:** brace enumeration ran over heredoc bodies, which bash never brace-expands, and a body with nested quoted braces overflowed it. A body that a data consumer reads (`cat > notes.txt <<'EOF'`) is now skipped. A body fed to a shell or an interpreter is still judged in full: `bash <<'EOF'`, `cat <<'EOF' | sh`, `python3 - <<'EOF'`.

Real writes still deny, including `echo hi > protected/x`, `cp a protected/x`, `awk '{print > "protected/x"}'` and a shell heredoc that writes into `protected/`.

Nothing to do on upgrade.

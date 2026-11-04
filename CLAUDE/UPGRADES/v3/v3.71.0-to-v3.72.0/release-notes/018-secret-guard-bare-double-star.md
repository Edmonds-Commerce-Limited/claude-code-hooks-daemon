# Callout: a bare `**` is no longer denied as a recursive, dot-matching glob when your shell does not expand it that way

**Plan**: 00556
**Issue**: #142
**Audience**: operators

`secret_file_guard` used to read a bare unquoted `**` as a recursive glob that also matches hidden names. So `ls **` was denied whenever a protected file existed anywhere below the working directory, hidden directories included. Bash does not expand it that way unless `globstar` (recursion) and `dotglob` (hidden names) are on.

The guard now reads the Bash tool's shell snapshots in `<Claude config dir>/shell-snapshots/`. When EVERY readable snapshot records both options as off, a bare `**` is judged as bash's default expansion: like `*`, one level deep, no dot names.

The conservative reading stays in force when any of these holds:

- a snapshot records `globstar` or `dotglob` as on;
- a snapshot cannot be read, or does not record both options;
- there is no snapshot;
- the command itself runs `shopt` or `set -O`.

A literal protected path, and a glob that spells a protected file name, are denied as before. At most the 200 newest snapshots are read, and the verdict is cached until the directory or a snapshot changes.

Nothing to do on upgrade. If your profile turns `globstar` or `dotglob` on, nothing changes for you.

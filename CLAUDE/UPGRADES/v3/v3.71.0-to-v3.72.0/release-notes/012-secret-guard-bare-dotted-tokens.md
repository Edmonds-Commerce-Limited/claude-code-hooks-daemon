# Callout: secret_file_guard no longer denies bare dotted words that are not files

**Plan**: 00556
**Audience**: operators

Addresses #145 and #143. The default `*.secret*` pattern matched any Bash token or authored-script word that merely contained `.secret`, so a setting key such as `app.secret.key` or a module-name string such as `logging.getLogger("pkg.x_secret_guard")` was denied as a read of a protected file.

A BARE dotted word (letters, digits, `_` and `-`, with at least one `.` and no `/`, and not starting with `.`, `~` or `$`) now counts as a mention only when one of these holds:

- it names a file that exists (relative to the command's working directories or the project root);
- it is in the protected-file index (a glob match, or the basename of an indexed file);
- it is the operand of a file-opening command or call: `cat`, `less`, `cp`, `source`, a redirect target, a `git` or `python`/`ansible` command, `open(...)`, `Path(...)`, and a module-shaped string passed to a call that opens files.

Newly allowed:

- a bare dotted token that is not a path, does not exist, is not indexed and is not a file-opening operand (for example `echo app.secret.key`, or `grep app.secret.key notes.txt`, where the first grep operand is a pattern);
- a module-name string handed to `import_module`, `find_spec`, `run_module`, `patch(` or `getLogger` in an authored script.

Still denied:

- any path (`./app.secret`, `conf/app.secret`, `~/x.secret`), any glob that reaches a protected file, and any variable;
- a bare name of an existing or indexed protected file, such as `cat app.secret`;
- a file-opening operand, including `open("app.secret")`, `Path("x.secret").read_text()` and a redirect target.

Residual risk, accepted by the owner: a file that does not exist, is not indexed and is read by a command outside the file-opening list is allowed.

Nothing to do on upgrade.

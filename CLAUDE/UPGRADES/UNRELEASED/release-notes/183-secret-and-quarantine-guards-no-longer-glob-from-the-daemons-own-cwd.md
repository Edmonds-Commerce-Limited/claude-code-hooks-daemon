# Callout: the secret and quarantine guards no longer glob from the daemon's own directory

**Plan**: 00474
**Audience**: operators

Both guards expand a glob they find in a Bash command against the disk, to
see whether it reaches a protected file. One of the places they looked was
the directory the daemon process itself runs in, which is `/`. A command that
merely contained text like `untracked/scratch/*/data.json` in a quoted
program, or an unquoted `!a/**` argument, made the guards try to walk the
whole filesystem, refuse, and deny the command as one they could not verify
(issues #64 and #66).

Globs are now expanded only against the project root and the working
directory the tool call reported. A glob whose fixed leading directories do
not exist matches nothing and is not an error. A glob that really is broad
under a directory that exists is still refused, and a glob that matches a
protected file is still denied.

# Callout: the upgrade guard follows a leading cd when judging a relative script

**Plan**: 00474
**Audience**: client projects

`upgrade_approval_guard` denied a command that runs no upgrade, such as `cd /proj && PYTHONPATH=/proj/src $V/python scratch/probe.py`. The script path was resolved against the hook's own working directory instead of the directory the command's leading `cd` moved to, so a perfectly readable script looked missing, and a script that cannot be found counts as the upgrade once a steering variable such as `PYTHONPATH` is set. The guard now follows a leading `cd <literal existing directory>` chain (joined by `&&`, `;` or a newline) when it looks the script up and reads its content. A `cd` it cannot be sure of (a computed or `~` target, a missing directory, a subshell, a pipe, `||`, or any later `cd`/`pushd`/`popd`) keeps the old behaviour and the deny. Every way the upgrade itself is recognised (by name, by `--skip-reading-confirmation`, by a script whose content carries the handoff variable, or by an unreadable script run with upgrade arguments) is unchanged. No action is needed.

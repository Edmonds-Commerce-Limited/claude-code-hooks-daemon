# Callout: post-upgrade tasks are now a mandatory upgrade step

**Plan**: 00376
**Audience**: client projects

A release's post-upgrade tasks (audits, migrations, workarounds to retire)
used to be read only when a config key's migration Note happened to point at
one, so an upgrade that changed no config key never saw them. The new
`hooks-daemon check-post-upgrade-tasks --from <previous> --to <new>` lists
every task of every upgrade guide you crossed, with its severity. A branch
install also gets the tasks staged for the next release. `/hooks-daemon upgrade` now runs it as mandatory step 6, and the config-optimisation review
moves to step 9. `LLM-UPDATE.md` has a mandatory "Carry Out Post-Upgrade
Tasks" section, and the bare upgrade script prints the list before its
metadata block. If you have upgraded before, run the command once over your
whole upgrade history to catch any task you missed.

# Callout: the first gated upgrade and what it asks of the owner

**Plan**: 00376
**Audience**: operators

`breaking: true` in a config-changes manifest now stops every upgrade that
crosses it for the owner's approval (exit `4`). Two published manifests
carried the flag. v3.65.0's was a data error: it renames and removes nothing,
and it now says `breaking: false`. v3.58.0's stays, because that release did
break configs.

So an upgrade to this release from v3.64.x or later asks the owner for
nothing new; it stops only for reading, with exit `3`. An upgrade from v3.57.x
or earlier crosses v3.58.0 and stops with exit `4`, as does any project whose
installed version the gate cannot read, or that a `critical` pre-upgrade task
detects: v3.64.0's `plan-qa --json` rename finds its call sites in projects
upgrading from v3.63.x or earlier that parse that output.

The installed daemon on such a project predates `approve-upgrade`. The stop
therefore also prints a command that runs the approval from the new release's
own code in the daemon clone, which works from any installed version. The
owner runs it in their own terminal and types the phrase it shows.

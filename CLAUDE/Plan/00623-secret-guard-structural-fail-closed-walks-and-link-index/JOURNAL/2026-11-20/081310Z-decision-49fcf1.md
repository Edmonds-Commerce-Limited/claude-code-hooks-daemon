## 08:13 · decision · — — Stand-in declined the 3.76.0 release decision

Stand-in tick (automated one-off, NOT the owner) fired for the `[awaiting-human]` stop on the 3.76.0 release.

The pending question is whether to re-invoke `/release 3.76.0 accept-wip` over the in-flight plans and branches the slate check reported (exit 2). That is a release decision, and releases are reserved for a human. The stand-in therefore declined and chose nothing. The release stays blocked until the owner re-invokes it.

State at the time: Plans 00626, 00628, 00623 and 00603 are merged to main (2bdbf9b02); the 00594, 00613, 00620, 00621 and 00627 builder branches are pushed and unmerged; a later real owner message can overturn this.

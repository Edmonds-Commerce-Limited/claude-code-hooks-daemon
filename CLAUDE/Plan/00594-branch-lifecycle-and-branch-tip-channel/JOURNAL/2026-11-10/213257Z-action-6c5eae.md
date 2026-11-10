## 21:32 · action · — — Task 4.4 on main: pools are counted per owner

Task 4.4 is on main. Pools now count only branches that are mine: a creator record in this clone, a local ref, or a remote tip authored by the clone's `user.email`. Anything else is foreign. It is listed in a new Foreign sweep group with age and author, sits in no pool, and never appears in a deny or a fix command. `branch-sweep --clean --remote` still deletes a foreign branch whose merge is proven.

The agent saw twelve of its seventeen new tests fail first. Fixtures that fabricate remote-only branches now declare a matching `user.email`; no assertion was weakened. The merged tree passes the targeted tier 42 of 42.

Open: the email rule is weak evidence for seats that share one identity. A configured owner for foreign-branch pressure is not built, and `branch-keep` on a proven-merged foreign branch is refused.

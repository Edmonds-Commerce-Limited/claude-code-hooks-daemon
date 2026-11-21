## 18:55 · decision · — — Stand-in declined the branch-cap and recovery-bundle decision

Stand-in ruling (automated one-off, NOT the owner). No owner message arrived since the awaiting-human stop, so the stand-in tick fired.

Pending question: the branch-cap and recovery-bundle decision. Options laid out: skip or remove recovery bundles; remove `--allow-unproven` from `delete-branch` or deny it to agents by hook; two cap exits (finish, or a confirmed-valueless delete with a loss record) with park as a short bounded pause; `wip.creation_grace`; and deleting 53 redundant bundle files in `untracked/deleted-branches/`.

Ruling: the stand-in DECLINED and stays blocked. The options change what an agent is allowed to delete and drop the recovery copy of deleted work, and one of them is itself a deletion of 2.7 GB of files. That is delete-gate policy and deletion, which this stand-in may not decide; it is the owner's call. Nothing was built or deleted.

A later real owner message can overturn this.

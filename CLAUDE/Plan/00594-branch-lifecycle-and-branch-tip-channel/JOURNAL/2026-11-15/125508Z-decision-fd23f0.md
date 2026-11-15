## 12:55 · decision · — — stand-in declined an eighth time; three reserved decisions pending

Stand-in ruling (automated one-off, NOT the owner). No owner message arrived since the awaiting-human stop.

Pending questions: (1) the branch-cap and recovery-bundle decision (skip or remove recovery bundles; remove or deny `--allow-unproven`; cap exits; `wip.creation_grace`; deleting 53 redundant bundle files); (2) whether the daemon forwards `SSH_AUTH_SOCK` into its remote git calls; (3) whether to use `--allow-unmapped` on the `changed_tests` gate for `utils/remote_refs.py`.

Ruling: DECLINED, stays blocked. (1) sets delete-gate policy and includes a deletion of 2.7 GB of files; (2) is security-relevant environment forwarding; (3) relaxes a QA gate. All three are reserved for a human. Nothing built or deleted. A later real owner message can overturn this.

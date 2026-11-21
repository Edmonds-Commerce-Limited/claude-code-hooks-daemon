## 14:29 · action · —

Review finding F-BYPS F1 / D-PATH F1 (blocked merge) fixed. Single use, the 2-reviewer step and the refuse-after cap read only one checkout's tracked ledger, so a restored branch could be deleted again from a second worktree, or after switching away from the commit holding the ledger line, and each worktree got its own removal budget.

Fix: the shared main-checkout state_dir now holds `consumed/<verdict_id>.json` and `consumed-agents/<sha256(agent)[:32]>.json`. Both are created exclusively with os.link in record_removal immediately before the ledger append, and a lost race burns the verdicts. A git refusal writes `cancelled/<removal key>.json`. `used_state()` unions the ledger with the shared markers. issue_requests, approve_removal, record_removal and build_digest all read through it. A store kind path that exists but is not a directory now raises RejectError instead of reading as empty.

The accepted-residue test is replaced by TestSingleUseAcrossCheckouts (5 tests; 4 were red first). Found while turning it green: a two-verdict removal claimed each agent marker once per verdict, so it collided with itself. Agents are now claimed once per removal.

## 09:41 · decision · —

OWNER RULINGS (the human, in session, by speech-to-text; partial, and the owner will come back to the rest):

- Q1, a report with no plan: there is NO fallback store. A dispatched agent asked for a durable report with no plan folder to put it in must stop and say so ("I have no plan to report into: shall I make one, or will you?"). The coordinator then either makes the plan or tells the agent to. Rationale: a second tracking mechanism for arbitrary reports would undermine the plan system; plans have a lifecycle (complete, archive), and every durable report belongs in one.
- Scope, 80/20: DROP the consumption ledger and the "unused scratch files at stop" gate (Goals 4 and 5, Phase 4, and the consumption parts of Phase 6). The owner judges usage tracking over-engineered and never quite right. This makes Q2 (does a Read count as using a file) and Q7 (whose files a stop answers for) moot.
- NEW requirement: a command that consumes a scratch file (for example `git commit -F <file>`, `gh ... --body-file <file>`, `mkplan.bash --journal ... <file>`) must chain `&& rm <file>`, so the file is removed only when the consuming command succeeds. Enforce it by blocking the unchained form. The set of consuming commands is to be picked out explicitly.
- Scratch directory: the owner is leaning towards a whitelist of file names. Not decided; the owner will return to it.
- Q3 to Q6: not yet answered.

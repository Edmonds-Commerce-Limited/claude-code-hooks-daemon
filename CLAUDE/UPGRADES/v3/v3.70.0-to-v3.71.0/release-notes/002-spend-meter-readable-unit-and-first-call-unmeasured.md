# Callout: the spend-meter segment reads plainly, and its unmeasured count stops counting fresh agents

**Plan**: 00474
**Audience**: everyone

The `Σ⚙` status segment now labels its figure `tok-eq` (token equivalents: tokens weighted by price) instead of `ite`, which read as a word cut off mid-render, and shows thousands as whole numbers (`max 278k`, not `max 277.5k`). Its `unmeasured` count no longer grows by one for nearly every subagent: the context-budget gate, the resume guard and the live count now treat a transcript that holds no assistant record yet as a fresh agent whatever its size, because the hook for an agent's first tool call runs before that agent's first assistant record is flushed, behind a prompt and request records that already run to about 400 KB. An assistant record with no usage still counts as unmeasured, so a transcript format change is still reported.

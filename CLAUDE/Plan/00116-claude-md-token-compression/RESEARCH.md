# Research: SOTA Token Compression for Normative Agent Instructions

**Plan**: 00116 — CLAUDE.md Token Compression
**Compiled**: 2026-05-29
**Web access**: Available. All findings below carry URLs. Where a claim rests on
the author's own reasoning rather than a source, it is labelled **(judgement)**.

---

## Why this matters: instruction length degrades adherence

The core justification for the effort is empirical, not aesthetic.

- **Lost in the Middle** (Liu et al., 2023; TACL 2024) — arXiv
  [2307.03172](https://arxiv.org/abs/2307.03172). Establishes a **U-shaped
  performance curve**: models attend most reliably to information at the
  **start** (primacy) and **end** (recency) of a long input, and degrade in the
  **middle**. Follow-up coverage measured a **30%+ accuracy drop** on
  multi-document QA when the answer moved from position 1 to position 10 in a
  20-document context. The U-shape is partly architectural — RoPE positional
  encoding decays attention toward the middle. → **Establishes**: burying
  load-bearing daemon rules in a 33k-token always-on tree predictably weakens
  adherence. The 407-line injected block sits in the *middle* of CLAUDE.md —
  the worst position.

- **Context rot / persistence in 2025-2026 models** — Morph,
  [Context Rot](https://www.morphllm.com/context-rot) and
  [Lost in the Middle LLM](https://www.morphllm.com/lost-in-the-middle-llm),
  citing Chroma's 2025 study of 18 frontier models (incl. GPT-4.1, Claude
  Opus 4, Gemini 2.5): **every model degrades at every input-length increment
  tested**; Du et al. (2025) showed context length *alone* degrades performance
  independent of retrieval quality. Also: *"append-only instructions yield
  5–10 F1 points less than prepend or dual placements"* — placement and length
  both matter. → **Establishes**: the problem is NOT solved by bigger context
  windows; shrinking the always-on footprint is the durable fix.

- **Anthropic — Effective context engineering for AI agents** (2025) —
  [anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
  Direct vendor guidance for the platform this daemon runs on. Citable phrases
  (confirmed via WebFetch):
  - Goal: find the *"smallest possible set of high-signal tokens that maximize
    the likelihood of some desired outcome"*; context should be *"informative,
    yet tight."*
  - **Altitude**: be *"specific enough to guide behavior effectively, yet
    flexible enough"* — avoid both *"hardcoding complex, brittle logic"* and
    *"vague, high-level guidance"*; strive for *"the minimal set of information
    that fully outlines your expected behavior."*
  - **Just-in-time**: maintain *"lightweight identifiers (file paths, stored
    queries, web links, etc.)"* and *"dynamically load data into context at
    runtime"*; agents *"assemble understanding layer by layer, maintaining only
    what's necessary in working memory."*
  → **Establishes**: the vendor's own recommended direction is *less* always-on
  context, organised, high-signal — exactly what this plan proposes.

---

## Technique families and their fidelity for NORMATIVE instructions

The central distinction for this plan: **normative instructions** (a blocked-
command list, a "do X before Y" rule) must remain **literally faithful and
unambiguous**. A rule that is lossily paraphrased can become wrong — "blocks
`git reset --hard`" must not soften to "blocks risky git resets." This rules out
several otherwise-popular techniques.

### 1. Automated prompt compression (LLMLingua family) — REJECT for our use

- **LLMLingua / LongLLMLingua / LLMLingua-2** (Microsoft Research). LLMLingua-2:
  arXiv [2403.12968](https://arxiv.org/abs/2403.12968),
  [llmlingua.com/llmlingua2.html](https://llmlingua.com/llmlingua2.html),
  [github.com/microsoft/LLMLingua](https://github.com/microsoft/LLMLingua).
  - LLMLingua-2 frames compression as **token classification** (keep/discard
    each token) distilled from GPT-4 — *extractive*, so it never generates new
    text, only **drops** tokens; this is why its authors call it "faithful." It
    achieves 2x–6x compression.
  - The original LLMLingua used a **budget controller** that compresses
    instructions/questions LESS aggressively than context/demonstrations,
    because instructions are "more sensitive to compression." → This is itself
    evidence that **instructions are the wrong target for aggressive automated
    compression.**
- **Prompt Compression for LLMs: A Survey** (NAACL 2025 oral) — arXiv
  [2410.12388](https://arxiv.org/html/2410.12388v2),
  [repo](https://github.com/ZongqianLi/Prompt-Compression-Survey). Splits hard
  prompt methods into **extractive token-removal** (preserves original wording,
  *lower* compression 2–10x, lower hallucination risk) vs **abstractive/
  paraphrase** (LLM rewrites, *higher* compression up to 20x, but "carries
  potential for hallucination or information loss").
- **Faithfulness literature** confirms the hierarchy: abstractive summarisation
  "still suffers from faithfulness errors... higher risk of hallucinations"
  (arXiv [2108.13684](https://arxiv.org/pdf/2108.13684)); and for *legal/
  financial* documents "where factual accuracy is paramount, a purely
  abstractive approach can be risky... an extractive approach... is often
  preferred." Even extractive is "not equal to faithful" — it can introduce
  incorrect coreference/discourse (arXiv
  [2209.03549](https://arxiv.org/pdf/2209.03549)).
- **Verdict**: **REJECT** runtime/automated compression for our injected block.
  These methods target *lossy context* (RAG passages, few-shot demos, chat
  history) where approximate meaning suffices. Our injected block is
  *normative*: a dropped negation or paraphrased command literal (`-D` vs `-d`,
  the `--staged` exception) is a correctness bug, not a quality regression. Even
  "faithful" LLMLingua-2 is probabilistic and not safe for load-bearing literals.
  The faithfulness literature explicitly recommends extractive/manual approaches
  for accuracy-critical (legal-like) text — our case.

### 2. Manual information-density editing (telegraphic style, tables, dedup) — ADOPT

Lossless-by-construction: a human/LLM author rewrites for density and a
*reviewer/test asserts the load-bearing terms survived*.

- **Token-efficiency editing works**: e.g. "Auth service: check JWT, return 401
  on failure" (13 tok) vs the verbose 22-tok equivalent; well-optimised prompts
  cut 40–70% of tokens by "removing redundancy and filler words while preserving
  essential context"
  ([inventivehq](https://inventivehq.com/blog/optimize-prompts-reduce-token-costs),
  [portkey](https://portkey.ai/blog/optimize-token-efficiency-in-prompts/)).
- **Tables over prose**: the daemon already does this in
  `destructive_git.get_claude_md()` (command→reason table). Tables strip
  connective prose while keeping every literal token. Matches Anthropic's
  "high-signal tokens" principle.
- **Deduplication / canonicalisation**: many handler blocks restate the same
  meta-rule ("when blocked, don't stop, read the reason, continue"). That rule
  already appears once in the injector's `_SECTION_INTRO`. Per-handler repetition
  is pure redundant tokens — single-source it.
- **Verdict**: **ADOPT** as the primary always-on-tier technique. It is the only
  family that is *provably* faithful (a test can assert key terms remain) and it
  aligns with Anthropic guidance and this project's own DRY/single-source rules.

### 3. Tiering / progressive disclosure / just-in-time loading — ADOPT (primary architecture)

- **Anthropic Agent Skills** (open standard, Dec 2025) —
  [equipping-agents-for-the-real-world-with-agent-skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills).
  At startup the agent pre-loads only each skill's **name + description** (a few
  dozen tokens) — "the first level of progressive disclosure... just enough...
  to know when each skill should be used without loading all of it." Full detail
  loads "only when the task requires them." A 3-level model (SKILL.md → MODULE.md
  → data files) is the canonical shape
  ([SwirlAI](https://www.newsletter.swirlai.com/p/agent-skills-progressive-disclosure),
  [MindStudio](https://www.mindstudio.ai/blog/progressive-disclosure-ai-agents-context-management)).
- **Anthropic context-engineering** (same URL as above) frames this as
  just-in-time loading via lightweight identifiers.
- **Verdict**: **ADOPT.** This is the architecturally correct fix. Keep a terse,
  always-on summary (one line per handler: name + what it blocks + the one-token
  escape/fix) and move full rationale/remediation behind an **on-demand
  drill-down** the agent fetches only when it trips a handler. The drill-down is
  a CLI command (`explain-handler <name>`) and/or a skill — a "lightweight
  identifier." Full fidelity is preserved: the detailed text still exists
  verbatim, just not *always* in context. This directly mirrors how Agent Skills
  already inject only name+description.

### 4. De-`@`-importing heavy docs (reference instead of auto-expand) — ADOPT

- Claude Code auto-expands `@path` imports in CLAUDE.md into *every* session. The
  five `@`-imports here (PlanWorkflow 25.5 KB, RELEASING 20.2 KB,
  Features/Bugs/General ~27 KB, HOOKS-DAEMON 10.6 KB) load whether or not the
  session does plan/release work.
- Dropping the `@` (plain `CLAUDE/PlanWorkflow.md` reference) converts them to
  **on-demand reads**: the agent reads them when it chooses to do plan/release
  work — precisely just-in-time loading.
- **Fidelity note**: zero content lost — files untouched; only their *automatic*
  expansion stops. **(judgement)** Risk: the agent forgets to read them;
  mitigated by leaving a one-line always-on trigger pointer at the decision point
  ("Before any release, READ CLAUDE/development/RELEASING.md").

---

## Summary recommendation table

| Technique | Family | Faithful for normative instructions? | Decision |
|-----------|--------|--------------------------------------|----------|
| LLMLingua / LLMLingua-2 (runtime token-drop) | Hard / extractive, automated | Probabilistic — NOT safe for load-bearing literals | **REJECT** |
| Soft / abstractive / paraphrase compression | Soft, automated | Lossy — hallucination/omission risk | **REJECT** |
| Telegraphic editing, hedging/filler removal | Manual density | Yes (author + test verify) | **ADOPT** |
| Tables over prose | Manual density | Yes | **ADOPT** |
| Deduplicate / canonicalise meta-rules | Manual density | Yes | **ADOPT** |
| Two-tier: terse summary + on-demand drill-down | Progressive disclosure | Yes (full text preserved, deferred) | **ADOPT (primary)** |
| De-`@` heavy imports → on-demand reads | Just-in-time loading | Yes (files untouched) | **ADOPT** |

**Headline**: For *normative* instructions, **do not** use automated/lossy
compression. Use **manual information-density editing** + **two-tier progressive
disclosure** + **de-`@`-importing** — all lossless-by-construction and
verifiable, and all matching Anthropic's own 2025 context-engineering / Agent
Skills guidance and the Lost-in-the-Middle / context-rot evidence that motivates
the work.

## Sources

1. Liu et al., *Lost in the Middle*, arXiv 2307.03172 — https://arxiv.org/abs/2307.03172
2. Morph, *Lost in the Middle LLM* — https://www.morphllm.com/lost-in-the-middle-llm ;
   *Context Rot* — https://www.morphllm.com/context-rot (cites Chroma 2025; Du et al. 2025)
3. Anthropic, *Effective context engineering for AI agents*, 2025 —
   https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
4. Anthropic, *Equipping agents for the real world with Agent Skills*, Dec 2025 —
   https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
5. Pan et al., *LLMLingua-2*, arXiv 2403.12968 — https://arxiv.org/abs/2403.12968 ;
   https://llmlingua.com/llmlingua2.html ; https://github.com/microsoft/LLMLingua
6. Li et al., *Prompt Compression for LLMs: A Survey*, NAACL 2025 — arXiv 2410.12388 —
   https://arxiv.org/html/2410.12388v2 ; https://github.com/ZongqianLi/Prompt-Compression-Survey
7. *Faithful or Extractive?* arXiv 2108.13684 — https://arxiv.org/pdf/2108.13684 ;
   *Extractive is not Faithful* arXiv 2209.03549 — https://arxiv.org/pdf/2209.03549
8. Token-efficiency guides — https://inventivehq.com/blog/optimize-prompts-reduce-token-costs ;
   https://portkey.ai/blog/optimize-token-efficiency-in-prompts/
9. Progressive-disclosure analyses — https://www.newsletter.swirlai.com/p/agent-skills-progressive-disclosure ;
   https://www.mindstudio.ai/blog/progressive-disclosure-ai-agents-context-management

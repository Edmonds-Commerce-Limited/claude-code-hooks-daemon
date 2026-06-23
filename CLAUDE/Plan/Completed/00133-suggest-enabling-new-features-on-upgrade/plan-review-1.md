# Plan 00133 — Architect Review #1

**Reviewer**: Opus (software architect)
**Reviewing**: `PLAN.md` (draft), `context.md`, `findings.md`
**Verdict**: The draft's *revive-config-changes* spine is correct and well-grounded, but it is scoped one conceptual level too narrow. It treats the problem as "announce new config **options**" and "suggestion-only." The user's steer expands it into two further axes the draft does not yet model: (1) **handler-level** opt-in/opt-out as a first-class, code-declared property (`get_default_enabled()`); and (2) a **behaviour-changing default flip** for memory-disable that carries a **mandatory migration**, which is a (semi-)breaking change — not a quiet patch. This review supplies the reconciled conceptual model, an architecture decision on `get_default_enabled()`, the opt-out upgrade experience, the memory-migration flow, the release sequencing, and a revised task breakdown.

---

## A. Reconcile the conceptual model

There are **three distinct kinds of "feature"** in play, and the draft conflates them. Naming them precisely is the prerequisite for everything else.

1. **A whole handler that is off-by-default** (opt-in handler). Example today: `lsp_enforcement` ships `enabled: false` in the full config template (`init_config.py:155`). "Enabling" it = setting `handlers.<event>.<name>.enabled: true`.
2. **A whole handler that is on-by-default** (opt-out handler). Example: `destructive_git` (`init_config.py:123`). The vast majority of handlers. "Disabling" = `enabled: false`.
3. **An option (a key) on an always-on handler**, whose *default value* governs whether a behaviour is active. This is the memory feature: `markdown_organization` is always on, but `allow_untracked_claude_memory` (handler field `_allow_untracked_claude_memory`, default `True` — `markdown_organization.py:111`) gates the protection. The protective behaviour is dormant until the option flips to `False`.

The critical fact I verified: **the daemon has no single source of truth for "default enabled state."** The config template in `init_config.py` (`ConfigTemplate.generate_full`) is a **hand-maintained string literal** (every `{enabled: true, priority: N}` is typed out by hand, e.g. lines 123–215). Handler classes carry `priority`/`terminal` defaults in `__init__`, but **not** an enabled-vs-disabled default. Option defaults live as plain instance fields (`self._allow_untracked_claude_memory = True`) and are injected at load time by the registry via `setattr(instance, f"_{option_key}", value)` (`registry.py:329`). So "what is on by default" is encoded in **two unconnected places** (the template string, and `__init__` field defaults), and "what an option defaults to" is encoded in a **third** (the field initialiser). This is the latent DRY/SSoT violation the user is sensing.

**Recommend** the plan adopt this vocabulary and model all three kinds, but treat the **option-default** case (kind 3) as the primary one for v3.x — because the feature the user actually cares about (memory) is kind 3, not a handler. The advisory must therefore be able to compare a client's config not just against "is this key present?" (kind 1/2) but against **"does this key hold the value the new default would set?"** (kind 3). The existing `_key_present_in_config` (`config_migrations.py:401`) only answers presence, which is sufficient for kind 1/2 ("you haven't configured this handler") but **insufficient for kind 3** — a client could have `allow_untracked_claude_memory: true` explicitly and the presence check would say "already configured, no suggestion," exactly suppressing the nudge the user wants. The advisory needs a notion of **recommended value** and a **value comparison**, not just presence.

**So: `get_default_enabled()` is necessary but not sufficient.** It cleanly models kinds 1/2 (handler on/off). It does **not** model kind 3 (the memory option's default value). We also need either a parallel notion of "default value of an option that the advisory compares against," or we keep that knowledge in the config-changes manifest as a `recommended_value:` field. See section B.

---

## B. Evaluate `get_default_enabled()` as architecture

### What it would be

A new method on `Handler` (`core/handler.py`), e.g.:

```python
def get_default_enabled(self) -> bool:
    """Whether this handler is enabled by default in a fresh config.

    True  = opt-out  (on unless the client disables it)
    False = opt-in   (off unless the client enables it)
    """
    return True
```

### Pros

- **Single source of truth for handler on/off-by-default.** Eliminates the hand-maintained `{enabled: true/false}` literals in `init_config.py`; `ConfigTemplate.generate_full` could *derive* the enabled flag from the handler instance. This is squarely aligned with the project's dogmatic SSoT/DRY stance (`/workspace/CLAUDE.md` "SINGLE SOURCE OF TRUTH — Config is truth, code reads config").
- **The advisory can be *derived* from code** for kind 1/2: "handler X declares `get_default_enabled() == False` and the client has not enabled it" → a dormant opt-in handler, surfaced automatically. No manifest hand-authoring for handler-level opt-ins.
- **Self-documenting intent at the point of definition** — the user's explicit preference ("encode this at the handler code level"). A reviewer reading the handler sees opt-in/opt-out without cross-referencing a template string.

### Cons / caveats

- **It does NOT cover kind 3 (options).** The memory feature is an option, not a handler, so `get_default_enabled()` would not touch it at all. If the plan adopts *only* `get_default_enabled()`, it solves the wrong half of the user's priority example. This is the single most important caveat.
- **Upgrade semantics are subtle.** A client who already has a config does **not** regenerate it from the template on every upgrade. The upgrade path runs `ConfigMerger.merge(new_default_config, diff)` which starts from a **deep copy of the new default config** (`config_merger.py:107`) and applies the *client's customisations* on top. So: a newly-added **opt-out** handler that appears in the new template **is** inherited on upgrade automatically (it's in the base, the client never overrode it). A newly-added **opt-in** handler also appears in the base but with `enabled: false`. The merger does **not** flip a client's existing value. Therefore `get_default_enabled()` changes *new-install* and *template-generation* behaviour, but an **upgrade only adopts a new default for keys the client never set** — which is exactly why the memory flip needs the advisory + migration, because most clients have no `allow_untracked_claude_memory` key at all and would silently inherit whatever the template now emits.
- **Migration cost.** Adding an abstract method to `Handler` breaks every project-level handler that doesn't implement it — this is precisely the failure mode `_ABSTRACT_METHOD_VERSIONS` (`project_loader.py:35`) exists to manage (it already maps `get_acceptance_tests → 2.5.0`, `get_claude_md → 2.30.0`). To avoid an avoidable breaking change, **add `get_default_enabled()` as a *concrete* base method returning `True`** (not abstract). Then no project handler breaks, and handlers opt into "off-by-default" by overriding. This is strictly better than the abstract route here because there is a sensible universal default (most handlers are opt-out) — unlike `get_claude_md`/`get_acceptance_tests` where a default would hide missing guidance.

### Recommendation

**Recommend: ADOPT `get_default_enabled()` as a concrete (non-abstract) base method defaulting to `True`, but do NOT make it the whole solution.** Pair it with a **`recommended_value`** field in the config-changes manifest schema for kind-3 options. Rationale:

- `get_default_enabled()` becomes the SSoT for handler-level enabled defaults and lets `init_config.py` derive the template (removing the literal-string duplication) and lets the advisory auto-derive dormant opt-in **handlers**.
- The config-changes manifest (extended with `recommended` / `dormant` / `recommended_value`) remains the SSoT for **option-level** promotion — which `get_default_enabled()` structurally cannot express, because options are not handlers.
- They are therefore **complementary, not redundant**: handler defaults live in code (derivable), option promotions live in the manifest (hand-curated at release, because an option's "recommended value + why" is editorial, not mechanical). This keeps each fact in exactly one place.

**Do the `get_default_enabled()` work as its own commit/phase, gated behind a version note** (add `get_default_enabled → <release>` to a comment near `_ABSTRACT_METHOD_VERSIONS`, even though it is concrete, so future readers know when it appeared). Migrating `init_config.py` to *derive* the template from declared defaults is a meaningful refactor with its own test surface; it can land in the mechanism release and does not block the manifest/advisory work.

---

## C. Design the opt-out upgrade experience

When a release flips a feature to default-on (opt-out), the upgrading client needs three things. Map each onto the **existing trio** — do **not** invent a fourth subsystem (the draft's Non-Goal is correct and reinforced here):

| Need                                                          | Owner mechanism                                                                                                            | Why                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| (i) **Told it's now on / now recommended**                    | **config-changes** advisory (`changed:` for a default flip; `added:` + `recommended` for a new option)                     | Its whole job is diffing the client config against per-version manifests and reporting. Extend it with `recommended`/`dormant`/`recommended_value` so it can *promote*, not just list.                                                                                                                                                           |
| (ii) **Behaviour actually enabled**                           | **config-changes** `changed:` entry **+** the merger inheriting the new template default for clients who never set the key | The merger starts from the new default (`config_merger.py:107`); a client with no `allow_untracked_claude_memory` key inherits the new template value automatically. A client who **explicitly** set the old value keeps it (merger preserves customisations) and must act on the advisory. **This split is the core of "opt-out done safely."** |
| (iii) **Mandatory migration executed/prompted** (memory case) | **post-upgrade-tasks** (`Type: data-migration` or `workflow-change`, `Severity: critical`)                                 | The post-upgrade-tasks README already enumerates `config-migration`, `data-migration`, `workflow-change` with `critical/recommended/optional` severity. This is *exactly* its purpose. The advisory says "this is now on"; the post-upgrade task says "now go move your existing memory into tracked docs."                                      |

So the responsibility split is:

- **config-changes** = "what changed in config, and what we recommend you do about it" (the announcement + recommendation).
- **post-upgrade-tasks** = "the one-off remediation you must run because of that change" (the migration).
- **truth-changes** = "statements in YOUR docs that are now false" (doc reconciliation) — relevant if the flip invalidates a documented claim (e.g. a project doc that says "memory is allowed here").

A default flip can legitimately touch **all three** in one release. That is fine and intended — they compose. What must NOT happen is a new parallel "feature-suggestions" manifest duplicating the config-changes loader/differ.

**One concrete gap to fix:** the advisory's presence-only check (`_key_present_in_config`) means a `changed:` (default flip) entry won't currently fire a "you should adopt this" suggestion for a client who has the key set to the **old** value. For default flips, the advisory must compare the client's *value* against `recommended_value` and warn when they differ. Add a `changed`-with-`recommended_value` advisory path (today `changed:` is documentation-only per SCHEMA.md line 81–82).

---

## D. Memory-migration-on-enable flow (concrete)

This is the part the draft omits entirely and the user is emphatic about ("we MUST ensure that the agent migrates current Claude memories into project docs or Claude rules as appropriate"). Design it as a **post-upgrade task** authored against the release that flips the default, plus reuse of Plan 00131's deferred phases.

**Trigger**: The post-upgrade-tasks file `NN-migrate-untracked-claude-memory.md` (`Type: data-migration`, `Severity: critical`, `Applies to: <clients crossing the flip release>`, `Idempotent: yes`). Surfaced when `upgrade.md` runs the post-upgrade-tasks step for the version range. Independently, the live `_deny_untracked_memory` message (`markdown_organization.py:949`) already tells the agent that reads stay allowed *so existing memory can be migrated* — so the first blocked write after the flip is itself a just-in-time trigger.

**What the agent is instructed to do** (the task body):

1. **Inventory** existing memory: read every `~/.claude/projects/*/memory/*.md` for this project (reads are never blocked — confirmed by `_is_claude_memory_path` allowing reads, and stated in the deny message).
2. **Classify each fact** by the progressive-disclosure rubric already encoded in `get_claude_md()`/`_deny_untracked_memory` (`markdown_organization.py:967-978`) — this is the SSoT for "as appropriate":
   - Always-relevant durable fact → `CLAUDE.md` (kept lean).
   - Path-/context-specific guidance → `.claude/rules/*.md` with `paths:` glob frontmatter.
   - Intent-triggered procedure → a thin skill under `.claude/skills/` pointing at a SSoT doc body.
   - Human-facing reference → `docs/`.
3. **Write** the migrated content into the chosen tracked location (Edit/Write — allowed because targets are tracked project paths, not memory paths).
4. **Verify** each fact landed (re-read the destination) **before** considering the source removable.
5. **Avoid data loss**: do **not** delete the source memory file as part of this task. The policy blocks *writes* to memory, not reads; leaving the source in place is harmless and reversible. Recommend the task explicitly say "leave the original memory file untouched; it is now inert. Deletion is the user's call." (Belt-and-braces against a bad migration.)

**Decision on "as appropriate"**: there is no automated classifier and there should not be one (YAGNI). The rubric in `_deny_untracked_memory` is the decision procedure; the agent applies judgement per fact. The task file restates the rubric verbatim (or links to it as SSoT — prefer link to avoid duplicating the rubric text).

**Ties to deferred Plan 00131 work** (from MEMORY.md, user-requested 2026-06-19, both deferred):

- **Plan 00131 Phase 6 (dogfood)** — activate the policy in *this* repo and migrate this repo's own `MEMORY.md`. The memory-migration post-upgrade task is the *productised, client-facing* version of that same exercise. **Recommend** running Phase 6 dogfood *first* (in the mechanism release) so the task instructions are battle-tested on our own repo before we ship the flip to clients. (Note: MEMORY.md is currently 25.7KB, over its 24.4KB limit — dogfooding the migration is also overdue maintenance.)
- **Plan 00131 Phase 4 (scaffolding skill)** — inventory docs, `@`-import audit, auto-build rules/skills. If/when it lands, the post-upgrade migration task should *invoke that skill* rather than re-describe the steps. Until then the task carries the manual rubric. **Recommend** the task body reference Phase 4's skill as the preferred path "if available," degrading to manual steps.

---

## E. Release shape & sequencing

The user floated a hot-fix. **Recommend AGAINST a hot-fix for the memory default flip, and AGAINST bundling the flip with the mechanism.** Reasoning, grounded in this repo's own rules:

- Flipping `allow_untracked_claude_memory` to default-`False` is **behaviour-changing**: clients who never set the key inherit blocking of memory writes they previously could do. RELEASING.md Step 9 ("Breaking Changes Check") and the "Changed section / changed defaults" criteria classify a changed default as upgrade-guide-worthy. A quiet PATCH would violate the project's own breaking-change discipline (and MEMORY.md's "NEVER push before acceptance tests" + behaviour-change caution).
- A default flip that *also* mandates a data migration is, in practice, a **semi-breaking MINOR with an upgrade guide** — not a patch. It needs: a `CLAUDE/UPGRADES/v3/...` guide, a `critical` post-upgrade task, a config-changes `changed:` entry with `recommended_value`, and likely a truth-changes entry.

**Recommended sequencing (two releases):**

1. **Release N — the mechanism (additive, MINOR).** Ships:

   - `get_default_enabled()` concrete base method + `init_config.py` derivation refactor.
   - config-changes schema extension (`recommended`, `dormant`, `recommended_value`) + advisory promotion rendering + `changed:`-value comparison path.
   - `check-config-migrations` wired into the skill `upgrade.md` (today only in `CLAUDE/LLM-UPDATE.md` lines 381/866 — confirmed missing from `upgrade.md`).
   - `UNRELEASED/config-changes/` staging dir + RELEASING.md steps (anti-rot).
   - **Backfill v3.x config-changes manifests** for dormant opt-in options (incl. a v3.23.0 `added: allow_untracked_claude_memory` entry marked `dormant: true, recommended: false` — i.e. "available, not yet recommended-on" — because in release N the default has NOT flipped).
   - Dogfood Plan 00131 Phase 6 in this repo (proves the migration story before shipping it).
     This release contains **no behaviour change** to any client → it satisfies the draft's "no handler default changed" Non-Goal and can move fast.

2. **Release N+1 — the memory default flip (semi-breaking MINOR + upgrade guide).** Ships:

   - `markdown_organization.py:111` default `True → False` (and the template default).
   - config-changes v{N+1} `changed: allow_untracked_claude_memory` with `recommended_value: false`, `recommended: true`.
   - `critical` post-upgrade task `NN-migrate-untracked-claude-memory.md`.
   - Upgrade guide under `CLAUDE/UPGRADES/v3/...`.
   - truth-changes entry if any documented "memory allowed" claim becomes false.

**Why split rather than bundle:** the mechanism is the thing that makes the flip *safe to announce*. Shipping the flip without the strengthened advisory + migration task in clients' hands would re-create the exact "dormant / silent" problem in reverse (silent *activation*). Ship the loudspeaker before you ship the thing it needs to announce. If the user insists on one release, it is *possible* to bundle (the mechanism is additive), but then the acceptance gate must cover both the advisory and the live default-flip behaviour, and it is unambiguously a MINOR-with-upgrade-guide, never a patch.

---

## F. Revised task breakdown (supersedes draft where noted)

Keep the draft's good bones: reuse config-changes (Decision 1 — **confirmed correct**), mirror truth-changes discipline, backfill v3.x, no auto-mutation. Changes: add the `get_default_enabled()` phase, add the option-**value** comparison, add the memory-migration task, and split the release.

### Phase 0: Confirm model & decisions (no code)

- ⬜ 0.1 Adopt the three-kinds vocabulary (handler opt-in / handler opt-out / option-default). Record in Technical Decisions.
- ⬜ 0.2 Confirm via `config_merger` reading: a client without a key inherits the new template default; a client with the key keeps their value. (Verified in this review — `config_merger.py:107`; restate in plan as the basis for the opt-out-safety design.)
- ⬜ 0.3 Decide schema additions: `recommended: bool`, `dormant: bool` on `added`; `recommended_value` on `added`/`changed`. Record as Technical Decision.
- ⬜ 0.4 Decide `get_default_enabled()` is **concrete, default True** (not abstract) — record rationale (no project-handler break; sensible universal default).

### Phase 1: `get_default_enabled()` (TDD) — mechanism release

- ⬜ 1.1 RED: tests for base default True, an opt-in handler overriding to False, and `init_config` deriving `enabled:` from the declared default.
- ⬜ 1.2 GREEN: add concrete method to `Handler`; override in current opt-in handlers (audit which template entries are `enabled: false`, e.g. `lsp_enforcement`).
- ⬜ 1.3 Refactor `ConfigTemplate.generate_full` to derive enabled state from handler instances (removes the literal-string duplication; SSoT).
- ⬜ 1.4 Add a version-note comment near `_ABSTRACT_METHOD_VERSIONS` recording `get_default_enabled → <release>`.
- ⬜ 1.5 QA + daemon restart RUNNING.

### Phase 2: Schema + advisory strengthening (TDD) — mechanism release

- ⬜ 2.1 RED: tests for `recommended`/`dormant` parsing; advisory **promotes** a dormant/recommended `added` distinctly; advisory **compares value** for a `changed` entry with `recommended_value` and warns when client value differs.
- ⬜ 2.2 GREEN: extend `ConfigChangeEntry` + parser; add a `🆕 Recommended — enable these` section above plain `💡 New Options Available`; implement the `changed`-value comparison (today `changed` is doc-only — SCHEMA.md:81). Optionally let the advisory auto-derive dormant opt-in **handlers** from `get_default_enabled()` (kind 1/2) so handler-level opt-ins need no manifest entry.
- ⬜ 2.3 Update `config-changes/SCHEMA.md` (new fields; `changed` now actionable).
- ⬜ 2.4 QA.

### Phase 3: Wire into upgrade flow — mechanism release

- ⬜ 3.1 Add a `check-config-migrations` step to `skills/hooks-daemon/upgrade.md` alongside `check-truth-changes` (confirmed absent today; present only in `CLAUDE/LLM-UPDATE.md:381,866`).
- ⬜ 3.2 Mirror v3.18.1 truth-changes treatment in `scripts/upgrade.sh` so a **bare** upgrade run also surfaces the advisory.
- ⬜ 3.3 Reconcile `CLAUDE/LLM-UPDATE.md` references with the new wording.

### Phase 4: Backfill v3.x manifests — mechanism release

- ⬜ 4.1 Inventory every opt-in option/handler added v3.0→v3.23.0 (cross-check release notes + handler fields), classified dormant vs neutral. (Findings already names: `allow_untracked_claude_memory` v3.23.0; `extra_allowed_markdown_paths` v3.19.0; `yolo_container_detection.show_on_session_start` v3.22.0.)
- ⬜ 4.2 Author `config-changes/v{X.Y.Z}.yaml` for each. v3.23.0 memory entry = `added`, `dormant: true`, `recommended: false` (NOT yet recommended-on in the mechanism release).
- ⬜ 4.3 Sanity-check `cli check-config-migrations --from 3.0.0 --to 3.23.0` against a fixture config → dormant options promoted, neutral ones in the quiet bucket.

### Phase 5: Release discipline (anti-rot) — mechanism release

- ⬜ 5.1 `CLAUDE/UPGRADES/UNRELEASED/config-changes/` + README mirroring `UNRELEASED/truth-changes/README.md`.
- ⬜ 5.2 RELEASING.md step (near Step 6) to move staged manifests at release.
- ⬜ 5.3 Step 7 (Opus doc review) checklist line: "did this release add/flip an opt-in feature → config-changes entry with `recommended`/`dormant`/`recommended_value` exists?"

### Phase 6: Dogfood the memory migration — mechanism release

- ⬜ 6.1 Execute Plan 00131 Phase 6 in this repo: enable the policy, migrate this repo's `MEMORY.md` into tracked docs/rules using the rubric. Capture friction; feed it into the task-file wording. (Also resolves the current 25.7KB MEMORY.md overflow.)

### Phase 7: Mechanism release

- ⬜ 7.1 Full QA (13/13) + H-1 gate (23/23) + daemon RUNNING. MINOR, additive, no behaviour change → document Step 12 scope.

### Phase 8: Memory default flip (separate, semi-breaking MINOR) — release N+1

- ⬜ 8.1 RED/GREEN: flip `_allow_untracked_claude_memory` default + template default; update tests asserting default-blocking.
- ⬜ 8.2 config-changes v{N+1} `changed: allow_untracked_claude_memory`, `recommended_value: false`, `recommended: true`.
- ⬜ 8.3 `critical` post-upgrade task `NN-migrate-untracked-claude-memory.md` (rubric or Phase-4-skill invocation).
- ⬜ 8.4 Upgrade guide `CLAUDE/UPGRADES/v3/...`; truth-changes entry if a documented claim flips.
- ⬜ 8.5 Full release with acceptance coverage of the live flip (PreToolUse blocking handler default changed → full Step 12 applies).

---

## G. Open decisions for the user

1. **`get_default_enabled()` — adopt now or defer?**
   *Recommend: adopt now, concrete-default-True*, because it removes a real SSoT violation (template string vs code) and lets handler-level opt-ins be auto-surfaced. It is low-risk (concrete, no project-handler break). The only cost is the `init_config` derivation refactor. If the user wants the smallest possible change, it can be deferred to a later plan and the manifest alone can carry handler opt-ins — but that perpetuates the duplicated enabled-state.

2. **One release or two?**
   *Recommend: two* (mechanism, then flip). Ship the announcement machinery before the thing it must announce. The user floated a hot-fix; a hot-fix for the *flip* is the wrong instrument (behaviour-changing + migration). A hot-fix/patch for *wiring the existing advisory into upgrade.md* alone would be defensible if the user wants something in clients' hands immediately — but it would surface nothing until manifests are backfilled, so it has little standalone value.

3. **Schema: `recommended`/`dormant` booleans vs a richer `promote:` block?**
   *Recommend: two booleans + `recommended_value`* (minimal, additive, easy to parse) over a nested block (YAGNI). Revisit only if a third promotion dimension appears.

4. **Should `changed:` become advisory-actionable (value comparison)?**
   *Recommend: yes* — it is required to make the opt-out default-flip surface for clients holding the old value. Today `changed` is documentation-only (SCHEMA.md:81). This is a small, contained advisory-logic addition.

5. **Memory migration: delete source memory or leave inert?**
   *Recommend: leave inert, never auto-delete.* The policy blocks writes, not reads; the source is harmless once migrated, and non-deletion is the safe, reversible default. Deletion is the user's explicit call.

6. **Dogfood before or after shipping the flip?**
   *Recommend: dogfood in the mechanism release (Phase 6), before shipping the flip.* Proves the migration instructions on our own repo and clears the MEMORY.md overflow.

---

## Notes & Updates

### 2026-06-22

- Architect review #1 written. Net: the draft is directionally right (revive config-changes; mirror truth-changes discipline; no new subsystem; suggestion-not-mutation), but must (a) model three kinds of feature not one, (b) add option-**value** comparison so a default flip surfaces, (c) add `get_default_enabled()` as a concrete SSoT for handler-level defaults — complementary to the manifest, not a replacement, (d) own the memory migration via a `critical` post-upgrade task tied to Plan 00131 Phases 4/6, and (e) split into a mechanism release then a semi-breaking flip release rather than a hot-fix.

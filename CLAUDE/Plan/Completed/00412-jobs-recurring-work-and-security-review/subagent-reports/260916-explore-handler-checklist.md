# New PreToolUse Deny Handler — Complete Ship Checklist

Explore agent (Opus 5), 2026-09-16. Read-only survey of /workspace.

---

## 1. Complete checklist for ONE new PreToolUse deny handler

The six files named in the request are all correct, but they are roughly **half**
of what the QA suite actually enforces.

### A. Source (mandatory)

| # | File | What |
|---|---|---|
| 1 | `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/<name>.py` | The handler. **No import/registration anywhere** — `HandlerRegistry` (`/workspace/src/claude_code_hooks_daemon/handlers/registry.py`, `EVENT_TYPE_MAPPING` ~line 40) discovers by `pkgutil` walk of the directory. There is no `__init__.py` export list to update. |
| 2 | `/workspace/src/claude_code_hooks_daemon/constants/handlers.py` | `HandlerIDMeta` entry (pattern at lines 74–92). ⚠️ `config_key` **must** equal `_to_snake_case(class_name)` — enforced by `/workspace/tests/unit/handlers/test_config_key_consistency.py:19`. |
| 3 | `/workspace/src/claude_code_hooks_daemon/constants/priority.py` | Priority constant (safety band 10–20; existing block lines 43–50). A literal `priority=10` in the handler is caught by `scripts/qa/check_magic_values.py`. |
| 4 | `/workspace/src/claude_code_hooks_daemon/constants/rule_ids.py` | One `RuleID` per rule (see §3). |
| 5 | **`/workspace/src/claude_code_hooks_daemon/block_report/fingerprints.py`** ⬅ MISSING FROM YOUR LIST | `FINGERPRINT_TABLE` entry keyed by `HandlerID.X.config_key` (lines 98–132). Strictly optional for a NEW handler (stage-1 rule-ID extraction covers `get_rules()`-migrated handlers automatically, per the module docstring lines 1–40), but every sibling deny handler has one. Omit deliberately, not by accident. |
| 6 | `/workspace/src/claude_code_hooks_daemon/utils/command_evasion.py` | Reuse `SUDO_INVOCATION` / `OPTIONAL_PATH` (+ `utils/shell_segmentation.py`) rather than a bare `\bcmd` anchor — required to survive the evasion tests (#21). |

### B. Config surfaces

| # | File | Note |
|---|---|---|
| 7 | `/workspace/src/claude_code_hooks_daemon/daemon/init_config.py` | `ConfigTemplate.generate_full()` — literal YAML lines (`sudo_pip` line 135, `curl_pipe_shell` line 136, `bash_safe_mode` line 215). This is the generated fresh-init template and the surface the default-enabled drift guard reads. |
| 8 | `/workspace/.claude/hooks-daemon.yaml` | Dogfood config. `tests/integration/test_dogfooding_config.py` fails if a discovered handler is absent **or** `enabled: false`. Its only exemptions are `validate_instruction_content` and `skill_opportunity_detector` (lines 131–140). **A default-OFF handler still has to appear here enabled, or be added to that frozenset.** (`bash_safe_mode` is default-off but dogfooded on at line 442 in warn mode.) |
| 9 | `/workspace/.claude/hooks-daemon.yaml.example` | `tests/integration/test_example_config.py:235` `test_example_config_includes_all_library_handlers` — exhaustive over the registry. Also guarded by `check_handler_reference.py`'s `example-config-phantom-handler` rule. |
| 10 | **`/workspace/CLAUDE/UPGRADES/config-changes/v<next>.yaml`** ⬅ MISSING | Per-release config-change manifest (`added:` entry with `recommended` / `dormant` / `description` / `migration_note`). Precedent for a new default-ON deny handler: `v3.62.0.yaml` (whose header comment is the canonical argument for `breaking: false`). Any `example_yaml` block must load against `Config` — `tests/integration/test_config_changes_manifest_examples.py`. |

### C. Docs surfaces (each has a QA gate)

| # | File | Gate |
|---|---|---|
| 11 | **`/workspace/docs/guides/HANDLER_REFERENCE.md`** ⬅ MISSING | `#### <config_key>` section (pattern: `sudo_pip` at line 1132) **plus** the master table row (~line 3959). Enforced by `/workspace/scripts/qa/check_handler_reference.py` rules `undocumented-blocking-handler`, `phantom-handler`, `priority-mismatch`, via `/workspace/tests/integration/test_handler_reference_check.py`. **This is the audit that most often bites a new blocking handler.** |
| 12 | **`/workspace/.claude/HOOKS-DAEMON.md`** ⬅ MISSING | Generated — run `bin/hooks-daemon generate-docs` (or `regenerate-docs`; see `daemon/cli.py:2843` / `:3014`). It is the ground truth for `scripts/qa/check_doc_truth.py` **and** for rule `undocumented-blocking-handler` above. Tracked in git, so a stale copy is a diff. |
| 13 | **`/workspace/CLAUDE.md`** (the `<hooksdaemon>` block) ⬅ MISSING | Written by `ClaudeMdInjector` on daemon startup. If your handler earns `get_claude_md()`, `tests/integration/test_claude_md_guidance_coverage.py::TestGuidanceActuallyReachesClaudeMd` (line 707, `test_every_earning_handler_has_a_section_in_claude_md` line 748) fails until you **restart the daemon** and commit the regenerated block. |
| 14 | `/workspace/docs/guides/CONFIGURATION.md` (lines 692/765), `/workspace/CLAUDE/LLM-INSTALL.md` (safety table line 249, sample line 276), `/workspace/docs/guides/GETTING_STARTED.md` | Hand-maintained; `check_doc_truth.py` and docs-qa see these. |
| 15 | `/workspace/CHANGELOG.md`, `/workspace/RELEASES/v<next>.md` | Release gate. |

### D. Tests you must touch — exact-equality tables (the "unexpected directories")

| # | File | Why it fails for a new handler |
|---|---|---|
| 16 | **`/workspace/tests/unit/daemon/test_default_enabled_template_consistency.py`** ⬅ MISSING, CRITICAL | `_EXPECTED_OPT_IN_CONFIG_KEYS` (line 33) is asserted **equal** (not subset) against both the template's `enabled: false` set and the set of classes returning `get_default_enabled() -> False` (assertions lines 111–119). Any default-OFF handler must be added here. |
| 17 | **`/workspace/tests/integration/test_acceptance_test_coverage.py`** ⬅ MISSING | Every handler with a `Decision.DENY` source path must ship a DENY-expecting `AcceptanceTest`, or appear in `_EXEMPT_FROM_DENY_TEST` (line 53) with a written reason. |
| 18 | **`/workspace/tests/integration/test_acceptance_negative_case_requirement.py`** ⬅ MISSING | Every DENY-capable handler must **also** ship a near-miss `Decision.ALLOW` `AcceptanceTest`. `_MISSING_NEGATIVE_CASE_ALLOWLIST` (line 43) is asserted equal in **both directions** (lines 108 and 113) — you cannot quietly add yourself without failing the staleness half later. Practically: **ship the ALLOW test**. |
| 19 | **`/workspace/tests/integration/test_acceptance_contract.py`** ⬅ MISSING | Every BLOCKING acceptance test must declare exactly one of `tool_payload` / `dispatch_as_bash` / `hook_input` / `harness_cannot_produce`, and the real handler is then driven with it and must produce the declared decision **and match every declared regex**. Unconditional, no allowlist. Handlers are built via `HandlerRegistry.register_all()` against this repo's real `.claude/hooks-daemon.yaml`. |
| 20 | `/workspace/tests/integration/test_claude_md_guidance_coverage.py` | `_EARNS_GUIDANCE` (line 69) / `_DORMANT_IN_THIS_PROJECT` (line 370) / `_EXEMPT_FROM_GUIDANCE` (line 385) / `_EXEMPT_DESPITE_DENYING` (line 609). Every handler must have a verdict **with a reason string**. `TestEveryHandlerHasARecordedVerdict` is at line 529. |
| 21 | `/workspace/tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py` | `_EVASION_CASES` (~line 70) plus a completeness check: a new pre_tool_use handler must be in the covered set or an explicitly-reasoned exclusion. Vectors: `git -C`, `sudo -H`, path-qualified binary, line continuation (both between and *inside* tokens). |
| 22 | `/workspace/tests/unit/handlers/pre_tool_use/test_command_synonym_evasion.py` | `_SWEPT_HANDLERS` (line 40) is deliberately bounded to five handlers, so you likely do NOT extend it — but check `_SYNONYM_CASES` (line 53) and `_NO_ORDINARY_SYNONYM_KNOWN` (line 69) if you add a `destructive_git` rule. |
| 23 | **`/workspace/tests/unit/test_rule_parity.py`** ⬅ MISSING, CRITICAL | See §3. Exhaustiveness both ways + `_DENY_WITHOUT_RULES_ALLOWLIST` (~line 320). |
| 24 | **`/workspace/tests/integration/test_handlers_do_not_match_prose.py`** ⬅ MISSING | Default-in-scope for every handler. Your regex must not fire on prose that merely *names* the command (journal text, heredocs, `echo "<sentence>"`). Handlers that match text deliberately are named with a reason. |
| 25 | **`/workspace/tests/integration/test_declared_behaviour_matches_source.py`** ⬅ MISSING | The handler's declared behaviour **tag** must not understate `Decision.DENY` — a deny handler tagged advisory / non-terminal fails. The tag feeds the Behaviour column of `.claude/HOOKS-DAEMON.md`, which `check_doc_truth.py` consumes as ground truth. |
| 26 | **`/workspace/tests/integration/test_documented_commands_are_not_self_denied.py`** ⬅ MISSING | Extracts commands from `README.md`, `CLAUDE/LLM-INSTALL.md`, `CLAUDE/LLM-UPDATE.md`, `docs/guides/GETTING_STARTED.md`, `CLAUDE/development/RELEASING.md` and drives them through handlers. **A new Bash deny that hits a documented command fails here.** Very likely for `curl` / `chmod` / `rm`-shaped rules. |
| 27 | **`/workspace/scripts/qa/dangerous-invocation-corpus.yaml`** + `/workspace/scripts/qa/check_dangerous_invocation_corpus.py` ⬅ MISSING, VERY LIKELY TO BITE | 20 rows, verdict held in **both** directions. New denies will flip `UNCOVERED-open` rows (e.g. `worktree-checkout-force`, `worktree-switch-force`, `worktree-reset-keep`, `filesystem-rm-rf`) to denied → the check fails until those rows are updated to `COVERED`. Exactly the class of audit in an unexpected directory. |
| 28 | `/workspace/tests/integration/test_handler_instantiation.py`, `test_every_handler_response_validates.py`, `test_all_handlers_response_validation.py`, `/workspace/tests/unit/handlers/test_registry_builtin_iteration.py`, `/workspace/tests/handlers/test_registry_config.py` | Automatic sweeps — no edit needed, but they fail if construction raises or the response is not schema-valid. |
| 29 | `/workspace/tests/unit/handlers/pre_tool_use/test_<name>.py` and `/workspace/tests/integration/handlers/test_pre_tool_use_safety.py` | Unit + integration tests (95% coverage bar — `CLAUDE/HANDLER_DEVELOPMENT.md:1078`). Existing `SudoPipHandler` block at `test_pre_tool_use_safety.py:348`. |
| 30 | `/workspace/scripts/qa/check_repo_hygiene.py` rule `orphaned-handler-guidance` (const line 118, section line 214) | Opposite direction of #13: a CLAUDE.md section with no handler behind it. |
| 31 | `/workspace/src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/optimise-invoke.sh` | If you reference the handler in the optimise checklist, `/workspace/tests/unit/scripts/test_optimise_checklist_handlers.py` validates every dotted `handlers.<event>.<name>` against `HandlerID` / `RETIRED_HANDLERS`. |
| 32 | `/workspace/scripts/qa/declared-invariant-pairs.yaml` | Only if you declare an invariant pair; `sudo_pip.py` is the reference row (lines 105–111). |

Also relevant: `/workspace/scripts/audit_handler_config_keys.py` is reused *by*
`check_handler_reference.py` as its config-key ground truth — no edit needed, but
it is why #2's snake-case rule is load-bearing.

---

## 2. How a handler ships default-OFF (opt-in)

**The default lives in the handler class**, as `Handler.get_default_enabled()`.
It is the declared SSoT; the YAML template carries a *curated duplicate literal*,
and a drift guard welds the two together. It is NOT in a config model default and
NOT only in `yaml.example`.

**(a) Base default — `/workspace/src/claude_code_hooks_daemon/core/handler.py:374-396`**

```python
def get_default_enabled(self) -> bool:
    """Whether this handler is enabled by default in a fresh config.

    Plan 00133. Single source of truth for a handler's *semantic* default
    enabled state. The config template still carries a curated
    ``{enabled: true/false}`` literal per handler (Decision 5); a drift-guard
    test (``test_default_enabled_template_consistency``) asserts the
    template's disabled set equals the set of handlers declaring
    ``get_default_enabled() -> False``, so the two can never diverge. The
    config-changes upgrade advisory consumes this method directly.

    ``True``  = opt-out  (on unless the client explicitly disables it).
    ``False`` = opt-in   (off unless the client explicitly enables it).
    """
    return True
```

Concrete, not abstract — so opt-out handlers implement nothing.

**(b) The override — `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/bash_safe_mode.py:184-193`**

```python
def get_default_enabled(self) -> bool:
    """Opt-in handler — off by default, per the feature's own framing.

    Plan 00268's cry-wolf analysis stands: forced errexit changes the
    semantics of every command, so enabling this is a per-project policy
    act, never a default. Must stay consistent with the
    ``enabled: false`` flag in the config template (enforced by
    ``test_default_enabled_template_consistency``).
    """
    return False
```

**(c) The template literal — `/workspace/src/claude_code_hooks_daemon/daemon/init_config.py:215`**

```python
"    bash_safe_mode: {enabled: false, priority: 36}  # Opt-in: require a set safety prelude on sequenced Bash (warn-first)\n"
```

**(d) The weld — `/workspace/tests/unit/daemon/test_default_enabled_template_consistency.py:33, 111-119`**

`_EXPECTED_OPT_IN_CONFIG_KEYS` (23 entries, incl. `bash_safe_mode`) is asserted
**equal** to (i) the `enabled: false` keys parsed out of
`ConfigTemplate.generate_full()` and (ii) the set of discovered classes whose
`get_default_enabled()` returns `False`. Three assertions, so all three sources
must agree.

### Recipe for shipping a mixed batch

- **ON by default**: do nothing (inherit `True`); write `{enabled: true, priority: N}`
  in `init_config.py`; do NOT touch `_EXPECTED_OPT_IN_CONFIG_KEYS`.
- **OFF by default**: override `get_default_enabled() -> False`; write
  `{enabled: false, priority: N}` in `init_config.py`; **add the config_key to
  `_EXPECTED_OPT_IN_CONFIG_KEYS`**; mirror `enabled: false` in
  `.claude/hooks-daemon.yaml.example`; mark `dormant: true` / `recommended: false`
  in the `CLAUDE/UPGRADES/config-changes/` manifest.
- The **dogfood** config `/workspace/.claude/hooks-daemon.yaml` is independent:
  `test_dogfooding_config.py` demands every discovered handler be enabled here,
  so a default-off handler is still turned ON in this repo (`bash_safe_mode`
  line 442, warn mode) unless added to that test's `opt_in_handlers` frozenset
  (lines 131–140).
- Consumer: `/workspace/src/claude_code_hooks_daemon/config_optimisation/checklist.py:127`
  and `:246` render the `[default off]` marker from this method.
- `get_relevance()` (`core/handler.py:398-423`) is orthogonal: "worth it, knowing
  the project" vs `get_default_enabled()`'s "safe without knowing the project".

---

## 3. How rule IDs are declared

**Declaration site:** `/workspace/src/claude_code_hooks_daemon/constants/rule_ids.py`
— a plain class `RuleID` with `NAME: str = "R-SCREAMING-KEBAB-CASE"` class
attributes, grouped by owning handler, each with a `#:` docstring comment
(destructive_git's nine at lines 33–62; `SUDO_PIP_INSTALL` line 112;
`PIP_BREAK_SYSTEM_PACKAGES` line 115; `CURL_PIPE_SHELL` line 90). Rule IDs are a
**public contract** (module docstring lines 1–20): renaming requires a
breaking-change upgrade-guide entry.

**What else must be updated:**

1. **`get_rules()` on the handler** must emit
   `Rule(rule_id=RuleID.X, blocked=..., why=..., fix=..., verbose=...)`.
   Mandatory in both directions:
   - `/workspace/tests/unit/test_rule_parity.py` `TestConstantHygiene`
     (lines 289–313) fails a constant declared but not emitted by any handler.
   - The inverse check (lines 126–135) fails an emitted `rule_id` with no
     named constant.
2. **Uniqueness and format:** `test_rule_parity.py:121` (no duplicate `rule_id`
   across handlers) and `/workspace/tests/unit/constants/test_rule_ids.py`
   (all values unique, string, non-empty, `R-` prefixed, only uppercase/digits/
   hyphens).
3. **Message header:** `RuleFormatter.terse()` / `.verbose()` must lead with
   `BLOCKED [R-...]` — `test_rule_parity.py` Task 7.2; and
   `block_report/fingerprints.py:_RULE_ID_HEADER_PATTERN` depends on that header
   for handler attribution from transcripts.
4. **explain-rule registry: NOTHING to update.**
   `/workspace/src/claude_code_hooks_daemon/rule_explain/lookup.py` builds its
   index dynamically from `HandlerRegistry` → `get_rules()` + `get_claude_md()`
   (`collect_handler_rules` / `discover_handler_rules`). It works automatically
   once step 1 is done. Same for `block_report` stage 1.
5. **Deny-without-rules allowlist:** a handler that denies but declares no `Rule`
   must be in `_DENY_WITHOUT_RULES_ALLOWLIST` (`test_rule_parity.py` ~line 320)
   with a reason. Avoid — declare rules instead.
6. **Per-rule content contracts:** `verbose` non-empty, `blocked` naming the
   offending invocation — see `/workspace/tests/unit/handlers/test_destructive_git.py:604`
   and `:610` for the destructive_git flavour of these.
7. There is **no** test asserting every RuleID appears in a doc; the
   documentation coupling is indirect, via `get_claude_md()` coverage (#20) and
   `HANDLER_REFERENCE.md` (#11).

---

## 4. The acceptance-test contract

`get_acceptance_tests() -> list[AcceptanceTest]`. The dataclass is at
`/workspace/src/claude_code_hooks_daemon/core/acceptance_test.py:230-250`
(field docs lines 150–229, validation `__post_init__` lines 252–290).

For a **blocking** handler there are four separate gates:

| Requirement | Enforced by |
|---|---|
| At least one test with `expected_decision=Decision.DENY` and `test_type=TestType.BLOCKING`, **or** an entry in `_EXEMPT_FROM_DENY_TEST` stating why | `/workspace/tests/integration/test_acceptance_test_coverage.py:53` |
| At least one **near-miss `Decision.ALLOW`** test (realistic command the handler correctly does *not* block) | `/workspace/tests/integration/test_acceptance_negative_case_requirement.py:96-118` (exact-equality ratchet, both directions) |
| Every BLOCKING test declares **exactly one** of `dispatch_as_bash=True` (derives `tool_payload` from `command`), `tool_payload=`, `hook_input=`, `harness_cannot_produce=`. Mutual exclusion raises at construction (`acceptance_test.py:269-290`). | `/workspace/tests/integration/test_acceptance_contract.py` — `test_every_blocking_test_declares_a_way_to_drive_it` (unconditional, no ratchet allowlist) |
| Driving the **real, config-registered** handler with that input produces the declared decision **and** every `expected_message_patterns` regex matches the real runtime text | `test_acceptance_contract.py` — `test_every_blocking_test_with_a_declared_input_produces_its_declared_verdict`. Handlers built via `HandlerRegistry.register_all()` (the same entry point the live daemon uses) against this repo's real `.claude/hooks-daemon.yaml`. |

Per-test field requirements: non-empty `title` / `command` / `description`;
`safety_notes` explaining why it is safe to execute; `recommended_model`
(`RecommendedModel.HAIKU` for simple blocks); `requires_main_thread=False` for
BLOCKING and ADVISORY.

Downstream consumers: `generate-playbook` →
`/workspace/tests/acceptance/test_playbook_harness.py` (release gate) and
`/workspace/tests/integration/test_acceptance_tool_payload_agrees_with_prose.py`.

Canonical shape to copy:
`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/sudo_pip.py:171-207`
— two DENY tests, `dispatch_as_bash=True`, `echo "…"` payloads harmless if
executed. `destructive_git`'s is at
`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:514-763`
(17 tests, including its near-miss ALLOW).

---

## 5. Minimal reference handler

Smallest by line count is
**`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/pip_break_system.py`**
(203 lines), but the recommended template is:

### `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/sudo_pip.py` (207 lines)

Four lines longer and strictly better, because it already uses the shared
evasion primitives that `test_blocking_handler_evasion.py` requires:

```python
from claude_code_hooks_daemon.utils.command_evasion import OPTIONAL_PATH, SUDO_INVOCATION
...
_SUDO_PIP_PATTERN = SUDO_INVOCATION + OPTIONAL_PATH + r"(?:pip3?|python3?\s+-m\s+pip)\s+install\b"
```

whereas `pip_break_system.py:101` still hardcodes a bare
`r"\b(pip3?|python3?\s+-m\s+pip)\s+install\s+.*--break-system-packages"`
that you would have to re-derive.

Candidate line counts: `pip_break_system.py` 203, `sudo_pip.py` 207,
`dangerous_permissions.py` 212, `curl_pipe_shell.py` 342, `bash_safe_mode.py` 398,
`destructive_git.py` 763.

**Structural skeleton either one gives you:**

1. Module-level `_VERBOSE_CONTENT` string constant (full first-fire teaching text).
2. `__init__`: `super().__init__(handler_id=HandlerID.X, priority=Priority.X, terminal=True)`,
   then one `Rule(...)` and a `RuleFormatter()`.
3. `matches()`: `command = get_bash_command(hook_input)` — **never** read
   `tool_input` directly; the canonical accessor returns `None` for non-Bash tools
   and normalises shell line continuations. Reading `tool_input` reopened the
   bypass hole historically (see the comment at `sudo_pip.py:102-105`).
4. `get_rules() -> [self._rule]`.
5. `handle()`: verbose-first / terse-after via
   `get_data_layer().disclosure` keyed on `(transcript_path, rule_id)`;
   no `transcript_path` fails toward verbose.
6. `get_claude_md()` (or a justified `None`, recorded in #20).
7. `get_acceptance_tests()` per §4.

---

## Three highest-risk items for a batch of new deny handlers

1. **`/workspace/scripts/qa/dangerous-invocation-corpus.yaml`** — new denies will
   flip `UNCOVERED-open` rows to denied and fail the check in the "good news"
   direction. Budget a pass over all 20 rows.
2. **`/workspace/tests/integration/test_documented_commands_are_not_self_denied.py`**
   — if any new rule catches a command this repo's own install/update/release docs
   instruct, the fix is to the doc, not the handler.
3. **`/workspace/tests/integration/test_acceptance_negative_case_requirement.py`**
   — plan a near-miss ALLOW test per handler from the start; retrofitting means
   touching an exact-equality frozenset asserted in both directions.

---

## Extending `destructive_git` with new rules

Files and exact line anchors:

- `/workspace/src/claude_code_hooks_daemon/constants/rule_ids.py:33-62` — add the
  new `RuleID` constants to the destructive_git block (the comment there says
  "9 rules"; update it).
- `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:286`
  — add `Rule(...)` to the rules list; `get_rules()` at line 362.
- Same file line 514+ — add a DENY `AcceptanceTest` per new rule.
- **`/workspace/tests/unit/handlers/test_destructive_git.py:574`** —
  `assert len(rules) == 9` is hardcoded.
- **`/workspace/tests/unit/handlers/test_destructive_git.py:582-594`** —
  `test_rule_ids_match_constants` asserts the exact set of nine.
- `/workspace/tests/unit/handlers/test_destructive_git.py:425-473` — the
  `BLOCKED [{RuleID.X}]` header assertions, one per rule.
- `/workspace/tests/unit/handlers/pre_tool_use/test_command_synonym_evasion.py`
  — `_SYNONYM_CASES` / `_NO_ORDINARY_SYNONYM_KNOWN` cover destructive_git's
  synonym axis (`git update-ref -d` for `branch -D`, `+refspec` for
  `push --force`); a new rule with a known plumbing synonym belongs here.
- `/workspace/tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py`
  `_EVASION_CASES["DestructiveGitHandler"]` — add the new spelling's
  `git -C /srv/project ...` and line-continuation respellings.
- `/workspace/scripts/qa/dangerous-invocation-corpus.yaml` rows
  `worktree-checkout-force`, `worktree-switch-force`, `worktree-reset-keep`
  are the ones most likely to flip to `COVERED`.

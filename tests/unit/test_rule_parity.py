"""Rule parity + integrity tests — Plan 00116, Phase 7 (anti-drift guarantee).

Everything in this module enumerates handlers and rules DYNAMICALLY (never a
hardcoded handler list), so it passes regardless of how many handlers have
migrated onto ``get_rules() -> list[Rule]`` at the time it runs. As of this
writing several handlers are mid-migration (Phase 3 fan-out still landing in
the main tree), so some checks here are EXPECTED to fail until every blocking
handler has migrated — that is the point: the failure names exactly which
handler/rule/constant is still outstanding.

Design contract (PLAN.md Phase 7 + Goal G7):
  - Task 7.1: every table ``RuleID`` is emitted by some handler's ``get_rules()``.
  - Task 7.2: every rule's terse/verbose message leads with a ``RuleID`` present
    in the table (enforced here via the ``RuleFormatter`` contract: ``terse()``/
    ``verbose()`` always start with ``BLOCKED [<rule_id>]``, and the id is drawn
    from the SAME ``Rule`` that produced the table row).
  - Task 7.3: no duplicate ``RuleID`` across handlers.
  - Decision D / Decision A / G4: rule IDs are a named-constant public contract,
    and the table row, terse reminder and verbose block all derive from ONE
    ``Rule`` object so they cannot drift apart.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.rule_explain.lookup import HandlerRules, discover_handler_rules

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so every handler can be CONSTRUCTED.

    A handler that raises on construction (e.g. one reading `ProjectContext`
    in ``__init__``) would silently drop out of ``discover_handler_rules()``,
    which would make every check below pass on a smaller-than-real handler
    set without telling us. Mirrors the same pattern already used by
    ``tests/integration/test_declared_behaviour_matches_source.py``.
    """
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


@pytest.fixture()
def all_handler_rules() -> list[HandlerRules]:
    """Every discoverable handler's config key, class name, rules and docs."""
    return discover_handler_rules()


@pytest.fixture()
def all_rules(all_handler_rules: list[HandlerRules]) -> list[tuple[HandlerRules, Rule]]:
    """Every declared ``Rule`` across every handler, paired with its owner."""
    return [(handler, rule) for handler in all_handler_rules for rule in handler.rules]


def _declared_rule_id_constants() -> dict[str, str]:
    """Every ``RuleID`` constant name -> value declared in ``constants/rule_ids.py``."""
    return {
        name: value
        for name, value in vars(RuleID).items()
        if not name.startswith("_") and isinstance(value, str)
    }


#: Matches the naming convention from ``constants/rule_ids.py``'s own docstring:
#: an ``R-`` prefix followed by SCREAMING-KEBAB-CASE.
_RULE_ID_PATTERN = re.compile(r"^R-[A-Z0-9-]+$")


# ---------------------------------------------------------------------------
# 1. No duplicate IDs
# ---------------------------------------------------------------------------


class TestNoDuplicateRuleIds:
    """Every ``Rule.rule_id`` is globally unique, a declared constant, and well-formed."""

    def test_discovery_is_not_vacuous(self, all_rules: list[tuple[HandlerRules, Rule]]) -> None:
        """A vacuous discovery would make every assertion below pass by omission."""
        assert all_rules, (
            "No rules were discovered at all. Either handler discovery is broken, "
            "or (during Phase 3 fan-out) genuinely zero handlers have migrated onto "
            "get_rules() yet — either way this test module is checking nothing."
        )

    def test_no_duplicate_rule_ids_globally(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """Each ``rule_id`` appears in exactly one handler's ``get_rules()``."""
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for handler, rule in all_rules:
            owner = seen.get(rule.rule_id)
            if owner is not None and owner != handler.config_key:
                duplicates.append(
                    f"{rule.rule_id} declared by both {owner} and {handler.config_key}"
                )
            else:
                seen[rule.rule_id] = handler.config_key
        assert (
            not duplicates
        ), "Duplicate RuleID(s) declared by more than one handler: " + "; ".join(duplicates)

    def test_every_rule_id_is_a_declared_ruleid_constant(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """Every emitted ``rule_id`` traces back to a named ``RuleID`` constant.

        Decision D: rule IDs are a public contract via NAMED constants, never
        a magic string typed directly into a handler's ``_RULE_DEFINITIONS``.
        """
        declared_values = set(_declared_rule_id_constants().values())
        undeclared = sorted({rule.rule_id for _handler, rule in all_rules} - declared_values)
        assert not undeclared, (
            "Rule ID(s) emitted by a handler's get_rules() but not declared as a "
            f"RuleID constant in constants/rule_ids.py: {undeclared}"
        )

    def test_every_rule_id_matches_naming_convention(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """Every emitted ``rule_id`` matches ``^R-[A-Z0-9-]+$``."""
        malformed = sorted(
            {
                rule.rule_id
                for _handler, rule in all_rules
                if not _RULE_ID_PATTERN.match(rule.rule_id)
            }
        )
        assert (
            not malformed
        ), f"Rule ID(s) violating the R-SCREAMING-KEBAB-CASE convention: {malformed}"


# ---------------------------------------------------------------------------
# 2. Rule completeness
# ---------------------------------------------------------------------------


class TestRuleCompleteness:
    """Every declared ``Rule`` carries every field the anti-drift contract needs."""

    def test_every_rule_has_non_empty_blocked(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        offenders = sorted(
            f"{handler.config_key}:{rule.rule_id}"
            for handler, rule in all_rules
            if not rule.blocked.strip()
        )
        assert not offenders, f"Rule(s) with empty 'blocked': {offenders}"

    def test_every_rule_has_non_empty_why(self, all_rules: list[tuple[HandlerRules, Rule]]) -> None:
        offenders = sorted(
            f"{handler.config_key}:{rule.rule_id}"
            for handler, rule in all_rules
            if not rule.why.strip()
        )
        assert not offenders, f"Rule(s) with empty 'why': {offenders}"

    def test_every_rule_has_non_empty_fix(self, all_rules: list[tuple[HandlerRules, Rule]]) -> None:
        offenders = sorted(
            f"{handler.config_key}:{rule.rule_id}"
            for handler, rule in all_rules
            if not rule.fix.strip()
        )
        assert not offenders, f"Rule(s) with empty 'fix': {offenders}"

    def test_every_rule_has_non_empty_verbose(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        offenders = sorted(
            f"{handler.config_key}:{rule.rule_id}"
            for handler, rule in all_rules
            if not rule.verbose.strip()
        )
        assert not offenders, f"Rule(s) with empty 'verbose': {offenders}"

    def test_every_rendering_contains_the_rule_id(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """Anti-drift property (Decision A / G4): all three renderings carry the ID.

        Because ``table_row``/``terse``/``verbose`` are all generated from the
        SAME ``Rule`` instance, none of them can name a different rule than the
        one that produced it — this is the mechanical guarantee behind "cannot
        drift apart", not just a naming convention.
        """
        formatter = RuleFormatter()
        offenders = []
        for handler, rule in all_rules:
            table_row = formatter.table_row(rule)
            terse = formatter.terse(rule)
            verbose = formatter.verbose(rule)
            if rule.rule_id not in table_row:
                offenders.append(f"{handler.config_key}:{rule.rule_id} missing from table_row")
            if rule.rule_id not in terse:
                offenders.append(f"{handler.config_key}:{rule.rule_id} missing from terse")
            if rule.rule_id not in verbose:
                offenders.append(f"{handler.config_key}:{rule.rule_id} missing from verbose")
        assert not offenders, "\n".join(offenders)


# ---------------------------------------------------------------------------
# 3. Formatter parity
# ---------------------------------------------------------------------------


class TestFormatterParity:
    """``RuleFormatter`` renders every declared rule without silent truncation."""

    def test_table_row_is_a_single_line(self, all_rules: list[tuple[HandlerRules, Rule]]) -> None:
        """A table row must not embed a newline (it is one markdown table line)."""
        formatter = RuleFormatter()
        offenders = [
            f"{handler.config_key}:{rule.rule_id}"
            for handler, rule in all_rules
            if "\n" in formatter.table_row(rule)
        ]
        assert not offenders, f"Rule(s) whose table_row embeds a newline: {offenders}"

    def test_table_row_contains_blocked_and_fix_verbatim(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """The table row must carry the FULL blocked literal and fix, not a truncation."""
        formatter = RuleFormatter()
        offenders = []
        for handler, rule in all_rules:
            row = formatter.table_row(rule)
            if rule.blocked not in row:
                offenders.append(
                    f"{handler.config_key}:{rule.rule_id} blocked missing from table_row"
                )
            if rule.fix not in row:
                offenders.append(f"{handler.config_key}:{rule.rule_id} fix missing from table_row")
        assert not offenders, "\n".join(offenders)

    def test_terse_contains_blocked_and_fix(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """The terse reminder must carry the blocked literal and the fix, not just the id."""
        formatter = RuleFormatter()
        offenders = []
        for handler, rule in all_rules:
            terse = formatter.terse(rule)
            if rule.blocked not in terse:
                offenders.append(f"{handler.config_key}:{rule.rule_id} blocked missing from terse")
            if rule.fix not in terse:
                offenders.append(f"{handler.config_key}:{rule.rule_id} fix missing from terse")
        assert not offenders, "\n".join(offenders)

    def test_verbose_contains_full_verbose_content(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        """The verbose block must carry the full ``Rule.verbose`` teaching content verbatim."""
        formatter = RuleFormatter()
        offenders = [
            f"{handler.config_key}:{rule.rule_id}"
            for handler, rule in all_rules
            if rule.verbose not in formatter.verbose(rule)
        ]
        assert not offenders, f"Rule(s) whose verbose() drops Rule.verbose content: {offenders}"


# ---------------------------------------------------------------------------
# 4. Constant hygiene
# ---------------------------------------------------------------------------


class TestConstantHygiene:
    """Every declared ``RuleID`` constant is actually used by some handler.

    EXPECTED TO FAIL while Phase 3 migrations are still landing: several
    ``RuleID`` constants (e.g. for ``markdown_organization``,
    ``validate_eslint_on_write``, ``auto_continue_stop``'s goal-ledger rule)
    were pre-declared alongside sibling migrations per MIGRATION-PATTERN.md,
    but their owning handler has not yet implemented ``get_rules()``. Do NOT
    delete these constants to make this test pass — they belong to
    still-landing work in the main tree, not to this worktree. Record any
    failing names in the delivery report instead.
    """

    def test_every_declared_ruleid_constant_is_used_by_some_handler(
        self, all_rules: list[tuple[HandlerRules, Rule]]
    ) -> None:
        used = {rule.rule_id for _handler, rule in all_rules}
        declared = _declared_rule_id_constants()
        orphans = sorted(value for value in declared.values() if value not in used)
        assert not orphans, (
            "RuleID constant(s) declared in constants/rule_ids.py but not emitted by any "
            f"handler's get_rules(): {orphans}. If this is a still-landing Phase 3 "
            "migration, leave the constant in place — it will stop being orphaned once "
            "its handler's get_rules() lands; do not delete it to silence this test."
        )


# ---------------------------------------------------------------------------
# 5. Every Decision.DENY handler declares rules (or is explicitly allowlisted)
# ---------------------------------------------------------------------------

#: Source marker meaning "this handler has a code path that denies a tool call".
_DENY_MARKER = "Decision.DENY"

#: Handlers whose module contains a Decision.DENY path but that legitimately
#: declare no Rule objects. Every entry MUST record why. This allowlist is
#: SEEDED from the state of the fan-out at Phase 7 authoring time (2026-08-31)
#: — the coordinator is expected to PRUNE this list as sibling Phase 3
#: migrations land, removing an entry the moment its handler gains get_rules().
_DENY_WITHOUT_RULES_ALLOWLIST: dict[str, str] = {
    "AutoApproveReadsHandler": (
        "Its Decision.DENY branch is defensive-only: matches() gates handle() to "
        "read-only tools already routed to Decision.ALLOW, so the DENY branch "
        "guards against a non-read tool reaching handle() by a path matches() "
        "does not permit today — not a live blocking rule with a table entry."
    ),
}


def _discover_deny_handler_classes() -> dict[str, type[Handler]]:
    """Concrete handler classes whose own module source contains a deny path."""
    found: dict[str, type[Handler]] = {}
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        try:
            source = inspect.getsource(module)
        except OSError:
            continue
        if _DENY_MARKER not in source:
            continue
        for attribute_name, attribute in vars(module).items():
            if (
                inspect.isclass(attribute)
                and issubclass(attribute, Handler)
                and attribute is not Handler
                and attribute.__module__ == module.__name__
                and not getattr(attribute, "__abstractmethods__", None)
            ):
                found[attribute_name] = attribute
    return found


class TestDenyingHandlerDeclaresRulesOrIsAllowlisted:
    """A handler with a Decision.DENY path must declare rules or explain why not."""

    def test_discovery_is_not_vacuous(self) -> None:
        assert _discover_deny_handler_classes(), (
            f"No handlers with the {_DENY_MARKER!r} marker were discovered. Either the "
            "marker changed or discovery broke — either way the check below would pass "
            "without examining anything."
        )

    def test_every_denying_handler_declares_rules_or_is_allowlisted(self) -> None:
        offenders = []
        for name, handler_class in sorted(_discover_deny_handler_classes().items()):
            if name in _DENY_WITHOUT_RULES_ALLOWLIST:
                continue
            try:
                instance = handler_class()
            except Exception as exc:
                offenders.append(f"{name} (failed to construct: {exc})")
                continue
            if not instance.get_rules():
                offenders.append(name)
        assert not offenders, (
            "These handlers have a Decision.DENY code path but declare no Rule objects "
            f"and are not in _DENY_WITHOUT_RULES_ALLOWLIST: {offenders}.\n\n"
            "Either implement get_rules() (see MIGRATION-PATTERN.md), or add a "
            "commented entry to _DENY_WITHOUT_RULES_ALLOWLIST explaining why the deny "
            "path genuinely needs no rule (e.g. unreachable/defensive-only)."
        )

    def test_every_allowlist_entry_names_a_real_denying_handler(self) -> None:
        stale = sorted(set(_DENY_WITHOUT_RULES_ALLOWLIST) - set(_discover_deny_handler_classes()))
        assert not stale, (
            "_DENY_WITHOUT_RULES_ALLOWLIST names handlers that no longer have a "
            f"Decision.DENY path (or no longer exist): {stale}. Remove them."
        )

    @pytest.mark.parametrize("class_name", sorted(_DENY_WITHOUT_RULES_ALLOWLIST))
    def test_every_allowlist_entry_carries_a_reason(self, class_name: str) -> None:
        reason = _DENY_WITHOUT_RULES_ALLOWLIST[class_name]
        assert len(reason.split()) >= 10, (
            f"{class_name}: the allowlist reason is too short to be an argument " f"({reason!r})."
        )

    @pytest.mark.parametrize("class_name", sorted(_DENY_WITHOUT_RULES_ALLOWLIST))
    def test_an_allowlist_entry_is_dropped_once_it_declares_rules(self, class_name: str) -> None:
        """If an allowlisted handler starts declaring rules, its entry is obsolete."""
        handler_class = _discover_deny_handler_classes().get(class_name)
        if handler_class is None:
            pytest.skip(
                "staleness is covered by test_every_allowlist_entry_names_a_real_denying_handler"
            )
        instance = handler_class()
        assert not instance.get_rules(), (
            f"{class_name} now declares rules via get_rules(), so its entry in "
            "_DENY_WITHOUT_RULES_ALLOWLIST is obsolete. Delete the entry."
        )

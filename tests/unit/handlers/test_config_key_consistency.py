"""Test config key consistency between HandlerID constants and registry.

This test ensures that HandlerID constants are the actual single source of truth
for config keys: the registry (``_get_config_key``) looks up each handler class's
HandlerID constant first, and only auto-generates a key via ``_to_snake_case``
for a class with no constant declared.
"""

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.handlers.registry import (
    _get_config_key_from_constant,
    _to_snake_case,
    iter_builtin_handler_classes,
)


class TestConfigKeyConsistency:
    """Tests for config key consistency between constants and registry."""

    def test_all_handler_constants_match_auto_generated_keys(self) -> None:
        """Test that all HandlerID.*.config_key match _to_snake_case(class_name)."""
        mismatches = []

        for attr_name in dir(HandlerID):
            if attr_name.startswith("_"):
                continue

            attr = getattr(HandlerID, attr_name)
            if not hasattr(attr, "class_name"):
                continue

            constant_key = attr.config_key
            auto_generated_key = _to_snake_case(attr.class_name)

            if constant_key != auto_generated_key:
                mismatches.append(
                    {
                        "handler": attr_name,
                        "class_name": attr.class_name,
                        "constant": constant_key,
                        "auto_generated": auto_generated_key,
                    }
                )

        # This will FAIL with current constants
        assert (
            len(mismatches) == 0
        ), f"Found {len(mismatches)} config key mismatches:\n" + "\n".join(
            f"  {m['handler']}: constant='{m['constant']}' != "
            f"auto_gen='{m['auto_generated']}' (class={m['class_name']})"
            for m in mismatches
        )

    def test_registry_should_use_handler_id_constants(self) -> None:
        """Registry looks up the HandlerID constant for each handler class and
        uses its config_key, rather than auto-generating one -- over every
        handler ``register_all`` would actually register, not a mock scenario."""
        refs = list(iter_builtin_handler_classes())
        assert refs, "iter_builtin_handler_classes() yielded nothing to check"

        fallback_used = []
        for ref in refs:
            class_name = ref.handler_cls.__name__
            constant_key = _get_config_key_from_constant(class_name)
            if constant_key is None:
                fallback_used.append(class_name)
                continue
            assert ref.config_key == constant_key, (
                f"{class_name}: registry used '{ref.config_key}', but its "
                f"HandlerID constant says '{constant_key}'"
            )

        assert not fallback_used, (
            f"{len(fallback_used)} handler(s) have no HandlerID constant and fell "
            f"back to _to_snake_case: {fallback_used}"
        )

    def test_previously_mismatched_handlers_now_fixed(self) -> None:
        """Test that previously mismatched handlers are now fixed.

        These handlers had mismatches between constants and auto-generated keys.
        After the fix, their constants now match the auto-generated keys.

        ``SESSION_CLEANUP`` was one of them and is no longer listed — the
        handler was removed in Plan 00237, so there is no constant left to
        check. The remaining entry still guards the same invariant.
        """
        previously_broken = [
            "SUGGEST_STATUSLINE",
        ]

        # Verify all previously broken handlers now have matching keys
        for handler_name in previously_broken:
            handler_meta = getattr(HandlerID, handler_name)
            auto_generated = _to_snake_case(handler_meta.class_name)

            assert handler_meta.config_key == auto_generated, (
                f"{handler_name}: constant '{handler_meta.config_key}' should match "
                f"auto-generated '{auto_generated}' (FIXED)"
            )

    def test_to_snake_case_conversion_accuracy(self) -> None:
        """Test that _to_snake_case() correctly converts class names.

        This validates the auto-generation logic is working correctly.
        """
        test_cases = [
            ("SuggestStatusLineHandler", "suggest_status_line"),
            ("QaSuppressionHandler", "qa_suppression"),
            ("DestructiveGitHandler", "destructive_git"),
            ("TddEnforcementHandler", "tdd_enforcement"),
        ]

        for class_name, expected_key in test_cases:
            actual_key = _to_snake_case(class_name)
            assert (
                actual_key == expected_key
            ), f"_to_snake_case('{class_name}') = '{actual_key}', expected '{expected_key}'"

    def test_handler_id_constants_have_required_fields(self) -> None:
        """Test that all HandlerID constants have required fields.

        Every HandlerIDMeta must have:
        - class_name (PascalCase with Handler suffix)
        - config_key (snake_case, no suffix)
        - display_name (kebab-case)
        """
        for attr_name in dir(HandlerID):
            if attr_name.startswith("_"):
                continue

            attr = getattr(HandlerID, attr_name)
            if not hasattr(attr, "class_name"):
                continue

            # All three fields must be non-empty strings
            assert (
                isinstance(attr.class_name, str) and attr.class_name
            ), f"{attr_name}.class_name must be non-empty string"
            assert (
                isinstance(attr.config_key, str) and attr.config_key
            ), f"{attr_name}.config_key must be non-empty string"
            assert (
                isinstance(attr.display_name, str) and attr.display_name
            ), f"{attr_name}.display_name must be non-empty string"

            # class_name should be PascalCase (starts with uppercase)
            assert attr.class_name[
                0
            ].isupper(), f"{attr_name}.class_name '{attr.class_name}' should be PascalCase"

            # config_key should be snake_case (no uppercase, no hyphens)
            assert (
                attr.config_key.islower()
            ), f"{attr_name}.config_key '{attr.config_key}' should be lowercase"
            assert (
                "-" not in attr.config_key
            ), f"{attr_name}.config_key '{attr.config_key}' should not contain hyphens"

            # display_name should be kebab-case (lowercase with hyphens allowed)
            assert (
                attr.display_name.islower() or "-" in attr.display_name
            ), f"{attr_name}.display_name '{attr.display_name}' should be kebab-case"

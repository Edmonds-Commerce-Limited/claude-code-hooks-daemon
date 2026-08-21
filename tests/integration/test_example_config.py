"""Test that example config exists and has correct structure.

This ensures upgrade script can reference a valid example config
when users need to replace their config due to validation errors.
"""

from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID


def _event_types_with_shipped_handlers() -> frozenset[str]:
    """Config keys of every event type that actually ships a handler module.

    Ground truth is the handler package on disk, intersected with the declared
    event registry. The intersection matters in both directions: it drops
    non-event directories that live alongside the real ones (``nitpick`` is a
    pseudo-event, ``utils`` is shared code), and it cannot invent an event the
    registry does not declare.
    """
    import claude_code_hooks_daemon.handlers as handlers_package
    from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta

    declared = {meta.config_key for meta in vars(EventID).values() if isinstance(meta, EventIDMeta)}
    handlers_root = Path(handlers_package.__file__).parent

    shipped: set[str] = set()
    for child in handlers_root.iterdir():
        if not child.is_dir() or child.name not in declared:
            continue
        if any(
            module.suffix == ".py" and not module.name.startswith("_") for module in child.iterdir()
        ):
            shipped.add(child.name)
    return frozenset(shipped)


@pytest.fixture
def example_config_path() -> Path:
    """Path to example config file."""
    return Path(__file__).parent.parent.parent / ".claude" / "hooks-daemon.yaml.example"


@pytest.fixture
def example_config(example_config_path: Path) -> dict:
    """Load and parse example config."""
    with open(example_config_path) as f:
        return yaml.safe_load(f)


def test_example_config_exists(example_config_path: Path) -> None:
    """Example config file must exist for upgrade script reference."""
    assert example_config_path.exists(), (
        "Missing .claude/hooks-daemon.yaml.example - "
        "upgrade script references this file when config validation fails"
    )


def test_example_config_valid_yaml(example_config: dict) -> None:
    """Example config must be valid YAML."""
    assert isinstance(example_config, dict)
    assert "version" in example_config
    assert "daemon" in example_config
    assert "handlers" in example_config


def test_example_config_no_self_install_mode(example_config: dict) -> None:
    """Example config should NOT have self_install_mode (only for daemon's own dogfooding)."""
    daemon_config = example_config.get("daemon", {})
    assert "self_install_mode" not in daemon_config, (
        "self_install_mode should not be in example config - "
        "it's only for the daemon's own dogfooding"
    )


def test_example_config_safety_handlers_enabled(example_config: dict) -> None:
    """Safety handlers should be enabled by default in example config."""
    pre_tool_use = example_config["handlers"]["pre_tool_use"]

    safety_handlers = [
        "destructive_git",
        "sed_blocker",
        "absolute_path",
        "curl_pipe_shell",
        "pipe_blocker",
        "dangerous_permissions",
        "git_stash",
        "lock_file_edit_blocker",
        "pip_break_system",
        "sudo_pip",
    ]

    for handler in safety_handlers:
        assert handler in pre_tool_use, f"Safety handler {handler} missing from example config"
        assert (
            pre_tool_use[handler]["enabled"] is True
        ), f"Safety handler {handler} should be enabled by default"


def test_example_config_plan_workflow_opt_in_by_default(example_config: dict) -> None:
    """F-PLANDEF: a stock install from the example must resolve plan_workflow as
    DISABLED, so it does not deploy CLAUDE/Plan/ + mkplan while the plan handlers
    ship disabled. The example carries no active top-level plan_workflow block
    (only a commented opt-in) and no per-handler track_plans_in_project, so the
    model default (False) governs.
    """
    config = Config.model_validate(example_config)
    assert config.plan_workflow.enabled is False, (
        "stock example config must leave plan workflow opt-in (disabled) so "
        "deploy matches the opt-in plan handlers"
    )


def test_example_config_no_per_handler_track_plans(example_config: dict) -> None:
    """F-PLANDIR: the example must not duplicate the plan directory in per-handler
    options — plan_workflow.directory is the single source of truth. No handler
    in the example may carry a track_plans_in_project option.
    """
    for event_type, handlers in example_config.get("handlers", {}).items():
        if not isinstance(handlers, dict):
            continue
        for handler_name, handler_cfg in handlers.items():
            if not isinstance(handler_cfg, dict):
                continue
            options = handler_cfg.get("options", {})
            if isinstance(options, dict):
                assert "track_plans_in_project" not in options, (
                    f"{event_type}.{handler_name} still carries a per-handler "
                    "track_plans_in_project; use top-level plan_workflow.directory"
                )


def test_example_config_workflow_handlers_disabled(example_config: dict) -> None:
    """Workflow handlers should be disabled by default (project-specific)."""
    pre_tool_use = example_config["handlers"]["pre_tool_use"]

    workflow_handlers = [
        "plan_number_helper",
        "plan_workflow",
        "plan_time_estimates",
        "markdown_organization",
        "tdd_enforcement",
    ]

    for handler in workflow_handlers:
        if handler in pre_tool_use:
            assert pre_tool_use[handler]["enabled"] is False, (
                f"Workflow handler {handler} should be disabled by default "
                "(project-specific configuration)"
            )


def test_example_config_covers_every_event_that_ships_a_handler(example_config: dict) -> None:
    """Every event type with a shipped handler must appear in the example config.

    The requirement is derived from the registry, not from a hardcoded list.
    The list this replaced named eleven events, three of which
    (``session_end``, ``notification``, ``subagent_stop``) ship no handler at
    all any more — their only entries had been retired. That left the test
    demanding sections the example config could fill only with a phantom
    handler or an empty key, so a STALE LIST was actively holding a false claim
    in place.

    Deriving it keeps the real intent and strengthens it: add a handler for a
    new event type and this fails until the example config covers it, with no
    list to remember to update.
    """
    handlers = example_config["handlers"]
    shipped_events = _event_types_with_shipped_handlers()

    assert shipped_events, "no shipped handlers discovered — the derivation itself is broken"

    missing = sorted(event for event in shipped_events if event not in handlers)
    assert not missing, (
        f"event type(s) {missing} ship handlers but have no section in the "
        "example config, so a new project starts with them undocumented"
    )


def test_example_config_offers_no_event_without_a_shipped_handler(example_config: dict) -> None:
    """The other direction — an event section nothing can fill is dead weight.

    Paired with the test above so the check discriminates. Without it, an
    example config could satisfy coverage while carrying empty sections for
    events whose handlers were all retired, which is how the three stale
    sections survived in the first place.
    """
    shipped_events = _event_types_with_shipped_handlers()

    orphans = sorted(event for event in example_config["handlers"] if event not in shipped_events)
    assert not orphans, (
        f"example config offers section(s) {orphans} for event type(s) that ship "
        "no handler; a user filling one in has nothing valid to name"
    )


def test_example_config_status_line_handlers_enabled(example_config: dict) -> None:
    """Status line handlers should be enabled by default."""
    status_line = example_config["handlers"]["status_line"]

    status_handlers = [
        "model_context",
        "git_branch",
        "git_repo_name",
        "daemon_stats",
        "account_display",
    ]

    for handler in status_handlers:
        assert handler in status_line, f"Status handler {handler} missing from example config"
        assert (
            status_line[handler]["enabled"] is True
        ), f"Status handler {handler} should be enabled by default"


def test_example_config_has_version_2(example_config: dict) -> None:
    """Example config should use version 2.0 format."""
    assert example_config["version"] == "2.0"


def test_example_config_input_validation_enabled(example_config: dict) -> None:
    """Input validation should be enabled by default."""
    daemon = example_config["daemon"]
    input_validation = daemon.get("input_validation", {})

    assert input_validation.get("enabled") is True
    assert input_validation.get("strict_mode") is True
    assert input_validation.get("log_validation_errors") is True


def test_example_config_includes_all_library_handlers(example_config: dict) -> None:
    """All library handlers must be present in example config (enabled or disabled).

    This test dynamically discovers all handlers from HandlerID constants
    and verifies each one is present in the example config.

    Excluded handlers:
    - Test handlers (test_server)
    """
    # Get all handler constants from HandlerID class
    all_handlers = []
    for attr_name in dir(HandlerID):
        if attr_name.startswith("_"):
            continue
        attr = getattr(HandlerID, attr_name)
        if hasattr(attr, "config_key"):
            all_handlers.append(attr.config_key)

    # Exclude test, internal, and pseudo-event handlers
    # Pseudo-event handlers (nitpick_*) are registered via pseudo_events config,
    # not the regular handlers section
    excluded_handlers = {
        "test_server",
        "dismissive_language_nitpick",
        "hedging_language_nitpick",
    }

    library_handlers = [h for h in all_handlers if h not in excluded_handlers]

    # Flatten all handlers from example config
    config_handlers = set()
    for event_type, handlers in example_config["handlers"].items():
        for handler_name in handlers.keys():
            config_handlers.add(handler_name)

    # Check each library handler is present
    missing_handlers = []
    for handler in library_handlers:
        if handler not in config_handlers:
            missing_handlers.append(handler)

    assert not missing_handlers, (
        f"Example config missing {len(missing_handlers)} library handlers:\n"
        f"{', '.join(sorted(missing_handlers))}\n\n"
        f"All library handlers must be present (enabled or disabled) "
        f"so users know what's available."
    )


def test_example_config_no_test_handlers(example_config: dict) -> None:
    """Example config should not include test handlers (test_server, etc).

    Test handlers are for development/debugging only and should not
    be in the example config that users copy.
    """
    # Flatten all handlers from example config
    config_handlers = set()
    for event_type, handlers in example_config["handlers"].items():
        for handler_name in handlers.keys():
            config_handlers.add(handler_name)

    test_handlers = [
        "test_server",
    ]

    found_test_handlers = [h for h in test_handlers if h in config_handlers]

    assert (
        not found_test_handlers
    ), f"Example config should not include test handlers: {', '.join(found_test_handlers)}"

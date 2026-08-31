"""The rule_explain package explains its no-daemon-required enumeration contract."""


def test_package_docstring_states_no_daemon_required() -> None:
    import claude_code_hooks_daemon.rule_explain as pkg

    assert pkg.__doc__ is not None
    assert "daemon" in pkg.__doc__.lower()

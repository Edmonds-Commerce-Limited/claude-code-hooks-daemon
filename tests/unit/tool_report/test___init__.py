"""The tool_report package exposes its privacy contract in its docstring."""


def test_package_docstring_states_the_privacy_contract() -> None:
    import claude_code_hooks_daemon.tool_report as pkg

    assert pkg.__doc__ is not None
    assert "names" in pkg.__doc__.lower()
    assert "never" in pkg.__doc__.lower()

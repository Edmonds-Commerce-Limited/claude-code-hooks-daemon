"""The package's public surface (Plan 00403 Phase 2).

The generator, the verification gates and the filing handler all have to agree
on what a valid report looks like — a gate that judged a report by a different
rule from the one that built it would either refuse valid reports or pass
leaking ones. So the re-export is a contract rather than a convenience, and it
is worth a test that fails when someone quietly moves one.

Named for the behaviour rather than for the file under test. The obvious name,
`test___init__.py`, collides by BASENAME with another suite's file of the same
name: neither directory is a package, so pytest derives the module name from the
basename alone and refuses to collect the second one. That failure appears only
in a whole-suite run — the file passes on its own — which is how it survived
several targeted runs (Plan 00405 N5).
"""

from __future__ import annotations

import claude_code_hooks_daemon.issue_report as issue_report
from claude_code_hooks_daemon.issue_report.reproduction import check_reproduction


class TestPublicSurface:
    def test_the_reproduction_check_is_re_exported(self) -> None:
        assert issue_report.check_reproduction is check_reproduction

    def test_dunder_all_matches_what_is_actually_exported(self) -> None:
        """``__all__`` that names something absent breaks ``from ... import *``."""
        for name in issue_report.__all__:
            assert hasattr(issue_report, name), f"__all__ names missing {name!r}"

    def test_the_package_documents_itself(self) -> None:
        assert issue_report.__doc__
        assert issue_report.__doc__.strip()

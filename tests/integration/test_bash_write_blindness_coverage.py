"""Every Write/Edit-keyed handler must carry a recorded verdict on Bash blindness.

Plan 00260. A handler that keys on the `Write` and `Edit` tools cannot see a
file that reaches disk through Bash -- `>`, `>>`, `tee`, or a `cat <<EOF`
heredoc. That is not 22 independent oversights: `core/utils.py`'s
``get_file_path()`` and ``get_file_content()`` both return ``None`` for any tool
that is not Write/Edit, so a handler *cannot* opt in even if its author wanted
to.

**The harm is not the missing check, it is the false claim.** Eight handlers
opened their resident guidance with an unqualified "Writing X is blocked".
An agent reading that treats a clean Bash write as evidence of safety, and the
inference is wrong precisely where it is most trusted. Plan 00260's own
verification confirmed live that a ``shell=True`` call and a hardcoded AWS key
land via heredoc having been denied via `Write`.

**Why a table rather than an audit.** The same argument as
``test_claude_md_guidance_coverage.py``: a hand-written sweep re-derives the
same verdicts every release and is blind to whatever it did not think to look
at. This file enumerates instead. It found ``WriteClobberGuardHandler``
immediately -- shipped one day before this test, with exactly this hole, and
absent from the hand-written map in
``CLAUDE/Plan/00260-*/BASH-BLINDSPOT-MAP.md`` because that map predates it.

**Discovery is a static source scan, not a call into ``matches()``.** Same
tradeoff the guidance-coverage file argues for and for the same reason:
constructing every handler with an input that reaches its keying decision is
not tractable, and a guard that is hard to run is a guard that gets deleted.
The cost is that a handler keying on Write/Edit through a helper in another
module would escape; no such shape exists today.

A verdict here is a statement about REACHABILITY, not about whether the gap is
worth closing. Ranking and remedy live in the plan.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.handler import Handler

# Source markers that mean "this handler keys on the Write/Edit tools".
# `get_file_path`/`get_file_content` are included because they enforce the
# tool-name test on the handler's behalf -- a handler calling either is keyed
# whether or not it names the tools itself.
_WRITE_EDIT_KEYING_MARKERS = (
    "ToolName.WRITE",
    "ToolName.EDIT",
    "get_file_path",
    "get_file_content",
)

# Verdicts. BLIND = a Bash write can violate the guarded premise and nothing
# sees it. PARTIAL = some Bash routes are covered. COVERED = every route that
# can violate the premise is seen. OUT-OF-FRAME = the premise is not about a
# file reaching disk, so a write detector would not help.
#
# COVERED is NOT "sees every possible command". `cp`/`mv`/`install`/`dd` are
# excluded from the content guards on purpose (Plan 00260 Task 3.5): those
# relocate bytes that were already on disk, so a linter denying them would
# report a defect the command did not introduce. The premise a linter guards is
# "content this command AUTHORED is well-formed", and every authoring route is
# seen.
_BLIND = "BLIND"
_PARTIAL = "PARTIAL"
_COVERED = "COVERED"
_OUT_OF_FRAME = "OUT-OF-FRAME"

# Source markers that mean "this handler resolves what a Bash command writes".
# A COVERED row must show one; a BLIND row must show none.
_BASH_WRITE_ACCESSORS = (
    "get_written_file_paths",
    "get_bash_write_targets",
)

_VALID_VERDICTS = (_BLIND, _PARTIAL, _COVERED, _OUT_OF_FRAME)

_BASH_BLINDNESS_VERDICT: dict[str, tuple[str, str]] = {
    "FlaggableWorkAdvisorHandler": (
        _PARTIAL,
        "a Bash command MENTIONING a flaggable path is matched by token glob "
        "scan (Plan 00278), so cat/grep/git over those paths still advise; "
        "but the topic-term route sees only tool_input text, so flaggable "
        "vocabulary reaching disk via heredoc body is not scanned. Advisory "
        "only -- the resident guidance names the routes it covers",
    ),
    "AbsolutePathHandler": (
        _OUT_OF_FRAME,
        "premise is about a TOOL ARGUMENT being absolute, not a file on disk; "
        "relative paths in Bash are normal, so a Bash-aware version would have "
        "to block `ls src/`",
    ),
    "DaemonDocsGuardHandler": (
        _OUT_OF_FRAME,
        "guards a READ path -- `cat .claude/hooks-daemon/CLAUDE/...` is invisible "
        "to it, but closing that needs a read-target detector, not a write one",
    ),
    "BritishEnglishHandler": (
        _BLIND,
        "prose written by heredoc into CLAUDE/ or docs/ is never scanned; "
        "advisory-only, and it publishes no resident guidance to be wrong",
    ),
    "CommentChangelogHandler": (
        _BLIND,
        "a comment carrying changelog narrative lands unexamined via heredoc",
    ),
    "CommentSizeHandler": (
        _BLIND,
        "an over-limit comment lands unexamined; its grow/shrink tiering also "
        "needs a before-state that a Bash payload does not carry",
    ),
    "ErrorHidingBlockerHandler": (
        _BLIND,
        "confirmed live in Plan 00260: an error-suppression idiom denied via "
        "Write lands via heredoc, and the clean write reads as a safety signal",
    ),
    "LintOnEditHandler": (
        _COVERED,
        "closed in Plan 00260 Task 3.5: every AUTHORING route (redirect, `tee`, "
        "heredoc) is linted via `get_written_file_paths`, so a heredoc can no "
        "longer land unparseable source in silence. Relocation (`cp`/`mv`/"
        "`install`/`dd`) is excluded by design, not by oversight -- see the "
        "COVERED note above",
    ),
    "GoalInjectionHandler": (
        _BLIND,
        "a PLAN.md status flip written by heredoc/redirect never fires the "
        "goal-intent signal; acceptable because the miss costs an optional "
        "advisory convenience (no goal injected), never a protection, and the "
        "inject-goal CLI fallback covers it on demand",
    ),
    "SecretFileGuardHandler": (
        _PARTIAL,
        "Plan 00272: the Write/Edit content scan (authored scripts referencing "
        "a protected path) has no Bash-write counterpart, but the Bash surface "
        "is judged by COMMAND TEXT instead -- a heredoc/redirect authoring such "
        "a script necessarily MENTIONS the protected path and is denied by the "
        "path-mention rule before the write happens, so the practical gap is "
        "only a path assembled from strings inside the heredoc body (already a "
        "documented class-(d) residual)",
    ),
    "LockFileEditBlockerHandler": (
        _BLIND,
        "a hand-written lock file lands via heredoc; damage surfaces at install "
        "time on someone else's machine; PATH-only, so cheap to close",
    ),
    "MarkdownOrganizationHandler": (
        _PARTIAL,
        "narrowed in Plan 00260 Task 3.4 and still PARTIAL for two different "
        "reasons. The memory-path rule now uses `get_bash_write_targets`, so "
        "`>|`, `dd of=`, `cp`/`mv`/`install`, every `tee` operand and quoted "
        "paths with spaces are covered; what remains uncovered there is a "
        "target the daemon cannot resolve (a variable or a glob) -- declined "
        "deliberately, because a wrong path would make a guard judge the wrong "
        "file. The markdown-LOCATION rule, by contrast, is still fully blind: "
        "it has no bash detection at all",
    ),
    "MarkdownTableFormatterHandler": (
        _BLIND,
        "tables written by heredoc are never reformatted; PATH-only, and the "
        "consequence is cosmetic drift rather than an unenforced rule",
    ),
    "DocsQaEditHandler": (
        _BLIND,
        "mitigated, not closed: `docs_qa_sweep` re-checks the whole doc "
        "corpus at session start regardless of how a file reached disk, "
        "the same batch-equivalent mitigation `plan_qa_edit` relies on",
    ),
    "PlanQaEditHandler": (
        _BLIND,
        "mitigated, not closed: `plan_qa_sweep` re-checks plan documents at "
        "session start on both surfaces, which is the batch equivalent Core "
        "Standard 15 asks for and that most rows here lack",
    ),
    "PlanTimeEstimatesHandler": (
        _BLIND,
        "same mitigation as `plan_qa_edit` -- the session sweep re-reads plan "
        "documents regardless of how they were written",
    ),
    "PlanWorkflowHandler": (
        _BLIND,
        "a PLAN.md created by heredoc never surfaces the workflow contract; "
        "advisory, so the cost is a missed prompt rather than an unenforced rule",
    ),
    "QaSuppressionHandler": (
        _BLIND,
        "worst of the content class: the written artefact is itself a blinding "
        "device, so QA then goes green BECAUSE of the thing that should have "
        "been blocked -- every other row leaves the problem detectable later",
    ),
    "RecoveryCronAdvisorHandler": (
        _PARTIAL,
        "plan CREATION via `mkplan.bash` is already detected from the Bash "
        "command; progress and completion detection need file content",
    ),
    "SecurityAntipatternHandler": (
        _BLIND,
        "confirmed live in Plan 00260: a `shell=True` call and a hardcoded AWS "
        "key both land via heredoc having been denied via Write",
    ),
    "SedBlockerHandler": (
        _PARTIAL,
        "incidentally, not by design: `_SED_WITH_EXECUTION_FLAG` is unanchored, "
        "so a flagged stream editor inside a heredoc body is matched and the "
        "Write-branch premise is upheld by accident; the flagless form is missed",
    ),
    "SensitiveContentHandler": (
        _BLIND,
        "highest severity: git metadata IS covered, file contents are not, so a "
        "term entering by heredoc is reported by nothing -- and once pushed it "
        "needs a history rewrite, which this repository has already had to do",
    ),
    "TddEnforcementHandler": (
        _BLIND,
        "the gate can only ever fire at creation, and once the file exists by "
        "the Bash route it can never fire for that file again; no batch "
        "equivalent walks the tree for untested source",
    ),
    "ValidateEslintOnWriteHandler": (
        _COVERED,
        "closed in Plan 00260 Task 3.5 alongside `lint_on_edit`: a `.ts`/`.tsx` "
        "file authored by a redirect, `tee` or a heredoc is ESLint-checked. "
        "Relocation is excluded by design",
    ),
    "ValidateInstructionContentHandler": (
        _BLIND,
        "and it is the Task 3.1a ALLOW-trap: `handle()` returns an explicit "
        "Decision.ALLOW for any tool that is not Write/Edit, so routing a Bash "
        "event here path-only would manufacture a POSITIVE all-clear -- "
        "strictly worse than the current silence",
    ),
    "WriteClobberGuardHandler": (
        _BLIND,
        "found by this test, not by the hand-written map that predates it: "
        "`cat > file` overwrites an unread file with no guard, so the guard "
        "shipped with the hole its own premise is about",
    ),
    "QuarantineArtefactReadGuardHandler": (
        _PARTIAL,
        "Plan 00278 Phase 3d.2: Write is never checked at the tool level at "
        "all -- authoring the DETAIL artefact is deliberately allowed via ANY "
        "route (Write tool or `cat > file <<EOF`), so there is no Write-side "
        "premise to violate. Edit is denied because editing requires reading "
        "old content; its Bash counterpart is judged by COMMAND TEXT via the "
        "revealing-bash-verb scan (cat/head/tail/less/grep family/interpreter "
        "one-liners), so cat/grep of the artefact via Bash IS caught -- but a "
        "verb outside that fixed list, or a wrapper script opening the file "
        "internally, is not (same honest-limits shape as SecretFileGuardHandler)",
    ),
}

# Handlers whose resident guidance opened with an unqualified "Writing X is
# blocked". The claim is FALSE for the Bash route, so each was corrected to
# name the route it actually covers. Correcting the claim costs no extra words;
# appending a disclaimer to a false sentence would have left the lie in place.
_CORRECTED_UNIVERSAL_CLAIM = (
    "CommentChangelogHandler",
    "ErrorHidingBlockerHandler",
    "PlanTimeEstimatesHandler",
    "QaSuppressionHandler",
    "SecurityAntipatternHandler",
    "SensitiveContentHandler",
    "TddEnforcementHandler",
    "ValidateInstructionContentHandler",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so every handler can be CONSTRUCTED.

    Several handlers call ``project_root()`` from ``__init__`` and raise
    without it. They must be constructed rather than skipped -- a handler that
    drops out of discovery is precisely the silent escape this file prevents.

    Function-scoped on purpose: the root ``conftest.py`` resets the singleton
    after every test, so a module-scoped setup would serve only the first.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _discover_write_edit_keyed_handlers() -> dict[str, type[Handler]]:
    """Concrete handlers whose module keys on the Write/Edit tools."""
    found: dict[str, type[Handler]] = {}
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        try:
            source = inspect.getsource(module)
        except OSError:
            continue
        if not any(marker in source for marker in _WRITE_EDIT_KEYING_MARKERS):
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


class TestEveryKeyedHandlerHasAVerdict:
    """The enumeration itself. A new handler cannot join silently."""

    def test_discovery_finds_handlers_at_all(self) -> None:
        """Vacuity guard: an empty discovery would make every test below pass blind."""
        assert _discover_write_edit_keyed_handlers(), (
            "No Write/Edit-keyed handlers discovered. Either the keying markers "
            f"changed ({_WRITE_EDIT_KEYING_MARKERS}) or discovery is broken -- in "
            "both cases the coverage check below would pass while checking nothing."
        )

    def test_no_keyed_handler_lacks_a_recorded_verdict(self) -> None:
        discovered = set(_discover_write_edit_keyed_handlers())

        missing = sorted(discovered - set(_BASH_BLINDNESS_VERDICT))

        assert not missing, (
            "These handlers key on the Write/Edit tools but carry no recorded "
            f"verdict about whether a Bash write can reach past them: {missing}.\n\n"
            "A file written with `>`, `>>`, `tee` or a `cat <<EOF` heredoc does not "
            "produce a Write/Edit event, so the handler never runs. Decide which it "
            f"is -- {_BLIND}, {_PARTIAL} or {_OUT_OF_FRAME} -- and record it in "
            "_BASH_BLINDNESS_VERDICT with the reason.\n\n"
            "If the handler's resident guidance claims to block something "
            "unconditionally, that claim is now false and must be corrected to name "
            "the route it covers. See CLAUDE/Plan/00260-*/BASH-BLINDSPOT-MAP.md."
        )

    def test_the_verdict_table_names_only_real_handlers(self) -> None:
        discovered = set(_discover_write_edit_keyed_handlers())

        stale = sorted(set(_BASH_BLINDNESS_VERDICT) - discovered)

        assert not stale, (
            f"_BASH_BLINDNESS_VERDICT names handlers that no longer key on "
            f"Write/Edit (or no longer exist): {stale}. Remove the stale rows -- a "
            "table that drifts from the code is worse than no table."
        )

    @pytest.mark.parametrize("class_name", sorted(_BASH_BLINDNESS_VERDICT))
    def test_each_verdict_is_valid_and_argued(self, class_name: str) -> None:
        verdict, reason = _BASH_BLINDNESS_VERDICT[class_name]

        assert verdict in _VALID_VERDICTS, f"{class_name}: unknown verdict {verdict!r}"
        assert len(reason.split()) >= 8, (
            f"{class_name}: the reason is too short to be an argument ({reason!r}). "
            "A bare verdict records that someone typed a word, not that the question "
            "was asked."
        )


class TestTheVerdictMatchesTheSource:
    """The table must not be able to drift from the code again.

    This exists because it already did. Plan 00260 Task 3.5 wired
    `lint_on_edit` and `validate_eslint_on_write` to Bash-authored files, and
    every test in this file kept passing while both rows still read BLIND --
    the census recorded a judgement made by hand and never re-checked it
    against the source. A hand-maintained table that silently goes stale is the
    same defect this whole file was written to catch, one level up.

    Only the two unambiguous verdicts are bound. PARTIAL is deliberately left
    alone: those handlers reach Bash by unrelated mechanisms -- a `mkplan.bash`
    command check, an unanchored regex that matches inside a heredoc body by
    accident -- so requiring the accessor there would assert a false uniformity.
    """

    @staticmethod
    def _source_of(class_name: str) -> str:
        handler_class = _discover_write_edit_keyed_handlers()[class_name]
        return inspect.getsource(importlib.import_module(handler_class.__module__))

    @pytest.mark.parametrize(
        "class_name",
        sorted(name for name, (v, _) in _BASH_BLINDNESS_VERDICT.items() if v == _COVERED),
    )
    def test_a_covered_handler_actually_reads_bash_write_targets(self, class_name: str) -> None:
        source = self._source_of(class_name)

        assert any(marker in source for marker in _BASH_WRITE_ACCESSORS), (
            f"{class_name} is recorded as {_COVERED}, but its module calls none of "
            f"{_BASH_WRITE_ACCESSORS}. Either the wiring was removed and the row is "
            "now a false claim of safety, or the verdict was never true."
        )

    @pytest.mark.parametrize(
        "class_name",
        sorted(name for name, (v, _) in _BASH_BLINDNESS_VERDICT.items() if v == _BLIND),
    )
    def test_a_blind_handler_has_not_been_quietly_wired(self, class_name: str) -> None:
        source = self._source_of(class_name)
        wired = [marker for marker in _BASH_WRITE_ACCESSORS if marker in source]

        assert not wired, (
            f"{class_name} is recorded as {_BLIND}, but its module now calls {wired}. "
            "The row is stale: update it (and the handler's resident guidance, which "
            "will still be describing a Write/Edit-only surface)."
        )


class TestTheFalseClaimsWereCorrected:
    """The harm was the unqualified claim, so the claim is what must change."""

    @staticmethod
    def _claim_paragraph(guidance: str) -> str:
        """The first prose paragraph, i.e. everything after the `## heading`."""
        parts = [block for block in guidance.split("\n\n") if block.strip()]
        return parts[1] if len(parts) > 1 else ""

    @pytest.mark.parametrize("class_name", sorted(_CORRECTED_UNIVERSAL_CLAIM))
    def test_the_opening_claim_names_the_route_it_covers(self, class_name: str) -> None:
        handler = _discover_write_edit_keyed_handlers()[class_name]()
        guidance = handler.get_claude_md() or ""
        claim = self._claim_paragraph(guidance)

        assert "Write" in claim or "Edit" in claim, (
            f"{class_name}'s resident guidance opens with an unqualified claim:\n\n"
            f"    {claim}\n\n"
            "That is FALSE for a file written through Bash, which this handler never "
            "sees. An agent reading it treats a clean Bash write as evidence of "
            "safety. Name the route the guard actually covers (`Write`/`Edit`) rather "
            "than appending a disclaimer to a sentence that is wrong."
        )


class TestTheTwoSectionsThatImplyBashCoverage:
    """Two sections do not merely omit the gap — they imply it is closed.

    Correcting an opening claim tells a reader what a guard covers. It does not
    undo a section that goes on to DESCRIBE Bash handling, because the reader
    then concludes the Bash surface was considered and dealt with. These two
    are the only sections in the block that do that, which is why they earn an
    explicit sentence where the other twenty do not.
    """

    def test_sensitive_content_names_the_file_write_gap(self) -> None:
        """It documents git-metadata Bash coverage, so silence reads as completeness.

        Ranked worst in the plan's severity list: a term entering by heredoc is
        reported by nothing, and once pushed it needs a history rewrite — which
        this repository has already had to perform once.
        """
        handler = _discover_write_edit_keyed_handlers()["SensitiveContentHandler"]()
        guidance = handler.get_claude_md() or ""

        assert "writes a FILE is NOT checked" in guidance, (
            "sensitive_content's guidance explains that Bash commands recording git "
            "METADATA are checked, without saying that a Bash command writing a FILE "
            "is not. A reader concludes the Bash surface is handled. It is the one "
            "section where that inference costs the most, so the gap must be named."
        )

    def test_markdown_organization_admits_its_bash_coverage_is_partial(self) -> None:
        """It claims bash side-doors are closed; the claim must stay bounded.

        This assertion was INVERTED by Task 3.4 and is worth the note. It used
        to require that `cp`, `mv`, `dd of=` and `>|` were named in the
        guidance as UNCOVERED. Those spellings are now covered, and the
        rewritten guidance still names all four -- as things it detects -- so
        the old substring checks kept passing while asserting the opposite of
        the truth. A test that passes for the wrong reason is worse than one
        that fails, because nothing ever revisits it.

        So it now pins what is still MISSING, which is the claim a reader can
        actually be misled by.
        """
        handler = _discover_write_edit_keyed_handlers()["MarkdownOrganizationHandler"]()
        guidance = handler.get_claude_md() or ""

        if "bash" not in guidance.lower():
            pytest.skip("project allows untracked Claude memory; the claim is not made")

        assert "not every route" in guidance, (
            "markdown_organization must not present its bash coverage as total. "
            "It is wide now, but a target the daemon cannot resolve is still "
            "declined by design, and a policy believed to be fully enforced is "
            "trusted more than it deserves."
        )
        assert "variable" in guidance, (
            "the specific uncovered shape -- an unresolvable target such as a "
            "variable -- must be named, not merely gestured at."
        )
        assert "LOCATION" in guidance, (
            "the markdown-LOCATION rule has no bash detection at all. That is "
            "the larger blind spot of the two and the guidance must say so, "
            "rather than letting the memory rule's coverage imply it."
        )


class TestTheClassWideBoundaryIsStatedOnce:
    """One shared statement, not 22 copies of it.

    Correcting each false claim tells a reader what a guard DOES cover; it does
    not tell them the class-wide fact that Bash writes are unguarded generally.
    That belongs in the guidance block's shared intro -- emitted once, read
    first, and costing every client project one paragraph rather than 22.
    """

    @staticmethod
    def _intro() -> str:
        from claude_code_hooks_daemon.core.claude_md_injector import ClaudeMdInjector

        return ClaudeMdInjector._build_section([])

    def test_the_intro_states_that_bash_writes_are_unchecked(self) -> None:
        intro = self._intro()

        for token in ("Bash", "heredoc"):
            assert token in intro, (
                f"The shared guidance intro does not mention {token!r}. Every "
                "content guard in this block keys on Write/Edit, so a reader who "
                "is not told about the Bash route will assume coverage that does "
                "not exist."
            )

    def test_the_intro_does_not_overclaim_in_the_other_direction(self) -> None:
        """Bash-command guards are unaffected; the intro must not imply otherwise.

        `destructive_git`, `sed_blocker` and `pipe_blocker` judge the command
        itself and lose nothing. An intro that read "the guards do not see Bash"
        would be its own false claim, and a more dangerous one.
        """
        intro = self._intro()

        assert "destructive" in intro or "command" in intro, (
            "The intro warns that Bash writes bypass the content guards but does "
            "not say which guards are unaffected. A reader could conclude that "
            "Bash is unguarded generally, which is false and more dangerous than "
            "the gap being described."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

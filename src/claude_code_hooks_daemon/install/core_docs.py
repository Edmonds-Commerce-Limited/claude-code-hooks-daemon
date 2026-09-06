"""Deploy the daemon's core documents, and seed a project's overrides (Plan 00334).

The daemon can be configured to enforce a workflow whose documentation it never
creates. ``plan_workflow.enabled: true`` makes ``workflow_docs`` default to
``CLAUDE/PlanWorkflow.md``, the handler tells the agent to read that file, and
until this module existed no install path produced it. A fresh client project
enforced a workflow against a document that did not exist. The same shape left
``worktree_file_copy``'s BLOCKING rule text pointing at ``CLAUDE/Worktree.md``,
equally absent.

Two documents per subject, and the split is the whole design
------------------------------------------------------------

``CLAUDE/core/<Name>.core.md``
    DAEMON-owned. Replaced wholesale on every deploy, exactly like
    ``mkplan.bash``, so an upstream improvement reaches every existing install
    on upgrade. Must never be hand-edited: the next deploy discards the edit.

``CLAUDE/<Name>.md``
    CLIENT-owned. Written once and never touched again, exactly like
    ``_TEMPLATE_.md``. Opens by referencing its core document, then carries
    whatever the project wants to add.

Collapsing these into one file fails whichever way it is done, which is why
there are two. A single client-owned document strands every existing client on
the version it was seeded with, because a deploy must never clobber a
customised file -- upstream fixes could then never reach anyone. A single
daemon-owned document destroys the client's customisation on every upgrade.
Separating them stops the refresh path and the customisation path competing for
the same file.

The vocabulary is not invented here: ``install/plan_workflow.py`` already
distinguishes DAEMON-owned from CLIENT-owned assets and states the rule for
each. This module applies it to documentation.

Why the core document is COPIED rather than referenced in place
---------------------------------------------------------------

A client install already contains this whole repository at
``.claude/hooks-daemon/``, so a reference could point there instead. That path
differs between client mode and self-install mode, where the daemon root IS the
project root -- and ``utils/cli_command`` documents at length what that
difference costs: it shipped a documented command that expanded to
``-m: command not found``, and agents concluded the package was broken and
tried to "repair" working installations. One copy makes one path correct in
both modes.

The consequence worth stating: this repository receives the same deployment a
client does. That is what makes the dogfooding real rather than a parallel copy
that drifts -- and drift here is not hypothetical. Plan 00211 found a concept
that lived in this project's own ``CLAUDE/PlanWorkflow.md`` for a long time and
never reached the client-facing deployed guidance, and its parity guard
explicitly records that a general drift checker was out of scope. Sharing one
document is that general fix.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_TEMPLATES_DIR_NAME: Final[str] = "templates"
_CORE_TEMPLATES_DIR_NAME: Final[str] = "core"

#: Where core documents land in a project, relative to its root. A sibling
#: directory rather than a filename convention, so ``ls CLAUDE/`` visibly
#: separates "ours to edit" from "the daemon's, do not touch".
CORE_DOCS_DIR: Final[str] = "CLAUDE/core"

#: Where the client-owned override documents land.
PROJECT_DOCS_DIR: Final[str] = "CLAUDE"

#: ``CORE_DOCS_DIR`` relative to an override document's own location. The
#: override sits in ``CLAUDE/`` and its core in ``CLAUDE/core/``, so a link
#: between them is one segment, not the full path.
_CORE_DIR_BASENAME: Final[str] = _CORE_TEMPLATES_DIR_NAME

#: Suffix marking a daemon-owned core document.
CORE_SUFFIX: Final[str] = ".core.md"

#: Regular file, no execute bit -- matches the project's 644 guidance for
#: non-executable deployed assets (contrast ``mkplan.bash``'s 755).
_DOC_MODE: Final[int] = 0o644

#: Directory mode, set EXPLICITLY rather than left to ``mkdir``.
#:
#: ``mkdir`` lands on ``0o777 & ~umask``, which is the installing process's
#: umask -- not a decision anyone made about these documents. Under a 077 umask
#: that is 0o700, and a 644 file inside a 700 directory is still unreadable to
#: everyone but the owner. A daemon installing as one user while a developer
#: works as another is the ordinary case, and the resulting symptom ("the
#: documents are not there") points away from the actual cause.
_DIR_MODE: Final[int] = 0o755

#: The core documents this daemon ships, by base name. Each entry produces a
#: daemon-owned ``CLAUDE/core/<name>.core.md`` and, when absent, a client-owned
#: ``CLAUDE/<name>.md`` that references it.
#:
#: A name belongs here when daemon guidance NAMES the client document: a path
#: quoted to a reader is a promise the daemon makes, so it must be one the
#: daemon also keeps. ``tests/unit/install/test_core_doc_deployment.py`` pins
#: that correspondence.
CORE_DOC_NAMES: Final[tuple[str, ...]] = (
    "PlanWorkflow",
    "Worktree",
)


@dataclass
class CoreDocsResult:
    """Outcome of a core-docs deploy."""

    success: bool = True
    refreshed_core: list[str] = field(default_factory=list)
    seeded_overrides: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def core_template_path(name: str) -> Path:
    """Absolute path to a bundled core document template.

    Args:
        name: Base name, e.g. ``"PlanWorkflow"``.
    """
    return (
        Path(__file__).resolve().parent
        / _TEMPLATES_DIR_NAME
        / _CORE_TEMPLATES_DIR_NAME
        / f"{name}{CORE_SUFFIX}"
    )


def core_reference_line(name: str) -> str:
    """The line a project's override document uses to point at its core.

    A plain markdown link, NOT an ``@``-import, and the distinction was
    contested rather than assumed. ``@path`` is Claude Code's CLAUDE.md import
    syntax and it is the obvious spelling for "read this first", but this
    project's R6 prohibits it outside the resident set because ``@``-imports
    re-inline eagerly and defeat progressive disclosure. The ``at-import-census``
    check offers an allowlist escape hatch expressly limited to "a deliberately
    always-loaded file" -- which a core document is not: it is read on demand,
    when an agent is told to. Taking the hatch would have declared these files
    resident to silence a check that was right.

    Nothing is lost by the link. The ``@`` would not have been a mechanism
    here either: it auto-resolves only inside a CLAUDE.md chain, and these
    documents sit outside one, so in both spellings the forced read is a
    convention an agent follows. What actually enforces it is
    ``test_core_doc_deployment.py``, which fails if an override stops
    referencing its core -- an unverified convention being indistinguishable
    from a broken one until someone reads the file.

    The link is relative to the override document's own location
    (``CLAUDE/X.md`` -> ``core/X.core.md``), which R6 permits as a
    verified-relative link and which resolves in a client project regardless
    of where its repository sits.
    """
    return f"[{CORE_DOCS_DIR}/{name}{CORE_SUFFIX}]({_CORE_DIR_BASENAME}/{name}{CORE_SUFFIX})"


def override_seed_content(name: str) -> str:
    """Initial body for a project's own (client-owned) document.

    Deliberately almost empty. It exists to make the core document reachable
    and to give project-specific guidance somewhere to go; anything more would
    be daemon content sitting in a file the daemon must never touch again.
    """
    return (
        f"# {name}\n"
        "\n"
        f"**Read first:** {core_reference_line(name)} — the daemon's core\n"
        "guidance for this subject, and the baseline everything below extends.\n"
        "\n"
        f"That file is DAEMON-owned: it is overwritten wholesale on every\n"
        "daemon upgrade, so never edit it and never copy its content here. A\n"
        "second copy is how the two drift apart, which is the failure this\n"
        "split exists to prevent.\n"
        "\n"
        "## Project-specific additions\n"
        "\n"
        "This file is yours. The daemon seeds it once and never modifies it\n"
        "again, so anything you add below survives every upgrade.\n"
    )


def deploy_core_docs(project_root: Path) -> CoreDocsResult:
    """Refresh daemon-owned core documents and seed client-owned overrides.

    Idempotent, and safe on every install and upgrade: core documents are
    overwritten unconditionally, override documents are created only when
    absent.

    Args:
        project_root: Absolute path to the project root.

    Returns:
        CoreDocsResult naming what was refreshed and what was seeded.
    """
    result = CoreDocsResult()

    core_dir = project_root / CORE_DOCS_DIR
    docs_dir = project_root / PROJECT_DOCS_DIR
    core_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    core_dir.chmod(_DIR_MODE)

    for name in CORE_DOC_NAMES:
        template = core_template_path(name)
        if not template.is_file():
            # A packaging defect, not a client problem: the bundle shipped
            # without a template its own manifest names. Reported at ERROR and
            # in the messages, but it does NOT fail the deploy -- the caller is
            # the plan-workflow bootstrap, and taking down mkplan.bash and the
            # plan directory over a missing document would trade the tooling
            # for the documentation about it.
            #
            # Nothing is being hidden by that choice: the case is caught at
            # BUILD time by test_core_docs.py's manifest-completeness check,
            # which is where a packaging defect belongs rather than in a
            # client's install output.
            result.messages.append(f"Core template missing from the bundle: {template.name}")
            logger.error("Core doc template not found: %s", template)
            continue

        _refresh_core_doc(template, core_dir, name, result)
        _seed_override_doc(docs_dir, name, result)

    return result


def _refresh_core_doc(template: Path, core_dir: Path, name: str, result: CoreDocsResult) -> None:
    """Copy the bundled core document over any existing one.

    Daemon-owned, so this overwrites without asking -- the same contract as
    ``mkplan.bash``. It is what lets an upstream correction reach an install
    that was set up long ago.
    """
    target = core_dir / f"{name}{CORE_SUFFIX}"
    shutil.copy2(template, target)
    target.chmod(_DOC_MODE)
    result.refreshed_core.append(target.name)
    result.messages.append(f"Refreshed {CORE_DOCS_DIR}/{target.name} (daemon-owned)")


def _seed_override_doc(docs_dir: Path, name: str, result: CoreDocsResult) -> None:
    """Create the project's own document, only when it does not exist.

    Client-owned. An existing file is left completely alone -- including one a
    project wrote itself before the daemon ever shipped a core version, which
    is the case that makes an unconditional write unacceptable.
    """
    target = docs_dir / f"{name}.md"
    if target.exists():
        result.messages.append(f"{PROJECT_DOCS_DIR}/{target.name} already exists (kept)")
        return

    target.write_text(override_seed_content(name), encoding="utf-8")
    target.chmod(_DOC_MODE)
    result.seeded_overrides.append(target.name)
    result.messages.append(f"Created {PROJECT_DOCS_DIR}/{target.name} (yours -- customise freely)")

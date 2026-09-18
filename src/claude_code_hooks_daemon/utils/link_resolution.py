"""Does a markdown link point at a file that exists? One answer, two callers.

Docs QA's ``pointer-resolves`` and plan QA's ``plan-link-resolves`` both ask
this. They were written months apart and answered it differently: docs QA
accepted a link written from the REPOSITORY ROOT as well as one written
relative to the file, plan QA only the latter. So the same link in the same
repository was fine to one check and a defect to the other.

The rule lives here so there is nothing to drift. It is deliberately about
FILE EXISTENCE only — no anchor resolution, no judgement about whether the
link should have been written differently. What each check does with the
answer stays that check's business.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.authored_paths import contained_authored_path


def _exists_within(base: Path, target: str, root: Path) -> bool:
    """Whether ``target`` resolves from ``base`` AND lands inside ``root``.

    Containment is the half a plain existence check does not do, and the half
    both callers need. A link target is AUTHORED, and a plain existence answer
    over it is an ORACLE: ``[x](/etc/passwd)`` needs no ``..`` to escape,
    because pathlib discards the base for an absolute right operand, and
    whether a finding appears then tells the reader whether that host path
    exists.

    ``base`` and ``root`` differ on purpose. A link resolves relative to its
    own DOCUMENT, so ``../sibling.md`` legitimately leaves the document's
    directory — it is leaving the REPOSITORY that is the hazard.
    """
    resolved = contained_authored_path(base, target, within=root)
    return resolved is not None and resolved.exists()


def link_resolves_literally(project_root: Path, source_dir: Path | None, target: str) -> bool:
    """Whether ``target`` exists at a path it can reasonably be read as naming.

    ``source_dir`` is the directory of the document the link was written in,
    or ``None`` when there is no such directory to resolve against.

    A leading ``/`` is ambiguous between two conventions this project's docs
    both use: a fully-qualified absolute filesystem path, and GitHub-style
    repo-root-relative shorthand. The literal path is tried FIRST, because
    naively stripping the slash and joining under ``project_root`` DOUBLES the
    root segment when ``project_root`` genuinely is the prefix, and falsely
    reports a real file as missing.

    Otherwise relative-to-the-document is tried first, then relative-to-root
    as a fallback — a plain link written without a leading ``/`` commonly means
    "from the repo root" in this project's own docs.
    """
    file_target = target.split("#", 1)[0]
    if not file_target:
        return True
    if file_target.startswith("/"):
        if _exists_within(project_root, file_target, project_root):
            return True
        return _exists_within(project_root, file_target.lstrip("/"), project_root)
    if source_dir is not None and _exists_within(source_dir, file_target, project_root):
        return True
    return _exists_within(project_root, file_target, project_root)

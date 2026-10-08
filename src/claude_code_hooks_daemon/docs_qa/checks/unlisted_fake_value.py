"""Check ``unlisted-fake-value`` (EDIT and SWEEP; Plan 00492, owner ruling D1).

Docs may use any fake value on the project's registry
(:data:`~claude_code_hooks_daemon.utils.fake_values.REGISTRY_RELATIVE_PATH`),
and anything that LOOKS like a fake but is not on it is a finding: use a
listed fake, or extend the registry for a genuinely new kind.

What counts as fake-looking is the registry's own, per kind (``fake_looking``).
A value that merely looks real is not this check's business: the
``sensitive_content`` guard judges those, and a registry kind with no
``fake_looking`` regex is never swept for.

A vendored page (one that opens with provenance frontmatter) cannot be edited,
so its remedy is to capture it again: ``remote-docs add --force`` swaps the
unlisted fakes for listed ones and records the swap in the provenance.

**Severity is ADVISE.** A missing registry is silent: a project that keeps
none has declared no fakes. A registry that cannot be parsed is reported once
against the registry file, never silently read as empty.
"""

import logging
from typing import Final

from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.remote_docs.provenance import parse_provenance
from claude_code_hooks_daemon.utils.authored_paths import authored_path
from claude_code_hooks_daemon.utils.fake_values import (
    REGISTRY_RELATIVE_PATH,
    FakeValuesError,
    FakeValuesRegistry,
    load_fake_values,
)
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

logger = logging.getLogger(__name__)

CHECK_ID: Final[str] = "unlisted-fake-value"

_MARKDOWN_SUFFIX: Final[str] = ".md"

_REMEDY_DOC: Final[str] = (
    f"Use a listed fake from `{REGISTRY_RELATIVE_PATH}`, or extend that file for a "
    "genuinely new kind of fake."
)
_REMEDY_VENDORED: Final[str] = (
    "This is a vendored page and must not be edited by hand. Capture it again with "
    f"`bin/hooks-daemon remote-docs add --force <source_url>`, which swaps unlisted fakes "
    f"for the listed ones in `{REGISTRY_RELATIVE_PATH}` and records the swap in provenance."
)


def _registry_finding(error: FakeValuesError) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=f"The fake-values registry cannot be read, so no fake can be judged: {error}",
        remediation=f"Fix `{REGISTRY_RELATIVE_PATH}` so it follows the registry schema.",
        path=REGISTRY_RELATIVE_PATH,
    )


def _unreadable_finding(rel_path: str, error: Exception) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=f"`{rel_path}` could not be read, so its fake values were not judged: {error}",
        remediation=(
            f"Make `{rel_path}` readable UTF-8 text, or move it out of the documentation tree."
        ),
        path=rel_path,
    )


def _findings_for(rel_path: str, content: str, registry: FakeValuesRegistry) -> list[Finding]:
    vendored = parse_provenance(content).ok
    findings: list[Finding] = []
    for number, line in enumerate(content.splitlines(), start=1):
        for kind, value in registry.unlisted_fake_looking(line):
            findings.append(
                Finding(
                    check_id=CHECK_ID,
                    severity=Severity.ADVISE,
                    message=(
                        f"`{rel_path}` line {number} holds `{value}`, which looks like a fake "
                        f"`{kind}` but is not on the fake-values registry."
                    ),
                    remediation=_REMEDY_VENDORED if vendored else _REMEDY_DOC,
                    path=rel_path,
                )
            )
    return findings


def _load(context: CheckContext) -> tuple[FakeValuesRegistry | None, list[Finding]]:
    try:
        return load_fake_values(context.project_root), []
    except FakeValuesError as error:
        return None, [_registry_finding(error)]


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    if context.file_path.suffix != _MARKDOWN_SUFFIX:
        return []
    registry, problems = _load(context)
    if registry is None:
        return problems
    rel_path = path_relative_to(context.file_path, context.project_root).as_posix()
    return _findings_for(rel_path, context.file_content, registry)


def _run_sweep(context: CheckContext) -> list[Finding]:
    registry, problems = _load(context)
    if registry is None:
        return problems
    if not any(entry.fake_looking is not None for entry in registry.kinds.values()):
        return []
    findings: list[Finding] = []
    for rel_path in context.markdown_paths or ():
        abs_path = authored_path(context.project_root, rel_path)
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # One unreadable document must not abort the whole sweep, and must
            # not read as a clean one: it is reported as a finding of its own.
            logger.warning("unlisted-fake-value: cannot read %s: %s", rel_path, exc)
            findings.append(_unreadable_finding(rel_path, exc))
            continue
        findings.extend(_findings_for(rel_path, content, registry))
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)

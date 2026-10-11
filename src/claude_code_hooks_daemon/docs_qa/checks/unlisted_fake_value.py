"""Check ``unlisted-fake-value`` (EDIT, STAGED and SWEEP; Plan 00492, owner ruling D1).

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

**Commit time BLOCKS a registry entry that is not visibly fake** (ledger 00474
N361, owner ruling C7). The STAGED stage reads the registry as the commit will
record it and denies a listed value that fails
:meth:`~claude_code_hooks_daemon.utils.fake_values.FakeValuesRegistry.not_visibly_fake`,
or a registry that cannot be parsed (every guard that reads it would raise).
Only entries the commit ADDS or CHANGES are judged, so an older entry never
turns every later commit into a sticky failure. The finding is severity BLOCK;
whether it denies is the project's ``documentation.qa.check_modes`` entry for
this check id, as for every docs QA check.

**Severity is ADVISE** everywhere else. A missing registry is silent: a project that keeps
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
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.fake_values import (
    REGISTRY_RELATIVE_PATH,
    FakeValuesError,
    FakeValuesRegistry,
    load_fake_values,
    parse_fake_values,
)
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

logger = logging.getLogger(__name__)

CHECK_ID: Final[str] = "unlisted-fake-value"
STATEMENT: Final[str] = (
    "Fake-looking values in docs must come from the fake-values registry. Use a listed fake or extend the registry."
)

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


def _not_visibly_fake_findings(registry: FakeValuesRegistry) -> list[Finding]:
    return [
        Finding(
            check_id=CHECK_ID,
            severity=Severity.ADVISE,
            message=(
                f"`{REGISTRY_RELATIVE_PATH}` lists `{value}` as a `{kind}` fake, but it does "
                "not look obviously fake."
            ),
            remediation=(
                "Replace it with a value that is obviously fake without anyone knowing it is "
                "one: the word `fake`, or a character repeated eight or more times."
            ),
            path=REGISTRY_RELATIVE_PATH,
        )
        for kind, value in registry.not_visibly_fake()
    ]


def _staged_registry_finding(error: FakeValuesError) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.BLOCK,
        message=f"The staged fake-values registry cannot be read, so no fake can be judged: {error}",
        remediation=f"Fix `{REGISTRY_RELATIVE_PATH}` so it follows the registry schema.",
        path=REGISTRY_RELATIVE_PATH,
    )


def _staged_not_visibly_fake_findings(
    staged: FakeValuesRegistry, head: FakeValuesRegistry
) -> list[Finding]:
    already_in_head = set(head.not_visibly_fake())
    return [
        Finding(
            check_id=CHECK_ID,
            severity=Severity.BLOCK,
            message=(
                f"This commit adds `{value}` to `{REGISTRY_RELATIVE_PATH}` as a `{kind}` fake, "
                "but it does not look obviously fake."
            ),
            remediation=(
                "Replace it with a value that is obviously fake without anyone knowing it is "
                "one: the word `fake`, or a character repeated eight or more times. Never put a "
                "real-looking value in the registry: it exempts that value from "
                "`sensitive_content`."
            ),
            path=REGISTRY_RELATIVE_PATH,
        )
        for kind, value in staged.not_visibly_fake()
        if (kind, value) not in already_in_head
    ]


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


def _run_staged(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []
    touched = [
        change
        for change in gitfacts.staged_changes()
        if change.path == REGISTRY_RELATIVE_PATH and not change.status.startswith("D")
    ]
    if not touched:
        return []
    text = gitfacts.recorded_text(REGISTRY_RELATIVE_PATH)
    if text is None:
        return []
    source = context.project_root / REGISTRY_RELATIVE_PATH
    try:
        staged = parse_fake_values(text, source)
    except FakeValuesError as error:
        return [_staged_registry_finding(error)]
    head_text = gitfacts.head_file_text(REGISTRY_RELATIVE_PATH)
    try:
        head = (
            parse_fake_values(head_text, source) if head_text is not None else FakeValuesRegistry()
        )
    except FakeValuesError as error:
        # An unreadable previous version vouches for nothing, so every staged entry is judged.
        logger.debug("HEAD registry unreadable, judging every staged entry: %s", error)
        head = FakeValuesRegistry()
    return _staged_not_visibly_fake_findings(staged, head)


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
    findings = _not_visibly_fake_findings(registry)
    if not any(entry.fake_looking is not None for entry in registry.kinds.values()):
        return findings
    for rel_path in context.markdown_paths or ():
        abs_path = authored_path(context.project_root, rel_path)
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # One unreadable document must not abort the whole sweep, and must
            # not read as a clean one: it is reported as a finding of its own.
            log_and_continue(
                logger,
                exc,
                reason=(
                    f"unreadable document {rel_path} is skipped so one bad file cannot abort "
                    "the sweep; it is reported as a finding of its own, never read as clean"
                ),
                level=logging.WARNING,
            )
            findings.append(_unreadable_finding(rel_path, exc))
            continue
        findings.extend(_findings_for(rel_path, content, registry))
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)

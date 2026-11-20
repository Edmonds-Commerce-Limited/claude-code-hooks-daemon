"""The no-value removal route's pure core (Plan 00620, DESIGN.md).

An ``unproven`` branch is never deleted on an agent's word. This route lets one go
only when TWO independent facts hold at delete time: a verdict written by a separate,
at-least-Opus reviewer agent (judging every unique commit and content-unique path),
and a recovery bundle the guard itself wrote and verified. Neither is sufficient
alone (RULINGS.md section 1).

This module answers questions and writes the records; it grants nothing. It holds:

- the inventory a reviewer judges and the guard recomputes (:func:`compute_inventory`);
- the state store of requests, dispatch bindings, verdicts and keeps (:class:`RejectStore`);
- verdict validation (:func:`verdict_problems`, :func:`verdict_set_problems`), where an
  empty list is the only pass and every failure to read is a problem, never a pass;
- request admission from the keep history and the removal rate (:func:`admit_request`);
- the recovery bundle, always under the MAIN checkout (:func:`write_bundle`,
  :func:`bundle_problems`);
- the append-only removal ledger (:func:`append_ledger`, :func:`read_ledger`).

Slice 2 wires it into ``delete-branch`` (via :class:`RejectRoute`), the
``branch-reject`` CLI, the dispatch gate and the SubagentStop recorder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.branch_records import branch_identities, identity
from claude_code_hooks_daemon.utils.git_repo import branch_ref, run_git
from claude_code_hooks_daemon.utils.load_scaling import scaled_timeout
from claude_code_hooks_daemon.utils.model_fallback_records import parse_fallback_payload
from claude_code_hooks_daemon.utils.model_tiers import OPUS, family_rank, resolve_model_family

#: The tier ``delete-branch`` reports for a removal this route made (slice 2).
TIER_REJECTED_BUNDLED = "rejected-bundled"

DECISION_NO_VALUE = "no-value"
DECISION_KEEP = "keep"
DECISIONS = frozenset({DECISION_NO_VALUE, DECISION_KEEP})

KIND_COMMIT = "commit"
KIND_PATH = "path"
KINDS = frozenset({KIND_COMMIT, KIND_PATH})

CITE_COMMIT = "commit:"
CITE_PATH = "path:"

SCHEMA_VERSION = 1

#: The ``outcome`` of a ledger line recording that git refused an appended removal.
OUTCOME_GIT_REFUSED = "git-refused"

_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OBJECT = re.compile(r"[0-9a-f]{7,64}")
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_ID_BYTES = 16
_TIP_IN_NAME = 12
_SECONDS_PER_HOUR = 3600.0
_SECONDS_PER_DAY = 86_400.0
_HASH_CHUNK = 1 << 20
_HEADER_LIMIT = 1 << 20
_FILTER_CAPABILITY = b"@filter"
_SIDECAR_SUFFIX = ".sha256"
_LEDGER_MODE = 0o644
_GIT_DIR_NAME = ".git"
_HEADS = "refs/"

_REQUESTS = "requests"
_DISPATCHES = "dispatches"
_VERDICTS = "verdicts"
_KEEPS = "keeps"
_STOPS = "stops"
_DIGEST_FILE = "digest.json"
_ENTRY_KEY = re.compile(r"[0-9a-f]{64}")

#: Path parts, name markers and suffixes a reviewer may judge worthless only with a
#: citation of what supersedes them (PLAN.md goal "doubt means keep").
_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec"})
_DOC_DIRS = frozenset({"docs", "doc"})
_DOC_SUFFIXES = frozenset({".md", ".rst", ".adoc"})
_CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf"})
_PLAN_PREFIX = ("CLAUDE", "Plan")
_JOURNAL_DIR = "JOURNAL"


class RejectError(RuntimeError):
    """A record, a git fact or a file this route rests on could not be read or written."""


class RejectRefusedError(RuntimeError):
    """The route refuses this request (a final keep, a closed route, the rate rule)."""


def new_id() -> str:
    """A fresh nonce or verdict id: 32 lowercase hex characters."""
    return secrets.token_hex(_ID_BYTES)


def _git_budget() -> float:
    return scaled_timeout(Timeout.GIT_BRANCH_SAFETY, Timeout.GIT_BRANCH_SAFETY_MAX)


def _git_out(repo: Path, *args: str) -> str:
    """Stdout of a git call; raises RejectError on any failure."""
    result = run_git(repo, *args, timeout=_git_budget())
    if result.returncode != 0:
        raise RejectError(f"git {' '.join(args)} failed: {result.stderr.strip() or 'no detail'}")
    return result.stdout


def _git_ok(repo: Path, *args: str) -> bool:
    return run_git(repo, *args, timeout=_git_budget()).returncode == 0


def _full_ref(ref: str) -> str:
    return ref if ref.startswith(_HEADS) else branch_ref(ref)


def _resolve(repo: Path, ref: str) -> str:
    return _git_out(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()


def branch_tip(repo: Path, branch: str) -> str:
    """The branch's current commit; raises RejectError when it does not resolve."""
    return _resolve(repo, branch_ref(branch))


# --- strict field readers: a wrong type is a RejectError, never a default ----------


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise RejectError(f"record field {key!r} is not a string")
    return value


def _float(data: Mapping[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RejectError(f"record field {key!r} is not a number")
    return float(value)


def _int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RejectError(f"record field {key!r} is not an integer")
    return value


def _bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise RejectError(f"record field {key!r} is not a boolean")
    return value


def _strs(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RejectError(f"record field {key!r} is not a list of strings")
    return tuple(value)


def _mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RejectError(f"record field {key!r} is not an object")
    return value


def _schema(data: Mapping[str, Any]) -> None:
    if _int(data, "schema") != SCHEMA_VERSION:
        raise RejectError(f"record schema is not {SCHEMA_VERSION}")


# --- records -------------------------------------------------------------------------


@dataclass(frozen=True)
class Inventory:
    """What the branch holds that the default lacks: unique commits and content-unique paths."""

    commits: tuple[str, ...]
    paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"commits": list(self.commits), "paths": list(self.paths)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Inventory:
        return cls(commits=_strs(data, "commits"), paths=_strs(data, "paths"))


@dataclass(frozen=True)
class Item:
    """The reviewer's judgement of one commit or one path."""

    kind: str
    ref: str
    decision: str
    reason: str
    superseded_by: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "decision": self.decision,
            "reason": self.reason,
            "superseded_by": list(self.superseded_by),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Item:
        return cls(
            kind=_str(data, "kind"),
            ref=_str(data, "ref"),
            decision=_str(data, "decision"),
            reason=_str(data, "reason"),
            superseded_by=_strs(data, "superseded_by"),
        )


@dataclass(frozen=True)
class Reviewer:
    """The reviewer agent, as the SubagentStop recorder read it from the agent transcript."""

    session_id: str
    agent_id: str
    models: tuple[str, ...]
    downgraded: bool
    fork: bool
    user_turns: int
    reply_sha256: str

    @property
    def identity(self) -> str:
        """``<session>:<agent>``, the form the creator and touch records use."""
        return identity(self.session_id, self.agent_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "models": list(self.models),
            "downgraded": self.downgraded,
            "fork": self.fork,
            "user_turns": self.user_turns,
            "reply_sha256": self.reply_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Reviewer:
        return cls(
            session_id=_str(data, "session_id"),
            agent_id=_str(data, "agent_id"),
            models=_strs(data, "models"),
            downgraded=_bool(data, "downgraded"),
            fork=_bool(data, "fork"),
            user_turns=_int(data, "user_turns"),
            reply_sha256=_str(data, "reply_sha256"),
        )


@dataclass(frozen=True)
class Verdict:
    """One reviewer's verdict on one branch tip (DESIGN.md section 4)."""

    verdict_id: str
    nonce: str
    branch: str
    tip: str
    default_sha: str
    inventory: Inventory
    items: tuple[Item, ...]
    overall: str
    issued_at: float
    reviewer: Reviewer

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "verdict_id": self.verdict_id,
            "nonce": self.nonce,
            "branch": self.branch,
            "tip": self.tip,
            "default_sha": self.default_sha,
            "inventory": self.inventory.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "overall": self.overall,
            "issued_at": self.issued_at,
            "reviewer": self.reviewer.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Verdict:
        _schema(data)
        raw_items = data.get("items")
        if not isinstance(raw_items, list) or not all(isinstance(i, dict) for i in raw_items):
            raise RejectError("record field 'items' is not a list of objects")
        return cls(
            verdict_id=_str(data, "verdict_id"),
            nonce=_str(data, "nonce"),
            branch=_str(data, "branch"),
            tip=_str(data, "tip"),
            default_sha=_str(data, "default_sha"),
            inventory=Inventory.from_dict(_mapping(data, "inventory")),
            items=tuple(Item.from_dict(item) for item in raw_items),
            overall=_str(data, "overall"),
            issued_at=_float(data, "issued_at"),
            reviewer=Reviewer.from_dict(_mapping(data, "reviewer")),
        )


@dataclass(frozen=True)
class RejectRequest:
    """An outstanding review request, recorded by ``branch-reject request``."""

    nonce: str
    branch: str
    tip: str
    default_sha: str
    inventory: Inventory
    reviewers_required: int
    prompt_sha256: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "nonce": self.nonce,
            "branch": self.branch,
            "tip": self.tip,
            "default_sha": self.default_sha,
            "inventory": self.inventory.to_dict(),
            "reviewers_required": self.reviewers_required,
            "prompt_sha256": self.prompt_sha256,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RejectRequest:
        _schema(data)
        return cls(
            nonce=_str(data, "nonce"),
            branch=_str(data, "branch"),
            tip=_str(data, "tip"),
            default_sha=_str(data, "default_sha"),
            inventory=Inventory.from_dict(_mapping(data, "inventory")),
            reviewers_required=_int(data, "reviewers_required"),
            prompt_sha256=_str(data, "prompt_sha256"),
            created_at=_float(data, "created_at"),
        )


@dataclass(frozen=True)
class DispatchRecord:
    """The daemon-observed binding of a request nonce to the reviewer agent it dispatched."""

    nonce: str
    session_id: str
    tool_use_id: str
    agent_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "nonce": self.nonce,
            "session_id": self.session_id,
            "tool_use_id": self.tool_use_id,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DispatchRecord:
        _schema(data)
        return cls(
            nonce=_str(data, "nonce"),
            session_id=_str(data, "session_id"),
            tool_use_id=_str(data, "tool_use_id"),
            agent_id=_str(data, "agent_id"),
        )


@dataclass(frozen=True)
class KeepRecord:
    """A ``keep`` verdict, kept so a later request on the same WORK is a re-review."""

    verdict_id: str
    branch: str
    tip: str
    commits: tuple[str, ...]
    reasons: tuple[str, ...]
    recorded_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "verdict_id": self.verdict_id,
            "branch": self.branch,
            "tip": self.tip,
            "commits": list(self.commits),
            "reasons": list(self.reasons),
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> KeepRecord:
        _schema(data)
        return cls(
            verdict_id=_str(data, "verdict_id"),
            branch=_str(data, "branch"),
            tip=_str(data, "tip"),
            commits=_strs(data, "commits"),
            reasons=_strs(data, "reasons"),
            recorded_at=_float(data, "recorded_at"),
        )


# --- the state store -----------------------------------------------------------------


class RejectStore:
    """One JSON file per record under ``root`` (DESIGN.md section 3).

    Reads fail closed: a file that exists but cannot be parsed raises RejectError, so
    a damaged record never reads as "absent" or as a pass. A file whose name is not a
    record id is never opened.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _check_id(record_id: str) -> None:
        if not _ID.fullmatch(record_id):
            raise RejectError(f"not a record id: {record_id!r}")

    def _path(self, kind: str, record_id: str) -> Path:
        self._check_id(record_id)
        return self.root / kind / f"{record_id}.json"

    def _write(self, kind: str, record_id: str, data: Mapping[str, Any]) -> None:
        path = self._path(kind, record_id)
        tmp = path.with_name(f".{path.name}.{new_id()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            raise RejectError(f"could not write {path}: {exc}") from exc
        finally:
            with suppress(FileNotFoundError, NotADirectoryError):
                tmp.unlink()

    @staticmethod
    def _load(path: Path) -> Mapping[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RejectError(f"could not read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise RejectError(f"{path} does not hold a JSON object")
        return data

    def _read(self, kind: str, record_id: str) -> Mapping[str, Any] | None:
        path = self._path(kind, record_id)
        if not path.exists():
            return None
        return self._load(path)

    def _all(self, kind: str) -> list[Mapping[str, Any]]:
        return [data for _, data in self._all_with_paths(kind)]

    def _all_with_paths(self, kind: str) -> list[tuple[Path, Mapping[str, Any]]]:
        directory = self.root / kind
        if not directory.is_dir():
            return []
        return [
            (path, self._load(path))
            for path in sorted(directory.glob("*.json"))
            if _ID.fullmatch(path.stem)
        ]

    def write_request(self, request: RejectRequest) -> None:
        self._write(_REQUESTS, request.nonce, request.to_dict())

    def read_request(self, nonce: str) -> RejectRequest | None:
        data = self._read(_REQUESTS, nonce)
        return None if data is None else RejectRequest.from_dict(data)

    def write_dispatch(self, record: DispatchRecord) -> None:
        self._write(_DISPATCHES, record.nonce, record.to_dict())

    def _create(self, kind: str, record_id: str, data: Mapping[str, Any]) -> bool:
        """Write a record only if none exists; False when one already does.

        ``os.link`` of a complete temp file is atomic and fails on an existing name, so
        of two racing writers exactly one creates the record and neither overwrites.
        """
        path = self._path(kind, record_id)
        tmp = path.with_name(f".{path.name}.{new_id()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError as exc:
            raise RejectError(f"could not write {path}: {exc}") from exc
        finally:
            with suppress(FileNotFoundError, NotADirectoryError):
                tmp.unlink()
        return True

    def create_dispatch(self, record: DispatchRecord) -> None:
        """Write the dispatch record only if none exists for its nonce.

        Two parallel dispatches of one prompt cannot both be admitted, and the second
        never overwrites the first. Raises RejectRefusedError when the record exists.
        """
        if not self._create(_DISPATCHES, record.nonce, record.to_dict()):
            raise RejectRefusedError(
                f"nonce {record.nonce} is already dispatched; one request binds one agent"
            )

    def read_dispatch(self, nonce: str) -> DispatchRecord | None:
        data = self._read(_DISPATCHES, nonce)
        return None if data is None else DispatchRecord.from_dict(data)

    def write_verdict(self, verdict: Verdict) -> None:
        self._write(_VERDICTS, verdict.verdict_id, verdict.to_dict())

    def create_verdict(self, verdict: Verdict) -> bool:
        """Write the verdict only if none exists under its id; False when one does."""
        return self._create(_VERDICTS, verdict.verdict_id, verdict.to_dict())

    def withdraw_verdict(self, verdict_id: str) -> None:
        """Remove the verdict, if any. Raises RejectError when it cannot be removed."""
        path = self._path(_VERDICTS, verdict_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise RejectError(f"could not withdraw {path}: {exc}") from exc

    def mark_stop(self, nonce: str) -> bool:
        """Record that the nonce's reviewer stopped; True only for its FIRST stop."""
        return self._create(_STOPS, nonce, {"schema": SCHEMA_VERSION, "nonce": nonce})

    def read_verdict(self, verdict_id: str) -> Verdict | None:
        data = self._read(_VERDICTS, verdict_id)
        return None if data is None else Verdict.from_dict(data)

    def verdicts_for(self, branch: str, tip: str) -> list[Verdict]:
        """Every stored verdict naming this branch and tip, oldest file name first.

        Raises RejectError when any verdict file's name is not its own id: the recorder
        files a verdict under its id, so a mismatch is a copy, and the store is not trusted.
        """
        verdicts: list[Verdict] = []
        for path, data in self._all_with_paths(_VERDICTS):
            verdict = Verdict.from_dict(data)
            if verdict.verdict_id != path.stem:
                raise RejectError(f"the verdict file {path} is not named by its own id")
            verdicts.append(verdict)
        return [v for v in verdicts if v.branch == branch and v.tip == tip]

    def write_keep(self, keep: KeepRecord) -> None:
        self._write(_KEEPS, keep.verdict_id, keep.to_dict())

    def keeps(self) -> list[KeepRecord]:
        return [KeepRecord.from_dict(data) for data in self._all(_KEEPS)]

    @property
    def digest_path(self) -> Path:
        """The digest watermark: one file, since its keys are 64 hex, not record ids."""
        return self.root / _DIGEST_FILE


@dataclass(frozen=True)
class RejectRoute:
    """What ``delete_branches`` needs to consult the route (slice 2, DESIGN.md section 10)."""

    store: RejectStore
    ledger_path: Path
    config: BranchRejectConfig
    now: float
    #: The DEFAULT branch the route judges against; None means the delete's own
    #: ``protected_ref``. A caller whose ``protected_ref`` may be an integration line
    #: must set it, since rejected work is never judged against a line.
    default_ref: str | None = None


# --- the inventory -------------------------------------------------------------------


def compute_inventory(repo: Path, branch: str, default_ref: str) -> Inventory:
    """The unique commits (merges included) and content-unique paths of ``branch``.

    Measured against ``default_ref`` only (DESIGN.md section 2). Every git failure
    raises RejectError: a failed walk must never read as an empty inventory.
    """
    from claude_code_hooks_daemon.daemon import branch_safety

    tip_ref = branch_ref(branch)
    default = _full_ref(default_ref)
    tip = _resolve(repo, tip_ref)
    base = _resolve(repo, default)
    unique = branch_safety.cherry_unique_shas(repo, base, tip, timeout=_git_budget())
    if unique is None:
        raise RejectError(f"git cherry {default} {tip_ref} failed")
    merges = _git_out(repo, "rev-list", "--merges", f"{base}..{tip}").split()
    try:
        reachable = branch_safety.reachable_object_shas(repo, base)
        paths = branch_safety.content_unique_paths_of(repo, tip, reachable)
    except Exception as exc:
        raise RejectError(f"the content walk of {tip_ref} failed: {exc}") from exc
    if not reachable:
        raise RejectError(f"no objects are reachable from {default}; the walk failed")
    return Inventory(commits=tuple(sorted({*unique, *merges})), paths=tuple(sorted(paths)))


def is_keep_by_default(path: str) -> bool:
    """Whether ``path`` is a test, plan or journal file, a doc, or config."""
    pure = PurePosixPath(path)
    parts = pure.parts
    name = pure.name
    suffix = pure.suffix.lower()
    is_test = (
        any(part in _TEST_DIRS for part in parts[:-1])
        or name.startswith("test_")
        or pure.stem.endswith("_test")
        or ".test." in name
        or ".spec." in name
    )
    is_plan = parts[: len(_PLAN_PREFIX)] == _PLAN_PREFIX or _JOURNAL_DIR in parts[:-1]
    is_doc = any(part in _DOC_DIRS for part in parts[:-1]) or suffix in _DOC_SUFFIXES
    return is_test or is_plan or is_doc or suffix in _CONFIG_SUFFIXES


# --- verdict validation --------------------------------------------------------------


def _shape_problems(verdict: Verdict) -> list[str]:
    problems: list[str] = []
    if not _ID.fullmatch(verdict.verdict_id) or not _ID.fullmatch(verdict.nonce):
        problems.append("the verdict id or nonce is not a record id")
    if verdict.verdict_id != verdict.nonce:
        # Single use is keyed on the id; only an id bound to the nonce (one stop per
        # nonce) stops a used verdict being re-filed under a fresh id and used again.
        problems.append("the verdict id is not its nonce; the recorder never wrote it")
    if verdict.overall not in DECISIONS:
        problems.append(f"overall decision {verdict.overall!r} is neither no-value nor keep")
    for item in verdict.items:
        if item.kind not in KINDS:
            problems.append(f"item {item.ref!r} has an unknown kind {item.kind!r}")
        if item.decision not in DECISIONS:
            problems.append(f"item {item.ref!r} has an unknown decision {item.decision!r}")
        if not item.reason.strip():
            problems.append(f"item {item.ref!r} gives no reason")
    if verdict.overall == DECISION_KEEP:
        problems.append("the overall verdict is keep; a keep verdict never removes a branch")
    elif any(item.decision == DECISION_KEEP for item in verdict.items):
        problems.append("the overall verdict is no-value but an item is judged keep")
    return problems


def _chain_problems(verdict: Verdict, store: RejectStore) -> list[str]:
    try:
        request = store.read_request(verdict.nonce)
        dispatch = store.read_dispatch(verdict.nonce)
    except RejectError as exc:
        return [f"the request or dispatch record is unreadable: {exc}"]
    problems: list[str] = []
    if request is None:
        problems.append("no outstanding request carries this verdict's nonce")
    else:
        for field_name in ("branch", "tip", "default_sha", "inventory"):
            if getattr(request, field_name) != getattr(verdict, field_name):
                problems.append(f"the verdict disagrees with its request on {field_name}")
    if dispatch is None:
        problems.append("no dispatch record binds this nonce to a reviewer agent")
    elif not dispatch.session_id or not dispatch.agent_id:
        # PreToolUse writes the record with an empty agent id; only PostToolUse binds
        # one. An unbound record is no binding, whatever the verdict claims.
        problems.append("the dispatch record for this nonce is not bound to a reviewer agent")
    elif (dispatch.session_id, dispatch.agent_id) != (
        verdict.reviewer.session_id,
        verdict.reviewer.agent_id,
    ):
        problems.append("the dispatch record binds this nonce to another agent")
    return problems


def _coverage_problems(verdict: Verdict) -> list[str]:
    keys = [(item.kind, item.ref) for item in verdict.items]
    problems = [
        f"duplicate item {kind} {ref}" for (kind, ref), count in Counter(keys).items() if count > 1
    ]
    expected = {(KIND_COMMIT, sha) for sha in verdict.inventory.commits} | {
        (KIND_PATH, path) for path in verdict.inventory.paths
    }
    missing = sorted(expected - set(keys))
    extra = sorted(set(keys) - expected)
    if missing or extra:
        problems.append(
            f"the items do not cover the inventory exactly: missing {missing}, extra {extra}"
        )
    return problems


def _git_problems(verdict: Verdict, repo: Path, default_ref: str) -> list[str]:
    try:
        tip = branch_tip(repo, verdict.branch)
    except RejectError as exc:
        return [f"{verdict.branch} no longer resolves to a branch tip: {exc}"]
    if tip != verdict.tip:
        return [
            f"the tip moved: the verdict is for {verdict.tip[:12]}, the branch is at {tip[:12]}"
        ]
    try:
        current = compute_inventory(repo, verdict.branch, default_ref)
    except RejectError as exc:
        return [f"the inventory could not be recomputed: {exc}"]
    if current != verdict.inventory:
        return ["the inventory recomputed from git does not equal the verdict's inventory"]
    return []


def citation_resolves(repo: Path, citation: str, default_ref: str) -> bool:
    """Whether a ``commit:<sha>`` or ``path:<path>`` citation resolves on the default."""
    default = _full_ref(default_ref)
    if citation.startswith(CITE_COMMIT):
        sha = citation[len(CITE_COMMIT) :]
        return bool(_OBJECT.fullmatch(sha)) and _git_ok(
            repo, "merge-base", "--is-ancestor", sha, default
        )
    if citation.startswith(CITE_PATH):
        path = citation[len(CITE_PATH) :]
        if not path or path.startswith("-"):
            return False
        return _git_ok(repo, "cat-file", "-e", f"{default}:{path}")
    return False


def _citation_problems(verdict: Verdict, repo: Path, default_ref: str) -> list[str]:
    problems: list[str] = []
    for item in verdict.items:
        if (
            item.kind == KIND_PATH
            and item.decision == DECISION_NO_VALUE
            and is_keep_by_default(item.ref)
            and not item.superseded_by
        ):
            problems.append(
                f"{item.ref} is kept by default (test, plan, doc or config) and no "
                "superseding citation is given"
            )
        problems.extend(
            f"citation {citation!r} on {item.ref} does not resolve on the default branch"
            for citation in item.superseded_by
            if not citation_resolves(repo, citation, default_ref)
        )
    return problems


def _time_problems(verdict: Verdict, now: float, config: BranchRejectConfig) -> list[str]:
    if verdict.issued_at > now:
        return ["the verdict is issued in the future"]
    if now >= verdict.issued_at + config.verdict_lifetime_hours * _SECONDS_PER_HOUR:
        return ["the verdict has expired"]
    return []


def _reviewer_problems(reviewer: Reviewer) -> list[str]:
    problems: list[str] = []
    floor = family_rank(OPUS)
    if not reviewer.models:
        problems.append("the reviewer record names no model")
    for model in reviewer.models:
        resolved = resolve_model_family(model)
        if resolved is None or floor is None or resolved[1] < floor:
            problems.append(f"reviewer model {model!r} is below Opus or unknown")
    if reviewer.downgraded:
        problems.append("the reviewer ran under a model downgrade")
    if reviewer.fork:
        problems.append("the reviewer is a fork, not a fresh context")
    if reviewer.user_turns != 1:
        problems.append(
            f"the reviewer was resumed or re-prompted ({reviewer.user_turns} human turns, "
            "exactly 1 is required)"
        )
    if not _SHA256.fullmatch(reviewer.reply_sha256):
        problems.append("the reviewer reply digest is not a sha256")
    return problems


def _independence_problems(verdict: Verdict, repo: Path) -> list[str]:
    try:
        identities = branch_identities(repo, verdict.branch)
    except RuntimeError as exc:
        return [f"the branch's creator and touch records are unreadable: {exc}"]
    if verdict.reviewer.identity in identities:
        return [f"reviewer {verdict.reviewer.identity} is the branch's creator or touched it"]
    return []


def verdict_problems(
    verdict: Verdict,
    *,
    repo: Path,
    store: RejectStore,
    default_ref: str,
    now: float,
    consumed: frozenset[str],
    config: BranchRejectConfig,
) -> list[str]:
    """Every reason ``verdict`` cannot unlock a delete; an empty list is the only pass.

    Runs every check (DESIGN.md section 5) rather than stopping at the first, so a
    refusal names everything wrong at once.
    """
    problems = _shape_problems(verdict)
    problems += _chain_problems(verdict, store)
    problems += _coverage_problems(verdict)
    problems += _git_problems(verdict, repo, default_ref)
    problems += _citation_problems(verdict, repo, default_ref)
    problems += _time_problems(verdict, now, config)
    if verdict.verdict_id in consumed or verdict.nonce in consumed:
        problems.append("the verdict was already used for a removal")
    problems += _reviewer_problems(verdict.reviewer)
    problems += _independence_problems(verdict, repo)
    return problems


def verdict_set_problems(verdicts: Sequence[Verdict], *, required: int) -> list[str]:
    """Problems with the SET of individually valid verdicts offered for one removal.

    Disagreement is keep, and two verdicts from one agent count once.
    """
    if not verdicts:
        return ["no verdict is offered"]
    problems: list[str] = []
    if any(v.overall != DECISION_NO_VALUE for v in verdicts):
        problems.append("a reviewer judged keep; disagreement between reviewers is keep")
    agents = {v.reviewer.identity for v in verdicts}
    if len(agents) < required:
        problems.append(
            f"{required} verdict(s) from distinct reviewer agents are required, "
            f"{len(agents)} distinct reviewer(s) found"
        )
    return problems


# --- admission: keep history and rate -------------------------------------------------


def reviewers_for_rate(removals: int, config: BranchRejectConfig) -> int | None:
    """Reviewers the next removal needs given ``removals`` in the window; None refuses."""
    if removals >= config.refuse_after:
        return None
    if removals >= config.two_reviewer_after:
        return 2
    return 1


def related_keeps(
    branch: str, tip: str, inventory: Inventory, keeps: Iterable[KeepRecord]
) -> list[KeepRecord]:
    """Keep records on the same WORK: same name, same tip, or any shared unique commit."""
    commits = set(inventory.commits)
    return [
        keep
        for keep in keeps
        if keep.branch == branch or keep.tip == tip or commits & set(keep.commits)
    ]


def admit_request(
    branch: str,
    tip: str,
    inventory: Inventory,
    keeps: Iterable[KeepRecord],
    removals_in_window_count: int,
    config: BranchRejectConfig,
) -> int:
    """The reviewers a new request needs (1 or 2); raises RejectRefusedError when refused.

    A keep is related to this request by name, by tip, or by sharing any unique commit,
    so renaming a branch earns no fresh start (RULINGS.md Q5).
    """
    related = related_keeps(branch, tip, inventory, keeps)
    if any(keep.tip == tip for keep in related):
        raise RejectRefusedError(f"a keep verdict on tip {tip[:12]} is final for that tip")
    if len(related) >= 2:
        raise RejectRefusedError(
            "the route is closed for this work: it has two keep verdicts already"
        )
    needed = 2 if related else 1
    by_rate = reviewers_for_rate(removals_in_window_count, config)
    if by_rate is None:
        raise RejectRefusedError(
            f"the removal rate is at the limit ({removals_in_window_count} removals in "
            f"{config.window_days} days, refuse_after {config.refuse_after})"
        )
    return max(needed, by_rate)


# --- the review request and its prompt (DESIGN.md section 9) ---------------------------

#: The shipped reviewer agent a review prompt must be dispatched to.
REVIEWER_AGENT_TYPE = "hooks-daemon-branch-reject-reviewer"

#: The first line of every review prompt is this marker followed by the nonce.
PROMPT_MARKER = "[branch-reject review] nonce "

VERDICT_BLOCK_START = "BRANCH-REJECT-VERDICT"
VERDICT_BLOCK_END = "END-BRANCH-REJECT-VERDICT"

_PROMPT_FIRST_LINE = re.compile(re.escape(PROMPT_MARKER) + r"([0-9a-f]{32})")
#: Unicode categories refused in any text the prompt quotes: every control, format,
#: surrogate, private-use and unassigned character, and the line and paragraph
#: separators. A newline in a file name would otherwise put caller-chosen lines
#: into a prompt the daemon claims to have composed alone.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def prompt_nonce(prompt: str) -> str | None:
    """The nonce of a well-formed review prompt's first line, else None."""
    match = _PROMPT_FIRST_LINE.fullmatch(prompt.split("\n", 1)[0])
    return match.group(1) if match else None


def prompt_digest(prompt: str) -> str:
    """The sha256 the dispatch gate compares a dispatched prompt against."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


# --- the dispatch gate (PreToolUse / PostToolUse ``Agent``) ---------------------------


@dataclass(frozen=True)
class DispatchCall:
    """What the dispatch gate reads from one PreToolUse ``Agent`` call."""

    session_id: str
    tool_use_id: str
    subagent_type: str
    prompt: str
    #: The family ``dispatch_tier`` predicts the call runs on; None when unknown.
    predicted_family: str | None
    #: True when the call asks to resume an earlier agent rather than start fresh.
    resume: bool
    #: True when the deployed reviewer definition is the shipped, CURRENT one.
    definition_current: bool


def is_reviewer_dispatch(subagent_type: str, prompt: str) -> bool:
    """Whether a dispatch is the gate's business: the reviewer type, or a review prompt.

    Cheap and store-free, so a damaged store never blocks an unrelated dispatch.
    """
    return subagent_type == REVIEWER_AGENT_TYPE or prompt.startswith(PROMPT_MARKER)


def _call_problems(call: DispatchCall) -> list[str]:
    problems: list[str] = []
    if call.subagent_type != REVIEWER_AGENT_TYPE:
        problems.append(
            f"a review prompt is dispatched only to the {REVIEWER_AGENT_TYPE} type, "
            f"not {call.subagent_type or '(none)'}"
        )
    if not call.session_id or not call.tool_use_id:
        problems.append("the call carries no session id or tool_use_id to bind")
    floor = family_rank(OPUS)
    rank = family_rank(call.predicted_family) if call.predicted_family else None
    if rank is None or floor is None or rank < floor:
        problems.append(
            f"the dispatch is predicted to run on {call.predicted_family or 'an unknown model'}, "
            "below Opus; drop the per-call model parameter"
        )
    if call.resume:
        problems.append("a review is a fresh agent, never a resumed one")
    if not call.definition_current:
        problems.append(
            f"the deployed {REVIEWER_AGENT_TYPE} definition is not the shipped one; "
            "redeploy it (hooks-daemon upgrade) before a review"
        )
    return problems


def dispatch_problems(call: DispatchCall, store: RejectStore) -> list[str]:
    """Every reason to deny a reviewer dispatch; an empty list is the only pass.

    The prompt must be byte-equal to an outstanding request's prompt (its sha256), and
    the nonce must not already be dispatched. A store that cannot be read is a problem.
    """
    problems = _call_problems(call)
    nonce = prompt_nonce(call.prompt)
    if nonce is None:
        problems.append(
            "the prompt is not a daemon-composed review prompt; dispatch the reviewer only "
            "with the exact prompt `hooks-daemon branch-reject request <branch>` prints"
        )
        return problems
    try:
        request = store.read_request(nonce)
        dispatched = store.read_dispatch(nonce)
    except RejectError as exc:
        return [*problems, f"the review state is unreadable: {exc}"]
    if request is None:
        problems.append(f"no outstanding request carries nonce {nonce}")
    elif prompt_digest(call.prompt) != request.prompt_sha256:
        problems.append(
            "the prompt differs from the one the request printed; pass it byte for byte, "
            "with nothing added or removed"
        )
    if dispatched is not None:
        problems.append(
            f"nonce {nonce} is already dispatched; run `branch-reject request` again for a "
            "fresh prompt"
        )
    return problems


def admit_dispatch(call: DispatchCall, store: RejectStore) -> DispatchRecord:
    """Admit a reviewer dispatch and record it, unbound, or raise RejectRefusedError.

    The record is created exclusively, so of two parallel dispatches of one prompt only
    one is admitted. Never touches the ledger.
    """
    problems = dispatch_problems(call, store)
    nonce = prompt_nonce(call.prompt)
    if problems or nonce is None:
        raise RejectRefusedError("; ".join(problems))
    record = DispatchRecord(
        nonce=nonce, session_id=call.session_id, tool_use_id=call.tool_use_id, agent_id=""
    )
    store.create_dispatch(record)
    return record


def bind_agent(
    store: RejectStore, nonce: str, *, session_id: str, tool_use_id: str, agent_id: str
) -> bool:
    """Fill the dispatch record's ``agent_id`` from PostToolUse; True when it bound.

    Binds only an unbound record whose session and ``tool_use_id`` match the call, and
    only to a non-empty agent id. Anything else is a no-op. Raises RejectError for a
    malformed nonce or an unreadable record.
    """
    record = store.read_dispatch(nonce)
    if record is None or record.agent_id or not agent_id:
        return False
    if (record.session_id, record.tool_use_id) != (session_id, tool_use_id):
        return False
    store.write_dispatch(DispatchRecord(nonce, session_id, tool_use_id, agent_id))
    return True


# --- the SubagentStop recorder ------------------------------------------------------

#: The outcomes of :func:`record_review_stop`.
STOP_RECORDED = "recorded"
STOP_WITHDRAWN = "withdrawn"
STOP_IGNORED = "ignored"

#: A reviewer transcript larger than this is not read; the stop records nothing.
_TRANSCRIPT_LIMIT = 64 << 20
_SAFE_AGENT_ID = re.compile(r"[A-Za-z0-9._-]+")
_SUPERSEDED = re.compile(
    r"(?P<reason>.*?)\s*(?:\[superseded-by:(?P<b>[^\]]*)\]|superseded-by:(?P<u>.*))"
)
_USER = "user"
_ASSISTANT = "assistant"
_TOOL_RESULT = "tool_result"
_TEXT = "text"


@dataclass(frozen=True)
class TranscriptFacts:
    """What the recorder reads from a reviewer agent's own transcript."""

    #: The first human turn's text; None when there is none or it is not plain text.
    first_user_text: str | None
    #: Every user record that is not machine traffic (``isMeta``) or a tool result.
    user_turns: int
    #: Each distinct ``message.model`` of an ``assistant`` record; "" for a missing one.
    models: tuple[str, ...]
    downgraded: bool
    #: The text blocks of the last ``assistant`` record that has any, joined by newlines.
    last_assistant_text: str | None
    #: True when any line is not a JSON object (for one, a half-written tail).
    damaged: bool


@dataclass(frozen=True)
class ReviewStop:
    """What the recorder reads from one SubagentStop payload and the agent's meta.json."""

    session_id: str
    agent_id: str
    agent_type: str
    meta_agent_type: str
    #: ``meta.json``'s camelCase ``toolUseId``: the binding to the dispatching call.
    meta_tool_use_id: str
    stop_hook_active: bool
    #: The payload's ``last_assistant_message``.
    reply: str


def _is_human_turn(record: Mapping[str, Any]) -> bool:
    # Every agent-transcript record is ``isSidechain``, so that flag says nothing here.
    if record.get("type") != _USER or record.get("isMeta"):
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        # Counted unless every block is a tool result: over-counting refuses the verdict.
        return not content or any(
            not isinstance(block, dict) or block.get("type") != _TOOL_RESULT for block in content
        )
    return True


def _assistant_text(record: Mapping[str, Any]) -> str | None:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return None
    texts = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == _TEXT
        and isinstance(block.get("text"), str)
    ]
    return "\n".join(texts) if texts else None


def read_review_transcript(path: Path) -> TranscriptFacts:
    """Read the WHOLE agent transcript (a downgrade anywhere counts, not just the tail).

    Raises RejectError when the file cannot be read or exceeds the size limit.
    """
    try:
        if path.stat().st_size > _TRANSCRIPT_LIMIT:
            raise RejectError(f"{path} exceeds {_TRANSCRIPT_LIMIT} bytes")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise RejectError(f"could not read {path}: {exc}") from exc
    first: str | None = None
    turns = 0
    models: list[str] = []
    downgraded = damaged = False
    last: str | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            damaged = True
            continue
        if not isinstance(record, dict):
            damaged = True
            continue
        if parse_fallback_payload(record) is not None:
            downgraded = True
        if _is_human_turn(record):
            turns += 1
            if turns == 1:
                content = record["message"].get("content")
                first = content if isinstance(content, str) else None
        elif record.get("type") == _ASSISTANT:
            message = record.get("message")
            model = message.get("model") if isinstance(message, dict) else None
            model = model if isinstance(model, str) else ""
            if model not in models:
                models.append(model)
            last = _assistant_text(record) or last
    return TranscriptFacts(first, turns, tuple(models), downgraded, last, damaged)


def _parse_tail(tail: str) -> tuple[str, str, tuple[str, ...]]:
    """``<decision>: <reason> [superseded-by: ...]`` -> (decision, reason, citations)."""
    decision, colon, rest = tail.partition(":")
    if not colon or decision not in DECISIONS:
        raise RejectRefusedError(f"no no-value|keep decision in {tail!r}")
    rest = rest.strip()
    match = _SUPERSEDED.fullmatch(rest)
    if match is None:
        return decision, rest, ()
    citations = tuple((match.group("b") or match.group("u") or "").split())
    if not citations or not all(c.startswith((CITE_COMMIT, CITE_PATH)) for c in citations):
        raise RejectRefusedError(f"a superseded-by list cites only commit: or path: in {tail!r}")
    return decision, match.group("reason"), citations


def _parse_item(line: str, inventory: Inventory) -> Item:
    for kind, refs in ((KIND_COMMIT, inventory.commits), (KIND_PATH, inventory.paths)):
        if not line.startswith(f"{kind} "):
            continue
        body = line[len(kind) + 1 :]
        for ref in sorted(refs, key=len, reverse=True):
            if body.startswith(f"{ref} "):
                with suppress(RejectRefusedError):
                    decision, reason, cites = _parse_tail(body[len(ref) + 1 :])
                    return Item(kind, ref, decision, reason, cites)
    raise RejectRefusedError(f"the verdict line {line!r} names nothing in the inventory")


def parse_verdict_reply(reply: str, request: RejectRequest) -> tuple[tuple[Item, ...], str]:
    """The items and overall decision of a reviewer reply; raises RejectRefusedError.

    The reply must end with exactly one verdict block (whitespace only after it), whose
    header names the request's nonce and tip and whose lines each judge a commit or path
    of the request's inventory. Any keep, on an item or overall, makes the verdict keep.
    """
    lines = [line.rstrip() for line in reply.rstrip().split("\n")]
    header = f"{VERDICT_BLOCK_START} nonce={request.nonce} tip={request.tip}"
    starts = [i for i, line in enumerate(lines) if line.startswith(f"{VERDICT_BLOCK_START} ")]
    if len(starts) != 1 or lines[starts[0]] != header:
        raise RejectRefusedError("the reply holds no single verdict block for this request")
    if lines[-1] != VERDICT_BLOCK_END or lines.count(VERDICT_BLOCK_END) != 1:
        raise RejectRefusedError("the verdict block is not the end of the reply")
    body = lines[starts[0] + 1 : -1]
    if not body or not body[-1].startswith("overall "):
        raise RejectRefusedError("the verdict block has no closing overall line")
    stated = body[-1][len("overall ") :]
    if stated not in DECISIONS:
        raise RejectRefusedError(f"overall {stated!r} is neither no-value nor keep")
    items = tuple(_parse_item(line, request.inventory) for line in body[:-1])
    keep = stated == DECISION_KEEP or any(i.decision == DECISION_KEEP for i in items)
    return items, DECISION_KEEP if keep else DECISION_NO_VALUE


def _identified(
    store: RejectStore, stop: ReviewStop, facts: TranscriptFacts
) -> RejectRequest | None:
    """The request this stop is the dispatched reviewer of, or None."""
    if {stop.agent_type, stop.meta_agent_type} != {REVIEWER_AGENT_TYPE}:
        return None
    if not _SAFE_AGENT_ID.fullmatch(stop.agent_id) or facts.first_user_text is None:
        return None
    nonce = prompt_nonce(facts.first_user_text)
    if nonce is None:
        return None
    request = store.read_request(nonce)
    dispatch = store.read_dispatch(nonce)
    if request is None or dispatch is None:
        return None
    if prompt_digest(facts.first_user_text) != request.prompt_sha256:
        return None
    if not stop.session_id or not stop.meta_tool_use_id:
        return None
    if (dispatch.session_id, dispatch.tool_use_id) != (stop.session_id, stop.meta_tool_use_id):
        return None
    if dispatch.agent_id and dispatch.agent_id != stop.agent_id:
        return None
    return request


def record_review_stop(
    store: RejectStore, stop: ReviewStop, facts: TranscriptFacts, *, now: float
) -> str:
    """Record a reviewer's verdict from its stop; returns a ``STOP_*`` outcome.

    A verdict counts only from a clean, FINAL stop. The first stop of an identified
    reviewer takes an exclusive ``stops/<nonce>`` marker before anything else; any later
    stop, or one with ``stop_hook_active`` (a stop hook blocked an earlier one), withdraws
    the nonce's verdict and writes nothing. The verdict id is the nonce, so a nonce has
    at most one verdict. A keep record is never withdrawn: it only restricts.

    Never writes the dispatch record's agent id and never touches the ledger. Raises
    RejectError when a record cannot be read or written.
    """
    request = _identified(store, stop, facts)
    if request is None:
        return STOP_IGNORED
    first = store.mark_stop(request.nonce)
    if not first or stop.stop_hook_active:
        store.withdraw_verdict(request.nonce)
        return STOP_WITHDRAWN
    if facts.damaged or facts.last_assistant_text != stop.reply:
        return STOP_IGNORED
    try:
        items, overall = parse_verdict_reply(stop.reply, request)
    except RejectRefusedError:
        return STOP_IGNORED
    verdict = Verdict(
        verdict_id=request.nonce,
        nonce=request.nonce,
        branch=request.branch,
        tip=request.tip,
        default_sha=request.default_sha,
        inventory=request.inventory,
        items=items,
        overall=overall,
        issued_at=now,
        reviewer=Reviewer(
            session_id=stop.session_id,
            agent_id=stop.agent_id,
            models=facts.models,
            downgraded=facts.downgraded,
            fork=False,
            user_turns=facts.user_turns,
            reply_sha256=hashlib.sha256(stop.reply.encode("utf-8")).hexdigest(),
        ),
    )
    if overall == DECISION_KEEP:
        kept = [i.reason for i in items if i.decision == DECISION_KEEP]
        store.write_keep(
            KeepRecord(
                verdict_id=request.nonce,
                branch=request.branch,
                tip=request.tip,
                commits=request.inventory.commits,
                reasons=tuple(kept or (i.reason for i in items)),
                recorded_at=now,
            )
        )
    if not store.create_verdict(verdict):
        store.withdraw_verdict(request.nonce)
        return STOP_WITHDRAWN
    return STOP_RECORDED


def _check_quotable(label: str, text: str) -> None:
    for char in text:
        if unicodedata.category(char) in _REFUSED_CATEGORIES:
            raise RejectRefusedError(
                f"{label} {text!r} holds a control character (U+{ord(char):04X}); the "
                "review prompt cannot quote it, so this branch cannot be reviewed"
            )


def compose_prompt(
    *,
    nonce: str,
    branch: str,
    tip: str,
    default_sha: str,
    commits: Sequence[tuple[str, str]],
    paths: Sequence[str],
    keep_reasons: Sequence[str],
) -> str:
    """The exact review prompt; raises RejectRefusedError on any unquotable text.

    Composed from git facts and the stored keep history only, never from caller text.
    Deterministic and without a trailing newline, so its sha256 is a stable identity.
    """
    _check_quotable("branch", branch)
    for sha, subject in commits:
        _check_quotable("commit subject", subject)
        _check_quotable("commit", sha)
    for path in paths:
        _check_quotable("path", path)
        if path.startswith('"'):
            # ls-tree C-quotes a name holding a control character or a quote, so the
            # inventory carries the quoted form; it is refused like the raw character.
            raise RejectRefusedError(
                f"path {path} is git-quoted (it holds a control character or a quote); "
                "the review prompt cannot quote it, so this branch cannot be reviewed"
            )
    for reason in keep_reasons:
        _check_quotable("earlier keep reason", reason)
    lines = [
        f"{PROMPT_MARKER}{nonce}",
        "",
        f"You are reviewing the unmerged work on branch `{branch}` at tip {tip}, measured "
        f"against the default branch at {default_sha}. Decide, for each item below, whether "
        "it has any value. Doubt means keep.",
        "",
        "Keep by default, unless you cite what supersedes it on the default branch: tests, "
        "plan and journal files, documentation, configuration, and any work a plan or "
        "journal describes.",
        "",
        "Read the work with read-only git commands only, for example `git show <sha>` and "
        f"`git diff {default_sha} {tip} -- <path>`. Change no file, branch or ref.",
        "",
        "Commits not on the default branch:",
        *([f"- {sha} {subject}" for sha, subject in commits] or ["- (none)"]),
        "Files whose content exists nowhere on the default branch:",
        *([f"- {path}" for path in paths] or ["- (none)"]),
    ]
    if keep_reasons:
        lines += [
            "",
            "An earlier review judged this work worth keeping, for these reasons:",
            *(f"- {reason}" for reason in keep_reasons),
            "A no-value verdict must answer each of them.",
        ]
    lines += [
        "",
        "Reply with exactly this block and nothing after it: one line per commit and per "
        "file listed above, each with a reason. A superseded-by list cites commits or "
        "paths on the default branch.",
        f"{VERDICT_BLOCK_START} nonce={nonce} tip={tip}",
        "commit <sha> no-value|keep: <reason> [superseded-by: commit:<sha> path:<path> ...]",
        "path <path> no-value|keep: <reason> [superseded-by: ...]",
        "overall no-value|keep",
        VERDICT_BLOCK_END,
    ]
    return "\n".join(lines)


def commit_subjects(repo: Path, shas: Sequence[str]) -> dict[str, str]:
    """Each commit's subject line; raises RejectError when any is missing."""
    if not shas:
        return {}
    out = _git_out(repo, "log", "--no-walk=unsorted", "--format=%H%x00%s", *shas)
    subjects: dict[str, str] = {}
    for record in out.split("\n"):
        if record:
            sha, _, subject = record.partition("\x00")
            subjects[sha] = subject
    missing = sorted(set(shas) - set(subjects))
    if missing:
        raise RejectError(f"git log did not report the subject of {missing}")
    return subjects


@dataclass(frozen=True)
class IssuedRequest:
    """A stored request and the exact prompt its reviewer must be dispatched with."""

    request: RejectRequest
    prompt: str


def issue_requests(repo: Path, branch: str, route: RejectRoute) -> list[IssuedRequest]:
    """Admit a review of ``branch`` and store one request per reviewer required.

    One nonce binds one reviewer agent, so a review needing two reviewers mints two
    requests. The caller must already have classified the branch as ``unproven`` with
    no refusal. Raises RejectRefusedError when admission refuses and RejectError when
    a fact cannot be read; nothing is stored in either case. Never touches the ledger.
    """
    if route.default_ref is None:
        raise RejectError("a review request needs the resolved default branch")
    default_ref = route.default_ref
    entries = read_ledger_entries(route.ledger_path)
    tip = branch_tip(repo, branch)
    default_sha = _resolve(repo, _full_ref(default_ref))
    inventory = compute_inventory(repo, branch, default_ref)
    if (branch_tip(repo, branch), _resolve(repo, _full_ref(default_ref))) != (tip, default_sha):
        raise RejectError("the branch or the default moved while the inventory was computed")
    keeps = route.store.keeps()
    removals = removals_in_window(effective_removals(entries), now=route.now, config=route.config)
    required = admit_request(branch, tip, inventory, keeps, removals, route.config)
    keep_reasons = tuple(
        reason for keep in related_keeps(branch, tip, inventory, keeps) for reason in keep.reasons
    )
    subjects = commit_subjects(repo, inventory.commits)
    issued: list[IssuedRequest] = []
    for _ in range(required):
        nonce = new_id()
        prompt = compose_prompt(
            nonce=nonce,
            branch=branch,
            tip=tip,
            default_sha=default_sha,
            commits=[(sha, subjects[sha]) for sha in inventory.commits],
            paths=inventory.paths,
            keep_reasons=keep_reasons,
        )
        request = RejectRequest(
            nonce=nonce,
            branch=branch,
            tip=tip,
            default_sha=default_sha,
            inventory=inventory,
            reviewers_required=required,
            prompt_sha256=prompt_digest(prompt),
            created_at=route.now,
        )
        issued.append(IssuedRequest(request=request, prompt=prompt))
    for item in issued:
        route.store.write_request(item.request)
    return issued


# --- the recovery bundle -------------------------------------------------------------


def main_checkout(repo: Path) -> Path:
    """The MAIN checkout of ``repo``'s repository; raises RejectError when there is none."""
    if _git_out(repo, "rev-parse", "--is-bare-repository").strip() == "true":
        raise RejectError(f"{repo} is a bare repository; there is no main checkout")
    common = Path(_git_out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    if common.name != _GIT_DIR_NAME:
        raise RejectError(f"the git common directory {common} is not a checkout's .git")
    return common.parent.resolve()


def bundle_path_for(repo: Path, config: BranchRejectConfig, branch: str, tip: str) -> Path:
    """``<main>/<bundle_dir>/<branch-slug>-<tip12>.bundle``."""
    slug = _SLUG_UNSAFE.sub("-", branch)
    return main_checkout(repo) / config.bundle_dir / f"{slug}-{tip[:_TIP_IN_NAME]}.bundle"


def sha256_of(path: Path) -> str:
    """The file's sha256; raises RejectError when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RejectError(f"could not read {path}: {exc}") from exc
    return digest.hexdigest()


@dataclass(frozen=True)
class BundleRecord:
    """A bundle the guard wrote, and what it recorded about it at write time.

    ``base`` is the default-branch commit the bundle was cut against: every
    prerequisite the bundle names must be an ancestor of it, or the bundle leans on
    a commit only the branch holds and restores nothing once the branch is gone.
    """

    path: Path
    sha256: str
    tip: str
    base: str


def bundle_prerequisites(path: Path) -> tuple[str, ...]:
    """The commits a bundle requires the receiving repository to hold already.

    Read from the bundle header (``-<oid>`` lines before the blank line). Raises
    RejectError when the file cannot be read or holds no complete header.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(_HEADER_LIMIT)
    except OSError as exc:
        raise RejectError(f"could not read {path}: {exc}") from exc
    end = head.find(b"\n\n")
    if end < 0:
        raise RejectError(f"{path} holds no complete bundle header")
    prerequisites: list[str] = []
    for raw in head[:end].split(b"\n")[1:]:
        if raw.startswith(_FILTER_CAPABILITY):
            raise RejectError(f"{path} is a filtered bundle, which omits objects")
        if not raw.startswith(b"-"):
            continue
        oid = raw[1:].split(b" ", 1)[0].decode("ascii", errors="replace")
        if not _OBJECT.fullmatch(oid):
            raise RejectError(f"{path} names a prerequisite that is not an object id")
        prerequisites.append(oid)
    return tuple(prerequisites)


def _prerequisite_problems(repo: Path, record: BundleRecord) -> list[str]:
    try:
        prerequisites = bundle_prerequisites(record.path)
    except RejectError as exc:
        return [f"the bundle header is not acceptable: {exc}"]
    return [
        f"the bundle prerequisite {oid[:12]} is not on the default branch at "
        f"{record.base[:12]}, so the bundle restores nothing once the branch is gone"
        for oid in prerequisites
        if not _git_ok(repo, "merge-base", "--is-ancestor", oid, record.base)
    ]


def bundle_problems(repo: Path, record: BundleRecord, branch: str) -> list[str]:
    """Every reason the bundle cannot back a removal; an empty list is the only pass."""
    if not record.path.is_file():
        return [f"the bundle file is missing: {record.path}"]
    problems: list[str] = []
    if sha256_of(record.path) != record.sha256:
        problems.append("the bundle's sha256 differs from the one recorded when it was written")
    verify = run_git(repo, "bundle", "verify", str(record.path), timeout=_git_budget())
    if verify.returncode != 0:
        problems.append(f"git bundle verify failed: {verify.stderr.strip() or 'no detail'}")
    heads = run_git(repo, "bundle", "list-heads", str(record.path), timeout=_git_budget())
    wanted = f"{record.tip} {branch_ref(branch)}"
    if heads.returncode != 0 or wanted not in heads.stdout.splitlines():
        problems.append(f"the bundle does not list {record.tip[:12]} as {branch_ref(branch)}")
    problems += _prerequisite_problems(repo, record)
    return problems


def write_bundle(
    repo: Path, branch: str, tip: str, default_sha: str, config: BranchRejectConfig
) -> BundleRecord:
    """Write (or reuse) the branch's recovery bundle in the main checkout and verify it.

    Never overwrites: an existing file at the path is verified and reused, and one
    that does not verify refuses. Raises RejectError on every failure.
    """
    current = branch_tip(repo, branch)
    if current != tip:
        raise RejectError(f"{branch} is at {current[:12]}, not the expected {tip[:12]}")
    path = bundle_path_for(repo, config, branch, tip)
    if not path.exists():
        _create_bundle(repo, branch, default_sha, path)
    record = BundleRecord(path=path, sha256=sha256_of(path), tip=tip, base=default_sha)
    problems = bundle_problems(repo, record, branch)
    if problems:
        raise RejectError(f"the bundle at {path} is not sound: {'; '.join(problems)}")
    if _written_sha256(path) != record.sha256:
        # `git bundle verify` reads the header, not the pack, so a planted or altered
        # file can pass every check above. Only bytes the guard wrote are trusted.
        raise RejectError(
            f"the bundle at {path} was not written by the guard, or changed since; "
            "move it aside to let the guard write its own"
        )
    return record


def _sha256_sidecar(path: Path) -> Path:
    return path.with_name(f"{path.name}{_SIDECAR_SUFFIX}")


def _written_sha256(path: Path) -> str | None:
    sidecar = _sha256_sidecar(path)
    if not sidecar.is_file():
        return None
    try:
        return sidecar.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RejectError(f"could not read {sidecar}: {exc}") from exc


def _create_bundle(repo: Path, branch: str, default_sha: str, path: Path) -> None:
    """Create the bundle, never overwriting, and record its sha256 beside it."""
    tmp = path.with_name(f".{path.name}.{new_id()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _git_out(repo, "bundle", "create", str(tmp), branch_ref(branch), f"^{default_sha}")
        path.hardlink_to(tmp)
        _sha256_sidecar(path).write_text(sha256_of(path) + "\n", encoding="utf-8")
    except OSError as exc:
        raise RejectError(f"could not write the bundle {path}: {exc}") from exc
    finally:
        with suppress(FileNotFoundError, NotADirectoryError):
            tmp.unlink()


def restore_commands(branch: str, tip: str, bundle: Path) -> tuple[str, str]:
    """The fetch from the bundle, and ``git branch <name> <tip>``."""
    ref = shlex.quote(f"{branch_ref(branch)}:{branch_ref(branch)}")
    return (
        f"git fetch {shlex.quote(str(bundle))} {ref}",
        f"git branch {shlex.quote(branch)} {tip}",
    )


# --- the ledger ----------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerLine:
    """One removal, as the tracked ledger records it (RULINGS.md Q8)."""

    branch: str
    tip: str
    default_sha: str
    verdict_ids: tuple[str, ...]
    reviewer_agent_ids: tuple[str, ...]
    reviewer_models: tuple[str, ...]
    reply_sha256s: tuple[str, ...]
    bundle_path: str
    bundle_sha256: str
    restore_commands: tuple[str, ...]
    removed_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "branch": self.branch,
            "tip": self.tip,
            "default_sha": self.default_sha,
            "verdict_ids": list(self.verdict_ids),
            "reviewer_agent_ids": list(self.reviewer_agent_ids),
            "reviewer_models": list(self.reviewer_models),
            "reply_sha256s": list(self.reply_sha256s),
            "bundle_path": self.bundle_path,
            "bundle_sha256": self.bundle_sha256,
            "restore_commands": list(self.restore_commands),
            "removed_at": self.removed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LedgerLine:
        _schema(data)
        return cls(
            branch=_str(data, "branch"),
            tip=_str(data, "tip"),
            default_sha=_str(data, "default_sha"),
            verdict_ids=_strs(data, "verdict_ids"),
            reviewer_agent_ids=_strs(data, "reviewer_agent_ids"),
            reviewer_models=_strs(data, "reviewer_models"),
            reply_sha256s=_strs(data, "reply_sha256s"),
            bundle_path=_str(data, "bundle_path"),
            bundle_sha256=_str(data, "bundle_sha256"),
            restore_commands=_strs(data, "restore_commands"),
            removed_at=_float(data, "removed_at"),
        )


def append_ledger(path: Path, line: LedgerLine) -> None:
    """Append one line with a single ``O_APPEND`` write, then fsync."""
    _append_payload(path, line.to_dict())


@dataclass(frozen=True)
class LedgerRefusal:
    """Git refused a removal whose line was already appended (DESIGN.md section 10).

    The ledger line goes in BEFORE git is asked (RULINGS.md section 1 item 5), so a
    refusal is recorded as a second, append-only line naming the same tip and
    verdicts. That attempt then counts as no removal, but its verdicts stay consumed.
    """

    branch: str
    tip: str
    verdict_ids: tuple[str, ...]
    detail: str
    refused_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "outcome": OUTCOME_GIT_REFUSED,
            "branch": self.branch,
            "tip": self.tip,
            "verdict_ids": list(self.verdict_ids),
            "detail": self.detail,
            "refused_at": self.refused_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LedgerRefusal:
        _schema(data)
        if _str(data, "outcome") != OUTCOME_GIT_REFUSED:
            raise RejectError(f"unknown ledger outcome {data.get('outcome')!r}")
        return cls(
            branch=_str(data, "branch"),
            tip=_str(data, "tip"),
            verdict_ids=_strs(data, "verdict_ids"),
            detail=_str(data, "detail"),
            refused_at=_float(data, "refused_at"),
        )


LedgerEntry = LedgerLine | LedgerRefusal


def _append_payload(path: Path, data: Mapping[str, Any]) -> None:
    payload = (json.dumps(data, sort_keys=True) + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _LEDGER_MODE)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise RejectError(f"could not append to the ledger {path}: {exc}") from exc


def append_refusal(path: Path, refusal: LedgerRefusal) -> None:
    """Append a ``git-refused`` line with a single ``O_APPEND`` write, then fsync."""
    _append_payload(path, refusal.to_dict())


def read_ledger_entries(path: Path) -> list[LedgerEntry]:
    """Every ledger entry in file order; a missing ledger is empty.

    Strict: a line that is not JSON, not an object, missing a field or naming an
    unknown outcome raises RejectError, so a damaged ledger refuses the route.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RejectError(f"could not read the ledger {path}: {exc}") from exc
    entries: list[LedgerEntry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise RejectError(f"{path} line {number} is not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise RejectError(f"{path} line {number} is not a JSON object")
        try:
            entry: LedgerEntry = (
                LedgerRefusal.from_dict(data) if "outcome" in data else LedgerLine.from_dict(data)
            )
        except RejectError as exc:
            raise RejectError(f"{path} line {number}: {exc}") from exc
        entries.append(entry)
    return entries


def effective_removals(entries: Iterable[LedgerEntry]) -> list[LedgerLine]:
    """The removal lines no ``git-refused`` line cancels (same tip and verdicts)."""
    materialised = list(entries)
    refused = {
        (entry.tip, entry.verdict_ids) for entry in materialised if isinstance(entry, LedgerRefusal)
    }
    return [
        entry
        for entry in materialised
        if isinstance(entry, LedgerLine) and (entry.tip, entry.verdict_ids) not in refused
    ]


def read_ledger(path: Path) -> list[LedgerLine]:
    """Every removal that happened; a missing ledger is empty, a damaged one raises."""
    return effective_removals(read_ledger_entries(path))


def consumed_verdict_ids(entries: Iterable[LedgerEntry]) -> frozenset[str]:
    """Every verdict id a removal, or a refused removal attempt, has already used."""
    return frozenset(verdict_id for entry in entries for verdict_id in entry.verdict_ids)


def removals_in_window(
    lines: Iterable[LedgerLine], *, now: float, config: BranchRejectConfig
) -> int:
    """Removals within the last ``window_days`` up to ``now``."""
    start = now - config.window_days * _SECONDS_PER_DAY
    return sum(1 for line in lines if start <= line.removed_at <= now)


# --- the delete route (slice 2, DESIGN.md section 10) ----------------------------------


@dataclass(frozen=True)
class RemovalApproval:
    """Everything the guard recomputed that lets one ``unproven`` branch go.

    ``bundle`` is None only on a dry run, which validates and writes nothing.
    """

    branch: str
    tip: str
    default_sha: str
    verdicts: tuple[Verdict, ...]
    bundle: BundleRecord | None


def _verdict_refusal(verdicts: Sequence[Verdict], problems: Mapping[str, list[str]]) -> str:
    detail = "; ".join(
        f"verdict {verdict_id[:12]}: {', '.join(found)}" for verdict_id, found in problems.items()
    )
    count = len(verdicts)
    return f"{count} verdict(s) on file for this tip, none usable" + (
        f" ({detail})" if detail else ""
    )


def approve_removal(
    repo: Path,
    branch: str,
    tip: str,
    route: RejectRoute,
    *,
    default_ref: str,
    write: bool,
    pending: int = 0,
) -> RemovalApproval:
    """Recompute every fact the route rests on; raise RejectRefusedError or RejectError.

    In order: the ledger reads cleanly; the admission rules (keep history and the
    removal rate, both re-read NOW, never trusted from the request) give the number
    of reviewers; any stored verdict for this tip judging ``keep`` refuses outright;
    the remaining verdicts each validate in full; the valid set meets the number from
    distinct agents; and, unless ``write`` is False, the bundle is written and
    verified against the default as it stands now.

    ``pending`` is the number of removals this same batch has already approved: none
    of them is in the ledger yet, and the rate must count them all the same.
    """
    entries = read_ledger_entries(route.ledger_path)
    default_sha = _resolve(repo, _full_ref(default_ref))
    inventory = compute_inventory(repo, branch, default_ref)
    removals = pending + removals_in_window(
        effective_removals(entries), now=route.now, config=route.config
    )
    required = admit_request(branch, tip, inventory, route.store.keeps(), removals, route.config)
    verdicts = route.store.verdicts_for(branch, tip)
    if not verdicts:
        raise RejectRefusedError("no reviewer verdict is on file for this tip")
    if any(
        v.overall != DECISION_NO_VALUE or any(i.decision != DECISION_NO_VALUE for i in v.items)
        for v in verdicts
    ):
        raise RejectRefusedError("a reviewer judged keep for this tip; disagreement is keep")
    consumed = consumed_verdict_ids(entries)
    valid: list[Verdict] = []
    problems: dict[str, list[str]] = {}
    for verdict in verdicts:
        found = verdict_problems(
            verdict,
            repo=repo,
            store=route.store,
            default_ref=default_ref,
            now=route.now,
            consumed=consumed,
            config=route.config,
        )
        if found:
            problems[verdict.verdict_id] = found
            continue
        request = route.store.read_request(verdict.nonce)
        if request is None:
            raise RejectError(f"the request {verdict.nonce[:12]} vanished during the check")
        required = max(required, request.reviewers_required)
        valid.append(verdict)
    if not valid:
        raise RejectRefusedError(_verdict_refusal(verdicts, problems))
    set_problems = verdict_set_problems(valid, required=required)
    if set_problems:
        raise RejectRefusedError("; ".join(set_problems))
    bundle = write_bundle(repo, branch, tip, default_sha, route.config) if write else None
    return RemovalApproval(
        branch=branch, tip=tip, default_sha=default_sha, verdicts=tuple(valid), bundle=bundle
    )


def record_removal(repo: Path, approval: RemovalApproval, route: RejectRoute) -> LedgerLine:
    """Re-verify the bundle and the verdicts' single use, then append the ledger line.

    Called after the tip re-check and BEFORE git is asked to delete (RULINGS.md
    section 1 item 5). Raises RejectError when anything no longer holds; the branch
    is then left in place.
    """
    if approval.bundle is None:
        raise RejectError("a dry-run approval cannot record a removal")
    problems = bundle_problems(repo, approval.bundle, approval.branch)
    if problems:
        raise RejectError(f"the bundle no longer verifies: {'; '.join(problems)}")
    ids = tuple(v.verdict_id for v in approval.verdicts)
    reused = consumed_verdict_ids(read_ledger_entries(route.ledger_path)) & set(ids)
    if reused:
        raise RejectError(f"verdict(s) already used by a concurrent removal: {sorted(reused)}")
    line = LedgerLine(
        branch=approval.branch,
        tip=approval.tip,
        default_sha=approval.default_sha,
        verdict_ids=ids,
        reviewer_agent_ids=tuple(v.reviewer.agent_id for v in approval.verdicts),
        reviewer_models=tuple(m for v in approval.verdicts for m in v.reviewer.models),
        reply_sha256s=tuple(v.reviewer.reply_sha256 for v in approval.verdicts),
        bundle_path=str(approval.bundle.path),
        bundle_sha256=approval.bundle.sha256,
        restore_commands=restore_commands(approval.branch, approval.tip, approval.bundle.path),
        removed_at=route.now,
    )
    append_ledger(route.ledger_path, line)
    return line


def record_git_refusal(line: LedgerLine, detail: str, route: RejectRoute) -> None:
    """Append the ``git-refused`` line cancelling ``line``; raises RejectError on failure."""
    append_refusal(
        route.ledger_path,
        LedgerRefusal(
            branch=line.branch,
            tip=line.tip,
            verdict_ids=line.verdict_ids,
            detail=detail,
            refused_at=route.now,
        ),
    )


# --- the digest (slice 3, RULINGS.md section 3 item 5) --------------------------------


def entry_key(entry: LedgerEntry) -> str:
    """The sha256 of the entry's canonical JSON: its identity, not its position.

    The ledger merges with ``merge=union``, so a line can arrive by a merge AFTER a
    digest, anywhere in the file. A positional or time watermark would read such a
    line as already digested; an identity key never does.
    """
    canonical = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DigestState:
    """The digest watermark: what an explicit mark-read has recorded as read.

    It gates nothing. ``approve_removal`` never reads it, so an agent that marks
    entries read hides them from the digest only, never unlocks a delete.
    """

    ledger_keys: frozenset[str]
    keep_ids: frozenset[str]
    marked_at: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "ledger_keys": sorted(self.ledger_keys),
            "keep_ids": sorted(self.keep_ids),
            "marked_at": self.marked_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DigestState:
        _schema(data)
        ledger_keys = _strs(data, "ledger_keys")
        keep_ids = _strs(data, "keep_ids")
        if not all(_ENTRY_KEY.fullmatch(key) for key in ledger_keys):
            raise RejectError("a digest ledger key is not a 64-hex entry key")
        if not all(_ID.fullmatch(key) for key in keep_ids):
            raise RejectError("a digest keep id is not a record id")
        return cls(
            ledger_keys=frozenset(ledger_keys),
            keep_ids=frozenset(keep_ids),
            marked_at=_float(data, "marked_at"),
        )


_NEVER_MARKED = DigestState(ledger_keys=frozenset(), keep_ids=frozenset(), marked_at=None)


def read_digest_state(path: Path) -> DigestState:
    """The watermark; a missing file was never marked, a damaged one raises RejectError."""
    if not path.exists():
        return _NEVER_MARKED
    return DigestState.from_dict(RejectStore._load(path))


def write_digest_state(path: Path, state: DigestState) -> None:
    """Write the watermark atomically (a sibling temp file, then ``os.replace``)."""
    if state.marked_at is None:
        raise RejectError("a written digest state records when it was marked")
    tmp = path.with_name(f".{path.name}.{new_id()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state.to_dict(), sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise RejectError(f"could not write {path}: {exc}") from exc
    finally:
        with suppress(FileNotFoundError, NotADirectoryError):
            tmp.unlink()


@dataclass(frozen=True)
class Digest:
    """Everything not yet marked read, and the route's rate state now.

    ``ledger_keys`` are the keys of the listed entries, so a mark-read marks exactly
    what was listed and never an entry that arrived after the listing.
    """

    removals: tuple[LedgerLine, ...]
    refusals: tuple[LedgerRefusal, ...]
    keeps: tuple[KeepRecord, ...]
    ledger_keys: frozenset[str]
    removals_in_window: int
    #: Reviewers the next removal needs; None when the route is refusing.
    reviewers_next: int | None
    last_marked_at: float | None

    @property
    def is_empty(self) -> bool:
        return not (self.removals or self.refusals or self.keeps)


def build_digest(
    ledger_path: Path, store: RejectStore, *, now: float, config: BranchRejectConfig
) -> Digest:
    """List every undigested ledger entry and keep record; never writes anything.

    Strict: a damaged ledger, keep record or watermark raises RejectError, so an
    unreadable state never reads as "nothing to digest". The rate counts every
    removal in the window, marked read or not.
    """
    entries = read_ledger_entries(ledger_path)
    keeps = store.keeps()
    state = read_digest_state(store.digest_path)
    fresh = [entry for entry in entries if entry_key(entry) not in state.ledger_keys]
    removals = removals_in_window(effective_removals(entries), now=now, config=config)
    return Digest(
        removals=tuple(entry for entry in fresh if isinstance(entry, LedgerLine)),
        refusals=tuple(entry for entry in fresh if isinstance(entry, LedgerRefusal)),
        keeps=tuple(keep for keep in keeps if keep.verdict_id not in state.keep_ids),
        ledger_keys=frozenset(entry_key(entry) for entry in fresh),
        removals_in_window=removals,
        reviewers_next=reviewers_for_rate(removals, config),
        last_marked_at=state.marked_at,
    )


def mark_digest_read(store: RejectStore, digest: Digest, *, now: float) -> DigestState:
    """Add exactly the listed entries to the watermark, recording when; returns it."""
    current = read_digest_state(store.digest_path)
    state = DigestState(
        ledger_keys=current.ledger_keys | digest.ledger_keys,
        keep_ids=current.keep_ids | {keep.verdict_id for keep in digest.keeps},
        marked_at=now,
    )
    write_digest_state(store.digest_path, state)
    return state


def branch_still_at_tip(repo: Path, line: LedgerLine) -> bool:
    """True when the removed branch still resolves at the recorded tip.

    A crash between the ledger append and git's answer leaves exactly that. Absent
    is the normal case and is False; any other git failure raises RejectError, so a
    failed lookup never reads as "removed".
    """
    result = run_git(
        repo,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{branch_ref(line.branch)}^{{commit}}",
        timeout=_git_budget(),
    )
    if result.returncode == 0:
        return result.stdout.strip() == line.tip
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return False
    raise RejectError(f"could not resolve {line.branch}: {result.stderr.strip() or 'no detail'}")

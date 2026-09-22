"""Resolve which prompt-cache TTL each request bucket gets (Plan 00452).

Claude Code decides a TTL per request, and every request falls into one of two
fixed buckets:

* **MAIN** — interactive turns, `-p` runs, Agent SDK turns, and the helpers run
  inline with them.
* **EVERYTHING ELSE** — sub-agents, workflows, in-process teammates, forks,
  compaction, session titles.

**The second bucket gets five minutes even on a subscription**, and that is the
fact this module exists to surface. It is the expensive half: a short sub-agent
never amortises its mandatory first cache write, and measured in this project
the two halves ran 98.87% (main, 1h) against 62.17% (sub-agent, 5m).

The resolution order is documented upstream and is NOT guessable, so it is
implemented once here rather than re-derived per call site. Vendored source:
``remote-docs/code.claude.com/docs/en/prompt-caching.md``.

**Only ``5m`` and ``1h`` are accepted; Claude Code ignores anything else.** A
project that sets ``3600`` or ``1hr`` believes it has chosen a TTL and has not,
so an invalid value falls through to the next control AND is reported in
``ignored`` — reporting it as an explicit choice would be worse than reporting
nothing at all.

**The MAIN default is deliberately ``None``.** It is one hour on a Claude
subscription within plan usage and five minutes on credits, an API key or a
cloud provider, and nothing inside a hook can see which applies. A guess there
would be a confident wrong answer about the more expensive half of the bill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

#: The main-conversation request bucket.
BUCKET_MAIN: Final[str] = "main"

#: Everything Claude Code runs outside the main conversation.
BUCKET_SUBAGENT: Final[str] = "subagent"

#: The only two values Claude Code honours.
VALID_TTLS: Final[frozenset[str]] = frozenset({"5m", "1h"})

#: Forces five minutes for BOTH buckets, ahead of every other control.
_FORCE_5M_VAR: Final[str] = "FORCE_PROMPT_CACHING_5M"

#: Requests one hour for BOTH buckets, but only if nothing more specific won.
_ENABLE_1H_VAR: Final[str] = "ENABLE_PROMPT_CACHING_1H"

#: Per-bucket (env var, settings key) pairs.
_BUCKET_CONTROLS: Final[dict[str, tuple[str, str]]] = {
    BUCKET_MAIN: ("CLAUDE_CODE_PROMPT_CACHE_TTL", "promptCacheTtl"),
    BUCKET_SUBAGENT: ("CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL", "subagentPromptCacheTtl"),
}

#: Bucket defaults. None means "depends on billing, and we cannot see it".
_BUCKET_DEFAULTS: Final[dict[str, str | None]] = {
    BUCKET_MAIN: None,
    BUCKET_SUBAGENT: "5m",
}

#: Env values that count as the flag being ON. Anything else leaves it off.
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

#: Minimum Claude Code version for the per-bucket settings and env vars.
MIN_VERSION_FOR_TTL_CONTROLS: Final[str] = "2.1.242"


@dataclass(frozen=True)
class TtlResolution:
    """Which TTL a bucket gets, where that came from, and what was ignored."""

    bucket: str
    ttl: str | None
    source: str
    explicit: bool
    ignored: list[tuple[str, str]] = field(default_factory=list)


def _is_truthy(raw: object) -> bool:
    """A flag env var is ON only for a recognised truthy value.

    `FORCE_PROMPT_CACHING_5M=0` must not behave like `=1`; treating mere
    presence as ON is the classic version of this bug.
    """
    return isinstance(raw, str) and raw.strip().lower() in _TRUTHY


def _valid_ttl(raw: object) -> str | None:
    """`raw` if Claude Code would honour it, else None.

    Case-sensitive on purpose: the documentation names `5m` and `1h`, and
    accepting `1H` here would claim a setting works when it does not.
    """
    return raw if isinstance(raw, str) and raw in VALID_TTLS else None


def resolve_ttl(
    bucket: str,
    settings: dict[str, Any] | None,
    env: dict[str, str] | None,
) -> TtlResolution:
    """Resolve one bucket's effective TTL.

    Args:
        bucket: `BUCKET_MAIN` or `BUCKET_SUBAGENT`.
        settings: Parsed `.claude/settings.json`. Anything that is not a dict
            is treated as absent — it comes from a file on disk that anything
            could have written.
        env: The process environment.

    Returns:
        The resolved `TtlResolution`.

    Raises:
        ValueError: The bucket is not one of the two documented ones. Raised
            rather than defaulted: a typo'd bucket silently reporting the main
            conversation's TTL would be a wrong answer wearing a right one's
            clothes.
    """
    if bucket not in _BUCKET_CONTROLS:
        raise ValueError(
            f"Unknown prompt-cache bucket {bucket!r}; expected "
            f"{BUCKET_MAIN!r} or {BUCKET_SUBAGENT!r}"
        )

    settings = settings if isinstance(settings, dict) else {}
    env = env if isinstance(env, dict) else {}
    env_var, settings_key = _BUCKET_CONTROLS[bucket]

    ignored: list[tuple[str, str]] = []
    for name, raw in ((env_var, env.get(env_var)), (settings_key, settings.get(settings_key))):
        if raw is not None and _valid_ttl(raw) is None:
            ignored.append((name, str(raw)))

    def _resolved(ttl: str | None, source: str, explicit: bool) -> TtlResolution:
        return TtlResolution(
            bucket=bucket, ttl=ttl, source=source, explicit=explicit, ignored=ignored
        )

    # 1. The debugging override beats everything, in both buckets.
    if _is_truthy(env.get(_FORCE_5M_VAR)):
        return _resolved("5m", _FORCE_5M_VAR, True)

    # 2. This bucket's own environment variable.
    from_env = _valid_ttl(env.get(env_var))
    if from_env:
        return _resolved(from_env, env_var, True)

    # 3. This bucket's own setting.
    from_settings = _valid_ttl(settings.get(settings_key))
    if from_settings:
        return _resolved(from_settings, settings_key, True)

    # A sub-agent's own `experimental.cacheTtl` frontmatter sits here in the
    # documented order. It is per-agent rather than per-session, so it cannot
    # be resolved from settings alone and is deliberately not modelled.

    # 5. The blanket one-hour request, if nothing more specific applied.
    if _is_truthy(env.get(_ENABLE_1H_VAR)):
        return _resolved("1h", _ENABLE_1H_VAR, True)

    # 6. The bucket default — nobody chose this.
    return _resolved(_BUCKET_DEFAULTS[bucket], "default", False)

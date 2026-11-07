"""The release-assets workflow publishes attested binaries for both architectures.

Plan 00572 Task 3.2. A tag push builds the relay and hooks-screen natively on
an x86_64 and an aarch64 runner, merges one SHA256SUMS over every asset,
attests them and uploads them to the tag's GitHub release. The asset names
must be the ones ``install/relay_deploy.py`` downloads, or the download route
fetches nothing.
"""

from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.install.relay_deploy import (
    PUBLISHED_RELAY_TARGETS,
    SHA256SUMS_ASSET_NAME,
    relay_asset_name_for_target,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-assets.yml"
RELEASING = REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    document: dict[Any, Any] = _workflow()
    triggers: dict[str, Any] = document["on"] if "on" in document else document[True]
    return triggers


def _job(name: str) -> dict[str, Any]:
    return _workflow()["jobs"][name]


def _runs(name: str) -> str:
    return "\n".join(step.get("run", "") for step in _job(name)["steps"])


def _uses(name: str) -> list[str]:
    return [step["uses"] for step in _job(name)["steps"] if "uses" in step]


def test_a_version_tag_push_triggers_it() -> None:
    assert _triggers()["push"]["tags"] == ["v*"]


def test_it_can_be_rerun_for_an_existing_tag() -> None:
    tag_input = _triggers()["workflow_dispatch"]["inputs"]["tag"]
    assert tag_input["required"] is True


def test_the_workflow_default_token_is_read_only() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}


def test_the_build_matrix_covers_both_architectures_on_native_runners() -> None:
    legs = _job("build")["strategy"]["matrix"]["include"]
    pairs = {(leg["runner"], leg["triple_arch"]) for leg in legs}
    assert pairs == {
        ("ubuntu-latest", "x86_64"),
        ("ubuntu-24.04-arm", "aarch64"),
    }


def test_every_published_relay_target_is_built() -> None:
    legs = _job("build")["strategy"]["matrix"]["include"]
    built = {f"{leg['triple_arch']}-unknown-linux-musl" for leg in legs}
    assert built == set(PUBLISHED_RELAY_TARGETS)


def test_one_failing_leg_does_not_cancel_the_other() -> None:
    assert _job("build")["strategy"]["fail-fast"] is False


def test_the_build_checks_out_the_tag_it_publishes() -> None:
    checkout = next(s for s in _job("build")["steps"] if "checkout" in s.get("uses", ""))
    assert "env.TAG" in checkout["with"]["ref"]


def test_the_build_produces_both_binaries_under_their_download_names() -> None:
    runs = _runs("build")
    assert "relay/build.sh" in runs
    assert "screen/build.sh" in runs
    assert "readelf -h" in runs
    for target in PUBLISHED_RELAY_TARGETS:
        arch = target.split("-", 1)[0]
        expected = relay_asset_name_for_target(target)
        assert expected == f"hooks-relay-{arch}-unknown-linux-musl"
    assert "hooks-relay-$TRIPLE" in runs
    assert "hooks-screen-$TRIPLE" in runs


def test_the_publish_job_waits_for_both_legs() -> None:
    assert _job("publish")["needs"] == "build"


def test_the_publish_job_holds_exactly_the_permissions_it_needs() -> None:
    assert _job("publish")["permissions"] == {
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_one_merged_checksum_manifest_covers_every_asset() -> None:
    runs = _runs("publish")
    assert "merge-multiple: true" in WORKFLOW.read_text(encoding="utf-8")
    assert f"sha256sum hooks-* > {SHA256SUMS_ASSET_NAME}" in runs


def test_the_assets_are_attested() -> None:
    attest = next(
        s for s in _job("publish")["steps"] if "attest-build-provenance" in s.get("uses", "")
    )
    assert "hooks-" in attest["with"]["subject-path"]


def test_the_release_is_awaited_then_uploaded_to_and_read_back() -> None:
    runs = _runs("publish")
    assert "gh release view" in runs
    assert "gh release upload" in runs
    assert "--clobber" in runs


def test_every_job_declares_a_timeout() -> None:
    for name, job in _workflow()["jobs"].items():
        assert isinstance(job.get("timeout-minutes"), int), name


def test_releasing_no_longer_uploads_the_relay_by_hand() -> None:
    text = RELEASING.read_text(encoding="utf-8")
    assert "build_relay_release_assets.sh" not in text
    assert "release-assets.yml" in text

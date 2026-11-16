#!/usr/bin/env python3
"""Plan 00609 proof: generated hook wrappers are root- and host-independent.

Re-runnable and read-only against the repo (all output under a temp dir and
this directory).  Run:  /workspace/.venv/bin/python prove.py   (exit 0 = all hold)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path("/workspace")
HERE = Path(__file__).resolve().parent
OLD_COMMIT = "8ea7c03c6^1"
HOSTS = ("host-one", "Host-Two.Example")
FAILURES: list[str] = []
LONG_SEGMENT = "deeply-nested-checkout-directory-"


def check(ok: bool, what: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {what}")
    if not ok:
        FAILURES.append(what)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def make_root(base: Path, kind: str, tag: str) -> Path:
    """A fresh checkout root: short, or deep enough to overflow AF_UNIX."""
    if kind == "short":
        root = base / f"s{tag}"
    else:
        root = base / (LONG_SEGMENT * 3) / f"x{tag}" / "checkout"
    # the daemon's own source dir marks a self-install (dogfood) layout, as in /workspace
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    return root


# --------------------------------------------------------------------------
# worker: a fresh process with HOSTNAME / XDG_RUNTIME_DIR really set
# --------------------------------------------------------------------------
def worker(root: Path, outdir: Path) -> None:
    sys.path.insert(0, str(REPO / "src"))
    from claude_code_hooks_daemon.config.models import TransportConfig
    from claude_code_hooks_daemon.daemon import paths
    from claude_code_hooks_daemon.install import forwarder_generator as fg

    transports = {
        "relay": TransportConfig(relay_enabled=True),
        "nc": TransportConfig(relay_enabled=False, nc_enabled=True),
        "both": TransportConfig(relay_enabled=True, nc_enabled=True),
    }
    untracked = root / "untracked"
    suffix = paths._get_hostname_suffix()
    sock = untracked / f"events{suffix}" / "pre-tool-use.sock"
    info = {
        "hostname_suffix": suffix,
        "get_untracked_dir": str(paths.get_untracked_dir(root)),
        "env_HOSTNAME": os.environ.get("HOSTNAME"),
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR"),
        "overflow_bytes": paths.socket_path_overflow(sock),
        "daemon_events_dir": str(paths.get_event_socket_dir_from_untracked(untracked)),
    }
    (outdir / "info.json").write_text(json.dumps(info, indent=1))

    # 1. generate from the BARE source (the generator's own strip of the tracked wrappers)
    for tname, transport in transports.items():
        d = outdir / tname
        d.mkdir(parents=True)
        for p in sorted((REPO / ".claude" / "hooks").iterdir()):
            if not p.is_file():
                continue
            bare = fg.strip_status_fast_path_block(fg.strip_relay_guard_block(p.read_text()))
            (d / p.name).write_text(
                fg.generate_forwarder_content(bare, p.name, transport, untracked, root)
            )

    # 2. the real deploy path: copy tracked wrappers in, regenerate in place
    hooks = root / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    for p in sorted((REPO / ".claude" / "hooks").iterdir()):
        if p.is_file():
            shutil.copy(p, hooks / p.name)
    shutil.copy(REPO / ".claude" / "hooks-daemon.yaml", root / ".claude" / "hooks-daemon.yaml")
    rewritten = fg.regenerate_deployed_hooks(root, hooks)
    (outdir / "regen_rewritten.json").write_text(json.dumps(rewritten))
    d = outdir / "regen"
    d.mkdir()
    for p in sorted(hooks.iterdir()):
        (d / p.name).write_bytes(p.read_bytes())


def run_worker(root: Path, host: str, outdir: Path, uid_tag: str, unshare: bool) -> bool:
    env = {
        "PATH": os.environ["PATH"],
        "HOSTNAME": host,
        "XDG_RUNTIME_DIR": f"/run/user/{uid_tag}",
    }
    cmd = [sys.executable, "-I", str(HERE / "prove.py"), "--worker", str(root), str(outdir)]
    if unshare:
        # a real UTS-namespace hostname change, so socket.gethostname() differs too
        cmd = ["unshare", "-Ur", "--uts", "sh", "-c", 'hostname "$1"; shift; exec "$@"', "sh", host, *cmd]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
    return r.returncode == 0


# --------------------------------------------------------------------------
# justification table for the '/'-rooted token scan
# --------------------------------------------------------------------------
PORTABLE = {
    "/bin/bash": "shebang interpreter path, present on every supported host",
    "/usr/bin/env": "portable shebang",
    "/dev/null": "POSIX null device",
    "/dev/stdin": "POSIX device",
    "/dev/stderr": "POSIX device",
    "/dev/stdout": "POSIX device",
}
LAYOUT = {
    "/.claude/hooks": "fixed layout segment: the glob the guard matches BASH_SOURCE against",
    "/.claude/hooks/": "same fixed layout segment",
}


def scan_tokens(text: str) -> list[tuple[str, str]]:
    """Every '/'-rooted token with the single character before it."""
    return [
        (m.group(0), text[m.start() - 1] if m.start() else "")
        for m in re.finditer(r"/[^\s\"'`;|&()<>{}\[\]=,$]*", text)
    ]


def justify(tok: str, before: str) -> str | None:
    if re.fullmatch(r"//.*|/[-\\]+|/", tok) and before:
        return "bash `${v//a/b}` substitution operator text, not a path"
    if tok in PORTABLE:
        return "PORTABLE: " + PORTABLE[tok]
    if tok in LAYOUT:
        return "LAYOUT: " + LAYOUT[tok]
    if re.fullmatch(r"/+\*?|/[-\\]+", tok) or tok.startswith(("/*", "//")) or tok.endswith("/*"):
        return "bash syntax (glob / `${v// /-}` substitution / `$a/$b` joins), no concrete location"
    if re.fullmatch(r"[A-Za-z0-9_}]", before):
        return "JOIN: appended to a run-time derived variable ($_rl_dir, $SCRIPT_DIR, ${..}), not an absolute path"
    return None


def main() -> int:
    print("== 0. repo state ==")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=REPO, text=True)
    origin = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=REPO, text=True, capture_output=True
    ).stdout.strip()
    is_anc = (
        subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], cwd=REPO).returncode
        == 0
    )
    print(f"HEAD          {head}")
    print(f"origin/main   {origin}  ({'same' if origin == head else 'DIFFERENT from HEAD'})")
    print(f"HEAD is an ancestor of origin/main: {is_anc}")
    print(f"git status --short: {status.strip() or '(clean)'}")
    check(status.strip() == "", "working tree clean")

    base = Path(tempfile.mkdtemp(prefix="p609-"))
    probe = subprocess.run(
        ["unshare", "-Ur", "--uts", "sh", "-c", "hostname uts-probe && hostname"],
        capture_output=True,
        text=True,
    )
    use_unshare = probe.returncode == 0 and probe.stdout.strip() == "uts-probe"
    print(f"\nreal UTS hostname change (unshare -Ur --uts) available: {use_unshare}")

    print("\n== 1/2. generate: 2 root shapes x 2 hostnames, a fresh process each ==")
    results: dict[tuple[str, str], Path] = {}
    infos: dict[tuple[str, str], dict[str, object]] = {}
    roots: list[str] = []
    n = 0
    for kind in ("short", "long"):
        for host in HOSTS:
            n += 1
            root = make_root(base, kind, str(n))
            roots.append(str(root))
            out = base / f"out-{kind}-{n}"
            out.mkdir()
            ok = run_worker(root, host, out, uid_tag=str(1000 + n), unshare=use_unshare)
            check(ok, f"worker ran: root={kind} HOSTNAME={host}")
            results[(kind, host)] = out
            i = json.loads((out / "info.json").read_text())
            infos[(kind, host)] = i
            print(
                f"  {kind:5} root len={len(str(root)):3} HOSTNAME={host!r}: generator-process suffix="
                f"{i['hostname_suffix']!r} overflow={i['overflow_bytes']}B XDG={i['XDG_RUNTIME_DIR']}\n"
                f"        untracked dir {i['get_untracked_dir']}\n"
                f"        daemon events dir (what used to be baked on overflow): {i['daemon_events_dir']}"
            )
    check(all(int(str(infos[("short", h)]["overflow_bytes"])) == 0 for h in HOSTS), "short roots fit AF_UNIX")
    check(
        all(int(str(infos[("long", h)]["overflow_bytes"])) > 0 for h in HOSTS),
        "long roots OVERFLOW AF_UNIX (fallback layout in play)",
    )
    check(
        all(
            not str(infos[("long", h)]["daemon_events_dir"]).startswith(str(infos[("long", h)]["get_untracked_dir"]))
            for h in HOSTS
        ),
        "long roots: the daemon's real events dir is OUTSIDE the untracked dir (old code baked it)",
    )
    check(
        all(str(infos[(k, h)]["get_untracked_dir"]).endswith("/untracked") and "hooks-daemon" not in str(infos[(k, h)]["get_untracked_dir"]) for k in ("short", "long") for h in HOSTS),
        "all roots resolve to the self-install layout <root>/untracked (same layout as /workspace)",
    )

    print("\n== 3. byte equality: sha256 across the 4 combinations, and vs tracked wrappers ==")
    tracked = {p.name: p.read_text() for p in sorted((REPO / ".claude/hooks").iterdir()) if p.is_file()}
    print(f"wrappers in /workspace/.claude/hooks (top level files): {len(tracked)}")
    combos = list(results)
    shas: dict[str, dict[str, str]] = {}
    for variant in ("relay", "nc", "both", "regen"):
        shas[variant] = {}
        mismatched = []
        for name in tracked:
            row = {sha((results[c] / variant / name).read_text()) for c in combos}
            if len(row) != 1:
                mismatched.append(name)
            shas[variant][name] = next(iter(row))
        check(not mismatched, f"[{variant}] all {len(tracked)} wrappers byte-identical across 4 combinations {mismatched}")
        bad = 0
        for c in combos[1:]:
            bad += subprocess.run(
                ["diff", "-rq", str(results[combos[0]] / variant), str(results[c] / variant)],
                capture_output=True,
            ).returncode
        check(bad == 0, f"[{variant}] `diff -rq` (byte compare) vs the other 3 combinations is clean")
    for variant in ("relay", "regen"):
        differ = [n_ for n_ in tracked if shas[variant][n_] != sha(tracked[n_])]
        check(not differ, f"[{variant}] equals tracked /workspace/.claude/hooks/*; differing: {differ}")
    rew = [json.loads((results[c] / "regen_rewritten.json").read_text()) for c in combos]
    check(all(r == [] for r in rew), f"regenerate_deployed_hooks over the tracked wrappers rewrote nothing: {rew}")
    guarded = [n_ for n_, t in tracked.items() if "relay hot path" in t]
    print(f"wrappers carrying the relay hot-path block: {len(guarded)} of {len(tracked)}")
    check(len(guarded) > 0, "non-vacuous: relay guard blocks are present")
    print("\nsha256 of each wrapper (relay variant; same in all 4 combinations; '=' = equals tracked):")
    for name in tracked:
        mark = "=" if shas["relay"][name] == sha(tracked[name]) else "!"
        print(f"  {shas['relay'][name]} {mark} {name}")

    print("\n== 4. absolute-path scan of every generated file (4 variants x 4 combinations) ==")
    corpus: dict[str, str] = {}
    for c in combos:
        for variant in ("relay", "nc", "both", "regen"):
            for name in tracked:
                corpus[f"{c[0]}/{c[1]}/{variant}/{name}"] = (results[c] / variant / name).read_text()
    forbidden = ["/workspace", "/home/", "/root/", "/run/user", "/tmp/", str(base), *roots, *HOSTS]
    forbidden += [h.lower() for h in HOSTS] + [str(1000 + k) for k in range(1, 5)]
    hits = {k: [f for f in forbidden if f in v] for k, v in corpus.items()}
    hits = {k: v for k, v in hits.items() if v}
    check(not hits, f"none of: temp roots, /workspace, /home/, /root/, /run/user, /tmp/, uids, hostnames; hits={list(hits.items())[:3]}")
    hexhits = {k: re.findall(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{6,}\b", v) for k, v in corpus.items()}
    hexhits = {k: v for k, v in hexhits.items() if v}
    check(not hexhits, f"no hex-hash token (>=6 hex chars); hits={list(hexhits.items())[:3]}")
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for k, v in corpus.items():
        for tok, before in scan_tokens(v):
            seen[(tok, before if re.fullmatch(r"[A-Za-z0-9_}]", before) else "")].add(k.rsplit("/", 1)[1])
    print(f"distinct '/'-rooted tokens across all generated files: {len(seen)}")
    unjustified = []
    for key in sorted(seen):
        tok, before = key
        why = justify(tok, before)
        if why is None:
            unjustified.append(tok)
            why = "UNJUSTIFIED"
        print(f"  {tok!r:44} in {len(seen[key]):2} files  {why[:60]}")
    check(not unjustified, f"every '/'-rooted token justified; unjustified={unjustified}")
    sys.path.insert(0, str(REPO / "src"))
    from claude_code_hooks_daemon.install import forwarder_generator as fg

    leaks = {
        k: [p for p in fg.surviving_absolute_paths(v) if p != "/.claude/hooks"] for k, v in corpus.items()
    }
    leaks = {k: v for k, v in leaks.items() if v}
    check(not leaks, f"generator's own surviving_absolute_paths() is empty bar the layout segment; {list(leaks.items())[:3]}")

    print("\n== 5. converge/upgrade path using the PRE-00609 generator ==")
    old_path = HERE / "old_forwarder_generator.py"
    old_path.write_text(
        subprocess.check_output(
            ["git", "show", f"{OLD_COMMIT}:src/claude_code_hooks_daemon/install/forwarder_generator.py"],
            cwd=REPO,
            text=True,
        )
    )
    spec = importlib.util.spec_from_file_location(
        "claude_code_hooks_daemon.install.forwarder_generator_old", old_path
    )
    assert spec is not None and spec.loader is not None
    logging.disable(logging.WARNING)  # the old generator warns about the fallback dir
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    from claude_code_hooks_daemon.config.models import TransportConfig

    os.environ["HOSTNAME"] = "conv-host"
    os.environ["XDG_RUNTIME_DIR"] = "/run/user/4242"
    for kind in ("short", "long"):
        proj = make_root(base, kind, "conv")
        hooks = proj / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        shutil.copy(REPO / ".claude/hooks-daemon.yaml", proj / ".claude" / "hooks-daemon.yaml")
        t = TransportConfig(relay_enabled=True)
        for name, text in tracked.items():
            bare = fg.strip_status_fast_path_block(fg.strip_relay_guard_block(text))
            (hooks / name).write_text(old.generate_forwarder_content(bare, name, t, proj / "untracked", proj))
        baked = [
            n_
            for n_ in tracked
            if str(proj) in (hooks / n_).read_text() or "/run/user" in (hooks / n_).read_text()
        ]
        from claude_code_hooks_daemon.daemon import paths as _paths

        fallback = str(_paths.get_event_socket_dir_from_untracked(proj / "untracked"))
        runtime = [n_ for n_ in tracked if fallback in (hooks / n_).read_text()]
        print(f"  [{kind}] pre-00609 output: {len(baked)} wrappers bake a path, {len(runtime)} bake {fallback}")
        check(len(baked) > 0, f"[{kind}] old output really embeds machine paths (non-vacuous)")
        if kind == "long":
            check(len(runtime) > 0, "[long] old output bakes the machine-specific AF_UNIX fallback events dir (the overflow case)")
        first = fg.regenerate_deployed_hooks(proj, hooks)
        second = fg.regenerate_deployed_hooks(proj, hooks)
        print(f"  [{kind}] first pass rewrote {len(first)} wrappers, second pass rewrote {len(second)}")
        check(len(first) > 0 and set(first) <= set(tracked), f"[{kind}] first pass rewrites the old-form wrappers")
        check(second == [], f"[{kind}] second pass rewrites nothing")
        check(
            all((hooks / n_).read_text() == tracked[n_] for n_ in tracked),
            f"[{kind}] converged wrappers equal the tracked wrappers byte for byte",
        )

    shutil.rmtree(base, ignore_errors=True)
    print("\n== RESULT ==")
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), Path(sys.argv[3]))
        sys.exit(0)
    sys.exit(main())

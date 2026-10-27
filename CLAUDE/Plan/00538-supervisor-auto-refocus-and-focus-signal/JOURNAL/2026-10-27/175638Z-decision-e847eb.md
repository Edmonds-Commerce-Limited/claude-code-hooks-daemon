## 17:56 · decision · —   — Owner ruling: vt100 crate, vendored

Owner ruling (2026-10-27), verbatim: "use the vt100 crate, vendored"

What it relaxes: the zero-crates rule that the relay follows (Plan 00290), for
`hooks-screen` ONLY. `screen/` becomes a cargo package depending on `vt100`
0.18.1 (exact pin), with its whole dependency tree vendored in `screen/vendor/`
and built offline and locked (`screen/.cargo/config.toml`, `screen/Cargo.lock`,
inventory and licenses in `screen/VENDORED.md`). The hand-written emulator is
deleted; the `Screen` boundary, classifier, CLI contract and exit codes are
unchanged.

What it does not touch: the relay (`relay/`) stays std-only plain rustc with
zero crates.

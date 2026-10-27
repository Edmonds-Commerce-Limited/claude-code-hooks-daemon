# Vendored crates for hooks-screen

Owner ruling (Plan 00538): hooks-screen uses the `vt100` crate, vendored. This
relaxes the zero-crates rule for `screen/` only; the relay (`relay/`) stays
std-only.

The sources under `screen/vendor/` are the unmodified output of `cargo vendor`.
`screen/.cargo/config.toml` replaces crates.io with that directory, and
`screen/Cargo.lock` pins every version, so the build needs no network:

    cargo build --release --offline --locked --target x86_64-unknown-linux-musl

`bash screen/build.sh` does exactly that. Never edit files under `vendor/`:
cargo verifies each file against its `.cargo-checksum.json`.

| Crate         | Version | License           | Role                                 |
| ------------- | ------- | ----------------- | ------------------------------------ |
| vt100         | 0.18.1  | MIT               | terminal screen model (direct dep)   |
| vte           | 0.15.0  | Apache-2.0 OR MIT | escape-sequence state machine        |
| arrayvec      | 0.7.8   | MIT OR Apache-2.0 | fixed-capacity vectors (via vte)     |
| itoa          | 1.0.18  | MIT OR Apache-2.0 | integer formatting (via vt100)       |
| memchr        | 2.8.3   | Unlicense OR MIT  | byte search (via vte)                |
| unicode-width | 0.2.2   | MIT OR Apache-2.0 | cell width of characters (via vt100) |

All licenses are permissive. To update: change the version in `Cargo.toml`, run
`cargo update` and `cargo vendor vendor` inside `screen/` (with network), review
the diff, and update this table.

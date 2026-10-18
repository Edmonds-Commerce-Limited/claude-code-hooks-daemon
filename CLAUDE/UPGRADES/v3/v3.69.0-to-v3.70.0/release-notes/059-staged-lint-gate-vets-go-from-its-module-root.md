# Callout: staged_lint_gate vets Go from its module root

**Plan**: 00525
**Audience**: client projects

`staged_lint_gate` ran `go vet <file>` from the daemon's working directory, so a Go file in a nested module (a `go.mod` in a subdirectory, importing its own module's packages) could not resolve its imports. Depending on the Go version that either denied a correct commit (`package ... is not in GOROOT`) or let the file through unchecked. The gate now finds the nearest `go.mod`, runs `go vet` from that directory on the file's package, exactly as `lint_on_edit` does, through one shared resolver. A correct nested-module package commits and a real `go vet` finding still blocks. The finding line in the message now skips the `# <package>` banner so it names the file. The same module-root working directory now also applies to Ansible (`ansible.cfg`) and Rust (`Cargo.toml`) files checked by the gate.

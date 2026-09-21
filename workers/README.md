# Deputy Workers MCP

Standalone portable staging for the frozen DeputyWorkers V1.1 deterministic
worker runtime. The server exposes a bounded lifecycle and exactly 22 registry
operations; it does not expose generic shell, arbitrary process execution,
generic ADB, or caller-selected paths and executables.

Deployment paths are server/operator configuration through `config.py` and the
`DEPUTYWORKERS_*` environment variables. MCP requests select only registered
operations and parameters. Device-mutating operations, including data clear,
uninstall, instrumentation, and scoped push, require the existing frozen
authorization contract.

Tests use synthetic repository, verifier, SDK, and device fixtures. They do not
constitute physical Android validation.

# Deputy Shell MCP umbrella architecture

The project contains two independent MCP runtimes. `agents/` provides
contained advisory AI reconnaissance over sanitized read-only snapshots.
`workers/` provides deterministic typed execution with a frozen capability
registry and mechanical evidence.

The model chooses intent; the server chooses authority. Agents findings are
untrusted advisory evidence. Workers results are deterministic evidence.
Neither subsystem exposes generic shell, arbitrary process execution, caller
selected paths, or caller-selected executables.

See `agents/docs/ARCHITECTURE.md` and `workers/docs/ARCHITECTURE.md` for
subsystem details.

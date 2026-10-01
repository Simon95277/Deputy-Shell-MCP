# Deputy Shell MCP umbrella architecture

The project contains two independent MCP runtimes. `agents/` provides
contained advisory AI reconnaissance over sanitized read-only snapshots.
`workers/` provides deterministic typed execution with a frozen capability
registry and mechanical evidence.

The model chooses intent; the server chooses authority, workflow, lifecycle,
evidence, and execution. Agents findings are untrusted advisory evidence.
Workers results are deterministic evidence. Neither subsystem exposes generic
shell, arbitrary process execution, caller-selected paths, or caller-selected
executables.

The normal control-tower contract is deliberately small:

- Agents: `deputy_recon(goal)`; the server binds the configured repository,
  manages the complete contained run, and returns a semantic outcome.
- Workers: `deputy_observe(request)` and `deputy_act(request)`; each request
  selects one typed operation from its MCP-native schema, and the server
  executes it to terminal state.

Run IDs, polling, cancellation, process identity, raw streams, and other
control-plane state are not part of the normal model-facing protocol. Internal
engines retain lifecycle/evidence behavior. Owner-only administrative tools
are opt-in with server process flags and absent from the default tool inventory.

See `agents/docs/ARCHITECTURE.md` and `workers/docs/ARCHITECTURE.md` for
subsystem details.

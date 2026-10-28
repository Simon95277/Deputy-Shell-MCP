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

Workers also supports the explicit `focused-a4-beta` mode. It replaces the
default two schemas with `deputy_prepare(request)`,
`deputy_choose(prepare_id, choice_id, choice_review)`,
`deputy_observe(intent_id)` and `deputy_act(intent_id, approval_review)` under
`DA-A4-BETA-2`. Nine fixed semantic mappings use the same 22-operation registry.
The server owns the active profile and bindings. Each choice and effectful
action requires a trusted interactive host to display complete arguments and
obtain a fresh human decision; review text alone is not consent.

Legacy requests can contain bounded repository-relative paths or device serials
where the typed operation permits them. A4 dispatch accepts only its intent and
review fields. Neither route adds arbitrary host-path/executable/argv authority.
Use the [installation guide](INSTALLATION.md), [host setup](MCP_HOST_SETUP.md)
and [A4 guide](../workers/docs/A4_USER_GUIDE.md) for practical examples.

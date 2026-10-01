# Deputy Workers V1.1 architecture

The MCP server owns the repository binding, runtime roots, trusted Python,
Android SDK/ADB binding, capability registry, lifecycle, integrity snapshots,
and evidence paths. The default model-facing surface is exactly
`deputy_observe` and `deputy_act`, each accepting one typed registered
operation via MCP-native operation-specific schemas.

The 22 enabled operations are defined by `WORKER_CAPABILITIES.json`. Read-only
and observational operations are distinct from device-mutating operations;
the latter include install, uninstall, clear-data, force-stop, activity start,
instrumentation, and scoped push.

`worker_v1` contains validation, durable storage, process lifecycle, repository
integrity, host operations, ADB mappings, and production execution. A small
server-side service converts one public intent into the existing trusted job,
waits internally for terminal state, and projects a semantic result. Public
responses omit run IDs, PIDs, argv, host paths, raw process streams, and other
control-plane mechanics. The existing internal lifecycle remains available;
owner-only lifecycle tools require `DEPUTYWORKERS_ENABLE_CONTROL_PLANE=1` at
process startup and are absent by default. The synthetic tests provide
controlled fixtures for portability and do not claim device or Android SDK
availability.

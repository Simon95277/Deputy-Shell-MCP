# Deputy Workers V1.1 architecture

The MCP server owns the repository binding, runtime roots, trusted Python,
Android SDK/ADB binding, capability registry, lifecycle, integrity snapshots,
and evidence paths. Callers submit typed registered operations only.

The 22 enabled operations are defined by `WORKER_CAPABILITIES.json`. Read-only
and observational operations are distinct from device-mutating operations;
the latter include install, uninstall, clear-data, force-stop, activity start,
instrumentation, and scoped push.

`worker_v1` contains validation, durable storage, process lifecycle, repository
integrity, host operations, ADB mappings, and production execution. The
synthetic tests provide controlled fixtures for portability and do not claim
device or Android SDK availability.

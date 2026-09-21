# Threat model

The MCP accepts bounded reconnaissance requests and creates sanitized,
read-only snapshots for a contained worker. The caller cannot choose arbitrary
executables, argv, cwd, environment, repository roots, network destinations,
or device targets. The worker receives only the job snapshot through a
read-only mount and provider-only network policy.

The repository snapshot is a point-in-time file selection, not a transactionally
coherent whole-tree snapshot. A source mutation during capture is detected by
the before/after state comparison; stronger whole-snapshot coherence remains a
future hardening item.

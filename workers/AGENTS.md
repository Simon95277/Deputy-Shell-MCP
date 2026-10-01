# DeputyWorkers operating contract

Workers are the deterministic, bounded execution subsystem. The server owns
paths, executables, capability mapping, and evidence boundaries. Keep the
fixed capability registry and fail closed on unsupported authority.

Workers remain independent from the advisory Agents subsystem. Do not expose
generic shell, arbitrary processes, arbitrary filesystem paths, generic ADB,
or caller-selected execution authority.

## Model-facing contract

The default MCP surface is exactly `deputy_observe` and `deputy_act`. Each
accepts one operation from a finite operation-specific schema; the server owns
repository binding, capability validation, any internal composition, durable
run lifecycle, integrity checks, evidence, and cleanup. A call returns one
terminal semantic outcome, never a run ID or polling instruction.

Legacy status/start/result/cancel and smoke tools are administrative or
development surfaces, not normal model controls. They are registered only
when the server owner starts the process with
`DEPUTYWORKERS_ENABLE_CONTROL_PLANE=1`.

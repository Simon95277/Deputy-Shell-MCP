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

## Experimental A4 mode

`focused-a4-beta` is a server-owned opt-in protocol with four public tools:
`deputy_prepare`, `deputy_choose`, `deputy_observe`, and `deputy_act`.
It maps nine semantic outcomes to the existing 22-operation registry.
Preserve exact profile, target, effect, stage, ticket expiry, and one-shot
dispatch checks. A pending ambiguous choice must not be replaced by a fresh
prepare request. A4 does not authenticate whether a clarification came from
the user; the MCP host's approval policy protects effectful calls. Keep the
legacy default and A4 mode isolated. Consult
[the A4 beta contract](docs/A4_BETA_CONTRACT.md) before changing either.
For examples see the [A4 user guide](docs/A4_USER_GUIDE.md). Current v2 choice
and action arguments include server-issued `choice_review` and `approval_review`.
The supported host must prompt the operator on each choice/action and show
complete arguments; model-copied reviews are not proof of human consent.

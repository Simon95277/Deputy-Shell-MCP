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

## Focused A4 beta mode

The default `legacy` protocol above remains unchanged. An operator may opt
into `DEPUTYWORKERS_PROTOCOL_MODE=focused-a4-beta` with a fixed
`DEPUTYWORKERS_A4_PROFILE`. In that mode the public inventory is exactly
`deputy_prepare`, `deputy_choose`, `deputy_observe`, and `deputy_act`.
Preparation resolves one of nine bounded semantic outcomes; a server-issued
intent binds the ordered stages, effect, profile, repository/device bindings,
authority digest, expiry, and runtime epoch. Observe accepts only an opaque
intent ID; act also requires the bounded, server-issued `approval_review` that
the host shows for a fresh operator decision. The server validates that review
against its sealed ticket and validates authority again before each stage, then
records a durable one-shot claim before dispatch. It neither falls back to
the legacy interface nor accepts caller-selected roots, executables, or argv.

An ambiguous registered choice remains pending for at most five minutes.
Another preparation is blocked until an exact choice is consumed, expires,
or is revoked on restart. `deputy_choose` requires a server-issued
`choice_review` and a separate host operator decision on that exact option.
The server cannot independently authenticate the origin of a clarification.
Synthetic model
qualification uses a non-executing Worker backend and proves no physical
Android behavior. The [A4 beta contract](A4_BETA_CONTRACT.md) specifies the
full mapping and fail-closed lifecycle. The current opt-in approval interface
is documented in the [Gate 1B addendum](A4_BETA_GATE1B_APPROVAL_ADDENDUM.md).

The model's choice of A4 over a host's built-in shell/Git/ADB tools is a host
integration concern, not a property enforced by the A4 server. The
[host integration guide](A4_BETA_HOST_INTEGRATION.md) gives session-level
routing guidance and explains how to avoid granting an alternate direct route
to the target. A4's server-side authority checks still apply regardless of
model routing instructions.

The [candidate scope](A4_BETA_RELEASE_SCOPE.md) records Gate 2's isolated
API 34 emulator qualification: seven Android observations verified, seven
mutating Worker operations synthetic-only, and no physical-device qualification.
Gate 3 enforces registered APK regular-file containment without symlink/reparse
traversal. APK bytes are not pinned across approval and installation; hostile
local writers and multi-tenant deployments remain unsupported.

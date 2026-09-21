# AGENTS.md — DeputyAgentsMCP operating contract

This file is the short, model-facing operating contract for this repository.
For the complete implementation-level description, read
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before changing runtime,
snapshot, containment, timeout, or public-tool behavior.

## What this project is

DeputyAgentsMCP exposes bounded AI reconnaissance workers to a supervising
model through MCP.

The supervising model chooses **intent**. The server chooses **authority**.

A caller may ask a reconnaissance question and select one approved workspace.
The caller may not choose arbitrary host paths, Docker arguments, networks,
providers, models, worker profiles, timeouts, mounts, or executables.

The primary production use is read-only reconnaissance of the Deputy Shell
repository through a fresh sanitized snapshot.

## Important distinction: DeputyAgents vs DeputyWorkers

- **DeputyAgentsMCP** runs contained AI child sessions for read-only
  investigation and independent reasoning.
- **DeputyWorkersMCP** is a different project for deterministic bounded
  operations such as Git/Gradle/JUnit/ADB/verifier work.

Do not treat DeputyAgents as a command-execution replacement for
DeputyWorkers.

## Public MCP tools

Normal work should prefer the asynchronous lifecycle:

- `deputy_recon_start(goal, workspace_id)`
- `deputy_recon_status(job_id)`
- `deputy_recon_cancel(job_id)`

Approved workspace IDs are:

- `BRIDGE_LAB`
- `DEPUTY_SHELL`

The public server hardcodes the worker profile to `RECON`.

`deputy_recon(goal, workspace_id)` is the legacy synchronous compatibility
surface. Do not use it for substantial long-running work when the async
lifecycle is available.

Diagnostic-only tools currently exposed:

- `deputy_child_ping()`
- `deputy_git_probe()`

They are not reconnaissance workers and must not be used as general-purpose
execution surfaces.

Maximum concurrent async reconnaissance jobs: **2**.

## Deputy Shell snapshot boundary

A DEPUTY_SHELL child never receives the live repository.

The server:

1. inspects the live repository with bounded read-only Git commands;
2. builds a sanitized master snapshot according to the server-owned allowlist;
3. verifies the repository did not change during capture;
4. copies the master snapshot into a per-job directory;
5. mounts only that per-job snapshot at `/workspace`, read-only;
6. launches the contained OpenCode worker.

The live Deputy Shell repository and the shared master snapshot must never be
mounted into the worker.

The current snapshot policy is:

`DA-FAST-2-positive-allowlist-v1`

Read `docs/ARCHITECTURE.md` for the exact allowlist, deny rules, approved
untracked paths, size limits, Git-state capture, and drift checks.

## Containment invariants

The worker container is currently created with these important restrictions:

- `--rm`
- `--read-only`
- `--cap-drop=ALL`
- `--security-opt no-new-privileges`
- PID limit 128
- memory limit 1 GiB
- CPU limit 2
- bounded tmpfs mounts only
- one read-only `/workspace` bind mount
- no Docker socket
- no live Deputy Shell mount
- no DeputyWorkers mount

The worker is attached only to a Docker `--internal` per-job network.

A Squid proxy is dual-homed to the Docker bridge network and the internal
job network. Its current ACL permits CONNECT only to `opencode.ai:443` and
denies everything else.

This is a **provider-only egress** design.

## Provider/privacy model

Do not describe this system as "source never leaves the machine."

The live repository is not exposed, but source files contained in the
sanitized snapshot may be read by the child and sent to the external model
provider as part of inference.

The current code explicitly records Deputy Shell provider exposure in the
snapshot audit.

Secret/path filtering reduces accidental exposure; it is not a PII scanner
and it is not a guarantee that provider-visible source is non-sensitive.

## OpenCode execution

The worker image is digest-pinned.

The server invokes OpenCode in JSON event mode using the `plan` agent and
`/workspace` as the working directory.

The repository code does **not** currently pass explicit model/provider flags
to OpenCode. Do not claim that a particular model is code-pinned unless the
implementation is changed to enforce that.

The provider network boundary is enforced separately by Squid.

## Timeouts and watchdogs

Do not casually change timeout constants.

Current important limits:

- preparation budget: 15 s
- individual snapshot Git command ceiling: 3 s
- true child idle timeout: 180 s
- active operation timeout: 900 s
- child absolute timeout: 1800 s
- outer watchdog: 1860 s

The legacy `CHILD_EXECUTION_BUDGET_MS = 300000` constant is still emitted in
adapter metadata, but it is **not the effective child runtime ceiling** in the
current executor. The current process collection path uses the state-aware
idle/active/absolute watchdogs above.

## Snapshot Git safety

Snapshot Git commands are read-only and run with:

- `GIT_OPTIONAL_LOCKS=0`
- `GIT_TERMINAL_PROMPT=0`
- `stdin=DEVNULL`
- explicit stdout/stderr pipes
- resolved server-owned Git executable
- 3 s per-command ceiling

Never introduce repository-mutating Git operations into snapshot capture.

## Evidence and cleanup

Each job writes bounded evidence under the server-owned evidence root,
including lifecycle state, contracts, result data, and cleanup information.

Cleanup is mandatory in a `finally` block.

Normal completion, error, cancellation, and timeout paths must all attempt to
remove the worker, proxy, and per-job Docker network.

## Status semantics

Important public states/results include:

- `STARTED`
- `RUNNING`
- `CANCELLING`
- `PASS`
- `TIMEOUT`
- `CANCELLED`
- `MODEL_ERROR`
- `CLIENT_ERROR`
- `OUTPUT_INVALID`
- `CONTAINMENT_ERROR`
- `BUSY`
- `NOT_FOUND`

Do not collapse these into a generic success/failure state.

## Current limitations / debt

Treat these as known implementation facts, not invitations to refactor them
without a milestone:

- async job state is in-memory and does not survive MCP process restart;
- `deputy_git_probe` is temporary diagnostic surface;
- host paths are server-owned and configurable through `DEPUTYAGENTS_*` environment variables;
- the async cancellation path has a known early-registration race worth
  hardening later;
- evidence/resource reconciliation across server restart is not yet durable;
- the OpenCode writable-state tmpfs set may need future expansion;
- packaging/installer ergonomics for other environments are not yet complete.

## Change discipline

When changing this project:

1. preserve the authority boundary;
2. keep the child untrusted;
3. keep DEPUTY_SHELL read-only from the child's perspective;
4. do not expose arbitrary host paths or execution controls;
5. fail closed on missing capability or containment validation failure;
6. preserve bounded preparation and child execution;
7. keep cleanup mandatory;
8. update `docs/ARCHITECTURE.md` and this file when behavior changes;
9. bump `RUNTIME_CONTRACT_VERSION` when live MCP semantics change;
10. run the full DeputyAgents tests, bridge tests, compile check, and staged
    sensitive scan before declaring a runtime milestone complete.

## Qualified production evidence

A real DEPUTY_SHELL async reconnaissance was successfully validated against a
fresh dirty working tree with:

- policy `DA-FAST-2-positive-allowlist-v1`
- 625 files
- 19,507,861 bytes
- fresh snapshot refresh ~6.03 s
- preparation ~6.905 s
- worker launch ~6.922 s
- read-only per-job `/workspace`
- live repository not mounted
- shared master not mounted
- provider-only network
- useful model result
- zero remaining DeputyAgents containers/networks after cleanup

Those numbers are historical qualification evidence, **not permanent
assertions**. File count, bytes, branch, HEAD, and timings may legitimately
change as Deputy Shell evolves.

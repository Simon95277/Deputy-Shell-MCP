# Deputy Shell MCP

Deputy Shell MCP is a bounded MCP server for launching independent AI
reconnaissance workers without giving those workers direct authority over the
host or the live Deputy Shell repository.

Deputy Shell MCP is part of the [Deputy Shell](https://deputyshell.com)
project. The contained AI-subagent runtime was originally developed internally
as DeputyAgentsMCP.

The core rule is:

> **The model chooses intent. The server chooses authority.**

A supervising model can request a read-only investigation against an approved
workspace. The server decides the actual host path, snapshot policy, Docker
image, worker profile, network, proxy, mounts, resource limits, timeouts, and
cleanup behavior.

## Start here

For models/agents working in this repository:

- [`AGENTS.md`](AGENTS.md) — short operating contract and safety invariants.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full implementation-level
  description of the MCP surface, snapshot policy, Docker/network containment,
  watchdogs, evidence, status semantics, limitations, and qualified production
  state.

Read both before changing runtime or containment behavior.

## Current runtime

Current runtime contract marker:

`DA-GIT-DIAG-2`

Current Deputy Shell snapshot policy:

`DA-FAST-2-positive-allowlist-v1`

The current implementation has been physically validated with a real
asynchronous DEPUTY_SHELL reconnaissance using a fresh sanitized snapshot.

## Public MCP tools

Preferred async lifecycle:

```text
deputy_recon_start(goal, workspace_id)
deputy_recon_status(job_id)
deputy_recon_cancel(job_id)
```

Approved workspace IDs:

```text
BRIDGE_LAB
DEPUTY_SHELL
```

Legacy synchronous compatibility surface:

```text
deputy_recon(goal, workspace_id)
```

Current diagnostics:

```text
deputy_child_ping()
deputy_git_probe()
```

`deputy_git_probe()` is temporary diagnostic surface, not a general-purpose
execution tool.

Maximum concurrent async reconnaissance jobs:

`2`

## What happens for a Deputy Shell job

At a high level:

```text
MCP caller
  -> bounded goal
server
  -> read-only Git state capture
  -> sanitized fresh Deputy Shell snapshot
  -> per-job snapshot copy
  -> read-only Docker mount at /workspace
  -> contained OpenCode plan agent
  -> internal Docker network
  -> Squid provider-only egress to opencode.ai:443
  -> bounded result/evidence
  -> mandatory cleanup
```

The live Deputy Shell repository is never mounted into the child.

The shared master snapshot is never mounted into the child.

Only the per-job sanitized snapshot is mounted, read-only.

## Containment highlights

Current worker restrictions include:

- digest-pinned OpenCode image;
- read-only container root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- PID, memory, and CPU limits;
- bounded tmpfs mounts;
- read-only `/workspace`;
- no Docker socket;
- internal per-job network;
- Squid allowlist permitting only CONNECT to `opencode.ai:443`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the exact command and
policy.

## Snapshot/privacy note

The system protects the **live repository and host authority** from the child.

It does **not** mean source is guaranteed to stay local.

Source included in the sanitized snapshot may be read by the child and sent to
the external inference provider. Secret filtering is defensive and
path-oriented; it is not a general content/PII scanner.

## DeputyAgents vs DeputyWorkers

These are separate systems:

- **DeputyAgentsMCP** — AI reconnaissance and independent reasoning.
- **DeputyWorkersMCP** — deterministic bounded engineering operations.

A supervising model should use DeputyAgents for read-only investigation and
DeputyWorkers for supported mechanical checks, then make the final engineering
decision itself.

## Current qualification evidence

The production freshness/containment gate was closed after a real
DEPUTY_SHELL async job passed with:

- fresh snapshot policy `DA-FAST-2-positive-allowlist-v1`;
- 625 files / 19,507,861 bytes at that point in time;
- snapshot refresh ~6.03 s;
- preparation ~6.905 s;
- worker launch ~6.922 s;
- read-only per-job `/workspace`;
- live repository not mounted;
- shared master not mounted;
- provider-only network;
- useful independent model result;
- zero remaining DeputyAgents containers/networks after cleanup.

Those counts/timings are historical validation evidence, not permanent
constants.

## Development status

This is an experimental project with a validated public baseline.

Known hardening work includes:

- durable job status across MCP restart;
- cancellation race cleanup;
- startup orphan reconciliation;
- removal or gating of temporary diagnostics;
- runtime-root/configuration wiring cleanup;
- packaging and installer ergonomics;
- stronger privacy controls for broader multi-user/public deployments.

The detailed list and current invariants live in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

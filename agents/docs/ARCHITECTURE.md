# DeputyAgents architecture and runtime contract

This describes Agents `1.0.0`, the companion in the
[published Focused A4 Beta](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1). Start with the repository
[installation guide](../../docs/INSTALLATION.md) and [host setup](../../docs/MCP_HOST_SETUP.md).

| Contract | Current value |
| --- | --- |
| Runtime | `DA-PRIVACY-1` |
| Source policy | `DA-PRIVACY-1-positive-policy-v1` |
| Byte coherence | `DA-BYTE-COHERENCE-1` |
| Source-policy schema | `deputy.agents.source-policy.v1` |
| Durable job schema | `deputy.agents.job-state.v1` |
| Trust model | `TRUSTED_SINGLE_OPERATOR_V1` |

## Public interface and authority

The default production inventory is **one tool**, `deputy_recon(goal)`. The
caller supplies a nonempty question, bounded to 4,096 UTF-8 bytes. The server
fixes its configured production repository/workspace and handles preparation,
execution, waiting, persistence and cleanup. The returned result is terminal;
the model does not choose paths, a provider, executable, mount, timeout or job ID.

Owner-only `deputy_recon_start`, `deputy_recon_status` and
`deputy_recon_cancel` are registered only with the exact server process setting
`DEPUTYAGENTS_ENABLE_CONTROL_PLANE=1`. Only that administrative interface
accepts the bounded `DEPUTY_SHELL`/`BRIDGE_LAB` workspace identifiers. It is not
the preferred model interface. `BRIDGE_LAB` is a development fixture path, not
the normal production snapshot policy.

Development diagnostics `deputy_child_ping` and `deputy_git_probe` require
`DEPUTYAGENTS_ENABLE_DIAGNOSTICS=1`. Missing, empty or other values disable
the flags. Neither flag is a caller parameter or can be enabled by goal text.
Normal deployments keep both flags off. The internal async concurrency limit
is two; normal callers do not manage its lifecycle.

Agents is advisory AI. Workers is the separate deterministic execution
subsystem. An Agents report never grants permission for a Worker or host action.

## Source-to-provider flow

```text
deputy_recon(goal)
  -> server-owned repository and source policy
  -> canonical source selection and source-before hashes
  -> copy a private candidate; hash candidate bytes
  -> high-confidence local content-secret scan
  -> source-after hashes and repository/path-state validation
  -> whole-snapshot byte coherence
  -> qualified shared master; per-job copy under snapshot lock
  -> mount only that copy read-only at /workspace
  -> OpenCode child; provider-only proxy egress
  -> bounded public report; local evidence; mandatory cleanup
```

Every included file must match the before/candidate/after SHA-256 comparison.
Git branch/HEAD, worktree/index/untracked state and path identity also have to
remain coherent. A failing refresh cannot execute a stale master as a fallback.
The live repository and the shared master are never mounted in the child.

The policy is server-owned JSON through `DEPUTYAGENTS_SOURCE_POLICY_JSON`.
It accepts bounded normalized relative prefixes/root filenames, exclusions,
approved untracked paths and size/count limits. No MCP caller can choose a
policy file or alter this configuration. Unknown fields, absolute/drive paths,
parent traversal and control characters are rejected.

The built-in Deputy Shell policy allows `app/src/`, `backend/` and `tools/`,
excluding `tools/linux-runtime/`. Allowed root files are `build.gradle`,
`build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`, `gradle.properties`,
`gradlew` and `gradlew.bat`. `app/build.gradle.kts` is not included by that
default. Absence from a snapshot does not prove absence from the live repository.
The explicit approved-untracked set is maintained in
[`source_policy.py`](../source_policy.py); all other untracked files are denied.

Hard exclusions remain in code: sensitive filenames, binary content, symlinks,
reparse points and unsafe linked parent components. The hard ceilings are
10 MiB per file, 5,000 files and 50 MiB total; a deployment policy may lower
them. The [installation guide](../../docs/INSTALLATION.md) gives a bounded policy
example for a different repository layout.

The exact candidate bytes are scanned before network/proxy/worker setup. A
high-confidence secret finding fails closed as `SNAPSHOT_CONTENT_POLICY_BLOCKED`;
no matched value, sensitive line or key body is written to the public result or
audit. Evidence records bounded paths/detector IDs/counts. PII heuristics are
separate warnings, not comprehensive detection or a default ban on every email.

Git capture uses read-only commands, a trusted Git executable, no stdin,
`GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0` and bounded calls. A Git command
has a three-second ceiling, shortened by the remaining preparation budget.
Git trace evidence records command labels and timings without arbitrary output
or the absolute source root. Git remote URLs and author identity are not needed
to expose source to the child.

## Provider and container contract

The server selects provider `opencode`, model `muse-spark-1.3-contributor-free`
and provider host `opencode.ai`. Selection source is `SERVER_OWNED`; the selector
is supplied through the CLI and inline server configuration. Project content
cannot replace it. A missing route or observed identity mismatch fails closed;
there is no fallback provider/model. The qualified route required no injected
credential. Provider pricing/availability is external; the model name is not
a promise of free inference forever.

OpenCode runs with the `plan` agent, JSON events and `/workspace` as its working
directory. The goal is ordinary task content, never parsed as execution flags.
Image digests and containment argv are authoritative in
[`bridge/core.py`](../bridge/core.py). Installation lists the same references.
No host OpenCode installation is required.

The worker has a read-only root filesystem and read-only per-job workspace,
all capabilities dropped, no-new-privileges, a PID limit of 128, 1 GiB memory
and two CPUs. Writable tmpfs is bounded. It has no Docker socket or live source
mount. Its only network is the per-job internal network. Squid is connected to
that network and the bridge; its ACL allows CONNECT only to `opencode.ai:443`.
Mount/network attestation checks this before normal child work.

Provider-exposable source can leave the machine through inference. Secret/path
filters do not make it confidential from the provider. Model output can quote
source. Configured identity is recorded separately from observed identity;
when runtime events omit identity fields, evidence does not claim verification.

## Durability, cancellation and cleanup

Durable job state is persisted atomically under the configured evidence root.
Terminal results survive server restart. A recovered nonterminal job becomes
`INTERRUPTED`, never fabricated success. Startup reconciliation only cleans
positively owned resources for recovered interrupted jobs using the server's
`ocb-*` resource naming contract. Unrelated Docker resources are not removed.

An early cancellation is retained in `PENDING_CANCELS` and checked before
preparation proceeds. Cancellation and reconciliation are idempotent. The
in-memory `_JOBS` and executor `ACTIVE` maps complement durable state; they
are not the only record of a job.

Cleanup runs from `finally` and attempts to remove the worker, proxy and
per-job network after success, error, timeout or cancellation. Cleanup evidence
can list another concurrently owned job; interpret it per job rather than
assuming every `ocb-*` entry belongs to the current request.

## Time and evidence bounds

| Bound in accepted code | Value |
| --- | ---: |
| Preparation | 30 seconds |
| Individual snapshot Git call | At most 3 seconds |
| True child idle | 180 seconds |
| Active operation | 900 seconds |
| Child absolute | 1,800 seconds |
| Outer watchdog | 1,860 seconds |

The public projection returns a bounded report on PASS or stable failure codes;
it omits internal job/session IDs, host paths, raw exceptions and lifecycle
mechanics. Local evidence can be richer and must stay operator-controlled.
Containment exceptions have bounded local-only diagnostics including exception
type/message/traceback and safely observed execution state; these are not MCP
fields. A bounded report is not a guarantee that source-derived text is private.

Paths are deployment configuration through `DEPUTYAGENTS_*`. Evidence, durable
jobs and snapshots default under the per-user runtime root, outside installed
code. The console entry point is `deputy-agents-mcp`; `--check` is read-only and
does not prove live Docker/provider readiness. See [installation](../../docs/INSTALLATION.md).

## Modules and maintenance

- `server.py`: one normal recon tool, public projection, durable registry and gated admin tools.
- `source_policy.py`, `snapshot.py`, `privacy.py`: policy validation, byte qualification and local scanning/sanitization.
- `bridge/core.py`, `bridge/provider_contract.py`: request/argv/image/provider contract.
- `bridge/executor.py`: containment lifecycle, progress/watchdogs and cleanup.
- `preflight.py`, `config.py`: installed entry-point checks and operator-owned paths.

Run the complete Agents suite, contract/import checks and package/privacy checks
after relevant changes. Runtime semantics require a contract review/version
decision. Do not casually change budgets, selection or provider authority.
CI and packaging qualification already exist, and the Focused A4 Beta is
publicly available. Future publications still require separate approval. OpenCode writable-state needs outside the fixed tmpfs
set and provider availability remain operational limits. Hostile local writers,
hostile shared users and multi-tenant isolation are outside this deployment.

## Historical infrastructure qualification

The following preserved record predates this documentation reconciliation. Its
counts and timings describe that run only, not a current source inventory or
a new qualification performed by editing this document.


The infrastructure gate was closed after a real asynchronous DEPUTY_SHELL
reconnaissance succeeded.

Validated run:

```text
runtime                         DA-PRIVACY-1
status                          PASS
snapshot policy                 DA-PRIVACY-1-positive-policy-v1
snapshot file count             625
snapshot bytes                  19,507,861
snapshot dirty                  true
snapshot refresh                6030 ms
preparation total               6905 ms
worker launch                   6922 ms
session                         present
workspace mount                 per-job snapshot
workspace target                /workspace
workspace read-only             true
live repository mounted         false
shared master mounted           false
network                         PROVIDER_ONLY
remaining containers            0
remaining networks              0
```

The validated Deputy Shell HEAD at that time was:

`fc2c1b1552d6760a1389c3b12e02c08a54b653de`

These values are **qualification evidence**, not runtime constants.

As Deputy Shell changes:

- file count can change;
- total bytes can change;
- dirty state can change;
- branch/HEAD can change;
- timings can change.

What should remain invariant are the authority, snapshot, containment, and
cleanup contracts.

---

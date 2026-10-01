# Deputy Shell MCP

Deputy Shell MCP is a bounded delegation layer for coding models, built for the
[Deputy Shell](https://deputyshell.com) project.

It gives an MCP-capable supervisor two different kinds of help without handing
the model a generic shell or unrestricted host access:

- **DeputyAgents** — contained AI reconnaissance over a sanitized, read-only
  snapshot of one server-configured repository.
- **DeputyWorkers** — deterministic, typed operations from a fixed capability
  registry for repository, build, test, process, and Android-device work.

> **The model chooses intent. The server chooses authority.**

The normal public surface is deliberately small:

| Runtime | Default MCP tools | Purpose |
| --- | --- | --- |
| Agents | `deputy_recon(goal)` | Ask an untrusted contained subagent to investigate source and return a bounded report. |
| Workers | `deputy_observe(request)` | Run one registered read-only/observational operation to terminal state. |
| Workers | `deputy_act(request)` | Run one registered state-changing/execution operation to terminal state. |

Everything else—repository binding, executable selection, lifecycle, run IDs,
polling, process details, evidence paths, cleanup, and internal composition—is
server-owned.
## Why this exists

A coding model is useful when it can inspect, test, and reason about a real
project. Giving it unrestricted shell/process/filesystem authority is a much
larger trust decision.

Deputy Shell MCP separates **reasoning** from **authority**:

```text
supervisor model
      |
      | intent only
      v
+-----------------------+
| Deputy MCP boundary   |
| server owns authority |
+----------+------------+
           |
     +-----+------+
     |            |
     v            v
DeputyAgents   DeputyWorkers
untrusted AI   trusted deterministic code
sanitized      fixed typed capabilities
snapshot       repository/device binding
```

The supervisor can ask for outcomes such as “inspect this architecture,”
“parse this registered JUnit report,” or “run this approved Gradle task.”
It cannot turn those interfaces into arbitrary `argv`, executable, shell,
working-directory, or host-path selection.
## DeputyAgents

DeputyAgents runs independent reconnaissance against a **fresh qualified
snapshot**, not the live repository.

The production path:

1. selects source through a server-owned positive policy;
2. copies selected bytes into a candidate snapshot;
3. runs bounded high-confidence secret scanning;
4. verifies source-after and byte-coherence invariants;
5. publishes the qualified read-only snapshot;
6. launches the contained OpenCode child with provider-only egress;
7. returns a bounded semantic report;
8. tears down contained resources and records owner-local evidence.

The fixed provider/model contract is currently:

- provider: `opencode`
- model: `muse-spark-1.3-contributor-free`

The caller cannot select the provider, model, source root, source policy,
container arguments, mounts, network, timeout, or executable. If OpenCode does
not expose authoritative runtime identity fields, Deputy reports that limitation
instead of inventing verification.

The child is treated as **untrusted advisory AI**. Its findings are evidence for
the supervisor, not authority to change the host.
### Important privacy boundary

DeputyAgents protects the live host/repository boundary; it does **not** claim
that provider-exposable source remains confidential from the configured
inference provider.

Only source admitted by the server-owned policy is eligible for the snapshot,
and documented high-confidence credential forms are scanned before provider
setup. That is not comprehensive secret, PII, or confidentiality detection.
Model output may quote qualified source.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the exact trust and data
boundaries.

## DeputyWorkers

DeputyWorkers is trusted deterministic server code. It exposes no generic shell
and no caller-selected executable or argv.

The frozen registry currently contains **22 operations** covering:

- repository state and diff checks;
- approved Gradle tasks and approved verifiers;
- JUnit parsing;
- bounded file checks and artifact hashing;
- owned-process evidence;
- device discovery and bounded ADB queries;
- scoped install/uninstall/data-clear/force-stop/activity/instrumentation;
- bounded logcat, push, pull, and registered dumpsys queries.

The MCP schema itself is the capability catalog. One public call selects one
registered semantic operation; any multi-step mechanics needed to satisfy that
intent stay inside the server.
For example, `CAPTURE_REPO_STATE` may internally compose the repository-state
capture with a diff check, but the caller still makes one semantic request and
receives one terminal semantic result.

The read/write split is explicit:

- `deputy_observe` accepts the 13 observational operations.
- `deputy_act` accepts the 9 execution or device-mutating operations.

The complete registry is in
[workers/WORKER_CAPABILITIES.json](workers/WORKER_CAPABILITIES.json).

## Control tower, not lifecycle API

Older Deputy builds exposed start/status/result/cancel mechanics directly to the
model. That made the supervisor manage infrastructure instead of intent.

The current control-tower design hides that machinery by default. Normal model
work should never need to:

- create or poll run IDs;
- manage containers/processes;
- retrieve raw evidence files;
- retry around `ACTIVE_RUN_EXISTS`;
- choose internal step sequences.

Workers serialize the synchronous public surface server-side when needed.
Agents performs its contained lifecycle internally.

Owner/admin lifecycle and diagnostic tools still exist for qualification and
debugging, but are absent from the default inventory. They require explicit
server-owned opt-in configuration.
## Installation

Python **3.10+** is required. Agents and Workers are separate distributions and
can use separate virtual environments.

From a clean checkout:

```powershell
python -m venv .venv-agents
.venv-agents\Scripts\python -m pip install .\agents
.venv-agents\Scripts\deputy-agents-mcp --check

python -m venv .venv-workers
.venv-workers\Scripts\python -m pip install .\workers
.venv-workers\Scripts\deputy-workers-mcp --check
```

At minimum, bind the repository server-side before launch:

```powershell
$env:DEPUTYAGENTS_DEPUTY_SHELL_ROOT = "C:\path\to\your\repo"
$env:DEPUTYWORKERS_DEPUTY_SHELL_ROOT = "C:\path\to\your\repo"
```

Agents also requires Docker and Git. Workers uses trusted Python and requires an
Android SDK/ADB only for device-bound operations.

`--check` validates prerequisites without pulling images, installing tools,
changing PATH, or performing device actions.
### Runtime state

Runtime/evidence data lives outside the installed package by default:

- Agents: `%LOCALAPPDATA%\DeputyShellAgentsMCP` on Windows
- Workers: `%LOCALAPPDATA%\DeputyWorkersMCP` on Windows
- Linux/POSIX: `$XDG_STATE_HOME` or `~/.local/state`
- macOS: the platform application-support directory

Important deployment overrides include:

- `DEPUTYAGENTS_DEPUTY_SHELL_ROOT`
- `DEPUTYAGENTS_RUNTIME_ROOT`
- `DEPUTYAGENTS_EVIDENCE_ROOT`
- `DEPUTYAGENTS_SNAPSHOT_ROOT`
- `DEPUTYAGENTS_DOCKER_EXE`
- `DEPUTYWORKERS_DEPUTY_SHELL_ROOT`
- `DEPUTYWORKERS_RUNTIME_ROOT`
- `DEPUTYWORKERS_EVIDENCE_ROOT`
- `DEPUTYWORKERS_PYTHON_EXE`
- `DEPUTYWORKERS_ANDROID_SDK_ROOT`
- `DEPUTYWORKERS_ADB_EXE`

These are deployment configuration. MCP callers cannot set them.

Any compatible MCP host that can launch stdio servers can host Deputy. Hermes is
not required.
## Security model

Supported deployment: **`TRUSTED_SINGLE_OPERATOR_V1`**.

The trusted machine owner controls configuration, runtime roots, the bound
repository, and local evidence. MCP callers are not trusted with host authority.
Deputy is **not** a hostile multi-user or multi-tenant isolation service.

Key invariants:

- no generic shell tool;
- no arbitrary process execution surface;
- no caller-selected executable or argv;
- no caller-selected repository root;
- Agents never mounts the live repository into the child;
- qualified snapshot source is read-only;
- provider/model selection is server-owned;
- Workers authority is restricted to the frozen typed registry;
- public results omit raw host paths, argv, environment values, process IDs,
  and raw subprocess streams.

Security details and known limitations:
[SECURITY.md](SECURITY.md) ·
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) ·
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
## Efficiency benchmark

Phase 11 tested the control-tower redesign against direct supervisor execution.
The benchmark is intentionally kept in the repository at
[benchmarks/efficiency/](benchmarks/efficiency/); raw campaign evidence remains
local and ignored.

What it established:

- versus the **old Deputy lifecycle design**, Workers E1–E3 supervisor cost fell
  from **2,132,559 to 1,023,874 tokens** (**51.99% lower**) and model-visible
  MCP calls fell from **39 to 22**;
- across available valid DIRECT-vs-DEPUTY paired cases E1–E6, Deputy used
  **0.94% fewer Luna supervisor tokens overall**;
- workload shape matters: structured JUnit parsing (E3) saved about **54%**,
  while several tiny or mixed tasks cost more through Deputy.

What it did **not** establish:

- a universal token-saving claim;
- total inference-token savings, because child-agent token usage was not
  authoritatively measured;
- active context-window/compaction savings, because that telemetry was not
  available.

The practical result is that delegation has a break-even point. A planned
post-Phase-11 refinement will let the control tower reject or redirect work
whose returned evidence cannot materially compress what the supervisor could
obtain directly. Security/authority boundaries still take precedence over
efficiency routing.
## Project status

Completed:

- lifecycle and reconciliation hardening;
- snapshot byte-coherence and positive source policy;
- provider/model contract hardening;
- packaging and reproducibility;
- CI and release-candidate gates;
- privacy/generalization work;
- control-tower public-surface redesign;
- Phase 11 efficiency benchmark and post-campaign closure.

Next:

1. below-break-even delegation/refusal routing;
2. Phase 12 v1.0 maturity gate and security-audit readiness.

Package metadata currently reports Agents `1.0.0` and Workers `1.1.0`.
Those package versions should not be read as a claim that the overall project
has completed its Phase 12 maturity/security gate.

See [docs/ROADMAP.md](docs/ROADMAP.md).

## Development and qualification

Both distributions declare `mcp>=2,<3` and are qualified against MCP `2.2.0`.

Run tests from each component directory after installing its dependencies:

```powershell
cd agents
python -m unittest discover -s tests -q

cd ..\workers
python -m unittest discover -s tests -q

cd ..
python -m unittest discover -s benchmarks\efficiency\tests -q
```
The ordinary CI suite uses synthetic fixtures. It does not execute live Docker
containment, provider inference, destructive ADB operations, or a real Android
device. Those remain separate local qualification domains.

Dependency and release details are documented in
[docs/CI.md](docs/CI.md). Deterministic qualification constraints live under
[constraints/](constraints/).

## Repository layout

```text
agents/                  contained reconnaissance MCP runtime
workers/                 deterministic bounded Workers MCP runtime
benchmarks/efficiency/   Phase 11 benchmark source, fixtures, schemas, tests
docs/                    architecture, threat model, CI, roadmap
scripts/                 bounded bootstrap and CI/release checks
constraints/             deterministic qualification/build constraints
```

## License

Apache-2.0. See [LICENSE](LICENSE).

## Vulnerability reports

Please use GitHub Private Vulnerability Reporting for security issues. Do not
post credentials, exploit details, private source, device data, or sensitive
runtime evidence in public Issues, pull requests, or discussions.

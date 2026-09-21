# DeputyAgentsMCP architecture and runtime contract

This document describes the current DeputyAgentsMCP implementation in enough
detail that another model or engineer can reason about the system without
reconstructing its behavior from commit history.

It is implementation documentation, not an aspirational design document.

Current runtime contract marker:

`DA-GIT-DIAG-2`

Current primary snapshot policy:

`DA-FAST-2-positive-allowlist-v1`

The short model-facing rules live in the repository root
[`AGENTS.md`](../AGENTS.md).

---

## 1. Purpose

DeputyAgentsMCP gives a supervising model access to **real independent AI
reconnaissance sessions** while preserving a server-controlled authority
boundary.

The core design rule is:

> The model chooses intent. The server chooses authority.

The caller can provide a bounded natural-language goal and choose one approved
workspace identifier. The caller cannot directly control host paths, model
provider, Docker invocation, network topology, mount sources, timeouts,
executables, or worker profile.

The current production use case is read-only reconnaissance of Deputy Shell.

DeputyAgentsMCP is intentionally separate from DeputyWorkersMCP.

- DeputyAgentsMCP = contained AI reasoning/reconnaissance.
- DeputyWorkersMCP = deterministic bounded engineering operations.

The projects solve different problems and should not be merged conceptually.

---

## 2. High-level architecture

The production DEPUTY_SHELL flow is:

```text
supervising model / MCP client
        |
        | deputy_recon_start(goal, "DEPUTY_SHELL")
        v
server.py
        |
        | async background thread
        v
bridge.executor.execute()
        |
        | trusted host-side snapshot refresh
        v
snapshot.py
        |
        | live repo read only
        | sanitized master snapshot
        v
local-snapshots/DEPUTY_SHELL
        |
        | copy while snapshot lock is held
        v
per-job evidence/<job>/snapshot
        |
        | bind mount, read only
        v
OpenCode worker container
        |
        | internal Docker network only
        v
Squid proxy
        |
        | CONNECT allowlist
        v
opencode.ai:443
```

The child does not receive the live Deputy Shell repository.

The child sees only a per-job copy of a sanitized snapshot mounted read-only
at `/workspace`.

The proxy is the only designed egress path.

---

## 3. Repository modules and responsibilities

### `server.py`

MCP-facing server.

Responsibilities:

- creates the FastMCP server;
- publishes public tools;
- validates async concurrency at the public boundary;
- owns the in-memory async job registry;
- launches async worker threads;
- exposes live/terminal status;
- forwards cancellation;
- exposes bounded diagnostics;
- attaches the runtime contract marker to public results.

Important current constants:

```text
RUNTIME_CONTRACT_VERSION = DA-GIT-DIAG-2
MAX_CONCURRENT_RECON = 2
```

The async job registry is process-local memory:

```text
_JOBS
_JOBS_LOCK
```

Therefore job status is not durable across MCP server restart.

### `snapshot.py`

Trusted host-side Deputy Shell snapshot builder.

Responsibilities:

- resolves the trusted Git executable;
- captures the live repository state using read-only Git commands;
- applies positive allowlist policy;
- applies sensitive/binary/reparse exclusions;
- includes only explicitly approved untracked files;
- enforces file/count/size limits;
- creates the sanitized master snapshot;
- writes snapshot manifest and audit evidence;
- compares repository state before and after capture;
- fails closed if the source changes during capture.

The worker does not call this logic.

It runs on the trusted host side before Docker worker launch.

### `bridge/core.py`

Static bridge contract and pure helpers.

Responsibilities:

- pinned Docker executable path;
- pinned OpenCode image digest;
- pinned Squid image digest;
- workspace identifiers;
- worker-profile mapping;
- request validation;
- BRIDGE_LAB snapshot behavior;
- result parsing;
- Docker worker argv construction;
- bounded public result shape.

### `bridge/executor.py`

Lifecycle orchestrator.

Responsibilities:

- preparation budget;
- per-job evidence directory;
- fresh snapshot preparation;
- Docker internal-network creation;
- Squid startup/configuration;
- mount attestation;
- worker launch;
- event streaming;
- session-id extraction;
- state-aware watchdog logic;
- timeout classification;
- result/evidence persistence;
- cleanup.

### `bridge/ping_child.py`

Minimal child-process transport diagnostic.

It only prints:

`pong`

It has no repository or network behavior.

### `tests/test_da_fast0.py`

Main contract/regression suite.

It tests public authority limits, snapshot semantics, containment, timeout
logic, async lifecycle, diagnostics, mount validation, cleanup invariants, and
Git-state behavior.

---

## 4. Public MCP surface

### 4.1 `deputy_recon_start(goal, workspace_id)`

Preferred entry point for real work.

Inputs:

- `goal: str`
- `workspace_id: "BRIDGE_LAB" | "DEPUTY_SHELL"`

The caller does **not** provide:

- worker profile;
- model;
- provider;
- timeout;
- Docker image;
- network;
- proxy;
- path;
- cwd;
- mount;
- executable.

Server behavior:

1. lock `_JOBS`;
2. count active jobs with status STARTED, RUNNING, or CANCELLING;
3. return `BUSY` if count is already 2;
4. allocate a random 32-character hex job ID;
5. create a STARTED/PREPARING record;
6. start daemon thread `deputy-recon-<prefix>`;
7. return immediately.

Initial response contains:

- status `STARTED`;
- job ID;
- runtime contract version;
- workspace ID.

### 4.2 `deputy_recon_status(job_id)`

Returns either:

- `NOT_FOUND`;
- live RUNNING/PREPARING state;
- or the final durable result currently held in `_JOBS`.

While running, it merges information from the public job record with the
executor's `ACTIVE` state.

Relevant live fields can include:

- `execution_state`;
- `preparation_phase`;
- `preparation_elapsed_ms`;
- `snapshot_lock_wait_ms`;
- `session_id`;
- `last_progress_type`;
- `last_progress_age_ms`;
- `active_operation_age_ms`.

### 4.3 `deputy_recon_cancel(job_id)`

If unknown:

`NOT_FOUND`

If already terminal:

returns the terminal result.

Otherwise:

1. marks the public job `CANCELLING`;
2. calls executor cancellation;
3. returns `CANCELLING`.

Executor cancellation sets an internal cancellation event and attempts to
remove the worker container.

Known limitation: there is a narrow race before the executor registers the
job in `ACTIVE`. The public layer can report `CANCELLING` while the internal
cancel call sees `NOT_FOUND`. This is hardening debt, not a reason to widen
authority.

### 4.4 `deputy_recon(goal, workspace_id)`

Legacy synchronous compatibility surface.

It executes the same bounded executor directly and appends the runtime
contract version.

For substantial work, prefer the async lifecycle because long model sessions
can exceed normal MCP request durations.

### 4.5 `deputy_child_ping()`

Diagnostic-only tool.

It verifies MCP -> child-process transport through two synthetic children:

Python:

```text
python.exe -I -S -u bridge/ping_child.py
```

CMD:

```text
cmd.exe /d /c echo pong
```

Both are bounded to 15 seconds.

This tool has no repository or provider purpose.

### 4.6 `deputy_git_probe()`

Temporary diagnostic-only tool introduced to diagnose MCP-hosted Git behavior.

It has no public parameters.

It reports bounded identity metadata and runs a fixed read-only Git sequence in
three modes:

1. direct production environment;
2. direct sanitized environment;
3. async-thread production environment.

It exists for diagnostics and is not part of the intended long-term product
surface.

---

## 5. Request authority and validation

`bridge.core.validate_request()` enforces:

- goal must be a non-empty string;
- goal maximum encoded size = 4096 bytes;
- workspace must exist in server-owned `WORKSPACES`;
- worker profile must exist in server-owned `WORKERS`.

Current worker mapping:

```text
RECON -> plan
```

Public MCP tools do not accept worker profile as caller input. The server
hardcodes `RECON`.

Current workspace identifiers:

```text
BRIDGE_LAB
DEPUTY_SHELL
```

The server, not the caller, maps those identifiers to host locations.

---

## 6. Deputy Shell source-state capture

Before building a DEPUTY_SHELL snapshot, `snapshot.py` records a canonical
repository state.

The Git executable is resolved once using `shutil.which("git")`.

If Git cannot be resolved, snapshot preparation fails closed.

### 6.1 Git subprocess environment

Every snapshot-owned Git subprocess uses:

```text
GIT_OPTIONAL_LOCKS=0
GIT_TERMINAL_PROMPT=0
stdin = DEVNULL
stdout = PIPE
stderr = PIPE
```

The command is run using the resolved server-owned Git executable and the
server-owned Deputy Shell repository path.

Per-command timeout:

`3 seconds`

or less if the remaining preparation budget is smaller.

No snapshot Git operation is allowed to mutate the repository.

### 6.2 Git commands

State capture currently uses:

```text
git rev-parse --abbrev-ref --symbolic-full-name @{upstream}
git diff --name-status --no-renames -z --
git diff --cached --name-status --no-renames -z --
git ls-files --others --exclude-standard -z
git ls-files -z
git branch --show-current
git rev-parse HEAD
```

This captures:

- upstream;
- unstaged tracked changes;
- staged/index changes;
- untracked paths;
- tracked-file inventory;
- branch;
- HEAD.

The NUL-delimited forms avoid breaking on filenames containing spaces.

### 6.3 Dirty semantics

Repository dirty state is:

```text
worktree changes
OR index changes
OR untracked paths
```

Staged-only changes are therefore included.

### 6.4 Before/after drift check

The repository is captured once before snapshot construction and once after.

The following are compared:

- branch;
- HEAD;
- upstream;
- worktree changes;
- index changes;
- untracked paths;
- dirty flag.

If any differ, snapshot creation fails with:

`SNAPSHOT_SOURCE_CHANGED_DURING_CAPTURE`

This prevents the worker from receiving a snapshot assembled across two
different source states.

### 6.5 Git trace

For job-backed refreshes, Git calls can be recorded in:

`git-trace.json`

Each invocation records bounded events including:

- ordinal;
- capture generation `BEFORE` or `AFTER`;
- command label;
- event `START | PASS | TIMEOUT | ERROR`;
- start timestamp;
- elapsed milliseconds.

The trace deliberately does not persist arbitrary command output or the host
repository path.

---

## 7. Deputy Shell snapshot policy

Current policy version:

`DA-FAST-2-positive-allowlist-v1`

The policy is positive-allowlist based.

### 7.1 Allowed tracked prefixes

```text
app/src/
backend/
tools/
```

### 7.2 Explicit excluded prefix

```text
tools/linux-runtime/
```

### 7.3 Allowed repository-root files

```text
build.gradle
build.gradle.kts
settings.gradle
settings.gradle.kts
gradle.properties
gradlew
gradlew.bat
```

Important consequence:

`app/build.gradle.kts` is **not currently included** because it is neither
under `app/src/` nor a repository-root allowlisted file.

A reconnaissance worker therefore cannot use the current DEPUTY_SHELL snapshot
to verify that file directly.

Do not confuse "not visible in the snapshot" with "absent from the repository."

### 7.4 Approved untracked paths

Untracked files are denied by default.

The current explicit approved set is:

```text
app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bContractWideCandidateProbeHarnessTest.kt
app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bPostInstallPreservationTest.kt
app/src/executionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidation.kt
app/src/main/java/com/deputyshell/app/runtime/pack/P3bCanonicalGenerationTreeFingerprintV1.kt
app/src/main/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1.kt
app/src/test/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1Test.kt
app/src/testExecutionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidationTest.kt
tools/android/verify_androidtest_dex_contents.py
tools/android/verify_validation_target_dex_contents.py
```

Anything else untracked is excluded.

The server owns this list. It is not caller-controlled.

### 7.5 Sensitive-name exclusions

The policy excludes paths/names matching sensitive vocabulary including:

- `.env`;
- `local.properties`;
- `google-services.json`;
- `signing.properties`;
- credentials;
- credential;
- token;
- password;
- secret;
- keystore;
- `.jks`;
- `.p12`;
- `.pfx`;
- `.pem`;
- `.key`;
- auth;
- session.

This is a defensive filename/path filter.

It is not content-level secret detection and not a PII scanner.

### 7.6 Binary exclusions

Current binary suffix deny set includes:

```text
.apk
.aab
.apks
.so
.dll
.exe
.class
.dex
.jar
.png
.jpg
.jpeg
.gif
.webp
.mp4
.ndjson
.bin
```

Files are also sampled and rejected as non-text if the first 8192 bytes
contain a NUL byte.

### 7.7 Reparse/symlink handling

Symlinks are rejected.

On Windows, paths with the reparse-point file attribute are rejected.

This prevents the allowlisted tree from escaping into another filesystem
location through a link/reparse boundary.

### 7.8 Snapshot limits

Current hard limits:

```text
max file size   = 10 MiB
max file count  = 5000
max total bytes = 50 MiB
```

Limit violations fail closed.

### 7.9 Snapshot manifest

The master snapshot receives:

`snapshot-manifest.json`

Current schema:

`deputy.recon.snapshot.v1`

The manifest includes:

- policy version;
- workspace ID;
- repo branch;
- repo HEAD;
- repo dirty state;
- creation time;
- file list;
- per-file size;
- per-file SHA-256;
- source-state label;
- file count;
- total bytes.

Current source-state labeling only distinguishes:

- `TRACKED_MODIFIED`
- `TRACKED_CLEAN`

The current implementation does not emit a distinct manifest label for an
approved untracked file. Models should not infer tracked status solely from
that label.

### 7.10 Snapshot audit

The audit includes:

- before state;
- after state;
- excluded paths grouped by reason;
- untracked classification;
- reparse points;
- hard limits;
- `provider_exposure`.

For Deputy Shell:

`provider_exposure = true`

That flag is intentional.

---

## 8. Snapshot publication and locking

For DEPUTY_SHELL jobs, `bridge.executor` uses a process-local
`SNAPSHOT_LOCK`.

The lock covers:

1. fresh master snapshot creation;
2. publication to the shared master location;
3. copy from the shared master into the job-specific snapshot directory.

This prevents two local reconnaissance jobs from refreshing/copying the shared
snapshot concurrently.

The worker does not mount the shared master.

It mounts only:

`<job evidence directory>/snapshot`

The mount is checked mechanically before launch.

---

## 9. Mount attestation

`_validate_mount_contract()` requires exactly one mount targeting
`/workspace`.

For the DEPUTY_SHELL worker, the mount must satisfy:

- source = this job's snapshot directory;
- target = `/workspace`;
- read-only flag present.

The generated Docker argv is rejected if it contains either:

- live Deputy Shell repository path;
- shared master snapshot path.

On success, public containment metadata reports:

```text
workspace_mount_source = JOB_SANITIZED_SNAPSHOT
workspace_mount_target = /workspace
workspace_mount_read_only = true
live_repo_mounted = false
shared_master_mounted = false
network_policy = PROVIDER_ONLY
```

This attestation describes the generated launch contract. It does not grant the
child any new authority.

---

## 10. Docker worker containment

### 10.1 Pinned images

OpenCode:

`ghcr.io/anomalyco/opencode@sha256:0d3c9551ea2522fcfd23fbc2e302fc87218d6c198bff277e8ab44d93a3bd6d3d`

Squid:

`ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029`

The image digests are server-owned constants.

### 10.2 Worker restrictions

The generated worker command includes:

```text
docker run
--rm
--network <per-job internal network>
--read-only
--cap-drop=ALL
--security-opt no-new-privileges
--pids-limit 128
--memory 1g
--cpus 2
```

Writable temporary filesystems:

```text
/tmp                         64 MiB
/root/.cache                128 MiB
/root/.local/share/opencode 128 MiB
/root/.config/opencode       64 MiB
```

Workspace mount:

```text
<job snapshot> -> /workspace, read only
```

No Docker socket is mounted.

No DeputyWorkers path is mounted.

No live Deputy Shell path is mounted.

### 10.3 OpenCode command

The image is invoked as:

```text
opencode run
  --format json
  --agent plan
  --dir /workspace
  <goal>
```

The worker profile `RECON` maps to OpenCode's `plan` agent.

Important: the repository code currently does **not** pass explicit
`--model` or provider selection flags.

Therefore a model/provider identity may be an operational property of the
pinned image/service configuration, but it is not currently enforced by this
repository's argv.

Do not document a specific model as code-pinned unless that changes.

---

## 11. Network containment

Each job receives a unique Docker network named from its job ID.

The job network is created with:

`docker network create --internal`

The worker is attached only to that internal network.

The Squid proxy is:

1. started on Docker's normal bridge network;
2. connected to the job's internal network.

The proxy is therefore dual-homed.

The worker reaches external service only through HTTP(S) proxy environment
variables:

```text
HTTP_PROXY=http://<proxy>:3128
HTTPS_PROXY=http://<proxy>:3128
NO_PROXY=localhost,127.0.0.1,::1
```

### 11.1 Squid ACL

Current generated Squid policy:

```text
http_port 3128
acl SSL_ports port 443
acl CONNECT method CONNECT
acl allowed_host dstdomain opencode.ai
http_access allow CONNECT allowed_host SSL_ports
http_access deny all
cache deny all
access_log /var/log/squid/access.log squid
cache_log none
pid_filename none
```

So the designed external network authority is:

`CONNECT opencode.ai:443`

Everything else is denied by Squid.

The worker also lacks a normal external Docker network, so direct external
egress is blocked by the internal-network design.

This provider-only egress path was physically qualified before the production
fresh-recon gate was closed.

---

## 12. Preparation lifecycle

Preparation has a hard budget of:

`15000 ms`

The budget begins at executor start and includes snapshot work plus Docker
network/proxy setup up to worker launch.

Preparation phases are persisted to `preparation-state.json`.

Important phases include:

```text
SNAPSHOT_LOCK_WAIT
SNAPSHOT_REPO_STATE
SNAPSHOT_GIT_UPSTREAM
SNAPSHOT_GIT_WORKTREE_DIFF
SNAPSHOT_GIT_INDEX_DIFF
SNAPSHOT_GIT_UNTRACKED
SNAPSHOT_GIT_TRACKED_FILES
SNAPSHOT_GIT_BRANCH
SNAPSHOT_GIT_HEAD
SNAPSHOT_PUBLICATION
NETWORK_CREATE
PROXY_START
PROXY_CONNECT
PROXY_READY
MOUNT_VALIDATE
WORKER_LAUNCH
```

A preparation overrun raises `PreparationTimeout` and returns terminal:

```text
status = TIMEOUT
timeout_reason = PREPARATION_TIMEOUT
execution_state = PREPARING
```

Terminal reporting can occur slightly after the nominal 15-second boundary
because exception unwinding/evidence/cleanup have their own bounded overhead.

The 15-second value is a worker-launch preparation boundary, not a promise that
the entire function returns by exactly 15.000 seconds.

---

## 13. Child event processing

The OpenCode process is launched with:

- stdout pipe;
- stderr pipe;
- stdin = DEVNULL;
- text mode.

Two daemon reader threads consume stdout/stderr.

Stdout is interpreted as newline-delimited JSON where possible.

The parser recognizes session IDs and text events.

A successful final response requires a valid session ID.

Final public text is bounded to the last 8192 characters assembled from text
events.

Malformed event lines are remembered and can cause `OUTPUT_INVALID`.

---

## 14. Execution-state machine and watchdog

The state-aware watchdog exists because a useful model operation can be quiet
for substantially longer than a normal idle period.

Meaningful event types currently include:

```text
session
step_start
tool_use
tool_result
step_finish
text
output
message
error
```

### 14.1 State transitions

`step_start`:

- sets state to `ACTIVE_STEP`;
- records outstanding step ID;
- records active-operation start time.

`step_finish`:

- sets state to `IDLE`;
- clears outstanding step metadata.

`tool_use` / `tool_result` while already active:

- preserve `ACTIVE_STEP`.

terminal-like events:

- set `TERMINAL`.

### 14.2 Timeout limits

Current effective watchdog limits:

```text
true idle timeout       = 180000 ms  (3 min)
active operation timeout = 900000 ms (15 min)
child absolute timeout   = 1800000 ms (30 min)
outer watchdog           = 1860000 ms (31 min)
```

While an operation is `ACTIVE_STEP`, the normal idle timeout is suppressed.

This is deliberate: model/tool execution can be alive even without output.

### 14.3 Legacy 300000-ms constant

`CHILD_EXECUTION_BUDGET_MS = 300000` still exists.

It is written into adapter-contract evidence.

It is **not** the current effective production model execution ceiling.

The current executor passes `CHILD_ABSOLUTE_TIMEOUT_SECONDS` into process
collection, additionally bounded by the remaining outer watchdog.

Models reading the code must not interpret 300000 ms as the actual hard stop.

---

## 15. Result classification

After process completion:

- cancellation event set -> `CANCELLED`;
- parsed API-style error -> `MODEL_ERROR`;
- other parsed error -> `CLIENT_ERROR`;
- malformed output or missing session ID -> `OUTPUT_INVALID`;
- nonzero process exit -> `CLIENT_ERROR`;
- otherwise -> `PASS`.

Preparation timeout returns `TIMEOUT`.

Child watchdog timeout returns `TIMEOUT` plus a specific reason such as:

- `CHILD_IDLE_TIMEOUT`;
- `ACTIVE_OPERATION_TIMEOUT`;
- `CHILD_ABSOLUTE_TIMEOUT`.

Unhandled containment/setup exceptions normally remain
`CONTAINMENT_ERROR`.

The public async layer additionally uses:

- `STARTED`;
- `RUNNING`;
- `CANCELLING`;
- `BUSY`;
- `NOT_FOUND`.

---

## 16. Evidence layout

The executor currently stores job evidence under the configured bridge root:

```text
<configured-bridge-root>/evidence/<job-id>/
```

This path is derived from the server-owned `BRIDGE_FIXTURES` configuration and
is not caller-controlled. `config.py` also defines `DEPUTYAGENTS_EVIDENCE_ROOT`,
but the current executor does not yet consume that setting; wiring it cleanly
is future packaging/runtime-root work.

Typical files can include:

```text
request.json
preparation-state.json
git-trace.json
snapshot/
snapshot-manifest.json
squid.conf
network-contract.json
adapter-contract.json
worker-stdout.txt
worker-stderr.txt
worker-state.json
squid-access.log
result.json
cleanup.json
```

Not every file exists on every path.

For example, a preparation failure before network creation will not have
network/adapter/worker evidence.

`snapshot.py` also writes a trusted audit under DeputyAgentsMCP's ignored
evidence area.

All evidence/local snapshot paths are ignored from Git.

### 16.1 Evidence bounds

Generic worker stdout/stderr evidence writes are bounded to:

`8192 bytes`

The public result text is also bounded.

### 16.2 Cleanup evidence nuance

`cleanup.json` records resource names and a post-cleanup inventory from
`list_resources()`.

That inventory lists all Docker resources with the DeputyAgents `ocb-`
prefix, not only resources belonging to the current job.

Therefore when two jobs run concurrently, another valid job can appear in the
remaining-resource list.

A literal zero-container/zero-network result is strongest when no other
DeputyAgents job is active.

---

## 17. Cleanup contract

Cleanup happens in executor `finally`.

The executor attempts to remove:

1. worker container;
2. proxy container;
3. per-job network.

Cleanup runs on success, timeout, cancellation, and failure paths.

The worker also has Docker `--rm`, but explicit removal is still attempted.

The cleanup path intentionally does not depend on the model cooperating.

---

## 18. Privacy and trust boundary

### 18.1 What the child does not receive

By design, the DEPUTY_SHELL worker does not receive:

- the live Deputy Shell checkout;
- arbitrary host directories;
- Docker socket;
- DeputyWorkers;
- other repositories;
- secret files excluded by snapshot policy;
- unapproved untracked paths.

### 18.2 What can leave the machine

The sanitized snapshot is provider-exposable.

If the child reads source from `/workspace`, that source can become part of
the model/provider request.

Therefore:

**"The live repository is not mounted" is true.**

**"Source never leaves the machine" is false.**

This architecture protects host/repository authority from the untrusted child.
It is not a confidentiality guarantee against the external inference provider.

Provider retention/training/privacy behavior is external to this server and
must not be invented by a model reading this repository.

### 18.3 Secret filter limitations

Filename/path filtering is not equivalent to content scanning.

A source file with an innocuous filename can still contain sensitive data.

The current policy is appropriate only for the explicitly accepted internal
use case and threat model.

Public/customer use requires additional privacy review and likely stronger
policy controls.

---

## 19. BRIDGE_LAB behavior

`BRIDGE_LAB` exists as a synthetic/controlled validation workspace.

Unlike DEPUTY_SHELL, it uses `bridge.core.build_snapshot()` rather than the
trusted live-repository snapshot policy.

The BRIDGE_LAB builder excludes obvious generated/sensitive paths and produces
a manifest with its own older policy marker.

Do not use BRIDGE_LAB results as proof that the live Deputy Shell freshness
path works.

The production gate was closed only after a real DEPUTY_SHELL job passed.

---

## 20. Current diagnostics

### 20.1 Child ping

Use when validating that the MCP host can create simple child processes.

Expected:

```text
Python PASS / pong
CMD PASS / pong
```

### 20.2 Git probe

`deputy_git_probe()` was introduced after intermittent MCP-hosted snapshot Git
timeouts.

It runs the fixed Git sequence:

```text
upstream
HEAD
branch
worktree diff
index diff
untracked enumeration
tracked-file enumeration
```

three times under:

- direct production environment;
- direct sanitized environment;
- async-thread production environment.

The current production Git helper is shared with the probe so diagnostics
exercise the same subprocess I/O behavior.

This tool should eventually be removed or moved behind a development-only
surface after the surrounding infrastructure is hardened.

---

## 21. Validated production state

The infrastructure gate was closed after a real asynchronous DEPUTY_SHELL
reconnaissance succeeded.

Validated run:

```text
runtime                         DA-GIT-DIAG-2
status                          PASS
snapshot policy                 DA-FAST-2-positive-allowlist-v1
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

## 22. Known implementation debt

Current known debt includes:

### Async durability

`_JOBS` is in memory.

MCP restart loses the public in-memory registry even though evidence files can
remain on disk.

Future hardening can reconcile durable evidence back into job state.

### Cancellation registration race

A cancellation can arrive before the executor has registered the job in
`ACTIVE`.

Public and internal cancellation status can momentarily disagree.

### Diagnostic tool exposure

`deputy_git_probe` is currently public MCP surface even though it is
diagnostic-only.

### Path configuration and packaging

Host paths are server-owned and configurable through `DEPUTYAGENTS_*`
environment variables. Public MCP callers still cannot provide arbitrary host
paths. Packaging and installer ergonomics remain future work.

### Evidence-root legacy

Job evidence is stored under the configured evidence root rather than a
fully self-contained DeputyAgents-owned runtime root.

### OpenCode writable state

The worker currently provides tmpfs for several OpenCode directories but not
every possible state/lock location.

Past experimentation identified writable state/lock behavior as future
hardening territory.

### Provider/model pinning

The OpenCode image is digest-pinned, but model/provider selection is not
explicitly pinned in the worker argv.

### Privacy/generalization

The current source policy is designed around a specific trusted owner's
internal repository and accepted provider exposure.

It is not yet a generalized multi-user privacy policy.

---

## 23. Non-goals

DeputyAgentsMCP is not intended to:

- give an AI unrestricted shell access to the host;
- let a child mutate Deputy Shell;
- expose Docker to the child;
- replace deterministic verification with model judgment;
- give callers arbitrary execution controls;
- make provider-visible source "local only";
- act as a persistent distributed job scheduler;
- provide durable multi-host orchestration.

---

## 24. Engineering invariants

Changes should preserve these invariants unless an explicit architecture
milestone intentionally replaces them.

### Authority

- public caller chooses goal/workspace only;
- server owns execution authority;
- missing capability fails closed.

### Snapshot

- live Deputy Shell is never mounted to the child;
- DEPUTY_SHELL snapshot is refreshed before a job;
- policy remains server-owned;
- untracked files remain deny-by-default;
- sensitive/reparse/binary exclusions stay fail-closed;
- source drift is detected.

### Container

- worker remains untrusted;
- read-only root filesystem;
- capabilities dropped;
- no-new-privileges;
- resource limits;
- read-only workspace;
- no Docker socket.

### Network

- worker internal network only;
- external egress only through the proxy;
- proxy allowlist remains narrow and explicit.

### Lifecycle

- preparation remains bounded;
- child runtime remains bounded;
- useful long-running active operations are not mistaken for idle;
- cleanup remains mandatory.

### Results

- status classification remains explicit;
- evidence remains bounded;
- public results do not expose unnecessary host paths.

---

## 25. Required maintenance when behavior changes

When modifying runtime behavior:

1. update implementation;
2. update tests;
3. update this document;
4. update `AGENTS.md` if model-facing rules changed;
5. update `README.md` if user-facing behavior changed;
6. bump `RUNTIME_CONTRACT_VERSION` for live MCP semantic changes;
7. run full DeputyAgents suite;
8. run bridge suite;
9. run Python compile validation;
10. run staged sensitive scan;
11. if containment/snapshot/runtime behavior materially changed, re-run the
    appropriate live qualification before claiming production validation.

Do not use documentation changes to silently redefine the runtime contract.
The implementation and tests remain authoritative.

---

## 26. How a supervising model should use DeputyAgents

For a normal Deputy Shell engineering milestone:

1. decide whether independent AI reconnaissance will materially help;
2. if yes, call `deputy_recon_start` with a narrow read-only goal;
3. retain the returned job ID;
4. poll only that job;
5. treat the report as evidence, not authority;
6. verify important findings directly or with deterministic DeputyWorkers;
7. make the engineering decision at the supervising-model level.

A subagent should be used for investigation, not as a way to evade the
supervisor's responsibility.

For high-risk milestones, task-local instructions may intentionally prohibit
LLM subagents while still allowing deterministic DeputyWorkers. That is a
valid use of the architecture.

---

## 27. Summary

DeputyAgentsMCP is a bounded delegation layer:

```text
supervisor
  -> intent
DeputyAgents server
  -> trusted fresh snapshot
  -> per-job read-only copy
  -> constrained Docker worker
  -> provider-only proxy
  -> bounded independent AI session
  -> evidence/result
supervisor
  -> judgment
```

The design goal is not "trust the child."

The design goal is to make the child useful **without requiring trust**.

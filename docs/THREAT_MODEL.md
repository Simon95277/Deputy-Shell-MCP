# Umbrella threat model

## Supported deployment and trust boundary

The supported deployment is `TRUSTED_SINGLE_OPERATOR_V1`: one trusted machine
owner controls server configuration, environment variables, runtime roots, and
the one configured source repository. MCP callers do not receive host-path or
execution authority. The contained Agents child is untrusted; Workers are
trusted deterministic server code. This is **not** a hostile shared
multi-tenant service and does not claim per-user filesystem, credential, or
tenant isolation. Provider-exposable source is externally exposed by design
when inference uses it; the local content scan blocks only documented
high-confidence credential patterns, not every sensitive or personal fact.

## Data-flow classification

| Data class | Examples and handling | External/public boundary |
| --- | --- | --- |
| `LOCAL_CONFIGURATION` | Owner-controlled roots, source policy, Docker/Git executable resolution, provider/model contract. No caller policy/path inputs. | Never returned as values; bounded status reports only logical contract IDs. |
| `LOCAL_RUNTIME` | Candidate/master/job snapshots, container/network identifiers, process argv, proxy configuration, runtime directories. | Only the per-job qualified snapshot is mounted read-only; host paths and raw argv are not MCP output. |
| `LOCAL_EVIDENCE` | Git state, snapshot manifests/audits, bounded Docker/process/proxy records, Workers run evidence and device output. | Stored under owner-controlled runtime roots; evidence may contain project/device-derived data and must be protected locally. |
| `PROVIDER_EXPOSABLE` | Exact text files selected by server-owned source policy after filename/binary rules, content-secret scan, and byte-coherence qualification. | Sent to the configured provider as needed for inference. Not confidential from that provider. |
| `MCP_PUBLIC_RESULT` | Logical job state, bounded model text, selected snapshot counts/policy IDs, typed Worker results. | Sanitized of host roots, environment values, raw process argv, and raw exception text; model text may quote qualified source. |
| `PUBLIC_REPOSITORY` | First-party source, tests, docs, workflow definitions. | Public by design; hygiene scans are bounded detectors, not full privacy review. |
| `CI_LOG` | Test/build summaries and workflow step output on ephemeral hosted runners. | No secrets are supplied; logs must not print local runtime evidence or environment dumps. |
| `RELEASE_ARTIFACT` | Agents/Workers wheels and sdists plus bounded manifest and checksums. | Package audit rejects runtime evidence, snapshots, credentials, and host-path residue. |

Git metadata is read locally for branch/HEAD/dirty coherence; authenticated
remote URLs and Git identity are not needed in the provider snapshot audit.
Workers may create detailed local operation evidence; MCP results should omit
machine-specific executable/root paths and process environment. Android serials
are retained only where typed device discovery/selection needs them; they are
operational identifiers, not credentials, and should remain within the trusted
operator context.

Concrete boundary handling: source bytes are selected by a server-owned
relative-path policy, copied into a candidate generation, hashed, scanned
locally for high-confidence credential patterns, then checked against
source-after hashes and Git path/state before publication. Only the qualified
per-job snapshot is mounted read-only. Git remote URLs, author identities,
absolute repository roots, Docker argv/inspect records, Squid access logs,
OpenCode stdout/stderr, snapshot audit detail, and Workers process/ADB logs are
local evidence, not MCP fields. The MCP result may include bounded model text
derived from source; that text is not guaranteed free of confidential source
content. Durable Agents state stores bounded request/result/lifecycle data;
local request evidence retains only goal digest/length, not raw goal text. It
does not store the environment or an unbounded model transcript. CI receives no provider,
device, or deployment secrets; release artifacts contain only audited
packages, checksums, and a bounded manifest.

## Agents

The AI child is untrusted. The design addresses prompt injection, provider
exposure, server-owned provider/model selection, workspace configuration
override, snapshot integrity, Docker containment, provider-only networking,
and lifecycle cleanup. The live repository is not mounted. The fixed Agents
contract selects `opencode` / `muse-spark-1.3-contributor-free`; callers and
snapshot content cannot select a different provider or model, and no host
credential environment is forwarded. Runtime identity is reported as
observed only when OpenCode emits both identity fields.

## Workers

Workers are trusted deterministic code. The relevant risks are capability
widening, host process execution, repository mutation, path escape, device
mutation, ADB authority, and trusted executable/configuration boundaries.
Workers are not claimed to be containerized.

### Focused A4 beta candidate

The A4 beta is an explicit server-selected protocol mode, not a simultaneous
model-facing route. In A4 mode only `deputy_prepare(request)`,
`deputy_choose(prepare_id, choice_id, choice_review)`,
`deputy_observe(intent_id)`, and `deputy_act(intent_id, approval_review)` are registered; legacy
operation schemas and lifecycle/admin controls are absent. No unsupported A4
request falls back to legacy Workers execution. Legacy mode remains the default
and preserves its current 22-operation registry.

Preparation is non-executing. A deterministic resolver can issue a ticket only
for one of the nine exact registered semantic mappings and only after all
material selectors and stages are resolved. An intent binds the selected
profile, ordered semantic operations, effect envelope, request digest,
registered target aliases, authority/registry identity, configured repository
and device bindings, expiry, runtime epoch, and dispatch state. Device aliases
resolve through a fixed local configuration under the server-owned runtime
root; MCP callers cannot supply serials, filesystem paths, executables, argv,
or profile configuration. Device serial values remain local.

Intent records use unpredictable opaque IDs, local integrity seals, bounded
expiry, atomic single-dispatch claims, and durable receipts. Replay and
concurrent duplicate dispatch are rejected. After restart, old prepared tickets
are revoked; an in-flight operation without a terminal receipt is recorded as
uncertain and never automatically retried. No public poll/status tool exposes
this lifecycle. These safeguards do not authenticate original user prose or
turn a compatible MCP client approval prompt into a universal authorization
guarantee. The residual input-fidelity limitation remains: the server receives
model-supplied request text, not an independently authenticated copy of the
user's message.

This is a qualification contract, not a production-readiness claim. Synthetic
tests cannot establish physical device safety; destructive device qualification
requires an explicitly authorized disposable device/emulator. The complete
contract and frozen qualification plan are in
`workers/docs/A4_BETA_CONTRACT.md`.

The A4 MCP server cannot prevent the host from separately granting its model
shell, Git, filesystem, or ADB access to the same target. Session instructions
can improve model routing but are not an isolation or authorization boundary.
Deployments that require the A4 authority boundary must restrict such alternate
host tools and require a fresh operator decision for `deputy_choose` and
effectful `deputy_act` calls. The `DA-A4-BETA-2` review fields bind the displayed
semantic operation, target, parameters, effect and expiry to the sealed A4
record before dispatch. The model's use of an issued `choice_id` or review
text does not independently prove that a human selected or approved it; that
property depends on the trusted interactive host. See the
[Gate 1B approval addendum](../workers/docs/A4_BETA_GATE1B_APPROVAL_ADDENDUM.md).

The compact Codex approval row alone is insufficient; the operator must inspect
complete arguments. MCP annotations and model-authored approval text are not
human authorization. The qualified Android target was an isolated API 34
emulator: seven observation operations verified, seven mutating Worker
operations synthetic-only, and no physical-device qualification. Registered APK
paths reject symlink/reparse escape, but APK bytes are not pinned across approval
and installation. Hostile local writers and multi-tenant deployments are outside
the supported scope. See the [qualification matrix and residual
limits](../workers/docs/A4_BETA_RELEASE_SCOPE.md).

For a plain-language walkthrough of this boundary and its effectful examples,
see the [A4 user guide](../workers/docs/A4_USER_GUIDE.md) and
[host setup](MCP_HOST_SETUP.md). Qualification evidence does not authorize
publication or certify other hosts or physical devices.

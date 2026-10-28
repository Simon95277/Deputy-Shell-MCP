# Focused A4 Workers beta contract

Status: current `DA-A4-BETA-2` contract for the
[published Focused A4 Beta](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1), Workers `1.2.0b1`.
The release followed independent technical acceptance and owner authorization.
This contract is not itself release authority or production certification.

For first use and examples see the [A4 user guide](A4_USER_GUIDE.md).

## Historical baseline and current scope

- Pre-A4 public main baseline: `e17ea58932df3b928c5dfd4455802db596eb18d9`.
- Historical pre-A4 local baseline: Agents 179/179 and Workers 355/355 on Windows
  CPython 3.10 with MCP 2.2.0 and the checked-in synthetic CI fixtures.
- Frozen Workers authority remains the 22 operations in
  `WORKER_CAPABILITIES.json`.
- Historical Proof 9 / A4 Intent-Bound `ADVANCE` was a research authorization to implement
  for qualification, not evidence that a production implementation exists.
- No new primitive, selector, executable, path, device, target, or effect is
  authorized by this contract.

## Protocol selection and compatibility

`DEPUTYWORKERS_PROTOCOL_MODE` is server-owned deployment configuration. The
default remains `legacy`. Only the exact value `focused-a4-beta` selects A4;
unknown values fail closed. `DEPUTYWORKERS_A4_PROFILE` is required in A4 mode
and must be one of `android`, `multi_repo`, `python_docker`, or
`deputy_mcp_package`. The active profile is not an MCP argument and never
changes during an intent's lifetime.

Legacy mode retains the existing `deputy_observe(request)` and
`deputy_act(request)` public schemas and their 22-operation registry. A4 mode
registers exactly `deputy_prepare(request)`,
`deputy_choose(prepare_id, choice_id, choice_review)`, `deputy_observe(intent_id)`, and
`deputy_act(intent_id, approval_review)`. It does not register legacy execution, owner lifecycle,
smoke, or diagnostic tools, even if the owner control-plane flag is set. An A4
request never falls back to legacy execution.

## Public inputs and outcomes

The declared inputs have bounded strings. The SDK-generated function schemas
list only the fields below; with MCP 2.2, unknown top-level fields are ignored
and convey no authority. Internal typed request/response models forbid extra
fields. Callers must not rely on unknown fields being rejected at the MCP
function boundary:

| Tool | Input | Effect |
|---|---|---|
| `deputy_prepare` | `{request: string}`; 1–8,000 Unicode characters | Non-executing resolution only. |
| `deputy_choose` | `{prepare_id: opaque string, choice_id: opaque string, choice_review: string}` | Selects one exact server-issued choice after host approval; never executes. |
| `deputy_observe` | `{intent_id: opaque string}` | Executes a ticket whose bound envelope is observation-only. |
| `deputy_act` | `{intent_id: opaque string, approval_review: string}` | Executes a ticket whose bound envelope includes an approved effect after a fresh host approval. |

Preparation outcomes are `CLEAR`, `CHOICE_REQUIRED`, `ARGUMENT_REQUIRED`,
`TARGET_NOT_REGISTERED`, `ARGUMENT_INVALID`, `UNSUPPORTED`, and
`MULTI_STEP_REQUIRED`. No outcome except `CLEAR` or a successful exact
`deputy_choose` issues an executable intent. Unresolved compound stages issue
no ticket. Errors are bounded codes; raw exceptions, host paths, argv, process
streams, serials, run IDs, and private Worker operation identifiers are not
returned.

`CLEAR` returns a random opaque `intent_id`, a bounded semantic summary,
effect class, stage count, and expiry. The summary may include only the
registered semantic names and caller-supplied bounded values required to
verify the interpreted request; it does not expose primitive/operation IDs.
Choices are bounded to the exact registered candidates produced by the
resolver and include opaque choice IDs and safe labels. Choice selection cannot
add, edit, or substitute a target, selector, stage, or effect.

## Nine-semantic map and effects

Mappings below are implementation-private and are not returned in MCP results.
They are copied from the accepted Proof 9 production-shape mapping and must be
checked against the live registry at startup and immediately before dispatch.

| Semantic | Server-owned profile(s) | Existing authority | Envelope / effect |
|---|---|---|---|
| `DEVICE_INVENTORY` | `android` | `ADB_LIST_DEVICES` | observe / device inventory |
| `ANDROID_PROPERTY` | `android` | `ADB_QUERY_PROPERTY` | observe / bounded property read |
| `ANDROID_LOG_CAPTURE` | `android`, `multi_repo` | `ADB_LOGCAT_CAPTURE` | observe / bounded log read |
| `ANDROID_INSTALL` | `android`, `multi_repo` | `ADB_INSTALL` | act / registered artifact install |
| `ANDROID_FORCE_STOP` | `android` | `ADB_FORCE_STOP_DEPUTY` | act / configured package stop |
| `ANDROID_CLEAR_DATA` | `android` | `ADB_CLEAR_DEPUTY_DATA` | act / configured package data clear |
| `REGISTERED_VERIFIER` | `python_docker`, `deputy_mcp_package` | `RUN_APPROVED_VERIFIER` | act / registered local verification |
| `REPO_STATE` | `multi_repo` | `CAPTURE_REPO_STATE` (existing internal `GIT_DIFF_CHECK` composition) | observe / configured repo state |
| `GIT_DIFF_CHECK` | `multi_repo` | `GIT_DIFF_CHECK` | observe / configured repo diff validation |

The profile matrix is server configuration, not model-selectable. Cross-profile
requests and cross-profile compounds fail closed. The only allowed device
targets are aliases resolved using a fixed server-owned file at
`RUNTIME_ROOT/a4-device-bindings.json`; the file path itself is not
configurable through MCP. Each alias maps to an operator-configured device
serial. A4 records bind the alias and a digest of the resolved binding; raw
serials remain local and are not copied into intent receipts. Missing or
unregistered aliases return `TARGET_NOT_REGISTERED`.

Artifacts, properties, verifier identifiers, repo root, and package/activity
selectors are limited to the existing server-owned registry/configuration.
Required values are never defaulted, clamped, approximated, or replaced by a
nearby registered value. `ANDROID_LOG_CAPTURE` requires an explicit bounded
line count in the existing range. Device inventory requires no selector.

Pure-observation compounds use `deputy_observe`. A compound containing any
effectful stage uses `deputy_act` for the entire ordered ticket. Compounds may
contain only semantics allowed by the active profile; stages execute in order
and stop on the first non-success result. Partial completion is reported
explicitly without claiming rollback. The A4 implementation imposes a smaller
bound (at most 8 stages) than the existing Worker job maximum.

## Intent, choice, and dispatch lifecycle

- IDs use cryptographically random tokens with at least 192 bits of entropy.
  Durable records are keyed by SHA-256 of the token; plaintext IDs are not
  persisted.
- Each record binds request digest, ordered semantic stages and normalized
  registered values, effect envelope, active profile, authority/registry
  digest, configured repo binding, device alias/binding digest where relevant,
  creation/expiry, process epoch, and state.
- Prepare choices expire after 5 minutes; executable tickets expire after 10
  minutes. Expired or unknown IDs fail closed.
- A ticket is single-dispatch for both observe and act. A second or concurrent
  use returns `INTENT_ALREADY_DISPATCHED`; it never replays or starts another
  Worker job. This also makes a lost MCP response non-retryable by ID.
- A durable claim is created atomically before Worker dispatch. Receipts record
  intent digest, dispatch state, internal run ID (local only), bounded terminal
  classification, and timestamps. Receipt data is HMAC-sealed using a local
  runtime key. Signing keys, internal run IDs, raw exceptions and local record
  bodies are not MCP fields; the public intent/choice IDs remain opaque handles.
- Immediately before dispatch, the implementation revalidates the ticket seal,
  profile, expiry, runtime epoch, current registry/mapping digest, registered
  parameters, repository binding, and device binding.
- After process restart, undispatched tickets and choices from the previous
  epoch are revoked. A dispatch lacking a durable terminal receipt is marked
  `OUTCOME_UNCERTAIN`; the system never silently restarts it. A4 does not expose
  status/poll/retry controls. Operator recovery is local and documented; an
  uncertain mutation requires owner review before new equivalent work.
- An unavailable or invalid local signing key fails closed; it is not silently
  regenerated while prior A4 records exist.

Both review strings are bounded to 1–1,800 characters and must be copied exactly
from the corresponding server response. The host must prompt for every choice
and action, showing complete arguments. The compact Codex approval row alone
is insufficient; inspect the full call. Model-authored approval text and MCP
annotations do not establish human authorization. See the
[current approval addendum](A4_BETA_GATE1B_APPROVAL_ADDENDUM.md).

The MCP server cannot cryptographically distinguish a user's new clarification
from model-generated text. `deputy_choose` therefore constrains selection to a
specific prior server-issued choice but is not represented as independent user
authentication. The existing host's approval behavior remains the user-facing
authorization boundary for `deputy_act`; unsupported hosts must not be described
as providing independent human confirmation.

## Result projection

The adapter reuses current job validation, `ProductionRunEngine`, operation
guards, repository/device bindings, child environment, integrity evidence,
timeouts, cancellation, sanitization, and cleanup. One intent may be submitted
to the engine once. Public A4 results contain the semantic summary, bounded
typed evidence, terminal status, completed-stage count and partial-completion
flag. They omit internal operation names, run IDs, PIDs, argv, absolute paths,
raw streams, and internal ticket data. `deputy_observe` cannot execute any
ticket whose bound effect is not observational; `deputy_act` cannot execute a
pure-observation ticket.

## Explicit non-goals and residual risks

The [published beta qualification scope](A4_BETA_RELEASE_SCOPE.md) records
the API 34 emulator observations, synthetic-only mutations, artifact-byte
limitation, and supported host profile. The original guided 12/12 campaign is
historical evidence for the previous protocol; it does not qualify these v2
review fields. Gate 1B supplies the current interactive evidence.

- The 14 unsupported Proof 9 semantics remain unsupported. No generic shell,
  arbitrary process, arbitrary path/root, free-form ADB, generic deploy,
  database mutation, or capability registration is added.
- The resolver is deterministic and conservative; uncertain/unsupported
  requests fail closed. A4 does not authenticate original user prose. The
  server receives the model-supplied preparation request.
- Device operations are scoped to server-owned aliases, but A4 is not a
  hostile multi-tenant boundary. Deployment remains
  `TRUSTED_SINGLE_OPERATOR_V1`.
- Synthetic tests do not establish physical-device behavior. No destructive
  test may be run without an explicitly authorized disposable device/emulator.
- This contract does not authorize a release, public merge, tag, deployment, or
  package publication.

## Original qualification plan (historical)

1. Preserve current legacy schemas and verify all 22 operations.
2. Test schemas, mode isolation, profile isolation, resolver positives,
   aliases, argument failures, compounds, and all unsupported semantic
   families.
3. Test ticket entropy/opaque persistence, altered/unknown/wrong-effect/
   wrong-profile/expired/revoked IDs, concurrent duplicate dispatch, replay,
   crash windows, restart invalidation, durable uncertain outcomes, and
   non-retry behavior.
4. Test each of nine mappings through the actual production adapter using
   synthetic repo/SDK/ADB fixtures; destructive effects are stubbed and
   asserted, never sent to a real device in CI.
5. Run the complete 22-operation legacy suite; package/installed-wheel and
   sdist tests; Windows and Linux CI; result sanitization and hygiene checks.
6. Run frozen held-out Luna qualification with no tuning after the freeze,
   including compounds, invalid selectors, hostile tool text, and all
   hard-zero criteria in the milestone. Preserve transcripts and usage.
7. Run independent security review. Resolve release-blocking findings.
8. Perform controlled real Worker qualification only for operations that can
   be safely exercised with configured disposable resources. Destructive
   Android qualification remains blocked until owner-authorized test hardware
   is explicitly identified.

Thresholds for model usability/performance must be frozen before any new held-
out evaluation. Proof 9 thresholds and results are not reused as production
qualification results.

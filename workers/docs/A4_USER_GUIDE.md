# Use Focused A4 Beta

A4 is an opt-in interface in the [published Workers `1.2.0b1` beta](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1),
protocol `DA-A4-BETA-2`. The release tag and archives are immutable; this
repository guide can receive reviewed documentation corrections.
You ask for a supported outcome, review what the server prepared, then make
one terminal observation or action call. Legacy Workers remains the default.
Start with the repository [installation](../../docs/INSTALLATION.md) and
[host setup](../../docs/MCP_HOST_SETUP.md) guides. In an extracted Workers
sdist those umbrella pages are not bundled; use the corresponding repository
documentation linked from its README.

## Profiles and nine mappings

The operator selects one profile at server startup. The assistant cannot change
it. Nine semantic mappings use existing operations from the **22-operation**
registry; they are not nine additional operations or 22 public MCP tools.

| Semantic outcome | Profile(s) | Result or effect |
| --- | --- | --- |
| `DEVICE_INVENTORY` | `android` | Observe registered devices; expose aliases rather than raw serials |
| `ANDROID_PROPERTY` | `android` | Observe an approved SDK-version or CPU-ABI property |
| `ANDROID_LOG_CAPTURE` | `android`, `multi_repo` | Capture a bounded log locally; public result reports the line count, not raw log text |
| `ANDROID_INSTALL` | `android`, `multi_repo` | Install a registered debug/release APK; effectful |
| `ANDROID_FORCE_STOP` | `android` | Stop the configured Deputy app; effectful |
| `ANDROID_CLEAR_DATA` | `android` | Clear that app's data; destructive |
| `REGISTERED_VERIFIER` | `python_docker`, `deputy_mcp_package` | Run the one registered runtime-integrity manifest verifier; effectful local execution |
| `REPO_STATE` | `multi_repo` | Observe Git HEAD, branch, dirty state and diff-check evidence |
| `GIT_DIFF_CHECK` | `multi_repo` | Observe the configured repository's whitespace/diff check |

`python_docker` is a profile name, not a general Docker interface. Unsupported
work never falls back to a shell or the legacy protocol. Missing selectors are
not filled with guesses. Device aliases and artifact names must already be
registered by the operator.

## The four tools

| Tool | Required arguments | What it does |
| --- | --- | --- |
| `deputy_prepare` | `request` | Interpret the request and prepare an intent or bounded choice; no target work |
| `deputy_choose` | `prepare_id`, `choice_id`, `choice_review` | Consume one exact approved choice; no target execution |
| `deputy_observe` | `intent_id` | Execute the prepared observation once and return a terminal result |
| `deputy_act` | `intent_id`, `approval_review` | Execute the approved effectful intent once and return a terminal result |

Copy IDs and review strings from their corresponding response. Do not invent,
edit or reuse them. Review fields are bounded to 1–1,800 characters; requests
are bounded to 1–8,000 characters. Unknown top-level fields are ignored by the
MCP 2.2 function wrapper and cannot add authority; use only the declared inputs.

The examples below show actual preparation arguments. Subsequent calls use
pseudocode to reference returned fields; those variable names are not literal
MCP argument values.

## Example 1: observe repository state

With profile `multi_repo`, call `deputy_prepare`:

```json
{"request":"Capture repository status"}
```

A `CLEAR` response includes `intent_id` and `intent.effect="OBSERVE"`. Call:

```text
deputy_observe(intent_id=prepared.intent_id)
```

Read the terminal status and the `REPO_STATE` facts. Do not poll or repeat the
intent: a second dispatch is rejected even if the first response was lost.

## Example 2: choose between registered APKs

This example requires profile `android` or `multi_repo` and the operator's
registered `LAB_DEVICE_ALPHA` alias. It is an explanation of the effectful
protocol, not authorization to install anything. The Android mutation path
has synthetic-only qualification.

Call `deputy_prepare`:

```json
{"request":"Install either the debug APK or release APK on LAB_DEVICE_ALPHA."}
```

On `CHOICE_REQUIRED`, show the exact options and wait for the operator to select
one. Do not rewrite the request to pick a preferred APK. A fresh preparation
while the choice is pending returns `CHOICE_PENDING`.

After the operator explicitly selects the debug option, submit that exact
option, subject to a human approval prompt showing all three arguments:

```text
deputy_choose(prepare_id=prepared.prepare_id,
              choice_id=selected.choice_id,
              choice_review=selected.choice_review)
```

Choice approval only issues a new intent. It does not install the APK.

## Example 3: separately approve the action

After that choice returns `CLEAR` with `intent.effect="ACT"`, inspect the
server-issued action review. It must still name the selected debug APK, exact
target, operation/effect and expiry. Call:

```text
deputy_act(intent_id=chosen.intent_id,
           approval_review=chosen.approval_review)
```

The host must ask the operator again before this action. Reject if anything
differs from the intended request. The server validates the exact review against
its sealed intent before dispatch. A model can copy the review, so the review
itself, an MCP annotation or model-authored confirmation is not human consent.
The host must display complete arguments; a compact truncated approval row is
insufficient. Host approval is required even for the registered verifier.

An explicit request such as "Install the registered debug APK on
LAB_DEVICE_ALPHA" can prepare an ACT intent directly; it still needs its own
approval. Device effects cannot be undone by rolling back the Python package.

## Example 4: reject unsupported work

Call `deputy_prepare`:

```json
{"request":"Run an arbitrary shell command"}
```

The response is `UNSUPPORTED`, with no executable intent. Stop. Do not reinterpret
this as permission to use another tool or add executable/path arguments.

## Other outcomes and recovery

- `ARGUMENT_REQUIRED` / `ARGUMENT_INVALID`: stop and obtain valid, explicit inputs.
- `TARGET_NOT_REGISTERED`: ask the operator to check the local alias configuration;
  never guess another device.
- `FAIL` / `BLOCKED` / `UNPROVEN`: inspect the result and stop as appropriate;
  absence of proof is not success.
- `OUTCOME_UNCERTAIN`: execution may have started. Stop for local evidence/target
  review; do not retry the intent or automatically prepare equivalent work.

Choice records expire after five minutes; intents after ten. Restart revokes
unconsumed prior-session IDs. A compound can contain up to eight supported
stages in the active profile; a compound containing any effect runs through
`deputy_act`, in order, stopping at the first non-success. Partial completion is
reported; no automatic rollback is promised.

## Limits you must keep in mind

Use a trusted single-operator deployment and a host that prompts on every
choice/action with complete arguments. An unrestricted alternative shell/ADB
route can bypass Deputy. Hostile local writers and multi-tenant use are unsupported.
Registered APK paths reject links/reparse escape, but APK bytes are not pinned
across approval/install. Seven Android observations were qualified on an isolated
API 34 emulator; seven mutating Worker operations remain synthetic-only. No
physical-device certification is claimed. See the [scope matrix](A4_BETA_RELEASE_SCOPE.md),
[host guide](A4_BETA_HOST_INTEGRATION.md) and [technical contract](A4_BETA_CONTRACT.md).

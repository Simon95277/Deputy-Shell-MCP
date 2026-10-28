# Focused A4 beta candidate scope

The Workers candidate version is `1.2.0b1`; the opt-in protocol is
`DA-A4-BETA-2`. Legacy Workers remains the default and retains all 22
operations. A4 maps nine fixed semantics to that registry. This candidate
does not complete the wider Phase 12 v1.0 maturity gate or certify production
use. Source qualification covers the scope below; public release is separately
gated and remains pending.

## Supported deployment and host

Deployment is `TRUSTED_SINGLE_OPERATOR_V1`. The operator controls the host,
configuration, one configured repository, runtime root and registered artifacts.
Hostile local writers, hostile shared users and multi-tenant deployments are
unsupported. Restrict alternative host shell/filesystem/ADB access when the
Deputy authority boundary is required.

Effectful A4 requires a trusted interactive MCP host that prompts for **every**
`deputy_choose` and `deputy_act` call and displays **complete arguments**.
The operator must inspect operation, effect, registered target, artifact or
parameters, ticket/choice and expiry. The compact Codex approval row alone
is insufficient; inspect the complete `Calling` arguments. A model can copy
server review strings. Model-authored approval text, tool annotations and an
opaque ticket are not human authorization. Hosts that auto-approve or hide
arguments are unqualified for effectful A4.

Gate 1B observed approve, reject and exact debug/release choice using Codex CLI
0.163.0, requested `gpt-6-luna` LOW, and an inert synthetic backend. Provider
observed model identity was not measured. The original guided 12/12 campaign
belongs to the previous protocol and remains historical evidence. Current v2
arguments are:

- `deputy_prepare(request)`
- `deputy_choose(prepare_id, choice_id, choice_review)`
- `deputy_observe(intent_id)`
- `deputy_act(intent_id, approval_review)`

## Android qualification matrix

Gate 2 qualified an isolated **API 34 emulator**. It did not qualify a physical
Android device. The owner-authorized direct synthetic APK installation and
scoped push only prepared that emulator; they did not qualify mutating Worker
product paths.

| Classification | Worker operations |
| --- | --- |
| Emulator verified (7) | `ADB_LIST_DEVICES`, `ADB_WAIT_FOR_DEVICE`, `ADB_QUERY_PROPERTY`, `ADB_QUERY_PACKAGE`, `ADB_PULL_SCOPED`, `ADB_DUMPSYS_REGISTERED`, `ADB_LOGCAT_CAPTURE` |
| Synthetic-only mutations (7) | `ADB_INSTALL`, `ADB_UNINSTALL_DEPUTY`, `ADB_CLEAR_DEPUTY_DATA`, `ADB_FORCE_STOP_DEPUTY`, `ADB_START_DEPUTY_ACTIVITY`, `ADB_INSTRUMENT`, `ADB_PUSH_SCOPED` |
| Physical device verified | None |

A4 exposes only its nine semantic mappings, not every Android operation in
this matrix. Ordinary CI uses inert fixtures and requires no device. Any new
device mutation qualification requires separate exact target/action authority.

## Artifact and recovery limits

Registered APK paths must resolve to regular files inside the configured
repository and may not traverse symlinks or reparse points. This prevents
static registered-path escape. APK bytes are **not pinned across preparation,
approval and installation**. The trusted operator must keep artifacts stable
through that window. No hostile-local-writer isolation is claimed.

Expired, changed-authority, wrong-effect, replayed and prior-epoch tickets fail
closed. An uncertain action is not automatically retried. Preserve the local
runtime and review receipts before deciding whether any new action is safe.
Package rollback does not roll back device effects or make old tickets usable.
See the [host guide](A4_BETA_HOST_INTEGRATION.md),
[approval addendum](A4_BETA_GATE1B_APPROVAL_ADDENDUM.md) and
[installation guide](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/docs/INSTALLATION.md).
For a first-use walkthrough see the [A4 user guide](A4_USER_GUIDE.md).

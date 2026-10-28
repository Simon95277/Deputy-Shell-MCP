# Focused A4 beta host integration

A4 is available in the [published Workers `1.2.0b1` beta](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1).
It remains an opt-in Workers protocol for a trusted single operator. The server
owns its profile, repository/device bindings, registered executables, and
operation mapping. A compatible MCP host should discover exactly four tools:
`deputy_prepare`, `deputy_choose`, `deputy_observe`, and `deputy_act`.

Start with the [installation and registration guide](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/docs/MCP_HOST_SETUP.md)
and [A4 examples](A4_USER_GUIDE.md). This document gives the host routing and
approval requirements; the server does not enforce which other tools a host grants.

## Route covered tasks

An MCP tool description does not force a coding model to use that tool. In
local synthetic qualification, unguided Luna requests sometimes went to the
host's ordinary shell/Git tools even though the A4 tools were callable. The
following session-level guidance made the A4 route explicit:

> For tasks covered by the configured A4 profile, call `deputy_prepare` with
> the user's request. Do not inspect or operate on the configured target using
> local shell, Git, filesystem, or ADB tools. If preparation returns `CLEAR`,
> dispatch its exact intent once through `deputy_observe` for `OBSERVE` or
> `deputy_act` for `ACT`. If it returns `CHOICE_REQUIRED`, show the exact choices
> and wait for an explicit user selection before calling `deputy_choose`.
> Never guess a choice or replace the unresolved request. Stop on unsupported
> or missing arguments.

For `DA-A4-BETA-2`, copy the server-issued `choice_review` on a chosen option
and `approval_review` on a CLEAR ACT ticket. The host must prompt the operator
for each `deputy_choose` and `deputy_act` call and show all arguments. See the
[Gate 1B approval addendum](A4_BETA_GATE1B_APPROVAL_ADDENDUM.md).

For Codex, supply this as session-level `developer_instructions` in the
isolated client configuration. Keep model and effort settings explicit during
qualification. The local guided campaign requested `gpt-6-luna` at LOW effort;
provider-observed model identity was not exposed by that client. Workers itself
is deterministic Python and does not use a model.

This guidance improves routing; it does not remove other host tools or create
a security boundary. If bypassing A4 matters, configure the host so its model
has no separate direct route to the target repository or device. A4 cannot
revoke authority that the host independently grants.

## Approval and choices

`deputy_prepare` never executes target work. `deputy_choose` selects only an
exact server-issued option, but the server cannot authenticate whether the
selection came from a human. The host must present the exact choice review
and require a human decision on the `deputy_choose` call. It must likewise
require a fresh human decision on the `deputy_act` call using the exact action
review. Automatic approval does not establish human consent for an install,
force-stop, clear-data, or verifier action.

The historical, previous-protocol 12-case guided model campaign used a synthetic,
non-executing Worker backend. It passed all cases, including a two-turn ambiguous APK choice and
single-dispatch no-retry checks. Those results establish routing and protocol
behavior in that frozen test setup. They do not establish physical Android
behavior or safety on a real device.

Gate 1B separately qualified the current `DA-A4-BETA-2` interactive approve,
reject, and exact-choice path in Codex CLI 0.163.0. A choice issues an intent;
an effectful intent still needs its own action approval. See the
[release scope](A4_BETA_RELEASE_SCOPE.md) for Android and artifact limitations.

## Codex `/mcp` diagnostic limitation

In one Codex CLI 0.163.0 setup, `/mcp` opened a second A4 process using the
same runtime root. The server's exclusive instance lock rejected that process,
so the UI displayed zero tools while the first connection had already listed
and called all four. Keep the lock. For that setup, inspect the first
connection's MCP `tools/list` response and a real model tool call; the `/mcp`
display alone is not conclusive.

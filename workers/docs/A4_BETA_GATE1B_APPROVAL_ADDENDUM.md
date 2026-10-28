# Focused A4 beta Gate 1B approval addendum

This addendum records the opt-in `DA-A4-BETA-2` interface. The original Gate A
contract and frozen qualification evidence describe `DA-A4-BETA-1` and remain
historical inputs. This change does not authorize publication or real-device
qualification.

## Server-issued review fields

The four A4 tool names are unchanged. `deputy_choose` now requires
`choice_review` alongside `prepare_id` and `choice_id`; `deputy_act` now
requires `approval_review` alongside `intent_id`. The fields are bounded
strings copied from the preceding server response, not new operation or target
selectors. `deputy_prepare` returns one `choice_review` per exact option on
`CHOICE_REQUIRED`. A `CLEAR` result for an ACT intent returns
`approval_review`. Observation dispatch still accepts only `intent_id`.

Each review states the semantic operation, effect class, registered device
alias or configured repository, relevant registered parameters, ticket/choice
identity, and UTC expiry. It omits raw serials, host paths, and executable
details. A4 recomputes the exact review from its integrity-sealed record and
rejects a missing, modified, swapped, expired, or replayed submission before
Worker dispatch. Review text is **not** an authorization token: the model can
copy it, and the host must obtain an independent operator decision for each
`deputy_choose` and `deputy_act` call.

## Supported host boundary

Use a trusted interactive MCP host configured to prompt for every
`deputy_choose` and `deputy_act` call, showing **all tool arguments** before the
operator approves or rejects. The operator reviews the server-issued operation,
target, parameter, effect, and expiry text and can reject the call. For an
unresolved choice, approving a displayed exact `deputy_choose` option is the
operator's selection; the model's choice alone is insufficient. The host must
not auto-approve these tools. An `approval_policy=never` host is suitable for
denial tests but cannot qualify permitted effectful execution. A4 cannot
authenticate the user message that led to preparation, and it cannot detect a
host that silently auto-approves or hides arguments. Deployments that need
these guarantees must enforce this host profile; mere model instructions do
not enforce it.

In the tested Codex CLI 0.163.0 terminal, the compact approval row abbreviates
long `approval_review` values. The complete value appears in the preceding
`Calling` arguments. The operator must inspect that complete call, including
target and artifact, before allowing it. A host that hides or truncates the
complete arguments without another trustworthy expansion is not qualified for
effectful A4 use.

The server validates the review **after** the host approves the call and
**before** Worker dispatch or choice consumption. A forged description may
therefore appear on a host card, but cannot authorize a different sealed
operation. Denial produces no call to the Worker. Choice approval only mints a
new intent; an ACT intent needs a separate, fresh `deputy_act` approval.

Legacy mode retains its prior two-tool schemas and 22-operation authority.
The nine A4 mappings and server-owned source/device/executable bindings are
unchanged.

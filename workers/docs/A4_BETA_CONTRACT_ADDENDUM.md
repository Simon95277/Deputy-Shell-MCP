# A4 beta contract addendum — choice and compound safety

This addendum records implementation corrections made after the original
Gate A contract freeze. The original freeze and qualification evidence remain
unchanged; this file is not a release authorization.

## Profile-specific model-facing discovery

`deputy_prepare` advertises the user-facing task families supported by the
server-selected A4 profile. The description is generated from the same fixed
profile set as the resolver mapping; it does not accept or select a profile
from an MCP argument. It directs callers to use A4 instead of local shell or
command tools for covered tasks, and distinguishes read-only observations from
effectful verifier/device actions. It also states that preparation never
executes and that normal host approval still applies to effectful dispatch.

This improves discovery only. It does not add task mappings, change the four
public tools or their schemas, expose internal Worker operation identifiers,
or widen repository/device authority. Unsupported tasks remain unsupported.

## Pending clarification

- A4 retains at most one unresolved choice per server instance/profile.
- While a choice is pending, a fresh `deputy_prepare` returns
  `BLOCKED` / `CHOICE_PENDING` and cannot mint a replacement intent. The
  original choice can be resolved with its server-issued choice ID, or it
  expires after the existing five-minute lifetime. A server restart revokes
  the unresolved choice as documented by the original contract.
- This gate prevents a new prepare request from silently replacing the
  unresolved request. It does **not** authenticate whether a call to
  `deputy_choose` originated from a human. The MCP host's approval behavior
  remains the only user-facing authorization boundary for effectful dispatch.

## Compound stage binding

- Each operation stage resolves device aliases only from its own bounded
  request segment. An alias mentioned in a different stage is never inferred
  as the missing target for this stage.
- When a stage has bounded choices, each choice retains all already-resolved
  and later-resolved compound stages in their original order. If the bounded
  choice product exceeds the existing public limit, preparation fails closed
  and requires a narrower request.

## MCP side-effect annotations

`deputy_prepare` and `deputy_choose` are advertised with
`readOnlyHint=false` because they persist short-lived ticket/choice state and
mint or consume authority tickets. They are also advertised with
`destructiveHint=true` because bounded capacity management may delete expired,
unclaimed local ticket records. This cleanup does not execute Worker
operations or mutate the target. `deputy_observe` is also advertised with
`readOnlyHint=false` because it persists a one-shot claim and receipt, while
remaining `destructiveHint=false` and never mutating the target repository or
device. Effectful target execution remains confined to `deputy_act`.

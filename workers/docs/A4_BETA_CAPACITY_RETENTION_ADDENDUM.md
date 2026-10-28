# A4 Beta capacity-retention addendum

This addendum supersedes the capacity/retention details of the original Gate A
contract freeze without changing its preserved evidence. The implementation
still uses the frozen nine semantic mappings and the same authority envelopes.

When the durable A4 record limit is reached, the server may reclaim records
only after authenticating their HMAC and confirming their expiry. Reclaimable
records are expired, pre-dispatch intent tickets without a dispatch claim and
expired prepare/choice records that cannot issue a live choice. A deleted
ticket is rejected as not found; it never becomes executable again.

The server does not reclaim unexpired records, records with malformed or
invalid integrity seals, dispatch-claimed intents, `DISPATCHING` records,
completed dispatch receipts, or `OUTCOME_UNCERTAIN` records. If capacity is
still exhausted after safe reclamation, the request fails closed with
`A4_STORAGE_LIMIT`. Choice capacity is checked before consuming a one-shot
choice, so a capacity refusal does not burn a valid choice.

This is local bounded retention for the existing intent store, not a new
operator-selected cleanup policy. No cleanup path accepts a caller-supplied
path, ticket state, or retention duration.

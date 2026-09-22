# Roadmap

## Agents hardening

- **Completed in lifecycle hardening:** durable job state across MCP restart;
- **Completed in lifecycle hardening:** early cancellation registration race;
- **Completed in lifecycle hardening:** startup orphan/resource reconciliation;
- **Completed in snapshot coherence:** whole-snapshot byte-level coherence;
- **Completed in diagnostic-surface hardening:** gate `deputy_git_probe` and
  `deputy_child_ping` behind explicit server-owned development configuration;
- **Completed in provider/model contract:** server-owned explicit provider and
  model selection with bounded configured-vs-observed identity evidence;
- packaging and installer maturity;
- broader privacy/generalization.

## Workers

- V2/C1 remains research only;
- future capability expansion requires an explicit architecture decision;
- release and packaging maturity.

## Shared

- CI;
- reproducible dependency validation;
- installer/release artifacts;
- contributor workflow;
- v1.0 maturity gate.

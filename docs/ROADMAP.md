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
- **Completed in packaging/reproducibility:** installable Agents and Workers
  distributions, stable console entry points, portable runtime roots,
  deterministic qualification constraints, bounded Windows bootstrap, and
  clean wheel/sdist qualification;
- broader privacy/generalization.

## Workers

- V2/C1 remains research only;
- future capability expansion requires an explicit architecture decision;
- release maturity remains later work.

## Shared

- **Next:** CI and release gates;
- reproducible dependency validation;
- installer/release artifacts;
- contributor workflow;
- v1.0 maturity gate.

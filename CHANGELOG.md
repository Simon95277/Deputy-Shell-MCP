# Changelog

All notable project changes are recorded here. This repository contains two
independent MCP runtimes: DeputyAgents and DeputyWorkers.

## Unreleased

### Added

- Added installable Agents and Workers Python distributions with stable console
  entry points, portable runtime roots, deterministic qualification constraints,
  and bounded Windows bootstrap support.
- Added GitHub Actions CI and a manual release-candidate qualification workflow
  covering Windows deterministic qualification, Linux portability, package
  builds, artifact auditing, checksums, and release-candidate bundle creation.
- Added the Phase 11 efficiency benchmark source, fixtures, schemas, runner,
  regression tests, and read-only post-campaign finalizer.
### Changed

- Reworked the normal MCP contract around the control-tower model:
  **the model chooses intent; the server chooses authority**.
- DeputyAgents now exposes only `deputy_recon(goal)` by default. Repository
  binding, snapshot selection, contained lifecycle, polling, and cleanup are
  server-owned.
- DeputyWorkers now exposes only `deputy_observe(request)` and
  `deputy_act(request)` by default over the frozen 22-operation registry.
  Run IDs, process details, raw evidence, and internal multi-step composition
  stay behind the server boundary.
- Added server-side serialization for normal Worker calls so concurrent requests
  do not leak the internal single-active-run lifecycle as
  `ACTIVE_RUN_EXISTS`.
- Updated public README, architecture, CI, roadmap, and subsystem documentation
  to describe the current trust model, installation path, capability boundary,
  and benchmark limitations.
### Security and privacy

- Added the `DA-PRIVACY-1-positive-policy-v1` server-owned source-selection
  policy for DeputyAgents.
- Added high-confidence content-secret scanning before provider setup.
- Added `DA-BYTE-COHERENCE-1` snapshot byte-coherence validation and
  source-after verification.
- Hardened provider/model selection so callers and snapshot content cannot
  replace the fixed OpenCode / `muse-spark-1.3-contributor-free` contract.
- Added bounded local-only containment failure diagnostics while keeping raw
  exception text and host details out of public MCP results.
- Added Workers public-result sanitization and explicit documentation of the
  `TRUSTED_SINGLE_OPERATOR_V1` deployment boundary.
### Validation and measured results

- Phase 9 CI and release-candidate gates completed successfully on the prior
  baseline.
- Phase 10 privacy/generalization work completed.
- Phase 11 control-tower efficiency work completed.
- Workers E1-E3 supervisor cost versus the old Deputy lifecycle design fell from
  **2,132,559 to 1,023,874 tokens (-51.99%)**, while model-visible MCP calls
  fell from **39 to 22**.
- Across available valid DIRECT-vs-DEPUTY E1-E6 pairs, Deputy used **0.94% fewer
  Luna supervisor tokens overall**. E6 alone used **10.41% more**, so the
  benchmark does not support a universal token-saving claim.
- Active context-window/compaction telemetry and child-agent token usage were
  not authoritatively measured and remain explicitly unmeasured.

### Planned

- Add below-break-even delegation/refusal routing so trivial work can remain
  direct when Deputy cannot materially compress the evidence returned to the
  supervisor, without weakening security or authority boundaries.
- Complete the Phase 12 v1.0 maturity and security-audit readiness gate.

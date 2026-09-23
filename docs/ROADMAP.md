# Roadmap

## Agents hardening

- **Completed in lifecycle hardening:** durable job state across MCP restart.
- **Completed in lifecycle hardening:** early cancellation registration race.
- **Completed in lifecycle hardening:** startup orphan/resource reconciliation.
- **Completed in snapshot coherence:** whole-snapshot byte-level coherence.
- **Completed in diagnostic-surface hardening:** gate `deputy_git_probe` and
  `deputy_child_ping` behind explicit server-owned development configuration.
- **Completed in provider/model contract:** server-owned explicit provider and
  model selection with bounded configured-versus-observed identity evidence.
- **Completed in packaging/reproducibility (Phase #8):** installable Agents and
  Workers distributions, stable console entry points, portable runtime roots,
  deterministic qualification constraints, bounded Windows bootstrap, and
  clean wheel/sdist qualification.

## Workers

- V2/C1 remains research only.
- Future capability expansion requires an explicit architecture decision.
- Destructive Android qualification remains outside ordinary contributor CI.

## Shared

- **Phase #9 — CI and release-candidate gates: COMPLETED.** PR CI, main CI,
  and manual release-candidate qualification passed. Candidate artifacts are
  checksummed and uploaded ephemerally; no release, tag, or PyPI publication
  was performed.
- **Phase #10 — privacy and generalization: IN PROGRESS.**
- Phase #11: efficiency benchmark.
- Phase #12: v1.0 maturity gate.

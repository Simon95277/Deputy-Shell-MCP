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
- **Phase #10 — privacy and generalization: COMPLETED.**
- **Phase #11 — efficiency benchmark: COMPLETED.** The control-tower redesign reduced
  Workers E1-E3 campaign supervisor cost by 51.99% (2,132,559 -> 1,023,874)
  and model-visible MCP calls from 39 to 22. Across available valid paired
  E1-E6 comparisons, Deputy supervisor usage was 0.94% lower overall; E6 alone
  was 10.41% higher, so efficiency depends on workload shape rather than MCP use
  being intrinsically cheaper.
- **Post-Phase #11 routing refinement: PLANNED.** Add a server-owned refusal /
  direct-routing policy for work that cannot materially compress the evidence
  Luna would otherwise consume. Security and authority requirements take
  precedence over efficiency routing.
- Phase #12: v1.0 maturity gate.

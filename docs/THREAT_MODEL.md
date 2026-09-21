# Umbrella threat model

## Agents

The AI child is untrusted. The design addresses prompt injection, provider
exposure, snapshot integrity, Docker containment, provider-only networking,
and lifecycle cleanup. The live repository is not mounted.

## Workers

Workers are trusted deterministic code. The relevant risks are capability
widening, host process execution, repository mutation, path escape, device
mutation, ADB authority, and trusted executable/configuration boundaries.
Workers are not claimed to be containerized.

# Umbrella threat model

## Agents

The AI child is untrusted. The design addresses prompt injection, provider
exposure, server-owned provider/model selection, workspace configuration
override, snapshot integrity, Docker containment, provider-only networking,
and lifecycle cleanup. The live repository is not mounted. The fixed Agents
contract selects `opencode` / `muse-spark-1.3-contributor-free`; callers and
snapshot content cannot select a different provider or model, and no host
credential environment is forwarded. Runtime identity is reported as
observed only when OpenCode emits both identity fields.

## Workers

Workers are trusted deterministic code. The relevant risks are capability
widening, host process execution, repository mutation, path escape, device
mutation, ADB authority, and trusted executable/configuration boundaries.
Workers are not claimed to be containerized.

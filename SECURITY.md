# Security policy

This project is experimental containment infrastructure. Please report
suspected vulnerabilities through GitHub Private Vulnerability Reporting for
this repository. Do not submit secrets, vulnerabilities, exploit details,
credentials, or private data through ordinary public Issues, pull requests, or
discussions.

See [the threat model](docs/THREAT_MODEL.md) for current boundaries and known
limitations. Agents qualifies each selected candidate generation with
`DA-BYTE-COHERENCE-1` byte coherence and the server-owned
`DA-PRIVACY-1-positive-policy-v1` source policy, including a deterministic
high-confidence content-secret scan before worker/provider setup. This reduces
specific exposure risks; it does not make provider-exposable source
confidential or provide comprehensive PII detection.

## Scope

Reports should address the bounded MCP server, its containment boundary, and
the snapshot/evidence handling implemented here. Do not include credentials,
private source, device data, or unrelated repository material in a report.

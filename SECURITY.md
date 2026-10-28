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

Deployment supports one trusted operator controlling the machine, configuration
and repository. Hostile local writers and multi-tenant use are unsupported.
Effectful A4 requires human approval for every choice/action with complete
arguments visible. The compact Codex approval row alone, model-authored review
text and MCP annotations are insufficient. Independent shell/ADB authority
granted by the MCP host can bypass the Deputy route.

Registered APK paths reject symlink/reparse escape, but APK bytes are not pinned
across approval/install. Seven Android observations were qualified on an isolated
API 34 emulator; seven mutating Worker operations remain synthetic-only. No
physical-device or universal production safety certification is claimed. See
the [qualification scope](workers/docs/A4_BETA_RELEASE_SCOPE.md) and
[user guide](workers/docs/A4_USER_GUIDE.md). Package version numbers do not mark
the wider Phase 12 v1.0 maturity gate complete.

Reports should address the bounded MCP server, its containment boundary, and
the snapshot/evidence handling implemented here. Do not include credentials,
private source, device data, or unrelated repository material in a report.

# Security policy

This project is experimental containment infrastructure. Please report
suspected vulnerabilities through GitHub Private Vulnerability Reporting for
this repository. Do not submit secrets, vulnerabilities, exploit details,
credentials, or private data through ordinary public Issues, pull requests, or
discussions.

See [the threat model](docs/THREAT_MODEL.md) for current boundaries and known
limitations. Snapshot capture does not yet provide transactional whole-tree
byte coherence; changes during capture are detected by bounded before/after
state checks.

## Scope

Reports should address the bounded MCP server, its containment boundary, and
the snapshot/evidence handling implemented here. Do not include credentials,
private source, device data, or unrelated repository material in a report.

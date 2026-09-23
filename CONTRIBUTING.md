# Contributing

Keep changes within the documented Agents and Workers contracts. Do not add
generic shell, arbitrary process, device, filesystem, or repository authority.
Workers capability changes require architecture review. Destructive Android
qualification is not part of ordinary contributor CI.

## Local checks

For the qualified Windows environment, use CPython 3.10 and MCP 2.2.0 from
`constraints/qualification-windows-py310.txt`. Run the Agents and Workers
unittest suites from their respective component directories. Workers tests
must use an explicit synthetic repository and SDK fixture; do not point them at
a personal Android project or device. The CI fixture and contract checks are
documented in [docs/CI.md](docs/CI.md).

The pull request checks run the Windows qualification, Linux portability
matrix, packaging/install checks, package-content audit, public-tree hygiene,
and contract consistency checks. These gates verify source and package
behavior. They intentionally do not run Docker, contact the provider, inspect a
live Deputy Shell checkout, or use ADB or a physical device.

Packaging checks build both distributions, install wheels in fresh virtual
environments from outside the checkout, rebuild wheels from source
distributions, and audit the resulting archive contents. Do not commit runtime
evidence, snapshots, credentials, logs, local configuration, or generated
qualification state.

## CI trust boundary

Pull request code is untrusted. The workflows declare only `contents: read`,
use GitHub-hosted runners, and do not reference secrets or deployment
environments, provider credentials, a Docker socket, a self-hosted runner, or
`pull_request_target`. Repository and organization settings remain responsible
for capping effective token permissions. The manual release-gate workflow
qualifies a candidate only when its selected ref and commit match current
`main`. It uploads a short-lived candidate bundle after all checks pass; it
does not publish a release, create a tag, or publish to PyPI.

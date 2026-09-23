# CI and release-candidate gates

## Pull request trust boundary

Repository code from pull requests, including fork pull requests, is untrusted.
The CI workflow uses the normal `pull_request` event, declares only
`contents: read`, and uses GitHub-hosted runners. It does not use
`pull_request_target`, reference repository or environment secrets, provider
credentials, a privileged Docker socket, a self-hosted runner, or a local
network path into the owner's machine. Checkout does not persist its token.
Workflow action references are pinned to full commit SHAs. Repository and
organization settings must continue to cap effective token permissions; those
external settings are not controlled by workflow source.

Windows test jobs create an inert synthetic repository, a placeholder SDK, and
a Docker-path placeholder used only by read-only preflight checks. Tests do
not execute Gradle, ADB, Docker, or provider inference. Linux runs source tests
against the same style of synthetic fixture. The Python 3.10 Windows job is
the deterministic dependency qualification; Linux is a portability and
compatibility gate.

## What the checks cover

- Agents and Workers unit suites and compile/import checks.
- The exact four production Agents tools, default-disabled diagnostics,
  provider/model contract, runtime/coherence/snapshot markers, and the
  22-entry Workers registry.
- Windows CPython 3.10 with the checked-in MCP 2.2.0 qualification lock, plus
  Linux CPython 3.10 and the newest stable Python version recorded in the
  workflow.
- Wheel and source-distribution builds, fresh wheel installs from unrelated
  working directories, and source-distribution-to-wheel rebuild installs.
- Deterministic package-content audit and bounded public-tree / secret hygiene.

The hygiene scan checks known credential patterns, private-key headers,
personal absolute home paths, personal email residue, and runtime/evidence
directories. It is a bounded source hygiene check, not comprehensive PII
detection.

CI does not qualify Docker containment, a live provider session, a live Deputy
Shell checkout, an Android SDK installation, an Android device, or destructive
ADB behavior. Those are separate local qualification domains and must not be
added to ordinary pull request CI.

## Manual release-candidate workflow

`release-gate.yml` runs only through `workflow_dispatch`. Its initial gate
checks the selected ref and commit against current `main` before any
repository test or build code runs; the Windows candidate job repeats that
check to catch a concurrent main update. It then runs Windows qualification
and waits for the Linux portability matrix before building the candidate. The
resulting artifact contains the two wheels, two source
distributions, `SHA256SUMS.txt`, and `release-manifest.json`. The workflow
recomputes the artifact hashes and rejects extra files before upload. Artifact
retention is 14 days.

This workflow only qualifies and uploads an ephemeral GitHub Actions artifact.
It does not create a release or tag, publish to PyPI, or change repository
settings. No workflow accepts caller-provided shell commands, build commands,
repository URLs, or upload destinations.

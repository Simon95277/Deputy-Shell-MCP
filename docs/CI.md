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
a Docker-path placeholder used only by read-only preflight checks. The SDK
fixture includes inert `adb` and `adb.exe` path placeholders for platform path
contracts; neither is executed. Tests do not execute Gradle, ADB, Docker, or
provider inference. Linux runs source tests against the same style of synthetic
fixture. The Python 3.10 Windows job is
the deterministic dependency qualification; Linux is a portability and
compatibility gate.

The process-creation identity token is a Windows-specific physical contract.
Windows qualification checks it against the live Windows process API. Linux
tests do not synthesize a host identity: they assert that POSIX liveness
evidence has no Windows creation token, while a focused mock verifies that a
provided authoritative token is preserved in bounded evidence.

## What the checks cover

- Agents and Workers unit suites and compile/import checks.
- Exactly one default production Agents tool and two default Workers tools;
  owner-only control-plane tools are absent by default; diagnostics remain
  default-disabled.
  provider/model contract, runtime/coherence/snapshot markers, and the
  22-entry Workers registry.
- Windows CPython 3.10 with the checked-in MCP 2.2.0 qualification lock, plus
  the explicitly configured Linux matrix (currently 3.10 and 3.14.7 in the
  checked-in workflows). Those matrix values are not a claim about today's
  newest Python release. Local beta qualification also covered Ubuntu/WSL 3.12.
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

The beta's local four-tool A4 qualification is separate from a public run of
these workflows. Source regressions cover A4 schemas, nine mappings, review
binding and restart/replay behavior; this documentation edit does not claim a
new remote CI result or publish an artifact. A public prerelease needs its own
approved final commit, verified packages and release decision.

## Run the source gates locally

Run from the repository root in a dedicated Python environment. On Windows
CPython 3.10, install `mcp==2.2.0` using
`--constraint constraints/qualification-windows-py310.txt`. On Linux, install
`mcp==2.2.0` normally; that is a portability check, not the Windows lock.
Do not install both runtime distributions into this one test environment.

PowerShell synthetic prerequisites and source checks:

```powershell
$qualificationRoot = Join-Path $env:TEMP ("deputy-ci-" + [guid]::NewGuid())
python scripts/ci_checks.py fixture --root "$qualificationRoot/repo" --sdk "$qualificationRoot/sdk" --docker-stub "$qualificationRoot/docker-stub.exe"
$env:DEPUTYWORKERS_DEPUTY_SHELL_ROOT = "$qualificationRoot/repo"
$env:DEPUTYWORKERS_RUNTIME_ROOT = "$qualificationRoot/workers-runtime"
$env:DEPUTYWORKERS_EVIDENCE_ROOT = "$qualificationRoot/workers-runtime/evidence"
$env:DEPUTYWORKERS_ANDROID_SDK_ROOT = "$qualificationRoot/sdk"
$env:DEPUTYWORKERS_ADB_EXE = "$qualificationRoot/sdk/platform-tools/adb.exe"
$env:DEPUTYWORKERS_PYTHON_EXE = (Get-Command python).Source
$env:DEPUTYWORKERS_PROTOCOL_MODE = "legacy"
$env:DEPUTYWORKERS_ENABLE_CONTROL_PLANE = "0"
$env:DEPUTYAGENTS_DEPUTY_SHELL_ROOT = "$qualificationRoot/repo"
$env:DEPUTYAGENTS_RUNTIME_ROOT = "$qualificationRoot/agents-runtime"
$env:DEPUTYAGENTS_DOCKER_EXE = "$qualificationRoot/docker-stub.exe"
$env:DEPUTYAGENTS_ENABLE_DIAGNOSTICS = "0"
$env:DEPUTYAGENTS_ENABLE_CONTROL_PLANE = "0"
python scripts/ci_checks.py contracts
python scripts/ci_checks.py tests --component agents
python scripts/ci_checks.py tests --component workers
python scripts/ci_checks.py hygiene
```

Linux equivalents:

```bash
qualification_root="$(mktemp -d)"
python scripts/ci_checks.py fixture --root "$qualification_root/repo" --sdk "$qualification_root/sdk" --docker-stub "$qualification_root/docker-stub"
export DEPUTYWORKERS_DEPUTY_SHELL_ROOT="$qualification_root/repo"
export DEPUTYWORKERS_RUNTIME_ROOT="$qualification_root/workers-runtime"
export DEPUTYWORKERS_EVIDENCE_ROOT="$qualification_root/workers-runtime/evidence"
export DEPUTYWORKERS_ANDROID_SDK_ROOT="$qualification_root/sdk"
export DEPUTYWORKERS_ADB_EXE="$qualification_root/sdk/platform-tools/adb"
export DEPUTYWORKERS_PYTHON_EXE="$(command -v python)"
export DEPUTYWORKERS_PROTOCOL_MODE=legacy
export DEPUTYWORKERS_ENABLE_CONTROL_PLANE=0
export DEPUTYAGENTS_DEPUTY_SHELL_ROOT="$qualification_root/repo"
export DEPUTYAGENTS_RUNTIME_ROOT="$qualification_root/agents-runtime"
export DEPUTYAGENTS_DOCKER_EXE="$qualification_root/docker-stub"
export DEPUTYAGENTS_ENABLE_DIAGNOSTICS=0
export DEPUTYAGENTS_ENABLE_CONTROL_PLANE=0
python scripts/ci_checks.py contracts
python scripts/ci_checks.py tests --component agents
python scripts/ci_checks.py tests --component workers
python scripts/ci_checks.py hygiene
```

The placeholders satisfy source-test prerequisites and must never be used as
real Docker/ADB executables. For process startup/discovery testing, use an
explicit inert executable harness or qualified real prerequisites; a placeholder
path passing preflight does not prove that a server can perform live work.
The accepted beta baseline is 179 Agents and 399 Workers tests; report actual
totals if tests are added. Preserve timing failures and investigate them.

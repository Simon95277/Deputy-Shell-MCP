# DeputyWorkers MCP

DeputyWorkers provides fixed, measured engineering operations to an MCP coding
assistant. Local Python code runs registered repository, test-report, artifact
and Android operations. Workers does not call an AI model and exposes no generic
shell, arbitrary executable or caller-selected command arguments.

Version `1.2.0b1` is a Focused A4 Beta candidate. **Legacy Workers remains the
default**, preserving all 22 operations through `deputy_observe(request)` and
`deputy_act(request)`. A request selects one typed registered operation. Some
operations accept bounded repository-relative paths or device serials; those
inputs do not replace the server-owned repository, executable or registry.

## Install and connect

Use Python 3.10+ and Git, a repository you control, and a separate Workers virtual
environment. Do not install Agents into it: both packages provide top-level
`server`, `config` and `preflight` modules. With that environment's Python:

```text
<workers-python> -m pip install mcp==2.2.0 ./deputy_workers_mcp-1.2.0b1-py3-none-any.whl
<workers-python> -m pip check
```

`<workers-python>` means the actual virtual-environment interpreter. The
[Windows/Linux installation guide](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/docs/INSTALLATION.md)
provides complete venv, checksum and sdist steps. Publication is pending; use
reviewed local candidate files until the GitHub prerelease is available.

Configure the server's `DEPUTYWORKERS_DEPUTY_SHELL_ROOT`, writable
`DEPUTYWORKERS_RUNTIME_ROOT`, its subordinate `DEPUTYWORKERS_EVIDENCE_ROOT`,
and absolute `DEPUTYWORKERS_PYTHON_EXE`. Keep runtime data outside installed
code. Run the installed `deputy-workers-mcp --check`, then register its absolute
stdio console path with no arguments and the same environment in the host.

SDK/ADB is needed only for Android operations, not repository observations.
`--check` reports configuration; it does not execute ADB, install tools, run a
verifier or qualify a device. The
[host guide](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/docs/MCP_HOST_SETUP.md)
includes a no-device repository-state example and expected inventories.

## Opt in to A4

Set `DEPUTYWORKERS_PROTOCOL_MODE=focused-a4-beta` and a fixed
`DEPUTYWORKERS_A4_PROFILE` before starting the server. Profiles are `android`,
`multi_repo`, `python_docker` and `deputy_mcp_package`; their names do not grant
general Python/Docker/package authority. A4 uses nine fixed semantic mappings
backed by the unchanged 22-operation registry, not 22 new model-facing tools.

The `DA-A4-BETA-2` public tools are:

- `deputy_prepare(request)`
- `deputy_choose(prepare_id, choice_id, choice_review)`
- `deputy_observe(intent_id)`
- `deputy_act(intent_id, approval_review)`

For examples see the repository
[A4 guide](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/workers/docs/A4_USER_GUIDE.md).
The sdist also includes this guide and the technical/host documents under `docs/`;
their umbrella links assume the repository layout. Repository URLs provide
the installation/host pages not bundled with the sdist.

## Approval and beta limitations

Effectful A4 requires a trusted interactive host prompting on every choice and
action, showing **complete arguments**. The compact Codex approval row alone
is insufficient. Model-authored review text and MCP annotations are not human
consent. Alternate unrestricted shell/ADB tools granted by the host can bypass
Deputy's route. Never automatically retry an uncertain action or prepare a new
equivalent action to bypass a consumed intent.

Deployment is `TRUSTED_SINGLE_OPERATOR_V1`. The operator controls configuration,
the repository and local evidence; hostile local writers and multi-tenant use
are unsupported. Public results omit host paths, argv and raw environment/process
streams; protect richer local evidence. Legacy typed device operations may
return operational serial identifiers; A4 exposes registered aliases instead.

Seven Android observations were verified on an isolated API 34 emulator. Seven
mutating Worker operations remain synthetic-only; physical devices are not
qualified. Registered APK paths reject symlink/reparse escape, but APK bytes are
not pinned across approval/install. Keep them stable through the approved action.
See the [qualification matrix](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/workers/docs/A4_BETA_RELEASE_SCOPE.md).

The source is Apache-2.0 licensed. Workers has no inference cost; your MCP host
may have its own charges. This beta does not certify universal production safety
or complete the wider Phase 12 maturity gate. Android targets, artifacts,
Gradle task and verifier remain the existing Deputy Shell registrations.

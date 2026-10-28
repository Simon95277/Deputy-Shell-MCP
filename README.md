# Deputy Shell MCP

Deputy Shell MCP lets an AI coding assistant delegate work through small,
restricted tools. You configure the repository and permitted operations; the
assistant asks for an outcome. The server checks the request, runs the work
and returns a result.

Use it to inspect source, check repository state, parse test results or perform
a registered engineering task without giving that tool a general shell. It was
built for [Deputy Shell](https://deputyshell.com). Repository inspection can work
on other configured Git repositories, but registered Android targets, artifacts,
the Gradle task and verifier remain specific to the existing Deputy Shell setup.
This beta is not a general command runner.

**Status:** Focused A4 Beta candidate, Workers `1.2.0b1` with Agents `1.0.0`.
Publication is pending. These versions do not imply production certification or
completion of the wider v1.0 maturity gate.

## Two kinds of help

| Component | What it does | What runs |
| --- | --- | --- |
| DeputyWorkers | Executes fixed operations and returns measured facts, such as Git state, test-report totals or an artifact hash | Local deterministic Python code; no AI model |
| DeputyAgents | Investigates a question about selected source and returns an advisory report | An untrusted OpenCode AI child in a restricted Docker container |

Workers can report whether a configured repository is clean. Agents can explain
an architecture decision using source selected by the operator. Agents advice
can be wrong; it does not authorize a host change.

## Start here

1. Install Python 3.10 or newer and Git. Agents also needs Docker with Linux
   containers. Android operations need the operator's Android SDK/ADB setup;
   repository-only Workers calls do not.
2. Obtain the reviewed packages and `SHA256SUMS.txt`. After publication they
   will be attached to the [GitHub prerelease](https://github.com/Simon95277/Deputy-Shell-MCP/releases).
   There is no published beta asset to download yet.
3. Follow the [Windows or Linux installation guide](docs/INSTALLATION.md).
   Install Agents and Workers into **separate virtual environments**, configure
   the source repository and runtime directories, then run `--check`.
4. Register the installed stdio command in your MCP host using the
   [host setup instructions](docs/MCP_HOST_SETUP.md), then try the read-only
   repository-state example.

Hermes is not required. A compatible MCP host can launch the stdio servers.
Effectful A4 use has additional human-approval requirements described below.
Agents uses OpenCode from its pinned container; a host OpenCode installation
is not required.

## Default Workers versus Focused A4 Beta

Workers keeps its **legacy interface as the default**. A4 is an explicit
operator choice made before the server starts.

| Mode | Tools visible to the assistant | How work is selected |
| --- | --- | --- |
| Legacy Workers | `deputy_observe(request)`, `deputy_act(request)` | One typed request selects an existing registered operation |
| Focused A4 Beta | `deputy_prepare`, `deputy_choose`, `deputy_observe`, `deputy_act` | Preparation resolves a supported request into a short-lived, single-use intent |
| Agents | `deputy_recon(goal)` | One question about the operator-configured source |

Legacy Workers retains **22 registered operations**, split into 13 observations
and 9 execution or device-changing operations. Some accept bounded
repository-relative paths or device serials; they cannot select arbitrary host
roots, executables or command arguments. The [registry](workers/WORKER_CAPABILITIES.json)
and discovered schemas define the allowed inputs.

A4 offers **nine fixed semantic mappings backed by that same registry**. It
does not add 22 model-facing tools. To opt in, set these server environment values:

```text
DEPUTYWORKERS_PROTOCOL_MODE=focused-a4-beta
DEPUTYWORKERS_A4_PROFILE=multi_repo
```

Profiles are `android`, `multi_repo`, `python_docker` and `deputy_mcp_package`.
Each supports a fixed subset of the nine mappings; `python_docker` does not
grant general Docker or Python execution.

The current A4 protocol is `DA-A4-BETA-2`:

- `deputy_prepare(request)` interprets a request without running target work.
- `deputy_choose(prepare_id, choice_id, choice_review)` records one exact choice after the operator selects and approves it.
- `deputy_observe(intent_id)` returns a terminal observation result.
- `deputy_act(intent_id, approval_review)` runs an effectful intent after a separate operator approval.

The [A4 user guide](workers/docs/A4_USER_GUIDE.md) walks through observations,
choices, approved actions and unsupported requests. The server handles process
lifecycle and waiting; the assistant does not operate start/status/poll tools.

## What authority does Deputy limit?

The operator fixes the source repository, runtime roots, executables and
registered capabilities. An MCP caller cannot replace those settings by adding
a host path, shell command, executable or environment to a request.

A4 choices and actions require a **trusted interactive host** that asks for
operator approval on every `deputy_choose` and `deputy_act` call and shows the
**complete arguments**. Inspect operation, target, artifact or parameters,
effect and expiry. The compact Codex approval row alone is insufficient.
Model-authored approval text and MCP annotations are not human consent.

Deputy cannot take away authority your host separately grants. If the assistant
also has unrestricted shell, filesystem or ADB access to the same target, it
can bypass the Deputy route. Restrict those alternatives when you need this
boundary. See [host integration](workers/docs/A4_BETA_HOST_INTEGRATION.md).

## Costs and provider privacy

The project is [Apache-2.0 licensed](LICENSE), with no project software license
fee. Workers runs locally and makes no AI inference request. Your MCP host or
supervisor model may have separate subscription or usage charges.

Agents contacts an external provider. The qualified server configuration is
provider `opencode`, model `muse-spark-1.3-contributor-free`. The qualified route
required no injected credential; its model name is not a promise of permanent
free service or availability. The server does not fall back to another route.

Before launching the child, Agents selects source using a bounded policy,
copies it, scans high-confidence secret patterns and checks that included bytes
stayed coherent during capture. The child receives a read-only copy of that
qualified snapshot, never the unrestricted live repository or Docker socket.
Its allowed egress is through a provider-only proxy.

**Selected source may be sent to the provider, and model output may quote it.**
The local scan cannot detect every secret or personal fact and does not make
source confidential from the provider. Review the policy before using Agents
on sensitive code. See [security](SECURITY.md) and the [threat model](docs/THREAT_MODEL.md).

## Supported scope and limitations

Deployment supports one trusted operator controlling the machine, configuration
and one repository. Hostile local writers, hostile shared users and multi-tenant
deployments are unsupported.

- Source suites and package checks passed on Windows CPython 3.10 and Ubuntu/WSL
  CPython 3.12 with MCP 2.2.0. Metadata declares Python 3.10+; other environments
  are not all individually qualified. macOS has runtime-path support but was
  not qualified for this beta.
- Seven Android observations were verified on an isolated API 34 emulator.
  Seven mutating Worker operations remain **synthetic-only**. No physical
  Android device has been certified. See the [operation matrix](workers/docs/A4_BETA_RELEASE_SCOPE.md).
- Registered APK paths reject symlink/reparse escape. **APK bytes are not pinned
  across approval and installation**; the trusted operator must keep them stable.
- Expired, replayed and prior-session A4 intents are rejected. An uncertain
  action must not be automatically retried or replaced with a fresh equivalent request.
- Independent review and bounded scans do not establish universal production
  safety or perfect leakage prevention.

## Further reading

- [Installation and recovery](docs/INSTALLATION.md)
- [MCP host setup and first use](docs/MCP_HOST_SETUP.md)
- [A4 user guide](workers/docs/A4_USER_GUIDE.md) and [technical contract](workers/docs/A4_BETA_CONTRACT.md)
- [Agents architecture](agents/docs/ARCHITECTURE.md) and [Workers architecture](workers/docs/ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md), [CI](docs/CI.md), [changelog](CHANGELOG.md) and [roadmap](docs/ROADMAP.md)
- [Historical efficiency benchmark and its limits](benchmarks/efficiency/README.md)

Use GitHub Private Vulnerability Reporting for security issues. Do not post
credentials, private source, device data or local runtime evidence in public issues.

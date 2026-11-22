# DeputyAgents MCP

DeputyAgents lets an MCP coding assistant ask one question about selected
source. The server builds and qualifies a snapshot, mounts a per-job copy
read-only in a restricted Docker container, runs an OpenCode child and returns
an advisory report. Published Agents `1.0.0` exposes `deputy_recon(goal)` with
its original fixed model contract. This unreleased source adds
`deputy_models()`, `deputy_select_model(model_id)` and `deputy_recon(goal)`.
The caller chooses a currently zero-priced, tool-capable chat model once; the
server stores that model ID under its runtime root and reuses it. If the live
catalog no longer accepts it, reconnaissance stops before launch and asks for
a replacement selection. Compatibility with the pinned OpenCode image is not
yet qualified. The source root, executable, provider, endpoint and lifecycle
remain server-owned.

Agents `1.0.0` is the companion package in the
[published Focused A4 Beta](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1).
Workers is a separate deterministic subsystem and must use a separate Python
environment: both distributions provide `server`, `config` and `preflight`
modules. The GitHub prerelease is available; no production certification is claimed.

## Install and configure

Use Python 3.10+, Git, Docker running Linux containers and an operator-controlled
Git repository. OpenCode runs from the pinned image; a host OpenCode installation
and Hermes are not required. Download and hash-check the wheel from the release,
then install it using the Agents
environment's Python, with MCP 2.2.0 for the qualified route:

```text
<agents-python> -m pip install mcp==2.2.0 ./deputy_shell_agents_mcp-1.0.0-py3-none-any.whl
<agents-python> -m pip check
```

`<agents-python>` means the actual interpreter in your separate Agents virtual
environment; it is not a literal command. The
[Windows/Linux installation guide](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/docs/INSTALLATION.md)
has complete venv, checksum, sdist, pinned-image and configuration steps.

Set server-owned `DEPUTYAGENTS_DEPUTY_SHELL_ROOT`, `DEPUTYAGENTS_RUNTIME_ROOT`
and, where needed, an absolute `DEPUTYAGENTS_DOCKER_EXE`. Create a writable
runtime directory outside installed code. Keep diagnostics and control plane
off. Then run the installed `deputy-agents-mcp --check` and register its absolute
path as a stdio server with no arguments. Configure the same environment in the
host; a GUI host may not inherit terminal exports. Preflight does not prove
live Docker, image or provider readiness.

The runtime defaults to `%LOCALAPPDATA%/DeputyShellAgentsMCP` on Windows,
`$XDG_STATE_HOME/DeputyShellAgentsMCP` or `~/.local/state/DeputyShellAgentsMCP`
on Linux, and the platform application-support location on macOS. Windows and
Ubuntu/WSL were qualified; macOS runtime-path support is not beta qualification.

The built-in source policy is tailored to Deputy Shell. For another layout,
the operator can provide bounded `deputy.agents.source-policy.v1` JSON through
`DEPUTYAGENTS_SOURCE_POLICY_JSON`; no caller can choose a policy path or modify
it through a goal. The installation guide includes a complete example.

## Use the model picker

The default MCP surface exposes three tools. Call `deputy_models()` and choose
a row with `recon_compatible: true`. Configure the exact ID once with
`deputy_select_model`; later reconnaissance calls need only the goal:

```text
deputy_select_model(model_id="<model_id copied from deputy_models>")
deputy_recon(goal="Summarize how worker-loss recovery is handled.")
```

The server checks the selected model against the live catalog before saving,
before work begins, and again before launching the child. A model listed as
free can later become unavailable or paid; in that case the request is blocked
without a fallback and returns fresh choices for reconfiguration.
The catalog also marks non-chat entries, such as decision-only models, as not
compatible with reconnaissance. `runner_image_compatibility` remains
`NOT_VERIFIED` until the pinned image can be checked.

## Costs, privacy and limits

Source code is Apache-2.0 licensed. Supervisor/model-host charges are separate.
The `deputy_models()` tool reads OpenCode's public model catalog and returns
models with zero listed text input, output and cache prices. The
`recon_compatible` flag means the live catalog advertises a chat model with
tool support; it does not prove the pinned runner image recognizes it. The
server checks the live catalog before preparation and again immediately before
launching OpenCode. It fails closed if the model is no longer listed at zero
price or no longer supports the required chat/tool interface. It has no
paid-model fallback. OpenCode can change prices or availability at any time;
the catalog check is not a permanent free-service guarantee.

OpenCode's free-model privacy terms differ by provider. Review those terms
before submitting source. Source and model output may be exposed to the selected
provider as described below.

Selected source may be sent to the provider and quoted in model output. A local
high-confidence content scan and `DA-BYTE-COHERENCE-1` byte validation precede
provider setup; they are not comprehensive PII detection or a confidentiality
guarantee. The child does not receive the live repository, host credentials or
Docker socket. Its configured egress is provider-only.

Deployment supports one trusted operator and one configured repository.
Hostile local writers and multi-tenant use are unsupported. Treat AI findings
as untrusted advice. See the repository
[architecture](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/agents/docs/ARCHITECTURE.md),
[security policy](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/SECURITY.md)
and [host setup](https://github.com/Simon95277/Deputy-Shell-MCP/blob/main/docs/MCP_HOST_SETUP.md).

# Connect an MCP host and make a first request

The [published Focused A4 Beta](https://github.com/Simon95277/Deputy-Shell-MCP/releases/tag/workers-v1.2.0b1)
contains Workers `1.2.0b1` and Agents `1.0.0`. Complete
[installation](INSTALLATION.md) first, including environment variables
and successful `--check` output. The host starts a local process and speaks MCP
over stdin/stdout; Deputy does not provide a public HTTP service or require a
browser login of its own. Authentication for a supervisor model belongs to
your chosen MCP host.

## Register Workers

Use your host's **stdio server** settings:

| Setting | Value |
| --- | --- |
| Command | Absolute installed `deputy-workers-mcp.exe` on Windows or `deputy-workers-mcp` on Linux |
| Arguments | Empty list |
| Environment | The `DEPUTYWORKERS_*` values from installation, including its own Python executable |

If your host uses `mcpServers` JSON, this is the shape for a Windows legacy
registration. **Replace every example path** with the actual absolute paths
from installation; JSON does not expand PowerShell variables or `~`:

```json
{"mcpServers":{"deputy_workers":{"command":"C:/DeputyMCP/workers-venv/Scripts/deputy-workers-mcp.exe","args":[],"env":{"DEPUTYWORKERS_DEPUTY_SHELL_ROOT":"C:/Projects/your-repository","DEPUTYWORKERS_RUNTIME_ROOT":"C:/DeputyMCP/workers-state","DEPUTYWORKERS_EVIDENCE_ROOT":"C:/DeputyMCP/workers-state/evidence","DEPUTYWORKERS_PYTHON_EXE":"C:/DeputyMCP/workers-venv/Scripts/python.exe","DEPUTYWORKERS_PROTOCOL_MODE":"legacy","DEPUTYWORKERS_ENABLE_CONTROL_PLANE":"0"}}}}
```

On Linux, use the installed `workers-venv/bin/deputy-workers-mcp` command,
`workers-venv/bin/python` interpreter, and your Linux source/state paths. Other
hosts use a different configuration file or UI; preserve the command, empty
arguments and explicit environment. Do not pass repository paths as tool args.
GUI hosts often do not inherit values exported in a separate terminal.

Only one server process may own a given A4 runtime root. Give independent test
registrations separate roots. Restart/reconnect after changing server settings.

## First use in default legacy mode

Discovery should show exactly `deputy_observe` and `deputy_act`. Ask your
assistant to call `deputy_observe` with these MCP arguments:

```json
{"request":{"operation":"CAPTURE_REPO_STATE"}}
```

This reads the configured repository's HEAD, branch and dirty state and includes
the service's diff-check evidence. No Android device is needed. Inspect the
returned status and facts; a failing check is not proof the server is broken.
No normal start/status/result/cancel call is needed.

## Switch to A4

Before effectful use, complete the approval checklist below. In the server
environment replace the mode with `focused-a4-beta` and add
`DEPUTYWORKERS_A4_PROFILE=multi_repo`, then start a fresh connection. A4 replaces
the legacy input schemas; do not send the legacy request object to A4 observe.

Discovery should now show exactly:

```text
deputy_prepare
deputy_choose
deputy_observe
deputy_act
```

First ask the assistant to call `deputy_prepare`:

```json
{"request":"Capture repository status"}
```

If the response is `CLEAR` and `intent.effect` is `OBSERVE`, call
`deputy_observe` once with the exact returned `intent_id`. The
[A4 user guide](../workers/docs/A4_USER_GUIDE.md) explains the other outcomes.
It also lists profile-specific tasks; a profile name is not permission to run
arbitrary Python, Docker, package or device commands.

## Approval checklist for effectful A4

Use a trusted interactive host configured to:

1. Prompt the operator for **every** `deputy_choose` and `deputy_act` call.
2. Show **all arguments** before approval, including the full server-issued
   `choice_review` or `approval_review`.
3. Let the operator reject without dispatching the tool.
4. Obtain an exact user choice before submitting a choice, then ask separately
   before executing the resulting action.

Some hosts also prompt for prepare/observe because those calls persist local
intent/receipt state. Do not use blanket automatic approval to work around this.
MCP annotations are hints; the host enforces its approval policy. Review text
is copyable by the model and is not itself proof of human consent.

The qualified interactive example used Codex CLI 0.163.0. Its compact approval
row truncates long arguments; inspect the complete preceding `Calling` arguments.
The compact row alone is insufficient. Hosts that hide full arguments or
auto-approve sensitive calls are unqualified for effectful A4. See the
[approval contract](../workers/docs/A4_BETA_GATE1B_APPROVAL_ADDENDUM.md).

Route covered tasks through preparation rather than separate shell/Git/ADB tools.
The [routing guidance](../workers/docs/A4_BETA_HOST_INTEGRATION.md) can help the
assistant choose A4, but instructions cannot revoke other host authority.

## Add Agents separately

Register the absolute command from the **Agents environment** as another stdio
server, with no arguments and the configured `DEPUTYAGENTS_*` environment.
Keep diagnostics and control plane set to `0`. Discovery should show only
`deputy_recon`.

After reviewing the source policy and provider-exposure limits, an example goal is:

```json
{"goal":"Explain the main architecture visible in this qualified source snapshot and cite the files you use."}
```

Calling recon launches contained inference and may send selected source to the
external provider. This is not part of the no-inference Workers quickstart.
The [Agents guide](../agents/README.md) explains costs and prerequisites.

## If discovery is confusing

Check server stderr, its configured mode/profile and the first connection's
actual MCP `tools/list` result. The legacy/A4 inventories are mutually exclusive.
Do not enable owner lifecycle or diagnostic flags to repair normal discovery.

In one tested Codex CLI 0.163.0 setup, `/mcp` started a duplicate server process
with the same runtime root. The protective instance lock rejected the duplicate,
so the UI showed zero tools while the original connection had discovered and
called four. Keep the lock; inspect wire discovery and an actual call on the
original connection. This is a setup-specific diagnostic limitation, not a claim
that every zero-tool display has that cause.

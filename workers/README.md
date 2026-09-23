# Deputy Workers MCP

Install the Workers runtime into a dedicated Python 3.10+ virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .\workers
.venv\Scripts\deputy-workers-mcp --check
```

The installed command is independent of the source checkout and current working
directory. Configure server-owned `DEPUTYWORKERS_*` environment variables for
the Deputy Shell checkout, trusted Python, Android SDK/ADB, and runtime/evidence
roots. The default runtime root is a per-user application-state directory
outside the installed package. `--check` is read-only and does not install
tools, pull images, or perform device operations.

The supported deployment trust model is `TRUSTED_SINGLE_OPERATOR_V1`: the
machine owner controls Workers configuration and the single bound repository.
This is not a hostile multi-user or multi-tenant service. MCP results omit
host roots, executable paths, argv, process IDs, environment values, and raw
subprocess stdout/stderr; richer bounded operation evidence remains in the
owner-controlled local runtime. Connected Android device serials are retained
only where needed to identify a device for a typed ADB operation; avoid sharing
those results outside the trusted operator context.

The frozen V1.1 capability registry contains exactly 22 operations. Capability
changes require architecture review. The ordinary CI suite uses synthetic
fixtures and does not execute destructive ADB operations.

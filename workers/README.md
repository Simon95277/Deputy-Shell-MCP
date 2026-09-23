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

The frozen V1.1 capability registry contains exactly 22 operations. Capability
changes require architecture review. The ordinary CI suite uses synthetic
fixtures and does not execute destructive ADB operations.

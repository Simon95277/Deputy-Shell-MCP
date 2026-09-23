param(
    [ValidateSet("Agents", "Workers")]
    [string]$Component = "Agents",
    [switch]$ConfirmReplace
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$componentRoot = Join-Path $repo $Component.ToLowerInvariant()
$venvRoot = Join-Path $env:LOCALAPPDATA ("DeputyShellMCP\venv-" + $Component.ToLowerInvariant())
$python = Join-Path $venvRoot "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $componentRoot -PathType Container)) {
    throw "Component source is missing: $Component"
}
if ((Test-Path -LiteralPath $venvRoot) -and -not $ConfirmReplace) {
    throw "Refusing to overwrite existing venv. Re-run with -ConfirmReplace: $venvRoot"
}
if (-not (Test-Path -LiteralPath $venvRoot)) {
    & python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed" }
$constraint = Join-Path $repo "constraints\qualification-windows-py310.txt"
if (-not (Test-Path -LiteralPath $constraint)) {
    throw "Qualification constraint set is missing: $constraint"
}
& $python -m pip install --constraint $constraint $componentRoot
if ($LASTEXITCODE -ne 0) { throw "package installation failed" }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw "dependency check failed" }

$command = if ($Component -eq "Agents") { "deputy-agents-mcp" } else { "deputy-workers-mcp" }
Write-Host "Installed $Component as $command in $venvRoot"
Write-Host "Run the command with --check after configuring the server-owned environment variables."

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
AGENTS_TOOLS = {
    "deputy_recon",
    "deputy_recon_start",
    "deputy_recon_status",
    "deputy_recon_cancel",
}
WORKERS_TOOLS = {
    "deputy_worker_status",
    "deputy_worker_start",
    "deputy_worker_run_status",
    "deputy_worker_result",
    "deputy_worker_cancel",
    "deputy_worker_smoke",
    "deputy_worker_exact_payload_smoke",
}
EXPECTED_TESTS = {"agents": 143, "workers": 334}
FORBIDDEN_ARCHIVE_PARTS = {
    ".git", ".venv", "evidence", "runtime", "runs", "logs", "snapshots",
    "local-snapshots", "bridge-lab", "deputy-shell-source", "android-sdk",
    "credentials", "tokens", "auth", "sessions", "qualification",
}
FORBIDDEN_PUBLIC_DIRS = FORBIDDEN_ARCHIVE_PARTS | {"dist", "build"}
FORBIDDEN_PUBLIC_FILES = {
    ".env", ".env.local", ".env.production", ".pypirc", ".npmrc",
    "credentials", "credentials.json", "secrets.json", "token", "token.txt",
    "id_rsa", "id_ed25519", "known_hosts", "authorized_keys",
}
FORBIDDEN_WORKER_OPERATIONS = {
    "SHELL", "ADB_SHELL", "RUN_SHELL", "EXEC", "EXECUTE", "RUN_COMMAND",
    "GENERIC_ADB", "ADB_RAW", "ARBITRARY_PROCESS",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"),
)
PERSONAL_PATH = re.compile(r"(?i)\b[A-Z]:" + r"\\Users\\[^\\\s]+\\")
PERSONAL_PATH_SLASH = re.compile(r"(?i)\b[A-Z]:" + "/" + "Users/[^/\\s]+/")
POSIX_HOME_PATH = re.compile(r"(?<![A-Za-z0-9_])/" + "(?:Users|home)/[^/\\s]+/")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
ALLOWED_SYNTHETIC_EMAILS = {"test@example.invalid"}
MAX_PUBLIC_FILE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5000
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024


def fail(message: str) -> None:
    raise SystemExit(message)


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
        capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )


def prepare_fixture(args: argparse.Namespace) -> None:
    repo = Path(args.root).resolve()
    sdk = Path(args.sdk).resolve()
    docker_stub = Path(args.docker_stub).resolve()
    for path in (repo, sdk):
        if path.exists() and any(path.iterdir()):
            fail(f"fixture destination must be empty: {path.name}")
        path.mkdir(parents=True, exist_ok=True)

    (repo / "app" / "build").mkdir(parents=True)
    (repo / "app" / "build.gradle.kts").write_text(
        "// Synthetic CI fixture; no Android project or device is used.\n",
        encoding="utf-8",
    )
    (repo / "gradlew.bat").write_text("@echo off\r\nexit /b 99\r\n", encoding="ascii")
    verifier = repo / "tools" / "android" / "verify-runtime-integrity-manifest.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("print('synthetic verifier fixture')\n", encoding="utf-8")

    git_env = os.environ.copy()
    git_env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    for command in (
        ["git", "-C", str(repo), "init", "--quiet", "--initial-branch=ci-fixture"],
        ["git", "-C", str(repo), "add", "app/build.gradle.kts", "gradlew.bat", "tools/android/verify-runtime-integrity-manifest.py"],
        ["git", "-C", str(repo), "-c", "user.name=CI Fixture", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "synthetic CI fixture"],
    ):
        result = run(command, env=git_env, capture=True)
        if result.returncode:
            fail("synthetic Git fixture initialization failed")

    (sdk / "platform-tools").mkdir(parents=True)
    # Both spellings are inert preflight fixtures: production's SDK contract
    # checks adb.exe, while POSIX config also names adb. Tests never execute them.
    for adb_name in ("adb.exe", "adb"):
        (sdk / "platform-tools" / adb_name).write_bytes(b"synthetic placeholder; never executable")
    for name in ("platforms", "build-tools", "cmdline-tools"):
        (sdk / name).mkdir()
    docker_stub.parent.mkdir(parents=True, exist_ok=True)
    docker_stub.write_bytes(b"synthetic preflight placeholder; never executed")
    print(json.dumps({"status": "PASS", "fixture": "synthetic-only", "git_repo": True,
                      "android_device": False, "docker_engine": False}, sort_keys=True))


def test_suite(args: argparse.Namespace) -> None:
    component = args.component
    if component not in EXPECTED_TESTS:
        fail("unknown test component")
    cwd = ROOT / component
    result = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=cwd, capture=True)
    combined = (result.stdout or "") + (result.stderr or "")
    print(combined, end="")
    match = re.search(r"Ran\s+(\d+)\s+tests?", combined)
    if result.returncode or not match or int(match.group(1)) != EXPECTED_TESTS[component]:
        fail(f"{component} suite failed or test count changed from {EXPECTED_TESTS[component]}")


def contract_check() -> None:
    env = os.environ.copy()
    env.pop("DEPUTYAGENTS_ENABLE_DIAGNOSTICS", None)
    probe = (
        "import asyncio,json,server; "
        "print(json.dumps(sorted(t.name for t in asyncio.run(server.mcp.list_tools()))))"
    )
    result = run([sys.executable, "-c", probe], cwd=ROOT / "agents", env=env, capture=True)
    if result.returncode:
        fail("Agents MCP discovery failed")
    try:
        tools = set(json.loads(result.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        fail("Agents MCP discovery returned invalid JSON")
    if tools != AGENTS_TOOLS:
        fail(f"Agents production tool set mismatch: {sorted(tools)}")
    workers_probe = (
        "import asyncio,json,server; "
        "print(json.dumps(sorted(t.name for t in asyncio.run(server.mcp.list_tools()))))"
    )
    workers_result = run([sys.executable, "-c", workers_probe], cwd=ROOT / "workers", capture=True)
    if workers_result.returncode:
        fail("Workers MCP discovery failed")
    try:
        worker_tools = set(json.loads(workers_result.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        fail("Workers MCP discovery returned invalid JSON")
    if worker_tools != WORKERS_TOOLS:
        fail(f"Workers public tool set mismatch: {sorted(worker_tools)}")

    sys.path.insert(0, str(ROOT / "agents"))
    try:
        from bridge.provider_contract import MODEL_ID, PROVIDER_ID, RUNTIME_CONTRACT_VERSION, SELECTION_SOURCE, evidence
        import snapshot
        # Both standalone projects intentionally own top-level config modules.
        # Import each under its own component path, as the installed runtimes do.
        sys.modules.pop("config", None)
        sys.path.insert(0, str(ROOT / "workers"))
        from worker_v1.capabilities import load_registry
        registry = load_registry()

        checks = {
            "runtime": RUNTIME_CONTRACT_VERSION == "DA-PACKAGING-1" == snapshot.RUNTIME_CONTRACT_VERSION,
            "coherence": snapshot.COHERENCE_VERSION == "DA-BYTE-COHERENCE-1",
            "snapshot_policy": snapshot.POLICY_VERSION == "DA-FAST-2-positive-allowlist-v1",
            "provider": PROVIDER_ID == "opencode",
            "model": MODEL_ID == "muse-spark-1.3-contributor-free",
            "selection": SELECTION_SOURCE == "SERVER_OWNED",
            "runtime_identity_honest": evidence()["runtime_identity_observable"] is False and evidence()["verified"] is False,
            "agents_tools": tools == AGENTS_TOOLS,
            "workers_tools": worker_tools == WORKERS_TOOLS,
            "workers_capabilities": len(registry) == 22 and all(item.get("enabled") is True for item in registry.values()),
            "workers_no_generic_authority": not (set(registry) & FORBIDDEN_WORKER_OPERATIONS),
            "mcp_qualification": importlib.metadata.version("mcp") == "2.2.0",
        }
    except Exception as exc:
        fail(f"contract imports failed: {type(exc).__name__}")
    if not all(checks.values()):
        fail("contract consistency failed: " + ", ".join(k for k, ok in checks.items() if not ok))

    docs = {
        ROOT / "README.md": ("opencode", "muse-spark-1.3-contributor-free", "deputy_recon_cancel"),
        ROOT / "agents" / "docs" / "ARCHITECTURE.md": (
            "DA-PACKAGING-1", "DA-BYTE-COHERENCE-1", "DA-FAST-2-positive-allowlist-v1",
        ),
        ROOT / "workers" / "README.md": ("22", "deputy-workers-mcp"),
    }
    for path, values in docs.items():
        text = path.read_text(encoding="utf-8")
        if not all(value in text for value in values):
            fail(f"high-value documentation contract mismatch: {path.name}")
    print(json.dumps({"status": "PASS", "agents_tools": sorted(tools), "workers_tools": sorted(worker_tools), "diagnostics_default": "DISABLED",
                      "runtime": RUNTIME_CONTRACT_VERSION, "coherence": snapshot.COHERENCE_VERSION,
                      "snapshot_policy": snapshot.POLICY_VERSION, "provider": PROVIDER_ID, "model": MODEL_ID,
                      "selection_source": SELECTION_SOURCE, "runtime_identity_observable": False,
                      "workers_capabilities": 22, "mcp": "2.2.0"}, sort_keys=True))


def hygiene_check(root: Path) -> list[str]:
    findings: list[str] = []
    listed = run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture=True)
    if listed.returncode:
        fail("public hygiene requires a Git worktree")
    paths = [root / item for item in listed.stdout.split("\x00") if item]
    for path in paths:
        rel = path.relative_to(root)
        parts = [part.lower() for part in rel.parts]
        if set(parts[:-1]) & FORBIDDEN_PUBLIC_DIRS:
            findings.append(f"forbidden public path: {rel.as_posix()}")
        lower = path.name.lower()
        env_file = lower.startswith(".env") and lower not in {".env.example", ".env.template"}
        credential_file = lower.startswith(("credentials.", "secrets.", "token."))
        if (lower in FORBIDDEN_PUBLIC_FILES or env_file or credential_file
                or lower.endswith((".pyc", ".pyo", ".pem", ".p12", ".pfx", ".jks", ".keystore"))):
            findings.append(f"forbidden public filename: {rel.as_posix()}")
        if lower.endswith((".patch", ".diff", ".pem", ".p12", ".pfx", ".jks", ".keystore", ".log", ".tmp", ".bak")):
            findings.append(f"forbidden file type: {rel.as_posix()}")
        if path.is_symlink():
            findings.append(f"symlink in public tree: {rel.as_posix()}")
            continue
        try:
            if path.stat().st_size > MAX_PUBLIC_FILE_BYTES:
                findings.append(f"public file exceeds bounded scan size: {rel.as_posix()}")
                continue
            data = path.read_bytes()
        except OSError:
            findings.append(f"unreadable public file: {rel.as_posix()}")
            continue
        text = data.decode("utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"secret pattern: {rel.as_posix()}")
                break
        if PERSONAL_PATH.search(text) or PERSONAL_PATH_SLASH.search(text) or POSIX_HOME_PATH.search(text):
            findings.append(f"personal absolute path: {rel.as_posix()}")
        emails = {m.group(0).lower() for m in EMAIL.finditer(text)} - ALLOWED_SYNTHETIC_EMAILS
        if emails:
            findings.append(f"non-synthetic email address: {rel.as_posix()}")
    return sorted(set(findings))


def public_hygiene(args: argparse.Namespace) -> None:
    findings = hygiene_check(Path(args.root).resolve())
    if findings:
        fail("PUBLIC TREE / SECRET HYGIENE failed:\n" + "\n".join(findings))
    print(json.dumps({"status": "PASS", "gate": "PUBLIC TREE / SECRET HYGIENE",
                      "scope": "tracked-source-tree content and paths; bounded patterns, not full PII detection"}, sort_keys=True))


def archive_names(path: Path) -> list[str]:
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        fail(f"package archive exceeds bounded audit limits: {path.name}")
    if path.suffix.lower() == ".whl" or path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS or sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
                fail(f"package archive exceeds bounded audit limits: {path.name}")
            if any(stat.S_ISLNK(info.external_attr >> 16) for info in infos):
                fail(f"package archive contains a symlink: {path.name}")
            return archive.namelist()
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS or sum(member.size for member in members if member.isfile()) > MAX_ARCHIVE_BYTES:
                fail(f"package archive exceeds bounded audit limits: {path.name}")
            if any(not (member.isfile() or member.isdir()) for member in members):
                fail(f"package archive contains a non-regular member: {path.name}")
            return [member.name for member in members]
    fail(f"unsupported package archive: {path.name}")
    return []


def audit_archive(path: Path) -> None:
    for name in archive_names(path):
        normalized = name.replace("\\", "/")
        archive_path = PurePosixPath(normalized)
        if (archive_path.is_absolute() or ".." in archive_path.parts
                or re.match(r"(?i)^[A-Z]:/", normalized)):
            fail(f"unsafe package member path in {path.name}")
        if (PERSONAL_PATH.search(name) or PERSONAL_PATH_SLASH.search(name)
                or POSIX_HOME_PATH.search(name)):
            fail(f"personal path in package member name: {path.name}")
        parts = {part.lower() for part in archive_path.parts}
        forbidden = parts & FORBIDDEN_ARCHIVE_PARTS
        if forbidden or any(part.endswith((".patch", ".diff", ".log", ".tmp", ".pyc")) for part in parts):
            fail(f"forbidden package member in {path.name}")
    if path.suffix.lower() == ".whl" or path.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(path)
        contents = ((name, archive.read(name)) for name in archive.namelist() if not name.endswith("/"))
    else:
        archive = tarfile.open(path, "r:gz")
        contents = ((member.name, archive.extractfile(member).read()) for member in archive.getmembers()
                    if member.isfile() and archive.extractfile(member) is not None)
    for name, data in contents:
        text = data.decode("utf-8", errors="replace")
        if PERSONAL_PATH.search(text) or PERSONAL_PATH_SLASH.search(text) or POSIX_HOME_PATH.search(text):
            fail(f"personal path in package member: {Path(name).name}")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            fail(f"secret pattern in package member: {Path(name).name}")


def audit_artifacts(args: argparse.Namespace) -> None:
    directory = Path(args.directory).resolve()
    archives = sorted(p for p in directory.iterdir() if p.is_file() and p.name.endswith((".whl", ".tar.gz")))
    if len(archives) != 4:
        fail(f"expected four package archives, found {len(archives)}")
    for path in archives:
        audit_archive(path)
    print(json.dumps({"status": "PASS", "artifacts": [p.name for p in archives], "forbidden_members": 0}, sort_keys=True))


def check_release_ref(args: argparse.Namespace) -> None:
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        fail("release qualification requires refs/heads/main")
    current = run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture=True)
    remote = run(["git", "rev-parse", "origin/main"], cwd=ROOT, capture=True)
    expected = os.environ.get("GITHUB_SHA")
    if current.returncode or remote.returncode or current.stdout.strip() != expected or remote.stdout.strip() != expected:
        fail("release qualification commit is not the current main HEAD")
    print(json.dumps({"status": "PASS", "commit": expected, "ref": "main"}, sort_keys=True))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_project(component: str) -> tuple[str, str]:
    text = (ROOT / component / "pyproject.toml").read_text(encoding="utf-8")
    name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', text)
    version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not name or not version:
        fail(f"package metadata missing for {component}")
    return name.group(1), version.group(1)


def installed_smoke(component: str, wheel: Path, sdist_wheel: Path, base: Path,
                    fixture: Path, sdk: Path, docker_stub: Path, build_constraints: Path,
                    qualification_constraints: Path) -> None:
    name = "agents" if component == "agents" else "workers"
    scripts = "Scripts" if os.name == "nt" else "bin"
    commands = {"agents": "deputy-agents-mcp", "workers": "deputy-workers-mcp"}
    for label, artifact in (("wheel", wheel), ("sdist-wheel", sdist_wheel)):
        venv_root = base / f"{component}-{label}-venv"
        venv.EnvBuilder(with_pip=True).create(venv_root)
        python = venv_root / scripts / ("python.exe" if os.name == "nt" else "python")
        pip_install = run([str(python), "-m", "pip", "install", "--constraint", str(qualification_constraints), str(artifact)], capture=True)
        if pip_install.returncode:
            fail(f"fresh {component} {label} install failed")
        pip_check = run([str(python), "-m", "pip", "check"], capture=True)
        if pip_check.returncode:
            fail(f"fresh {component} {label} pip check failed")

        env = os.environ.copy()
        env.pop("DEPUTYAGENTS_ENABLE_DIAGNOSTICS", None)
        env.update({
            "DEPUTYAGENTS_RUNTIME_ROOT": str(base / f"{component}-{label}-agents-runtime"),
            "DEPUTYAGENTS_DEPUTY_SHELL_ROOT": str(fixture),
            "DEPUTYAGENTS_DOCKER_EXE": str(docker_stub),
            "DEPUTYWORKERS_RUNTIME_ROOT": str(base / f"{component}-{label}-workers-runtime"),
            "DEPUTYWORKERS_DEPUTY_SHELL_ROOT": str(fixture),
            "DEPUTYWORKERS_ANDROID_SDK_ROOT": str(sdk),
            "DEPUTYWORKERS_PYTHON_EXE": str(python),
        })
        entry = venv_root / scripts / (commands[component] + (".exe" if os.name == "nt" else ""))
        if not entry.is_file():
            fail(f"installed {component} console entrypoint missing")
        check = run([str(entry), "--check"], cwd=base, env=env, capture=True)
        if check.returncode:
            fail(f"installed {component} {label} preflight failed")
        try:
            payload = json.loads(check.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            fail(f"installed {component} preflight returned invalid JSON")
        if payload.get("status") != "PASS":
            fail(f"installed {component} preflight did not pass")

        if component == "agents":
            code = ("import asyncio,json,server; "
                    "print(json.dumps({'origin':server.__file__,'tools':sorted(t.name for t in asyncio.run(server.mcp.list_tools()))}))")
        else:
            code = ("import asyncio,json,server; from worker_v1.capabilities import load_registry; "
                    "print(json.dumps({'origin':server.__file__,'capabilities':len(load_registry()),'tools':sorted(t.name for t in asyncio.run(server.mcp.list_tools()))}))")
        smoke = run([str(python), "-I", "-c", code], cwd=base, env=env, capture=True)
        if smoke.returncode:
            fail(f"installed {component} {label} import/discovery failed")
        try:
            info = json.loads(smoke.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            fail(f"installed {component} import smoke returned invalid JSON")
        origin = Path(info["origin"]).resolve()
        if venv_root.resolve() not in origin.parents:
            fail(f"installed {component} imported outside its fresh environment")
        if component == "agents" and set(info["tools"]) != AGENTS_TOOLS:
            fail("installed Agents tool discovery mismatch")
        if component == "workers" and (info["capabilities"] != 22 or set(info.get("tools", [])) != WORKERS_TOOLS):
            fail("installed Workers registry or tool discovery mismatch")


def release_bundle(args: argparse.Namespace) -> None:
    out = Path(args.output).resolve()
    temp = Path(args.temp).resolve()
    out.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        fail("release output directory must start empty")
    build_constraints = ROOT / "constraints" / "build-tools-windows-py310.txt"
    qualification_constraints = ROOT / "constraints" / "qualification-windows-py310.txt"
    build_root = temp / "built"
    rebuild_root = temp / "sdist-rebuilt"
    smoke_root = temp / "smoke"
    for path in (build_root, rebuild_root, smoke_root):
        path.mkdir()

    fixture = temp / "fixture-repo"
    sdk = temp / "fixture-sdk"
    docker_stub = temp / "fixture-bin" / ("docker-stub.exe" if os.name == "nt" else "docker-stub")
    prepare_fixture(argparse.Namespace(root=str(fixture), sdk=str(sdk), docker_stub=str(docker_stub)))

    built: dict[str, dict[str, Path]] = {}
    for component in ("agents", "workers"):
        result = run([sys.executable, "-m", "build", "--dependency-constraints-txt", str(build_constraints),
                      "--outdir", str(build_root), str(ROOT / component)], cwd=ROOT, capture=True)
        if result.returncode:
            print(result.stdout or "", end="")
            print(result.stderr or "", end="", file=sys.stderr)
            fail(f"{component} wheel/sdist build failed")
        package_name, version = parse_project(component)
        normalized = package_name.replace("-", "_").lower()
        wheel = next((p for p in build_root.glob("*.whl") if p.name.lower().startswith(normalized + "-" + version.lower())), None)
        sdist = next((p for p in build_root.glob("*.tar.gz") if p.name.lower().startswith(normalized + "-" + version.lower())), None)
        if wheel is None or sdist is None:
            fail(f"{component} build did not produce both wheel and sdist")
        built[component] = {"wheel": wheel, "sdist": sdist}
        rebuilt = rebuild_root / component
        rebuilt.mkdir()
        result = run([sys.executable, "-m", "build", "--wheel", "--dependency-constraints-txt", str(build_constraints),
                      "--outdir", str(rebuilt), str(sdist)], cwd=temp, capture=True)
        if result.returncode:
            print(result.stdout or "", end="")
            print(result.stderr or "", end="", file=sys.stderr)
            fail(f"{component} sdist rebuild failed")
        rebuilt_wheels = list(rebuilt.glob("*.whl"))
        if len(rebuilt_wheels) != 1:
            fail(f"{component} sdist must rebuild into exactly one wheel")
        installed_smoke(component, wheel, rebuilt_wheels[0], smoke_root, fixture, sdk, docker_stub,
                        build_constraints, qualification_constraints)
        shutil.copy2(wheel, out / wheel.name)
        shutil.copy2(sdist, out / sdist.name)

    for path in sorted(p for p in out.iterdir() if p.is_file()):
        audit_archive(path)
    package_artifacts = sorted(p for p in out.iterdir() if p.name.endswith((".whl", ".tar.gz")))
    if len(package_artifacts) != 4:
        fail("release bundle does not contain four package artifacts")

    records = [{"filename": p.name, "sha256": sha256(p)} for p in package_artifacts]
    sums_text = "".join(f"{record['sha256']}  {record['filename']}\n" for record in records)
    (out / "SHA256SUMS.txt").write_text(sums_text, encoding="ascii", newline="\n")
    agents_name, agents_version = parse_project("agents")
    workers_name, workers_version = parse_project("workers")
    manifest = {
        "schema": "deputy.mcp.release-candidate.v1",
        "qualification_status": "PASS",
        "repository": "Simon95277/Deputy-Shell-MCP",
        "commit": os.environ.get("GITHUB_SHA", args.commit),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", args.run_id),
        "qualification": {
            "windows_python": "3.10",
            "linux_portability_python": "3.10 and 3.14.7",
            "mcp": "2.2.0",
            "agents_tests": EXPECTED_TESTS["agents"],
            "workers_tests": EXPECTED_TESTS["workers"],
            "workers_capabilities": 22,
            "runtime_contract": "DA-PACKAGING-1",
            "coherence_contract": "DA-BYTE-COHERENCE-1",
            "snapshot_policy": "DA-FAST-2-positive-allowlist-v1",
            "provider": "opencode",
            "model": "muse-spark-1.3-contributor-free",
            "agents_production_tools": sorted(AGENTS_TOOLS),
        },
        "packages": [
            {"name": agents_name, "version": agents_version},
            {"name": workers_name, "version": workers_version},
        ],
        "artifacts": records,
    }
    (out / "release-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_bundle(out, manifest)
    print(json.dumps({"status": "PASS", "schema": manifest["schema"], "artifacts": records,
                      "release_files": sorted(p.name for p in out.iterdir())}, sort_keys=True))


def verify_bundle(directory: Path, manifest: dict | None = None) -> None:
    if manifest is None:
        manifest = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "deputy.mcp.release-candidate.v1" or manifest.get("qualification_status") != "PASS":
        fail("release manifest schema or status invalid")
    package_records = manifest.get("artifacts")
    if not isinstance(package_records, list) or len(package_records) != 4:
        fail("release manifest artifact list invalid")
    expected_names = {record.get("filename") for record in package_records}
    if len(expected_names) != 4 or None in expected_names:
        fail("release manifest artifact filenames invalid")
    sum_records: dict[str, str] = {}
    for line in (directory / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if not match or match.group(2) in sum_records:
            fail("SHA256SUMS format invalid")
        sum_records[match.group(2)] = match.group(1)
    if set(sum_records) != expected_names:
        fail("SHA256SUMS filenames differ from manifest")
    for record in package_records:
        path = directory / record["filename"]
        if not path.is_file() or sha256(path) != record["sha256"] or sum_records[path.name] != record["sha256"]:
            fail("release artifact SHA-256 verification failed")
        audit_archive(path)
    expected_files = expected_names | {"SHA256SUMS.txt", "release-manifest.json"}
    if {p.name for p in directory.iterdir()} != expected_files:
        fail("release bundle contains unexpected files")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--root", required=True)
    fixture.add_argument("--sdk", required=True)
    fixture.add_argument("--docker-stub", required=True)
    fixture.set_defaults(func=prepare_fixture)
    tests = sub.add_parser("tests")
    tests.add_argument("--component", required=True, choices=tuple(EXPECTED_TESTS))
    tests.set_defaults(func=test_suite)
    contracts = sub.add_parser("contracts")
    contracts.set_defaults(func=lambda _: contract_check())
    hygiene = sub.add_parser("hygiene")
    hygiene.add_argument("--root", default=str(ROOT))
    hygiene.set_defaults(func=public_hygiene)
    audit = sub.add_parser("audit-artifacts")
    audit.add_argument("--directory", required=True)
    audit.set_defaults(func=audit_artifacts)
    ref = sub.add_parser("check-release-ref")
    ref.set_defaults(func=check_release_ref)
    bundle = sub.add_parser("release-bundle")
    bundle.add_argument("--output", required=True)
    bundle.add_argument("--temp", required=True)
    bundle.add_argument("--commit", required=True)
    bundle.add_argument("--run-id", required=True)
    bundle.set_defaults(func=release_bundle)
    verify = sub.add_parser("verify-bundle")
    verify.add_argument("--directory", required=True)
    verify.set_defaults(func=lambda args: verify_bundle(Path(args.directory).resolve()))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

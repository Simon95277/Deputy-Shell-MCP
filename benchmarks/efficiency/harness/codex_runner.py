"""One isolated Codex configuration and launch path for benchmark runs.

The benchmark never reads the normal Codex config. Each invocation gets an
isolated CODEX_HOME containing generated config.toml and a temporary copy of
the existing ChatGPT auth file. Credential contents are never persisted in
benchmark evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Python 3.10 compatibility for the benchmark runner.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


CODEX_EXECUTABLE = Path(os.environ.get("DEPUTY_BENCHMARK_CODEX_EXECUTABLE", "codex"))
CODEX_VERSION = "codex-cli 0.155.0"
MODEL = "gpt-6-luna"
EFFORT = "low"
AGENTS_SERVER_NAME = "DeputyAgentsControlTowerLab"
WORKERS_SERVER_NAME = "DeputyWorkersControlTowerLab"
EXPECTED_TOOLS = {"deputy_recon", "deputy_observe", "deputy_act"}
FORBIDDEN_SERVERS = {"deputy_agents_lab", "deputy_workers", "DeputyWorkersV2Lab"}
ENV_ALLOWLIST = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
    "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "COMSPEC",
}


@dataclass(frozen=True)
class LaunchPlan:
    argv: tuple[str, ...]
    env: dict[str, str]
    config_home: Path
    config_path: Path
    config_sha256: str
    config_contract_sha256: str
    deputy_server_names: tuple[str, ...]
    repository_root: Path
    working_directory: Path
    arm: str
    official: bool


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _server_specs(target: Path, run_root: Path, repository_root: Path,
                  server_python: Path) -> list[dict[str, Any]]:
    source_policy = {
        "schema": "deputy.agents.source-policy.v1",
        "policy_id": "EFFICIENCY_FIXTURE_V1",
        "allowed_prefixes": ["app/src/", "tools/"],
        "allowed_root_files": [".gitignore"],
        "excluded_prefixes": [],
        "approved_untracked": [],
        "limits": {"max_file_bytes": 262144, "max_file_count": 128,
                   "max_total_bytes": 2097152},
    }
    agents = repository_root / "agents"
    workers = repository_root / "workers"
    return [
        {
            "name": AGENTS_SERVER_NAME,
            "command": str(server_python),
            "args": [str(agents / "server.py")],
            "cwd": str(agents),
            "env": {
                "DEPUTYAGENTS_DEPUTY_SHELL_ROOT": str(target),
                "DEPUTYAGENTS_RUNTIME_ROOT": str(run_root / "agents-runtime"),
                "DEPUTYAGENTS_SOURCE_POLICY_JSON": json.dumps(
                    source_policy, separators=(",", ":"),
                ),
            },
        },
        {
            "name": WORKERS_SERVER_NAME,
            "command": str(server_python),
            "args": [str(workers / "server.py")],
            "cwd": str(workers),
            "env": {
                "DEPUTYWORKERS_PYTHON_EXE": str(server_python),
                "DEPUTYWORKERS_DEPUTY_SHELL_ROOT": str(target),
                "DEPUTYWORKERS_RUNTIME_ROOT": str(run_root / "workers-runtime"),
                "DEPUTYWORKERS_ANDROID_SDK_ROOT": str(
                    workers / "tests" / "fixtures" / "synthetic_sdk"
                ),
            },
        },
    ]


def render_config(arm: str, target: Path, run_root: Path, repository_root: Path,
                 server_python: Path) -> tuple[str, tuple[str, ...]]:
    """Render the complete isolated config; never emit disable-only MCP tables."""
    if arm not in {"DIRECT", "DEPUTY"}:
        raise ValueError("BENCHMARK_ARM_INVALID")
    lines = [
        'model = "gpt-6-luna"',
        'model_reasoning_effort = "low"',
        'sandbox_mode = "workspace-write"',
        "",
        "[windows]",
        'sandbox = "unelevated"',
    ]
    if arm == "DIRECT":
        lines.extend([
            "",
            f"[projects.{_toml_string(str(target.resolve()))}]",
            'trust_level = "trusted"',
        ])
    specs = _server_specs(target, run_root, repository_root, server_python) if arm == "DEPUTY" else []
    for spec in specs:
        lines.extend([
            "",
            f"[mcp_servers.{spec['name']}]",
            "enabled = true",
            f"command = {_toml_string(spec['command'])}",
            "args = [" + ", ".join(_toml_string(arg) for arg in spec["args"]) + "]",
            f"cwd = {_toml_string(spec['cwd'])}",
            "env = { " + ", ".join(
                f"{key} = {_toml_string(value)}" for key, value in spec["env"].items()
            ) + " }",
        ])
    text = "\n".join(lines) + "\n"
    validate_config_text(text, arm)
    return text, tuple(spec["name"] for spec in specs)


def validate_config_text(config_text: str, arm: str,
                         working_directory: Path | None = None) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(config_text)
    except Exception as exc:
        raise ValueError("BENCHMARK_CONFIG_TOML_INVALID") from exc
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("BENCHMARK_MCP_CONFIG_INVALID")
    expected = {AGENTS_SERVER_NAME, WORKERS_SERVER_NAME} if arm == "DEPUTY" else set()
    if set(servers) != expected or FORBIDDEN_SERVERS.intersection(servers):
        raise ValueError("BENCHMARK_MCP_INVENTORY_INVALID")
    for server in servers.values():
        if not isinstance(server, dict) or set(server) != {"enabled", "command", "args", "cwd", "env"}:
            raise ValueError("BENCHMARK_MCP_SERVER_SHAPE_INVALID")
        if server["enabled"] is not True or not server["command"] or not server["args"]:
            raise ValueError("BENCHMARK_MCP_SERVER_DISABLED_OR_INCOMPLETE")
    if parsed.get("model") != MODEL or parsed.get("model_reasoning_effort") != EFFORT:
        raise ValueError("BENCHMARK_MODEL_CONFIG_INVALID")
    if parsed.get("sandbox_mode") != "workspace-write":
        raise ValueError("BENCHMARK_SANDBOX_CONFIG_INVALID")
    if parsed.get("windows", {}).get("sandbox") != "unelevated":
        raise ValueError("BENCHMARK_WINDOWS_SANDBOX_CONFIG_INVALID")
    allowed_top_level = {"model", "model_reasoning_effort", "sandbox_mode", "windows", "mcp_servers", "projects"}
    if set(parsed) - allowed_top_level:
        raise ValueError("BENCHMARK_CONFIG_UNEXPECTED_TOP_LEVEL_KEY")
    if not isinstance(parsed.get("windows"), dict) or set(parsed["windows"]) != {"sandbox"}:
        raise ValueError("BENCHMARK_WINDOWS_CONFIG_SHAPE_INVALID")
    projects = parsed.get("projects", {})
    if not isinstance(projects, dict) or len(projects) > 1:
        raise ValueError("BENCHMARK_PROJECT_TRUST_SHAPE_INVALID")
    for project_path, project in projects.items():
        if (not isinstance(project, dict) or set(project) != {"trust_level"}
                or project.get("trust_level") != "trusted"):
            raise ValueError("BENCHMARK_PROJECT_TRUST_INVALID")
        if working_directory is not None and Path(project_path).resolve() != working_directory.resolve():
            raise ValueError("BENCHMARK_PROJECT_TRUST_PATH_INVALID")
    if arm == "DIRECT" and working_directory is not None and str(working_directory.resolve()) not in projects:
        raise ValueError("BENCHMARK_DIRECT_PROJECT_TRUST_INVALID")
    return parsed


def benchmark_config_projection(config_text: str, arm: str,
                                working_directory: Path | None = None) -> dict[str, Any]:
    """Return only immutable benchmark authority/config fields, excluding Codex project trust state."""
    parsed = validate_config_text(config_text, arm, working_directory)
    servers = parsed.get("mcp_servers", {})
    projection = {
        "model": parsed["model"],
        "model_reasoning_effort": parsed["model_reasoning_effort"],
        "sandbox_mode": parsed["sandbox_mode"],
        "windows": {"sandbox": parsed["windows"]["sandbox"]},
        "mcp_servers": {
            name: {
                "enabled": server["enabled"],
                "command": server["command"],
                "args": server["args"],
                "cwd": server["cwd"],
                "env": server["env"],
            }
            for name, server in sorted(servers.items())
        },
    }
    return projection


def benchmark_config_contract_sha256(config_text: str, arm: str,
                                     working_directory: Path | None = None) -> str:
    canonical = json.dumps(benchmark_config_projection(config_text, arm, working_directory),
                           sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_benchmark_config_transition(before: dict[str, Any], after: dict[str, Any],
                                         arm: str, working_directory: Path) -> bool:
    """Permit only Codex's exact per-project trust-state addition for this session cwd."""
    project_key = os.path.normcase(os.path.normpath(str(working_directory.resolve()))).casefold()

    def canonical_projects(projects: Any) -> dict[str, dict[str, str]] | None:
        if not isinstance(projects, dict):
            return None
        if not projects:
            return {}
        if len(projects) != 1:
            return None
        key, value = next(iter(projects.items()))
        normalized = os.path.normcase(os.path.normpath(str(Path(key).resolve()))).casefold()
        if normalized != project_key or value != {"trust_level": "trusted"}:
            return None
        return {project_key: {"trust_level": "trusted"}}

    before_projects = canonical_projects(before.get("projects", {}))
    after_projects = canonical_projects(after.get("projects", {}))
    expected = {project_key: {"trust_level": "trusted"}}
    if before_projects is None or after_projects is None:
        return False
    if arm == "DIRECT":
        return before_projects == expected and after_projects == expected
    return before_projects in ({}, expected) and after_projects in ({}, expected) and not (
        before_projects == expected and after_projects == {}
    )


def _config_mutation_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        paths = []
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                paths.append(child)
            else:
                paths.extend(_config_mutation_paths(before[key], after[key], child))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [prefix]
        paths = []
        for index, (left, right) in enumerate(zip(before, after)):
            paths.extend(_config_mutation_paths(left, right, f"{prefix}[{index}]"))
        return paths
    return [] if before == after else [prefix]


def build_environment(base: dict[str, str], codex_home: Path) -> dict[str, str]:
    """Keep OS essentials only, force isolated config home, and prohibit API-key auth."""
    selected = {key: value for key, value in base.items()
                if key.upper() in ENV_ALLOWLIST and isinstance(value, str)}
    selected.pop("OPENAI_API_KEY", None)
    selected["CODEX_HOME"] = str(codex_home.resolve())
    return selected


def prepare_config_home(config_home: Path, config_text: str,
                        auth_source: Path | None = None, *, reuse: bool = False,
                        arm: str | None = None, working_directory: Path | None = None,
                        expected_config_contract_sha256: str | None = None) -> Path:
    """Create isolated Codex state and copy only the account auth file."""
    if auth_source is None:
        profile = os.environ.get("USERPROFILE")
        if not profile:
            raise RuntimeError("BENCHMARK_CHATGPT_AUTH_SOURCE_UNAVAILABLE")
        auth_source = Path(profile) / ".codex" / "auth.json"
    if not auth_source.is_file():
        raise RuntimeError("BENCHMARK_CHATGPT_AUTH_SOURCE_UNAVAILABLE")
    config_path = config_home / "config.toml"
    auth_copy = config_home / "auth.json"
    marker = config_home / ".benchmark-auth-copy-managed"
    if reuse:
        if not config_home.is_dir() or not marker.is_file():
            raise RuntimeError("BENCHMARK_CODEX_HOME_REUSE_INVALID")
        if arm not in {"DIRECT", "DEPUTY"} or working_directory is None:
            raise RuntimeError("BENCHMARK_CODEX_HOME_REUSE_CONTRACT_REQUIRED")
        current_text = config_path.read_text(encoding="utf-8")
        try:
            before = validate_config_text(config_text, arm, working_directory)
            after = validate_config_text(current_text, arm, working_directory)
            contract_hash = benchmark_config_contract_sha256(current_text, arm, working_directory)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("BENCHMARK_CODEX_HOME_CONFIG_MISMATCH") from exc
        if (contract_hash != expected_config_contract_sha256
                or not validate_benchmark_config_transition(before, after, arm, working_directory)):
            raise RuntimeError("BENCHMARK_CODEX_HOME_CONFIG_MISMATCH")
        if not auth_copy.is_file():
            shutil.copyfile(auth_source, auth_copy)
        return config_path
    if config_home.exists() or config_home.is_symlink():
        raise FileExistsError("BENCHMARK_CODEX_HOME_ALREADY_EXISTS")
    config_home.mkdir(parents=True)
    config_path.write_text(config_text, encoding="utf-8", newline="\n")
    shutil.copyfile(auth_source, auth_copy)
    marker.write_text("DEPUTY_BENCHMARK_CODEX_HOME_V1\n", encoding="ascii")
    return config_path


def remove_isolated_auth_copy(config_home: Path, repository_root: Path) -> bool:
    """Remove only an auth copy created by this runner, never a link or user file."""
    home = config_home.resolve()
    if home.is_relative_to(repository_root.resolve()):
        raise RuntimeError("BENCHMARK_AUTH_HOME_INSIDE_REPOSITORY")
    marker = home / ".benchmark-auth-copy-managed"
    auth_copy = home / "auth.json"
    if not marker.is_file():
        return False
    if auth_copy.is_symlink():
        raise RuntimeError("BENCHMARK_AUTH_COPY_IS_SYMLINK")
    if auth_copy.is_file():
        auth_copy.unlink()
        return True
    return False


def build_exec_argv(prompt: str, working_directory: Path, *,
                    codex_executable: Path = CODEX_EXECUTABLE,
                    output_file: Path | None = None,
                    resume_session_id: str | None = None) -> tuple[str, ...]:
    """Build fresh exec argv; resume is deliberately handled separately."""
    if not prompt or not str(codex_executable):
        raise ValueError("BENCHMARK_CODEX_INVOCATION_INVALID")
    if not working_directory.is_absolute():
        raise ValueError("BENCHMARK_WORKING_DIRECTORY_NOT_ABSOLUTE")
    if resume_session_id is not None:
        return build_resume_argv(resume_session_id, prompt, codex_executable=codex_executable,
                                 output_file=output_file)
    command = [str(codex_executable), "exec", "--skip-git-repo-check", "--json",
               "--model", MODEL, "--cd", str(working_directory),
               "-c", 'model_reasoning_effort="low"']
    if output_file is not None:
        command.extend(["--output-last-message", str(output_file)])
    command.append(prompt)
    _validate_argv(tuple(command))
    return tuple(command)


def build_resume_argv(session_id: str, prompt: str, *,
                      codex_executable: Path = CODEX_EXECUTABLE,
                      output_file: Path | None = None) -> tuple[str, ...]:
    """Build argv using only options shown by `codex exec resume --help`."""
    if not str(codex_executable) or not prompt:
        raise ValueError("BENCHMARK_CODEX_INVOCATION_INVALID")
    if not session_id or any(ch.isspace() for ch in session_id):
        raise ValueError("BENCHMARK_RESUME_SESSION_INVALID")
    command = [str(codex_executable), "exec", "resume", "--skip-git-repo-check",
               "--json", "--model", MODEL, "-c", 'model_reasoning_effort="low"']
    if output_file is not None:
        command.extend(["--output-last-message", str(output_file)])
    command.extend([session_id, prompt])
    _validate_argv(tuple(command), resume=True)
    return tuple(command)


def _validate_argv(argv: tuple[str, ...], *, resume: bool = False) -> None:
    if "--ask-for-approval" in argv or "--ignore-user-config" in argv:
        raise ValueError("BENCHMARK_UNSUPPORTED_OR_NONISOLATED_FLAG")
    if argv.count("--skip-git-repo-check") != 1:
        raise ValueError("BENCHMARK_SKIP_GIT_FLAG_INVALID")
    if resume and any(flag in argv for flag in ("--sandbox", "--cd")):
        raise ValueError("BENCHMARK_RESUME_FRESH_ONLY_OPTION")
    if resume and argv[2] != "resume":
        raise ValueError("BENCHMARK_RESUME_SUBCOMMAND_INVALID")
    for index, item in enumerate(argv):
        if item == "-c" and (index + 1 >= len(argv) or "=" not in argv[index + 1]):
            raise ValueError("BENCHMARK_CONFIG_OVERRIDE_NOT_ATOMIC")
        if item.startswith("mcp_servers.") and item.endswith("=false"):
            raise ValueError("BENCHMARK_DISABLE_ONLY_MCP_OVERRIDE_FORBIDDEN")


def build_launch_plan(*, prompt: str, arm: str, target: Path, run_root: Path,
                      config_home: Path, working_directory: Path,
                      repository_root: Path, server_python: Path,
                      official: bool, base_environment: dict[str, str] | None = None,
                      auth_source: Path | None = None,
                      codex_executable: Path = CODEX_EXECUTABLE,
                      output_file: Path | None = None,
                      resume_session_id: str | None = None,
                      reuse_config_home: bool = False) -> LaunchPlan:
    """Canonical builder used identically by shadow probes and official slots."""
    if not target.is_absolute() or not run_root.is_absolute() or not config_home.is_absolute():
        raise ValueError("BENCHMARK_PATHS_NOT_ABSOLUTE")
    repo = repository_root.resolve()
    if config_home.resolve().is_relative_to(repo) or working_directory.resolve().is_relative_to(repo):
        raise ValueError("BENCHMARK_CODEX_PATH_MUST_BE_OUTSIDE_SOURCE_REPOSITORY")
    config_text, names = render_config(arm, target, run_root, repository_root, server_python)
    validate_config_text(config_text, arm, working_directory)
    expected_config_contract_sha256 = benchmark_config_contract_sha256(
        config_text, arm, working_directory,
    )
    config_path = prepare_config_home(config_home, config_text, auth_source,
                                      reuse=reuse_config_home, arm=arm,
                                      working_directory=working_directory,
                                      expected_config_contract_sha256=expected_config_contract_sha256)
    env = build_environment(dict(os.environ if base_environment is None else base_environment), config_home)
    argv = build_exec_argv(prompt, working_directory, codex_executable=codex_executable,
                           output_file=output_file, resume_session_id=resume_session_id)
    return LaunchPlan(
        argv=argv,
        env=env,
        config_home=config_home.resolve(),
        config_path=config_path.resolve(),
        config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        config_contract_sha256=benchmark_config_contract_sha256(
            config_path.read_text(encoding="utf-8"), arm, working_directory,
        ),
        deputy_server_names=names,
        repository_root=repo,
        working_directory=working_directory.resolve(),
        arm=arm,
        official=official,
    )


def run_plan(plan: LaunchPlan, cwd: Path, stdout_path: Path, stderr_path: Path,
             process_timeout_s: int = 660, *, argv: tuple[str, ...] | None = None,
             process_record_path: Path | None = None) -> dict[str, Any]:
    invocation = plan.argv if argv is None else argv
    executable = Path(invocation[0])
    if not executable.is_file() and shutil.which(invocation[0]) is None:
        raise RuntimeError("BENCHMARK_CODEX_EXECUTABLE_UNAVAILABLE")
    config_bytes = plan.config_path.read_bytes()
    config_before_text = config_bytes.decode("utf-8")
    config_before_path = None
    config_after_path = None
    config_state_path = None
    if process_record_path is not None:
        config_before_path = process_record_path.with_name(process_record_path.stem + "-config-before.toml")
        config_after_path = process_record_path.with_name(process_record_path.stem + "-config-after.toml")
        config_state_path = process_record_path.with_name(process_record_path.stem + "-config-state.json")
        config_before_path.write_bytes(config_bytes)
    try:
        config_before_parsed = validate_config_text(config_before_text, plan.arm, plan.working_directory)
        projection_before = benchmark_config_projection(config_before_text, plan.arm, plan.working_directory)
        projection_before_hash = benchmark_config_contract_sha256(
            config_before_text, plan.arm, plan.working_directory,
        )
    except (ValueError, TypeError):
        if config_state_path is not None:
            config_state_path.write_text(json.dumps({
                "raw_before_sha256": hashlib.sha256(config_bytes).hexdigest(),
                "raw_after_sha256": None,
                "benchmark_contract_unchanged": False,
                "config_validation": "INVALID_BEFORE_LAUNCH",
                "config_before_path": str(config_before_path.resolve()),
            }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("BENCHMARK_CONFIG_CONTRACT_INVALID_BEFORE_LAUNCH")
    if projection_before_hash != plan.config_contract_sha256:
        if config_state_path is not None:
            config_state_path.write_text(json.dumps({
                "raw_before_sha256": hashlib.sha256(config_bytes).hexdigest(),
                "raw_after_sha256": None,
                "benchmark_config_contract_sha256_expected": plan.config_contract_sha256,
                "benchmark_config_contract_sha256_before": projection_before_hash,
                "benchmark_contract_unchanged": False,
                "config_validation": "CONTRACT_CHANGED_BEFORE_LAUNCH",
                "config_before_path": str(config_before_path.resolve()),
            }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("BENCHMARK_CONFIG_CONTRACT_CHANGED_BEFORE_LAUNCH")
    if Path(plan.env.get("CODEX_HOME", "")).resolve() != plan.config_home:
        raise RuntimeError("BENCHMARK_CODEX_HOME_MISMATCH")
    if cwd.resolve().is_relative_to(plan.repository_root):
        raise RuntimeError("BENCHMARK_PROJECT_CONFIG_LAYER_NOT_ISOLATED")
    if cwd.resolve() != plan.working_directory:
        raise RuntimeError("BENCHMARK_WORKING_DIRECTORY_MISMATCH")
    if any(name.upper() == "OPENAI_API_KEY" for name in plan.env):
        raise RuntimeError("BENCHMARK_API_KEY_AUTH_FORBIDDEN")
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc = subprocess.Popen(invocation, cwd=str(cwd), env=plan.env,
                                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        pid = proc.pid
        try:
            code = proc.wait(timeout=process_timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                code = proc.wait(timeout=5)
            timed_out = True
    config_after_bytes = plan.config_path.read_bytes()
    config_after_text = config_after_bytes.decode("utf-8")
    config_validation_after = "VALID"
    try:
        config_after_parsed = validate_config_text(config_after_text, plan.arm, plan.working_directory)
        projection_after = benchmark_config_projection(config_after_text, plan.arm, plan.working_directory)
        projection_after_hash: str | None = benchmark_config_contract_sha256(
            config_after_text, plan.arm, plan.working_directory,
        )
        project_transition_valid = validate_benchmark_config_transition(
            config_before_parsed, config_after_parsed, plan.arm, plan.working_directory,
        )
    except (ValueError, TypeError):
        config_validation_after = "INVALID"
        try:
            config_after_parsed = tomllib.loads(config_after_text)
        except Exception:
            config_after_parsed = {}
        projection_after = {}
        projection_after_hash = None
        project_transition_valid = False
    contract_unchanged = (projection_before_hash == projection_after_hash == plan.config_contract_sha256
                          and project_transition_valid and config_validation_after == "VALID")
    mutations = _config_mutation_paths(config_before_parsed, config_after_parsed)
    if config_after_path is not None and config_state_path is not None:
        config_after_path.write_bytes(config_after_bytes)
        config_state = {
            "raw_before_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "raw_after_sha256": hashlib.sha256(config_after_bytes).hexdigest(),
            "raw_bytes_changed": config_bytes != config_after_bytes,
            "benchmark_config_contract_sha256_before": projection_before_hash,
            "benchmark_config_contract_sha256_after": projection_after_hash,
            "benchmark_contract_unchanged": contract_unchanged,
            "config_validation_after": config_validation_after,
            "project_trust_transition_valid": project_transition_valid,
            "detected_mutation_paths": mutations,
            "config_before_path": str(config_before_path.resolve()),
            "config_after_path": str(config_after_path.resolve()),
            "projection_before": projection_before,
            "projection_after": projection_after,
        }
        config_state_path.write_text(json.dumps(config_state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = {
        "pid": pid, "exit_code": code, "elapsed_ms": int((time.monotonic() - started) * 1000),
        "timed_out": timed_out, "started_utc": started_utc,
        "ended_utc": datetime.now(timezone.utc).isoformat(), "argv": list(invocation),
        "working_directory": str(cwd.resolve()), "config_home": str(plan.config_home),
        "config_path": str(plan.config_path), "config_sha256": plan.config_sha256,
        "stdout_jsonl_path": str(stdout_path.resolve()), "stderr_path": str(stderr_path.resolve()),
        "environment_variable_names": sorted(plan.env),
        "raw_config_before_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "raw_config_after_sha256": hashlib.sha256(config_after_bytes).hexdigest(),
        "config_contract_sha256": plan.config_contract_sha256,
        "config_contract_unchanged": contract_unchanged,
        "config_validation_after": config_validation_after,
        "project_trust_transition_valid": project_transition_valid,
        "config_mutation_paths": mutations,
        "config_before_path": str(config_before_path.resolve()) if config_before_path else None,
        "config_after_path": str(config_after_path.resolve()) if config_after_path else None,
        "config_state_path": str(config_state_path.resolve()) if config_state_path else None,
    }
    if process_record_path is not None:
        process_record_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = process_record_path.with_name(process_record_path.name + ".tmp")
        temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(process_record_path)
    if not contract_unchanged:
        raise RuntimeError("BENCHMARK_CONFIG_CONTRACT_CHANGED_DURING_PROCESS")
    return result


class CodexSessionRunner:
    """Own a single isolated Codex conversation across fresh and resume turns."""

    def __init__(self, plan: LaunchPlan, *, process_timeout_s: int = 660):
        self.plan = plan
        self.process_timeout_s = process_timeout_s

    def start_session(self, stdout_path: Path, stderr_path: Path,
                      process_record_path: Path) -> dict[str, Any]:
        return run_plan(self.plan, self.plan.working_directory, stdout_path, stderr_path,
                        self.process_timeout_s, process_record_path=process_record_path)

    def resume_session(self, session_id: str, prompt: str, stdout_path: Path,
                       stderr_path: Path, process_record_path: Path) -> dict[str, Any]:
        argv = build_resume_argv(session_id, prompt)
        return run_plan(self.plan, self.plan.working_directory, stdout_path, stderr_path,
                        self.process_timeout_s, argv=argv, process_record_path=process_record_path)


def parse_jsonl(data: bytes | str) -> list[dict[str, Any]]:
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def final_message(events: list[dict[str, Any]]) -> str:
    messages = []
    for event in events:
        if event.get("type") not in {"item.started", "item.updated", "item.completed"}:
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            messages.append(item.get("text", ""))
    return messages[-1] if messages else ""


def turn_usage(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event["usage"] for event in events
        if event.get("type") == "turn.completed"
        and isinstance(event.get("usage"), dict)
    ]


def _read_line(process: subprocess.Popen[str], timeout_s: float) -> str:
    messages: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        messages.put(process.stdout.readline())

    threading.Thread(target=reader, daemon=True).start()
    try:
        line = messages.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise TimeoutError("MCP_STDIO_RESPONSE_TIMEOUT") from exc
    if line == "":
        raise RuntimeError("MCP_STDIO_EOF")
    return line


def inspect_stdio_tools(server: dict[str, Any], timeout_s: float = 12.0) -> list[str]:
    """Perform bounded MCP initialize + tools/list against one configured server."""
    env = {key: value for key, value in os.environ.items()
           if key.upper() in ENV_ALLOWLIST and isinstance(value, str)}
    env.update(server.get("env", {}))
    proc = subprocess.Popen(
        [server["command"], *server["args"]], cwd=server["cwd"], env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "phase11d-inventory-check", "version": "1"}},
        }) + "\n")
        proc.stdin.flush()
        initialize = json.loads(_read_line(proc, timeout_s))
        if initialize.get("id") != 1 or "result" not in initialize:
            raise RuntimeError("MCP_INITIALIZE_REJECTED")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()
        while True:
            response = json.loads(_read_line(proc, timeout_s))
            if response.get("id") == 2:
                if "error" in response:
                    raise RuntimeError("MCP_TOOLS_LIST_REJECTED")
                tools = response.get("result", {}).get("tools", [])
                return [item["name"] for item in tools if isinstance(item, dict) and isinstance(item.get("name"), str)]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def inspect_configured_tool_inventory(config_path: Path, arm: str) -> dict[str, list[str]]:
    config_text = config_path.read_text(encoding="utf-8")
    parsed = validate_config_text(config_text, arm)
    inventory = {
        name: sorted(inspect_stdio_tools(server))
        for name, server in parsed.get("mcp_servers", {}).items()
    }
    actual = {tool for tools in inventory.values() for tool in tools}
    if arm == "DEPUTY" and actual != EXPECTED_TOOLS:
        raise RuntimeError("BENCHMARK_EFFECTIVE_MCP_TOOL_INVENTORY_INVALID")
    if arm == "DIRECT" and actual:
        raise RuntimeError("BENCHMARK_DIRECT_ARM_MCP_INVENTORY_NOT_EMPTY")
    return inventory

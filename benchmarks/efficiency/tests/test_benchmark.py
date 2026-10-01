from __future__ import annotations

import json
import hashlib
import importlib.util
import inspect
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "harness"
sys.path.insert(0, str(HARNESS))
import benchmark
import codex_runner


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="efficiency-fixture-")
        cls.root = Path(cls.tmp.name) / "one"
        cls.info = benchmark.prepare_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def valid_deputy_record(case):
        trace = [{"tool": tool, "operation": operation}
                 for tool, operation in benchmark.EXPECTED_DEPUTY_TRACE[case]]
        agents = sum(tool == "deputy_recon" for tool, _ in benchmark.EXPECTED_DEPUTY_TRACE[case])
        workers = sum(tool == "deputy_observe" for tool, _ in benchmark.EXPECTED_DEPUTY_TRACE[case])
        record = benchmark.empty_run(case, "DEPUTY", 1, "test", "low")
        used = (["agents"] if agents else []) + (["workers"] if workers else [])
        record["execution"].update({"required_subsystems_used": used, "agents_calls": agents,
            "workers_calls": workers, "mcp_calls": len(trace), "deputy_tool_trace": trace})
        if case == "E6":
            record["execution"].update({"e6_stage_a_recorded": True, "e6_same_session_stage_b": True,
                "e6_stage_a_tool_trace": trace, "e6_stage_b_tool_trace": []})
        return record

    def test_six_versioned_case_definitions_are_unique(self):
        cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(benchmark.CASES.glob("E*.json"))]
        self.assertEqual([c["case_id"] for c in cases], ["E1", "E2", "E3", "E4", "E5", "E6"])
        self.assertEqual(json.loads((benchmark.HERE / "benchmark.json").read_text()) ["benchmark_version"], "EFFICIENCY-BENCHMARK-1")
        for c in cases:
            self.assertTrue(c.get("prompt") or c.get("stage_a") or c.get("stage_a_direct"))

    def test_d7_resume_transport_uses_caller_supplied_prompt(self):
        runner = self._load_d7_campaign_runner()
        class FakeSessionRunner:
            def resume_session(self, session_id, prompt, stdout_path, stderr_path, process_record_path):
                self.arguments = (session_id, prompt, stdout_path, stderr_path, process_record_path)
                return {"exit_code": 0}

        fake = FakeSessionRunner()
        paths = tuple(Path(f"{name}.jsonl") for name in ("out", "err", "process"))
        response = runner.resume_session_with_caller_prompt(fake, "same-thread", "FIXED_SYNTHETIC_STAGE_B", *paths)
        self.assertEqual(response, {"exit_code": 0})
        self.assertEqual(fake.arguments, ("same-thread", "FIXED_SYNTHETIC_STAGE_B", *paths))
        source = inspect.getsource(runner.resume_session_with_caller_prompt)
        self.assertNotIn("make_prompt", source)
        self.assertNotIn('cases" / "E6.json', source)

    def test_d7_official_e6_stage_b_uses_frozen_case_prompt(self):
        runner = self._load_d7_campaign_runner()
        case = json.loads((benchmark.CASES / "E6.json").read_text(encoding="utf-8"))
        selected = runner.make_prompt(case, "DEPUTY", "stage_b")
        self.assertEqual(selected, "DEPUTY ARM: Use only the required current Deputy subsystem for target-repository evidence. "
                         "Do not use local file, shell, or repository tools to inspect the target.\n\n" + case["stage_b"])
        source = inspect.getsource(runner.run_slot)
        self.assertIn('make_prompt(case, slot["arm"], "stage_b")', source)

    def test_d7_interrupted_resume_requires_caller_prompt_and_does_not_select_case_semantics(self):
        runner = self._load_d7_campaign_runner()
        signature = inspect.signature(runner.resume_interrupted_e6_shadow)
        self.assertEqual(list(signature.parameters), ["stage_b_prompt"])
        source = inspect.getsource(runner.resume_interrupted_e6_shadow)
        self.assertNotIn("make_prompt", source)
        self.assertNotIn('case["stage_b"]', source)
        self.assertIn("resume_session_with_caller_prompt", source)

    @staticmethod
    def _load_d7_campaign_runner():
        path = (benchmark.HERE / "evidence" / "phase11d7-20261001" / "campaign_runner.py")
        spec = importlib.util.spec_from_file_location("phase11d7_campaign_runner_test", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("D7_CAMPAIGN_RUNNER_IMPORT_FAILED")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_probe_and_official_use_same_isolated_config_environment_builder(self):
        target = Path("C:/synthetic fixture/target")
        root = Path("C:/synthetic fixture/run")
        codex_home = Path("C:/synthetic fixture/codex-home")
        cwd = Path("C:/synthetic fixture/client")
        repository = Path("C:/source repository")
        python = Path("C:/python/python.exe")
        base = {
            "PATH": "C:/Windows/System32",
            "USERPROFILE": "C:/SyntheticHome",
            "CODEX_HOME": "C:/SyntheticHome/.codex",
            "OPENAI_API_KEY": "must-not-be-forwarded",
            "UNRELATED_SECRET": "must-not-be-forwarded",
        }

        def fake_prepare(path, config_text, auth_source=None, **kwargs):
            reuse = kwargs.get("reuse", False)
            if reuse:
                raise AssertionError("unexpected reuse during initial builder parity test")
            path.mkdir(parents=True)
            config = path / "config.toml"
            config.write_text(config_text, encoding="utf-8")
            return config

        with tempfile.TemporaryDirectory() as temp:
            home_a = Path(temp) / "probe"
            home_b = Path(temp) / "official"
            with mock.patch.object(codex_runner, "prepare_config_home", side_effect=fake_prepare):
                probe = codex_runner.build_launch_plan(
                    prompt="PROBE", arm="DEPUTY", target=target, run_root=root,
                    config_home=home_a, working_directory=cwd, repository_root=repository,
                    server_python=python, official=False, base_environment=base,
                    codex_executable=codex_runner.CODEX_EXECUTABLE,
                )
                official = codex_runner.build_launch_plan(
                    prompt="OFFICIAL", arm="DEPUTY", target=target, run_root=root,
                    config_home=home_b, working_directory=cwd, repository_root=repository,
                    server_python=python, official=True, base_environment=base,
                    codex_executable=codex_runner.CODEX_EXECUTABLE,
                )
            self.assertEqual(probe.argv[:-1], official.argv[:-1])
            self.assertEqual(probe.env["CODEX_HOME"], str(home_a.resolve()))
            self.assertEqual(official.env["CODEX_HOME"], str(home_b.resolve()))
            self.assertNotIn("OPENAI_API_KEY", probe.env)
            self.assertNotIn("UNRELATED_SECRET", probe.env)
            self.assertEqual(probe.deputy_server_names, official.deputy_server_names)
            self.assertEqual(probe.deputy_server_names, (
                codex_runner.AGENTS_SERVER_NAME, codex_runner.WORKERS_SERVER_NAME,
            ))
            self.assertEqual(probe.config_sha256, official.config_sha256)
            self.assertNotEqual(probe.official, official.official)

    def test_isolated_configs_have_exact_arm_inventory_and_no_legacy_tables(self):
        target = Path("C:/synthetic fixture/target")
        run_root = Path("C:/synthetic fixture/run")
        repository = Path("C:/source repository")
        python = Path("C:/python/python.exe")
        deputy_text, names = codex_runner.render_config("DEPUTY", target, run_root, repository, python)
        deputy = codex_runner.validate_config_text(deputy_text, "DEPUTY")
        self.assertEqual(set(deputy["mcp_servers"]), {
            codex_runner.AGENTS_SERVER_NAME, codex_runner.WORKERS_SERVER_NAME,
        })
        self.assertEqual(set(names), set(deputy["mcp_servers"]))
        self.assertEqual(
            set(deputy["mcp_servers"][codex_runner.AGENTS_SERVER_NAME]["args"]),
            {str(repository / "agents" / "server.py")},
        )
        self.assertEqual(
            set(deputy["mcp_servers"][codex_runner.WORKERS_SERVER_NAME]["args"]),
            {str(repository / "workers" / "server.py")},
        )
        for legacy in codex_runner.FORBIDDEN_SERVERS:
            self.assertNotIn(legacy, deputy_text)
        direct_text, direct_names = codex_runner.render_config(
            "DIRECT", target, run_root, repository, python,
        )
        direct_config = codex_runner.validate_config_text(direct_text, "DIRECT")
        self.assertEqual(direct_config.get("mcp_servers", {}), {})
        self.assertEqual(direct_config["projects"][str(target.resolve())]["trust_level"], "trusted")
        self.assertEqual(direct_names, ())

    def test_canonical_argv_keeps_flags_atomic_and_rejects_legacy_disable_override(self):
        argv = codex_runner.build_exec_argv(
            "PROMPT", Path("C:/synthetic fixture/client").resolve(),
            codex_executable=codex_runner.CODEX_EXECUTABLE,
        )
        self.assertEqual(argv[0:2], (str(codex_runner.CODEX_EXECUTABLE), "exec"))
        self.assertEqual(argv.count("--skip-git-repo-check"), 1)
        self.assertNotIn("--ignore-user-config", argv)
        self.assertNotIn("--ask-for-approval", argv)
        self.assertEqual(argv.count("-c"), 1)
        self.assertEqual(argv[argv.index("-c") + 1], 'model_reasoning_effort="low"')
        with self.assertRaisesRegex(ValueError, "DISABLE_ONLY_MCP"):
            codex_runner._validate_argv(("codex.exe", "exec", "--skip-git-repo-check", "-c",
                                         "mcp_servers.deputy_agents_lab.enabled=false"))

    def test_fresh_and_resume_argv_match_codex_0155_option_support(self):
        cwd = Path("C:/synthetic fixture/client").resolve()
        fresh = codex_runner.build_exec_argv("FRESH", cwd)
        resume = codex_runner.build_resume_argv("00000000-0000-0000-0000-000000000001", "RESUME")
        self.assertIn("--cd", fresh)
        self.assertNotIn("--sandbox", fresh)
        self.assertNotIn("--cd", resume)
        self.assertNotIn("--sandbox", resume)
        for argv in (fresh, resume):
            self.assertIn("--json", argv)
            self.assertIn("--model", argv)
            self.assertIn(codex_runner.MODEL, argv)
            self.assertIn("--skip-git-repo-check", argv)
            self.assertNotIn("--ask-for-approval", argv)
            self.assertNotIn("--ignore-user-config", argv)
            self.assertEqual(argv[argv.index("-c") + 1], 'model_reasoning_effort="low"')
        self.assertEqual(resume[2], "resume")

    def test_resume_argv_is_accepted_by_installed_codex_cli_0155(self):
        codex = codex_runner.CODEX_EXECUTABLE
        if not codex.is_file():
            self.skipTest("Codex CLI executable unavailable")
        proc = subprocess.run([str(codex), "exec", "resume", "--help"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("Usage: codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]", proc.stdout)
        self.assertNotIn("--sandbox", proc.stdout)
        self.assertNotIn("--cd", proc.stdout)

    def test_codex_project_trust_mutation_changes_raw_hash_not_contract_hash(self):
        target = Path("C:/synthetic fixture/target")
        run_root = Path("C:/synthetic fixture/run")
        repository = Path("C:/source repository")
        python = Path("C:/python/python.exe")
        cwd = Path("C:/synthetic fixture/client").resolve()
        original, _ = codex_runner.render_config("DEPUTY", target, run_root, repository, python)
        mutated = original + f'\n[projects.{codex_runner._toml_string(str(cwd))}]\ntrust_level = "trusted"\n'
        self.assertNotEqual(
            codex_runner.hashlib.sha256(original.encode()).hexdigest(),
            codex_runner.hashlib.sha256(mutated.encode()).hexdigest(),
        )
        self.assertEqual(
            codex_runner.benchmark_config_contract_sha256(original, "DEPUTY", cwd),
            codex_runner.benchmark_config_contract_sha256(mutated, "DEPUTY", cwd),
        )
        before = codex_runner.validate_config_text(original, "DEPUTY", cwd)
        after = codex_runner.validate_config_text(mutated, "DEPUTY", cwd)
        self.assertTrue(codex_runner.validate_benchmark_config_transition(before, after, "DEPUTY", cwd))

        lower_case_mutation = original + (
            f"\n[projects.{codex_runner._toml_string(str(cwd).lower())}]\n"
            'trust_level = "trusted"\n'
        )
        after_lower_case = codex_runner.validate_config_text(lower_case_mutation, "DEPUTY", cwd)
        self.assertTrue(codex_runner.validate_benchmark_config_transition(
            before, after_lower_case, "DEPUTY", cwd,
        ))
        wrong_cwd = original + (
            f"\n[projects.{codex_runner._toml_string(str(cwd.parent / 'other'))}]\n"
            'trust_level = "trusted"\n'
        )
        after_wrong_cwd = codex_runner.tomllib.loads(wrong_cwd)
        self.assertFalse(codex_runner.validate_benchmark_config_transition(
            before, after_wrong_cwd, "DEPUTY", cwd,
        ))

    def test_benchmark_contract_changes_for_server_command(self):
        target, run_root, repository = Path("C:/target"), Path("C:/run"), Path("C:/repo")
        original, _ = codex_runner.render_config("DEPUTY", target, run_root, repository, Path("C:/python.exe"))
        command = codex_runner._toml_string(str(Path("C:/python.exe")))
        altered = original.replace(f"command = {command}", 'command = "C:/different/server.py"', 1)
        self.assertNotEqual(
            codex_runner.benchmark_config_contract_sha256(original, "DEPUTY"),
            codex_runner.benchmark_config_contract_sha256(altered, "DEPUTY"),
        )

    def test_legacy_registration_model_effort_and_sandbox_changes_fail_contract(self):
        original, _ = codex_runner.render_config(
            "DEPUTY", Path("C:/target"), Path("C:/run"), Path("C:/repo"), Path("C:/python.exe"),
        )
        invalid_configs = (
            original + '\n[mcp_servers.deputy_agents_lab]\nenabled = true\ncommand = "x"\nargs = ["x"]\ncwd = "x"\nenv = {}\n',
            original.replace('model = "gpt-6-luna"', 'model = "other-model"'),
            original.replace('model_reasoning_effort = "low"', 'model_reasoning_effort = "high"'),
            original.replace('sandbox_mode = "workspace-write"', 'sandbox_mode = "danger-full-access"'),
            original.replace('sandbox = "unelevated"', 'sandbox = "elevated"'),
        )
        for config in invalid_configs:
            with self.subTest(config=config[:45]), self.assertRaises(ValueError):
                codex_runner.benchmark_config_contract_sha256(config, "DEPUTY")

    def test_session_start_and_resume_share_home_config_and_durable_process_evidence(self):
        class FakeProcess:
            pid = 4242

            def __init__(self, on_wait=None):
                self.on_wait = on_wait

            def wait(self, timeout=None):
                if self.on_wait:
                    self.on_wait()
                return 0

        with tempfile.TemporaryDirectory(prefix="codex-session-runner-") as temp:
            root = Path(temp)
            repository = root / "source"
            target = root / "fixture"
            run_root = root / "runtime"
            client = root / "client"
            home = root / "isolated-home"
            auth = root / "account-auth.json"
            for path in (repository, target, run_root, client):
                path.mkdir()
            auth.write_text('{"synthetic-auth-fixture":true}', encoding="utf-8")
            plan = codex_runner.build_launch_plan(
                prompt="STAGE_A", arm="DEPUTY", target=target, run_root=run_root,
                config_home=home, working_directory=client, repository_root=repository,
                server_python=root / "python.exe", official=False,
                base_environment={"PATH": "C:/Windows/System32", "USERPROFILE": str(root)},
                auth_source=auth,
            )
            runner = codex_runner.CodexSessionRunner(plan)
            records = [root / "stage-a-process.json", root / "stage-b-process.json"]

            changed_runtime_state = False

            def fake_popen(argv, **kwargs):
                is_resume = "resume" in argv

                def add_codex_project_trust():
                    nonlocal changed_runtime_state
                    if not is_resume and not changed_runtime_state:
                        with plan.config_path.open("a", encoding="utf-8") as stream:
                            stream.write(
                                f'\n[projects.{codex_runner._toml_string(str(client.resolve()).lower())}]\n'
                                'trust_level = "trusted"\n'
                            )
                        changed_runtime_state = True
                return FakeProcess(add_codex_project_trust)

            with mock.patch.object(codex_runner.subprocess, "Popen", side_effect=fake_popen) as popen:
                start = runner.start_session(root / "a.jsonl", root / "a.stderr", records[0])
                resume_plan = codex_runner.build_launch_plan(
                    prompt="STAGE_B", arm="DEPUTY", target=target, run_root=run_root,
                    config_home=home, working_directory=client, repository_root=repository,
                    server_python=root / "python.exe", official=False,
                    base_environment={"PATH": "C:/Windows/System32", "USERPROFILE": str(root)},
                    auth_source=auth, reuse_config_home=True,
                )
                resume = codex_runner.CodexSessionRunner(resume_plan).resume_session(
                    "00000000-0000-0000-0000-000000000001", "STAGE_B",
                    root / "b.jsonl", root / "b.stderr", records[1],
                )
                self.assertEqual(popen.call_count, 2)
            self.assertEqual((start["exit_code"], resume["exit_code"]), (0, 0))
            persisted = [json.loads(path.read_text(encoding="utf-8")) for path in records]
            self.assertEqual(persisted[0]["config_home"], persisted[1]["config_home"])
            self.assertEqual(persisted[0]["config_path"], persisted[1]["config_path"])
            self.assertNotEqual(persisted[0]["config_sha256"], persisted[1]["config_sha256"])
            self.assertEqual(persisted[0]["exit_code"], 0)
            self.assertEqual(persisted[1]["exit_code"], 0)
            self.assertTrue(persisted[0]["config_contract_unchanged"])
            self.assertTrue(persisted[1]["config_contract_unchanged"])
            self.assertNotEqual(persisted[0]["raw_config_before_sha256"],
                                persisted[0]["raw_config_after_sha256"])
            self.assertEqual(persisted[0]["config_contract_sha256"],
                             persisted[1]["config_contract_sha256"])
            state = json.loads(records[0].with_name("stage-a-process-config-state.json").read_text())
            self.assertTrue(state["raw_bytes_changed"])
            self.assertEqual(state["benchmark_config_contract_sha256_before"],
                             state["benchmark_config_contract_sha256_after"])
            self.assertNotIn("--sandbox", persisted[1]["argv"])
            self.assertNotIn("--cd", persisted[1]["argv"])
            config = codex_runner.validate_config_text(plan.config_path.read_text(encoding="utf-8"), "DEPUTY")
            self.assertEqual(config["model"], "gpt-6-luna")
            self.assertEqual(config["model_reasoning_effort"], "low")
            self.assertEqual(config["sandbox_mode"], "workspace-write")
            self.assertEqual(config["windows"]["sandbox"], "unelevated")
            self.assertEqual(set(config["mcp_servers"]), {
                codex_runner.AGENTS_SERVER_NAME, codex_runner.WORKERS_SERVER_NAME,
            })
            codex_runner.remove_isolated_auth_copy(home, repository)

    def test_resume_refuses_security_relevant_config_change_before_process_launch(self):
        class FakeProcess:
            pid = 6161

            @staticmethod
            def wait(timeout=None):
                return 0

        with tempfile.TemporaryDirectory(prefix="codex-config-contract-") as temp:
            root = Path(temp)
            repository, target, run_root, client = [root / n for n in ("repo", "target", "run", "client")]
            for path in (repository, target, run_root, client):
                path.mkdir()
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            plan = codex_runner.build_launch_plan(
                prompt="STAGE_A", arm="DEPUTY", target=target, run_root=run_root,
                config_home=root / "home", working_directory=client, repository_root=repository,
                server_python=root / "python.exe", official=False,
                base_environment={"PATH": "C:/Windows/System32", "USERPROFILE": str(root)},
                auth_source=auth,
            )
            config = plan.config_path.read_text(encoding="utf-8")
            original_command = codex_runner._toml_string(str(root / "python.exe"))
            plan.config_path.write_text(
                config.replace(f"command = {original_command}", 'command = "C:/unauthorized/server.py"', 1),
                encoding="utf-8",
            )
            record = root / "resume-process.json"
            with mock.patch.object(codex_runner.subprocess, "Popen", return_value=FakeProcess()) as popen:
                with self.assertRaisesRegex(RuntimeError, "CONTRACT_CHANGED_BEFORE_LAUNCH"):
                    codex_runner.CodexSessionRunner(plan).resume_session(
                        "00000000-0000-0000-0000-000000000001", "STAGE_B",
                        root / "out.jsonl", root / "err.txt", record,
                    )
                popen.assert_not_called()
            state = json.loads(record.with_name("resume-process-config-state.json").read_text())
            self.assertFalse(state["benchmark_contract_unchanged"])
            self.assertEqual(state["config_validation"], "CONTRACT_CHANGED_BEFORE_LAUNCH")
            codex_runner.remove_isolated_auth_copy(plan.config_home, repository)

    def test_process_exit_is_persisted_before_derived_postprocessing_failure(self):
        class FakeProcess:
            pid = 5151

            @staticmethod
            def wait(timeout=None):
                return 7

        with tempfile.TemporaryDirectory(prefix="codex-process-evidence-") as temp:
            root = Path(temp)
            repository, target, run_root, client = [root / name for name in ("repo", "target", "run", "client")]
            for path in (repository, target, run_root, client):
                path.mkdir()
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            plan = codex_runner.build_launch_plan(
                prompt="FIXED", arm="DIRECT", target=target, run_root=run_root,
                config_home=root / "home", working_directory=target, repository_root=repository,
                server_python=root / "python.exe", official=False,
                base_environment={"PATH": "C:/Windows/System32", "USERPROFILE": str(root)},
                auth_source=auth,
            )
            process_record = root / "process.json"
            with mock.patch.object(codex_runner.subprocess, "Popen", return_value=FakeProcess()):
                codex_runner.run_plan(plan, target, root / "out.jsonl", root / "err.txt",
                                      process_record_path=process_record)
            with self.assertRaisesRegex(RuntimeError, "POSTPROCESSING_FAILURE"):
                raise RuntimeError("POSTPROCESSING_FAILURE")
            persisted = json.loads(process_record.read_text(encoding="utf-8"))
            self.assertEqual(persisted["exit_code"], 7)
            self.assertEqual(persisted["pid"], 5151)
            self.assertTrue(persisted["started_utc"] and persisted["ended_utc"])
            self.assertTrue(Path(persisted["stdout_jsonl_path"]).is_file())
            self.assertTrue(Path(persisted["stderr_path"]).is_file())
            codex_runner.remove_isolated_auth_copy(plan.config_home, repository)

    def test_canonical_event_parser_extracts_answer_and_authoritative_usage(self):
        raw = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "synthetic-session"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2,
                                                              "cached_input_tokens": 3}}),
            "not-json",
        ])
        events = codex_runner.parse_jsonl(raw)
        self.assertEqual(codex_runner.final_message(events), "OK")
        self.assertEqual(codex_runner.turn_usage(events), [{
            "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 3,
        }])

    def test_generated_exec_options_are_accepted_by_installed_codex_cli(self):
        codex = codex_runner.CODEX_EXECUTABLE
        if not codex.is_file():
            self.skipTest("Codex CLI executable unavailable")
        argv = list(codex_runner.build_exec_argv(
            "PROMPT", Path.cwd(), codex_executable=codex,
        ))
        argv[-1] = "--help"
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("Run Codex non-interactively", proc.stdout)

    def test_e1_known_answer_and_malformed_or_wrong_values(self):
        answer = benchmark.expected("E1", self.root)
        self.assertEqual(benchmark.grade("E1", answer, self.root)["status"], "PASS")
        self.assertEqual(benchmark.grade("E1", {**answer, "extra": 1}, self.root)["status"], "FAIL")
        self.assertEqual(benchmark.grade("E1", {**answer, "size_bytes": True}, self.root)["status"], "FAIL")
        self.assertEqual(benchmark.grade("E1", {"case_id": "E1"}, self.root)["status"], "FAIL")

    def test_e2_git_answer_independent_of_worker(self):
        answer = benchmark.expected("E2", self.root)
        self.assertEqual(answer["dirty"], False)
        self.assertEqual(benchmark.grade("E2", answer, self.root)["status"], "PASS")
        self.assertEqual(benchmark.grade("E2", {**answer, "dirty": True}, self.root)["status"], "FAIL")

    def test_e3_separate_junit_parser_and_exact_failure_identity(self):
        answer = benchmark.expected("E3", self.root)
        self.assertEqual((answer["tests"], answer["failures"], answer["errors"], answer["skipped"]), (6, 1, 1, 1))
        self.assertEqual(benchmark.grade("E3", answer, self.root)["status"], "PASS")
        self.assertEqual(benchmark.grade("E3", {**answer, "failing_testcases": []}, self.root)["status"], "FAIL")
        self.assertEqual(benchmark.grade("E3", {**answer, "tests": True}, self.root)["status"], "FAIL")

    def test_e4_allowlisted_paths_and_exact_semantics(self):
        answer = benchmark.expected("E4", self.root)
        self.assertEqual(benchmark.grade("E4", answer, self.root)["status"], "PASS")
        changed = json.loads(json.dumps(answer)); changed["facts"]["caller_selects_argv"]["evidence"] = "README.md"
        self.assertEqual(benchmark.grade("E4", changed, self.root)["status"], "FAIL")
        changed = json.loads(json.dumps(answer)); changed["facts"]["generic_shell_exposed"]["value"] = 0
        self.assertEqual(benchmark.grade("E4", changed, self.root)["status"], "FAIL")

    def test_e4_accepts_directly_inspected_authoritative_source_paths(self):
        answer = benchmark.expected("E4", self.root)
        answer["facts"]["caller_selects_arbitrary_path"]["evidence"] = (
            "app/src/main/java/benchmark/privacy/SourceSelector.kt"
        )
        answer["facts"]["generic_shell_exposed"]["evidence"] = (
            "app/src/main/java/benchmark/execution/Executor.kt"
        )
        self.assertEqual(benchmark.grade("E4", answer, self.root)["status"], "PASS")
        answer["facts"]["generic_shell_exposed"]["evidence"] = "README.md"
        self.assertEqual(benchmark.grade("E4", answer, self.root)["status"], "FAIL")

    def test_e5_exact_order_and_caller_pin_semantics(self):
        answer = benchmark.expected("E5", self.root)
        self.assertEqual(benchmark.grade("E5", answer, self.root)["status"], "PASS")
        changed = dict(answer); changed["ordered_stages"] = list(reversed(answer["ordered_stages"]))
        self.assertEqual(benchmark.grade("E5", changed, self.root)["status"], "FAIL")
        changed = dict(answer); changed["ordered_stages"] = ["initial source selection", *answer["ordered_stages"][1:]]
        self.assertEqual(benchmark.grade("E5", changed, self.root)["status"], "FAIL")
        prompt = json.loads((benchmark.CASES / "E5.json").read_text(encoding="utf-8"))["prompt"]
        for identifier in benchmark.E5_STAGES:
            self.assertIn(identifier, prompt)

    def test_e6_stage_a_and_b_graders(self):
        self.assertEqual(benchmark.grade("E6A", benchmark.expected("E6A", self.root), self.root)["status"], "PASS")
        expected = benchmark.expected("E6B", self.root)
        self.assertEqual(benchmark.grade("E6B", expected, self.root)["status"], "PASS")
        wrong = {"case_id": "E6", "decision": "ACCEPT", "violations": []}
        self.assertEqual(benchmark.grade("E6B", wrong, self.root)["status"], "FAIL")
        wrong = {"case_id": "E6", "decision": "REJECT", "violations": ["CALLER_CONTROLS_EXECUTABLE", "CALLER_CONTROLS_ARGV"]}
        self.assertEqual(benchmark.grade("E6B", wrong, self.root)["status"], "FAIL")
        prompt = json.loads((benchmark.CASES / "E6.json").read_text(encoding="utf-8"))["stage_b"]
        for identifier in expected["violations"]:
            self.assertIn(identifier, prompt)

    def test_e6_prompt_and_validator_share_explicit_semantic_contract(self):
        case = json.loads((benchmark.CASES / "E6.json").read_text(encoding="utf-8"))
        direct = benchmark.prompt_for_arm(case, "DIRECT", "stage_a")
        deputy = benchmark.prompt_for_arm(case, "DEPUTY", "stage_a")
        for operation in ("CAPTURE_REPO_STATE", "CHECK_FILE", "HASH_ARTIFACT"):
            self.assertIn(operation, deputy)
        self.assertIn("exactly once each", deputy)
        self.assertIn("strictly sequentially", deputy)
        self.assertIn("CHECK_FILE with path tools/benchmark/proposal.json", deputy)
        self.assertIn("HASH_ARTIFACT with path tools/benchmark/proposal.json", deputy)
        self.assertIn("deputy_recon exactly once", deputy)
        for evidence in ("repository HEAD", "branch", "clean/dirty state", "diff-check result",
                         "proposal existence", "proposal byte size", "proposal SHA-256"):
            self.assertIn(evidence, direct)
            self.assertIn(evidence.split()[0], deputy)
        self.assertIn("proposal SHA-256", direct)
        self.assertIn("authority architecture is sufficiently evidenced", direct)
        self.assertNotIn("deputy_observe", direct)
        self.assertNotIn("deputy_recon", direct)
        self.assertIn("Use the normal local", direct)
        expected_a = benchmark.expected("E6A", self.root)
        self.assertEqual(expected_a["architecture_evidence_sufficient"], True)
        self.assertEqual(expected_a["repository_branch"], "benchmark/efficiency-v1")
        self.assertEqual(expected_a["proposal_size_bytes"], 96)
        self.assertTrue(expected_a["diff_check_pass"])
        self.assertFalse(expected_a["repository_dirty"])
        self.assertNotIn("architecture_ready", benchmark.expected("E6A", self.root))
        self.assertIn("same Codex conversation/session", case["stage_b"])
        self.assertIn("Using only the evidence already gathered", case["stage_b"])
        self.assertIn("Do not gather any additional evidence", case["stage_b"])
        self.assertIn("make no Deputy calls", case["stage_b"])
        for identifier in benchmark.EXPECTED_E6["violations"]:
            self.assertIn(identifier, case["stage_b"])
        described = [("deputy_observe", operation)
                     for operation in ("CAPTURE_REPO_STATE", "CHECK_FILE", "HASH_ARTIFACT")]
        described.append(("deputy_recon", None))
        self.assertCountEqual(described, benchmark.EXPECTED_E6_STAGE_A_TRACE)

    def test_e6_both_arms_share_semantics_and_stage_b_contract(self):
        case = json.loads((benchmark.CASES / "E6.json").read_text(encoding="utf-8"))
        stage_a_direct = benchmark.prompt_for_arm(case, "DIRECT", "stage_a")
        stage_a_deputy = benchmark.prompt_for_arm(case, "DEPUTY", "stage_a")
        stage_b_direct = benchmark.prompt_for_arm(case, "DIRECT", "stage_b")
        stage_b_deputy = benchmark.prompt_for_arm(case, "DEPUTY", "stage_b")
        self.assertEqual(stage_b_direct, stage_b_deputy)
        self.assertIn("same Codex conversation/session", stage_b_direct)
        self.assertIn("only the evidence already gathered during Stage A", stage_b_direct)
        for violation in ("CALLER_SELECTED_ARGV", "CALLER_SELECTED_EXECUTABLE"):
            self.assertIn(violation, stage_b_direct)
        self.assertIn("Do not make the final ACCEPT/REJECT decision", stage_a_direct)
        self.assertIn("Do not make the final ACCEPT/REJECT decision", stage_a_deputy)
        self.assertIn("architecture_evidence_sufficient", stage_a_direct)
        self.assertIn("architecture_evidence_sufficient", stage_a_deputy)

    def test_e6_protocol_rejects_missing_operation_or_agents_and_stage_b_calls(self):
        valid = self.valid_deputy_record("E6")
        self.assertEqual(benchmark.validate_protocol(valid)["status"], "PASS")
        for mutation in ("worker", "agents", "stage_b"):
            with self.subTest(mutation=mutation):
                record = self.valid_deputy_record("E6")
                execution = record["execution"]
                if mutation == "worker":
                    execution["deputy_tool_trace"] = [entry for entry in execution["deputy_tool_trace"]
                                                      if entry["operation"] != "CHECK_FILE"]
                    execution["workers_calls"] -= 1
                    execution["mcp_calls"] -= 1
                    execution["e6_stage_a_tool_trace"] = list(execution["deputy_tool_trace"])
                elif mutation == "agents":
                    execution["deputy_tool_trace"] = [entry for entry in execution["deputy_tool_trace"]
                                                      if entry["tool"] != "deputy_recon"]
                    execution["agents_calls"] = 0
                    execution["mcp_calls"] -= 1
                    execution["e6_stage_a_tool_trace"] = list(execution["deputy_tool_trace"])
                else:
                    execution["e6_stage_b_tool_trace"] = [{"tool": "deputy_recon", "operation": None}]
                self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")

    def test_e6_protocol_rejects_duplicate_extra_and_lifecycle_calls(self):
        for tool_entry in ({"tool": "deputy_observe", "operation": "CHECK_FILE"},
                           {"tool": "deputy_act", "operation": "GRADLE"},
                           {"tool": "deputy_worker_start", "operation": None}):
            with self.subTest(tool_entry=tool_entry):
                record = self.valid_deputy_record("E6")
                record["execution"]["deputy_tool_trace"].append(tool_entry)
                record["execution"]["mcp_calls"] += 1
                record["execution"]["workers_calls"] += tool_entry["tool"] in {"deputy_observe", "deputy_act"}
                record["execution"]["e6_stage_a_tool_trace"].append(tool_entry)
                self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")

    def test_e6_direct_target_access_fails_independently(self):
        record = self.valid_deputy_record("E6")
        record["execution"]["direct_target_access"] = True
        result = benchmark.validate_protocol(record)
        self.assertEqual(result["status"], "BENCHMARK_PROTOCOL_VIOLATION")
        self.assertFalse(result["checks"]["deputy_arm_has_no_direct_target_access"])

        direct = benchmark.empty_run("E6", "DIRECT", 1, "test", "low")
        direct["execution"].update({"mcp_calls": 0, "direct_target_access": True})
        self.assertEqual(benchmark.validate_protocol(direct)["status"], "PASS")

    def test_campaign_record_loader_accepts_current_and_preserved_formats_only(self):
        temp = Path(tempfile.mkdtemp(prefix="campaign-record-loader-"))
        try:
            historical_dir = temp / "run-01-E1-DIRECT-R1"
            historical_dir.mkdir()
            historical = benchmark.empty_run("E1", "DIRECT", 1, "test", "low")
            (historical_dir / "record.json").write_text(json.dumps(historical), encoding="utf-8")
            current_dir = temp / "run-02-E1-DEPUTY-R1"
            current_dir.mkdir()
            current = benchmark.empty_run("E1", "DEPUTY", 1, "test", "low")
            (current_dir / "result.json").write_text(json.dumps(current), encoding="utf-8")
            self.assertEqual(len(benchmark.load_run_records(temp)), 2)
            (current_dir / "result.json").write_text('{"unrelated": true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CAMPAIGN_RECORD_SCHEMA_INVALID"):
                benchmark.load_run_records(temp)
        finally:
            shutil.rmtree(temp)

    def test_direct_protocol_rejects_deputy_calls_and_requires_target_access(self):
        record = benchmark.empty_run("E1", "DIRECT", 1, "test", "medium")
        record["execution"].update({"direct_target_access": True, "mcp_calls": 1})
        self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")
        record["execution"]["mcp_calls"] = 0
        self.assertEqual(benchmark.validate_protocol(record)["status"], "PASS")

    def test_authoritative_semantic_trace_table_covers_all_cases(self):
        self.assertEqual(set(benchmark.EXPECTED_DEPUTY_TRACE), {"E1", "E2", "E3", "E4", "E5", "E6"})
        for case, expected_trace in benchmark.EXPECTED_DEPUTY_TRACE.items():
            with self.subTest(case=case):
                record = self.valid_deputy_record(case)
                self.assertEqual(benchmark.validate_protocol(record)["status"], "PASS")
                self.assertEqual(len(expected_trace), record["execution"]["mcp_calls"])

    def test_each_deputy_case_rejects_missing_duplicate_extra_and_lifecycle_trace(self):
        for case, expected_trace in benchmark.EXPECTED_DEPUTY_TRACE.items():
            with self.subTest(case=case, defect="missing"):
                record = self.valid_deputy_record(case)
                record["execution"]["deputy_tool_trace"].pop()
                record["execution"]["mcp_calls"] -= 1
                tool = expected_trace[-1][0]
                record["execution"]["agents_calls" if tool == "deputy_recon" else "workers_calls"] -= 1
                self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")
            with self.subTest(case=case, defect="duplicate"):
                record = self.valid_deputy_record(case)
                record["execution"]["deputy_tool_trace"].append(dict(record["execution"]["deputy_tool_trace"][0]))
                record["execution"]["mcp_calls"] += 1
                tool = expected_trace[0][0]
                record["execution"]["agents_calls" if tool == "deputy_recon" else "workers_calls"] += 1
                self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")
            with self.subTest(case=case, defect="extra"):
                record = self.valid_deputy_record(case)
                record["execution"]["deputy_tool_trace"].append({"tool": "deputy_observe", "operation": "GIT_DIFF_CHECK"})
                record["execution"]["mcp_calls"] += 1
                record["execution"]["workers_calls"] += 1
                record["execution"]["required_subsystems_used"] = sorted(set(record["execution"]["required_subsystems_used"]) | {"workers"})
                self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")
            with self.subTest(case=case, defect="lifecycle"):
                record = self.valid_deputy_record(case)
                record["execution"]["deputy_tool_trace"].append({"tool": "deputy_worker_start", "operation": None})
                record["execution"]["mcp_calls"] += 1
                self.assertEqual(benchmark.validate_protocol(record)["status"], "BENCHMARK_PROTOCOL_VIOLATION")

    def test_direct_target_access_is_rejected_independently_of_valid_trace(self):
        record = self.valid_deputy_record("E1")
        self.assertEqual(benchmark.validate_protocol(record)["status"], "PASS")
        record["execution"]["direct_target_access"] = True
        result = benchmark.validate_protocol(record)
        self.assertEqual(result["status"], "BENCHMARK_PROTOCOL_VIOLATION")
        self.assertFalse(result["checks"]["deputy_arm_has_no_direct_target_access"])

    def test_e2_capture_repo_state_is_the_only_visible_worker_call(self):
        record = self.valid_deputy_record("E2")
        self.assertEqual(record["execution"]["deputy_tool_trace"], [
            {"tool": "deputy_observe", "operation": "CAPTURE_REPO_STATE"}])
        self.assertEqual(benchmark.validate_protocol(record)["status"], "PASS")
        service = (benchmark.HERE.parents[1] / "workers" / "worker_v1" / "service.py").read_text(encoding="utf-8")
        self.assertIn('"operation": "GIT_DIFF_CHECK"', service)
        self.assertIn('"diff_check_pass"', service)

    def test_preserved_d7_e1_trace_passes_without_mutating_historical_result(self):
        path = benchmark.HERE / "evidence" / "phase11d7-20261001" / "runs" / "run-01-E1-DEPUTY-R1" / "result.json"
        original = path.read_bytes()
        record = json.loads(original)
        corrected = json.loads(json.dumps(record))
        self.assertEqual([entry["operation"] for entry in corrected["execution"]["deputy_tool_trace"]],
                         ["CHECK_FILE", "HASH_ARTIFACT"])
        self.assertEqual(benchmark.validate_protocol(corrected)["status"], "PASS")
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(original).digest())

    def test_preserved_e6_semantic_trace_fixture_passes(self):
        record = self.valid_deputy_record("E6")
        self.assertEqual(benchmark.validate_protocol(record)["status"], "PASS")

    def test_missing_token_and_context_telemetry_stays_null(self):
        record = benchmark.enforce_missing_telemetry(benchmark.empty_run("E6", "DEPUTY", 1, "test", "medium"))
        self.assertIsNone(record["supervisor"]["total_tokens"])
        self.assertIsNone(record["context"]["peak_context_tokens"])
        self.assertIsNone(record["total_inference_tokens"])
        self.assertEqual(record["supervisor"]["token_telemetry"], "UNMEASURED")
        self.assertEqual(record["context"]["telemetry"], "UNMEASURED")
        self.assertEqual(record["delegate"]["token_telemetry"], "UNMEASURED")

    def test_partial_context_and_child_usage_are_not_promoted_or_zero_filled(self):
        record = benchmark.empty_run("E1", "DEPUTY", 1, "test", "medium")
        record["context"]["model_context_window"] = 128000
        record["delegate"]["input_tokens"] = 900
        record["supervisor"]["total_tokens"] = 1200
        normalized = benchmark.enforce_missing_telemetry(record)
        self.assertEqual(normalized["context"]["telemetry"], "PARTIAL")
        self.assertEqual(normalized["delegate"]["token_telemetry"], "PARTIAL")
        self.assertIsNone(normalized["delegate"]["output_tokens"])
        self.assertIsNone(normalized["total_inference_tokens"])

    def test_cached_and_reasoning_counters_are_not_double_counted(self):
        record = benchmark.empty_run("E1", "DEPUTY", 1, "test", "medium")
        sup = record["supervisor"]; sup.update({k: 0 for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")}); sup["total_tokens"] = 100; sup["token_telemetry"] = "MEASURED"
        dep = record["delegate"]; dep.update({"input_tokens": 20, "cache_read_tokens": 10, "cache_write_tokens": 3, "output_tokens": 5, "reasoning_tokens": 2, "token_telemetry": "MEASURED"})
        self.assertEqual(benchmark.enforce_missing_telemetry(record)["total_inference_tokens"], 125)

    def test_fixture_is_deterministic_and_git_clean(self):
        with tempfile.TemporaryDirectory(prefix="efficiency-fixture-two-") as temp:
            second = Path(temp) / "repo"
            info = benchmark.prepare_fixture(second)
            self.assertEqual(info["head"], self.info["head"])
            self.assertEqual(info["fixture_sha256"], self.info["fixture_sha256"])
            self.assertFalse(benchmark.capture_repo(second)["dirty"])

    def test_deputy_arm_workspace_is_created_empty_and_disjoint(self):
        with tempfile.TemporaryDirectory(prefix="efficiency-arm-") as temp:
            client = Path(temp) / "deputy-client"
            plan = benchmark.prepare_arm_plan("DEPUTY", self.root, client)
            self.assertFalse(plan["target_repository_visible_to_supervisor"])
            self.assertTrue(plan["workspaces_disjoint"])
            self.assertEqual(list(client.iterdir()), [])
            self.assertFalse((client / "tools/benchmark/payload.txt").exists())
            self.assertFalse(plan["mcp_registration_changed"])
            with self.assertRaises(ValueError):
                benchmark.prepare_arm_plan("DEPUTY", self.root, self.root / "client")

    def test_generated_junit_outputs_are_ignored(self):
        state = benchmark.capture_repo(self.root)
        self.assertFalse(state["dirty"])
        self.assertNotIn("app/build/test-results/testDebugUnitTest/TEST-benchmark-a.xml", state["files"])

    def test_fixture_has_synthetic_only_authority_and_pipeline_evidence(self):
        texts = "\n".join(p.read_text(encoding="utf-8") for p in self.root.rglob("*.kt"))
        self.assertIn("CapabilityRegistry.resolve", texts)
        self.assertIn("CoherenceVerifier.sameBytes", texts)
        self.assertIn("ProviderContract.invoke", texts)
        self.assertNotIn("ProcessBuilder", texts)
        self.assertNotIn("Runtime.getRuntime", texts)

    def test_pipeline_implementation_orders_all_e5_stages(self):
        path = self.root / "app/src/main/java/benchmark/privacy/Publisher.kt"
        source = path.read_text(encoding="utf-8")
        markers = ["SourceSelector.select", "SnapshotBuilder.copyCandidate", "SecretScanner.scan",
                   "val sourceAfterValidation", "CoherenceVerifier.sameBytes", "SnapshotBuilder.publish",
                   "ProviderContract.invoke"]
        positions = [source.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_campaign_schedule_is_deterministic_balanced_and_60_runs(self):
        order = benchmark.campaign_order(5)
        self.assertEqual(len(order), 60)
        self.assertEqual(order, benchmark.campaign_order(5))
        for case in ("E1", "E2", "E3", "E4", "E5", "E6"):
            subset = [x for x in order if x["case_id"] == case]
            self.assertEqual([x["arm"] for x in subset].count("DIRECT"), 5)
            self.assertEqual([x["arm"] for x in subset].count("DEPUTY"), 5)

    def test_aggregate_reports_failures_and_does_not_claim_unmeasured_savings(self):
        record = benchmark.empty_run("E1", "DIRECT", 1, "test", "medium")
        out = benchmark.aggregate([record])
        self.assertEqual(out["cases"]["E1"]["DIRECT"]["blocked"], 1)
        self.assertEqual(out["overall_paired_comparisons"]["supervisor_token_reduction"]["status"], "UNMEASURED")

    def test_finalize_marks_protocol_violation_before_answer_correctness(self):
        record = benchmark.empty_run("E1", "DIRECT", 1, "test", "medium")
        record["execution"]["direct_target_access"] = True
        record["execution"]["mcp_calls"] = 1
        finalized = benchmark.finalize_record(record, "E1", benchmark.expected("E1", self.root), self.root)
        self.assertEqual(finalized["result"]["status"], "BENCHMARK_PROTOCOL_VIOLATION")

    def test_finalize_keeps_e6_stage_case_identity(self):
        record = benchmark.empty_run("E6", "DIRECT", 1, "test", "medium")
        record["execution"]["direct_target_access"] = True
        finalized = benchmark.finalize_record(
            record, "E6A", benchmark.expected("E6A", self.root), self.root
        )
        self.assertEqual(finalized["result"]["status"], "PASS")

    def test_aggregate_computes_reductions_only_from_measured_passing_pairs(self):
        records = []
        for arm, tokens, ctx, total in (("DIRECT", 100, 80, 100), ("DEPUTY", 60, 40, 130)):
            record = benchmark.empty_run("E1", arm, 1, "test", "medium")
            record["result"]["status"] = "PASS"
            record["supervisor"].update({"total_tokens": tokens, "token_telemetry": "MEASURED"})
            record["context"].update({"context_growth_tokens": ctx, "telemetry": "MEASURED"})
            record["total_inference_tokens"] = total
            records.append(record)
        comparison = benchmark.aggregate(records)["cases"]["E1"]["paired_comparisons"]
        self.assertEqual(comparison["supervisor_token_reduction"]["mean_absolute_reduction"], 40)
        self.assertEqual(comparison["supervisor_context_growth_reduction"]["mean_absolute_reduction"], 40)
        self.assertEqual(comparison["total_inference_token_change"]["mean_absolute_reduction"], -30)

    def test_raw_evidence_patterns_are_ignored(self):
        ignore = (benchmark.HERE.parents[1] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("benchmarks/efficiency/evidence/", ignore)
        self.assertIn("benchmarks/efficiency/runtime/", ignore)

    def test_result_schema_and_missing_case_fields_are_rejected(self):
        schema = json.loads((benchmark.HERE / "schemas/run.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "deputy.mcp.efficiency-run.v1")
        self.assertIn("context", schema["required"])
        self.assertIn("delegate", schema["required"])
        self.assertEqual(benchmark.grade("E5", {"case_id": "E5"}, self.root)["status"], "FAIL")
        result = benchmark.grade("E4", None, self.root)
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()

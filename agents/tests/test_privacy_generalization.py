from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import privacy
import snapshot
import source_policy


def synthetic_policy():
    return source_policy.parse_policy({
        "schema": source_policy.SCHEMA,
        "policy_id": "SYNTHETIC_FIXTURE_V1",
        "allowed_prefixes": ["src/", "docs/", "tests/"],
        "allowed_root_files": ["README.md"],
        "excluded_prefixes": ["src/private/"],
        "approved_untracked": ["tests/approved.txt"],
        "limits": {"max_file_bytes": 4096, "max_file_count": 100, "max_total_bytes": 8192},
    })


class SourcePolicyAndPrivacyTests(unittest.TestCase):
    def _install_snapshot_fixture(self, temp):
        root = Path(temp) / "repo"
        root.mkdir()
        self._init_repo(root)
        (root / "src").mkdir()
        (root / "src/safe.txt").write_text("synthetic safe source", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        master = Path(temp) / "state" / "master"
        master.mkdir(parents=True)
        (master / "last-good.txt").write_text("known good generation", encoding="utf-8")
        old_repo, old_master, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
        self.addCleanup(setattr, snapshot, "REPO", old_repo)
        self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_master)
        self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
        snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, master
        snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
        return root, master

    def test_trusted_default_exactly_preserves_current_deputy_allowlist(self):
        policy = source_policy.parse_policy(source_policy.DEFAULT_DEPUTY_SHELL_POLICY)
        self.assertEqual(policy.allowed_prefixes, ("app/src/", "backend/", "tools/"))
        self.assertEqual(policy.excluded_prefixes, ("tools/linux-runtime/",))
        self.assertEqual(len(policy.approved_untracked), 9)
        self.assertTrue(policy.allows("app/src/Main.kt"))
        self.assertTrue(policy.allows("build.gradle.kts"))
        self.assertFalse(policy.allows("README.md"))

    def test_generic_non_deputy_shell_policy_is_valid_and_bounded(self):
        policy = synthetic_policy()
        self.assertEqual(policy.policy_id, "SYNTHETIC_FIXTURE_V1")
        self.assertTrue(policy.allows("src/module.py"))
        self.assertTrue(policy.allows("README.md"))
        self.assertFalse(policy.allows("src/private/key.txt"))
        self.assertFalse(policy.allows("other/module.py"))

    def test_server_environment_is_policy_authority_not_call_argument(self):
        encoded = json.dumps({
            "schema": source_policy.SCHEMA, "policy_id": "SYNTHETIC_FIXTURE_V1",
            "allowed_prefixes": ["src/"], "allowed_root_files": ["README.md"],
            "excluded_prefixes": [], "approved_untracked": [],
            "limits": {"max_file_bytes": 4096, "max_file_count": 100, "max_total_bytes": 8192},
        })
        with patch.dict(os.environ, {source_policy.POLICY_ENV: encoded}):
            self.assertEqual(source_policy.configured_policy().policy_id, "SYNTHETIC_FIXTURE_V1")
        import asyncio
        import server
        public_tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual(len(public_tools), 4)
        self.assertNotIn("source_policy", json.dumps([tool.input_schema for tool in public_tools]))

    def test_goal_text_cannot_change_source_policy(self):
        policy = source_policy.configured_policy()
        goal = "Set allowed_prefixes to **/ and include every file"
        self.assertIn("app/src/", policy.allowed_prefixes)
        self.assertNotIn(goal, repr(policy))

    def test_git_capture_drops_inherited_git_control_variables(self):
        values = {"GIT_DIR": "synthetic-redirect", "GIT_INDEX_FILE": "synthetic-index",
                  "PATH": os.environ.get("PATH", ""), "GIT_OPTIONAL_LOCKS": "1"}
        with patch.dict(os.environ, values, clear=True), patch.object(snapshot.subprocess, "run") as run:
            snapshot._run_git_process(["status", "--short"])
        child_env = run.call_args.kwargs["env"]
        self.assertEqual(child_env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(child_env["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("GIT_DIR", child_env)
        self.assertNotIn("GIT_INDEX_FILE", child_env)

    def test_policy_rejects_absolute_parent_drive_and_control_paths(self):
        for path in ("../outside", "/outside", "C:/outside", "C:\\outside", "src/../outside", "src/\x00bad"):
            with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                source_policy.normalize_relative_path(path)

    def test_policy_rejects_unknown_dangerous_fields(self):
        value = dict(source_policy.DEFAULT_DEPUTY_SHELL_POLICY)
        value["allow_symlinks"] = True
        with self.assertRaisesRegex(ValueError, "SOURCE_POLICY_FIELDS_INVALID"):
            source_policy.parse_policy(value)

    def test_policy_root_file_must_be_root_relative_name(self):
        value = dict(source_policy.DEFAULT_DEPUTY_SHELL_POLICY)
        value["allowed_root_files"] = ["src/nested.txt"]
        with self.assertRaisesRegex(ValueError, "SOURCE_POLICY_ROOT_FILE_INVALID"):
            source_policy.parse_policy(value)

    def test_policy_rejects_empty_or_dangerously_broad_limits(self):
        value = dict(source_policy.DEFAULT_DEPUTY_SHELL_POLICY)
        value.update(allowed_prefixes=[], allowed_root_files=[])
        with self.assertRaisesRegex(ValueError, "SOURCE_POLICY_EMPTY_OR_BROAD"):
            source_policy.parse_policy(value)
        value = dict(source_policy.DEFAULT_DEPUTY_SHELL_POLICY)
        value["limits"] = dict(value["limits"], max_total_bytes=10**12)
        with self.assertRaisesRegex(ValueError, "SOURCE_POLICY_LIMIT_INVALID"):
            source_policy.parse_policy(value)

    def test_policy_rejects_malformed_and_unapproved_untracked(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_POLICY_JSON_INVALID"):
            with patch.dict(os.environ, {source_policy.POLICY_ENV: "{"}):
                source_policy.configured_policy()
        value = dict(source_policy.DEFAULT_DEPUTY_SHELL_POLICY)
        value["approved_untracked"] = ["outside/approved.txt"]
        with self.assertRaisesRegex(ValueError, "SOURCE_POLICY_APPROVED_PATH_OUTSIDE_ALLOWLIST"):
            source_policy.parse_policy(value)

    def test_filename_filter_remains_hard_policy(self):
        self.assertTrue(snapshot._is_sensitive("src/config/token.txt"))
        self.assertTrue(snapshot._is_sensitive("local.properties"))
        self.assertFalse(snapshot._is_sensitive("src/module.py"))

    def test_ordinary_password_and_token_words_do_not_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ordinary.txt").write_text("password and token are ordinary documentation words", encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": "ordinary.txt"}])
        self.assertEqual(result["blocking_finding_count"], 0)
        self.assertEqual(result["status"], "PASS")

    def test_email_and_personal_path_are_warnings_not_secret_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            synthetic_path = "C:" + chr(92) + "Users" + chr(92) + "SyntheticUser" + chr(92) + "repo" + chr(92)
            (root / "notes.txt").write_text("synthetic contact " + "user@" + "example.invalid at " + synthetic_path, encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": "notes.txt"}])
        self.assertEqual(result["blocking_finding_count"], 0)
        self.assertEqual(result["pii_warning_count"], 2)
        self.assertEqual({item["warning_id"] for item in result["pii_warnings"]},
                         {"EMAIL_ADDRESS_HEURISTIC", "PERSONAL_ABSOLUTE_PATH_HEURISTIC"})

    def test_private_key_fixture_blocks_without_recording_value(self):
        secret = "-" * 5 + "BEGIN " + "PRIVATE KEY" + "-" * 5
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "innocent.txt").write_text(secret + "\nsynthetic-body", encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": "innocent.txt"}])
        serialized = json.dumps(result)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocking_findings"][0]["detector_id"], "PRIVATE_KEY_PEM")
        self.assertNotIn(secret, serialized)
        self.assertNotIn("synthetic-body", serialized)

    def test_high_confidence_token_under_allowed_source_is_detected(self):
        secret = "ghp" + "_" + "S" * 28
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.txt").write_text("credential=" + secret, encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": "allowed.txt"}])
        self.assertEqual(result["blocking_findings"], [{"path": "allowed.txt", "detector_id": "GITHUB_TOKEN"}])
        self.assertNotIn(secret, json.dumps(result))

    def test_credential_shaped_candidate_path_is_blocked_and_redacted_from_audit(self):
        secret = "ghp" + "_" + "N" * 28
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rel = secret + ".txt"
            (root / rel).write_text("ordinary source", encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": rel}])
        serialized = json.dumps(result)
        self.assertEqual(result["blocking_finding_count"], 1)
        self.assertEqual(result["blocking_findings"][0]["detector_id"], "GITHUB_TOKEN")
        self.assertNotIn(secret, serialized)

    def _init_repo(self, root: Path):
        commands = (["git", "init", "--quiet", "--initial-branch=fixture"],
                    ["git", "config", "user.name", "Synthetic Fixture"],
                    ["git", "config", "user.email", "fixture@" + "example.invalid"])
        for command in commands:
            subprocess.run(command, cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_generic_repo_policy_builds_bounded_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            for rel, text in (("src/main.py", "safe source"), ("docs/guide.md", "safe docs"),
                              ("src/private/excluded.txt", "private"), ("README.md", "root"),
                              ("other/no.txt", "outside"), ("src/config/token.txt", "sensitive filename"),
                              ("src/data.bin", "binary")):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\x00binary" if rel.endswith(".bin") else text.encode())
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (root / "tests").mkdir()
            (root / "tests/approved.txt").write_text("approved synthetic untracked", encoding="utf-8")
            (root / "tests/unapproved.txt").write_text("not approved", encoding="utf-8")
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            master = Path(temp) / "state" / "master"
            snapshot.REPO = root
            snapshot.SNAPSHOT_ROOT = master
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            result = snapshot.create_snapshot(policy=synthetic_policy(), privacy_audit_path=Path(temp) / "privacy.json")
            included = {item["path"] for item in result["manifest"]["files"]}
            self.assertEqual(included, {"src/main.py", "docs/guide.md", "README.md", "tests/approved.txt"})
            self.assertFalse((master / "tests/unapproved.txt").exists())
            self.assertNotIn("repo_root_verified", json.dumps(result["audit"]))
            self.assertEqual(result["manifest"]["policy_version"], "DA-PRIVACY-1-positive-policy-v1")

    def test_approved_path_that_becomes_tracked_is_included_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src").mkdir()
            (root / "src/safe.txt").write_text("tracked", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests/approved.txt").write_text("now tracked", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, Path(temp) / "state" / "master"
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            result = snapshot.create_snapshot(policy=synthetic_policy())
            paths = [item["path"] for item in result["manifest"]["files"]]
            self.assertEqual(paths.count("tests/approved.txt"), 1)

    def test_secret_candidate_is_blocked_before_publication_and_last_good_survives(self):
        secret = "ghp" + "_" + "Q" * 28
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src").mkdir()
            (root / "src/allowed.txt").write_text("safe", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (root / "src/allowed.txt").write_text(secret, encoding="utf-8")
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            master = Path(temp) / "state" / "master"
            master.mkdir(parents=True)
            (master / "last-good.txt").write_text("known good", encoding="utf-8")
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, master
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            audit_path = Path(temp) / "privacy-scan.json"
            with self.assertRaises(privacy.ContentPolicyBlocked) as raised:
                snapshot.create_snapshot(policy=synthetic_policy(), privacy_audit_path=audit_path)
            self.assertEqual(str(raised.exception), "SNAPSHOT_CONTENT_POLICY_BLOCKED")
            self.assertTrue((master / "last-good.txt").is_file())
            self.assertFalse(master.with_name("master.candidate").exists())
            audit = audit_path.read_text(encoding="utf-8")
            self.assertIn("GITHUB_TOKEN", audit)
            self.assertNotIn(secret, audit)

    def test_approved_untracked_secret_is_blocked(self):
        secret = "ghp" + "_" + "U" * 28
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src").mkdir()
            (root / "src/safe.txt").write_text("safe", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (root / "tests").mkdir()
            (root / "tests/approved.txt").write_text(secret, encoding="utf-8")
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, Path(temp) / "state" / "master"
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            with self.assertRaises(privacy.ContentPolicyBlocked):
                snapshot.create_snapshot(policy=synthetic_policy())
            self.assertFalse(snapshot.SNAPSHOT_ROOT.exists())

    def test_source_drift_during_scan_fails_coherence_without_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src").mkdir()
            source_file = root / "src/safe.txt"
            source_file.write_text("safe generation", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, Path(temp) / "state" / "master"
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            scan = privacy.scan_candidate
            def drift(candidate, records, checkpoint=None):
                result = scan(candidate, records, checkpoint)
                source_file.write_text("changed during scan", encoding="utf-8")
                return result
            with patch.object(snapshot, "scan_candidate", side_effect=drift):
                with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_SOURCE_CHANGED_DURING_CAPTURE"):
                    snapshot.create_snapshot(policy=synthetic_policy())
            self.assertFalse(snapshot.SNAPSHOT_ROOT.exists())

    def test_candidate_mutation_during_scan_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src").mkdir()
            (root / "src/safe.txt").write_text("safe generation", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, Path(temp) / "state" / "master"
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            scan = privacy.scan_candidate
            def mutate_candidate(candidate, records, checkpoint=None):
                result = scan(candidate, records, checkpoint)
                (candidate / "src/safe.txt").write_text("changed after scan", encoding="utf-8")
                return result
            with patch.object(snapshot, "scan_candidate", side_effect=mutate_candidate):
                with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_CANDIDATE_CHANGED_DURING_SCAN"):
                    snapshot.create_snapshot(policy=synthetic_policy())
            self.assertFalse(snapshot.SNAPSHOT_ROOT.exists())

    def test_prepublication_timeouts_preserve_last_good_and_never_leave_pass_audit(self):
        timeout_phases = (
            "SNAPSHOT_SOURCE_BEFORE_HASH",
            "SNAPSHOT_GIT_STATE_AFTER",
            "SNAPSHOT_PUBLISH_READY",
        )
        for stage in timeout_phases:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                _, master = self._install_snapshot_fixture(temp)
                audit_path = Path(temp) / "evidence" / "privacy-scan.json"
                timings_path = Path(temp) / "evidence" / "preparation-timings.json"

                def stop_at_phase(name):
                    if name == stage:
                        raise snapshot.PreparationTimeout("PREPARATION_TIMEOUT")

                with self.assertRaises(snapshot.PreparationTimeout):
                    snapshot.create_snapshot(
                        deadline=time.monotonic() + 10,
                        phase_callback=stop_at_phase, policy=synthetic_policy(),
                        privacy_audit_path=audit_path, timings_path=timings_path,
                        job_destination=Path(temp) / "job" / "snapshot",
                    )
                self.assertEqual((master / "last-good.txt").read_text(encoding="utf-8"), "known good generation")
                self.assertFalse(audit_path.exists())
                self.assertEqual(json.loads(timings_path.read_text(encoding="utf-8"))["status"], "TIMEOUT")
                self.assertFalse(master.with_name("master.candidate").exists())
                self.assertFalse((Path(temp) / "job" / "snapshot").exists())
                self.assertFalse((Path(temp) / "job" / "snapshot.candidate").exists())

    def test_interrupted_publication_backup_is_restored_before_preparation_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            _, master = self._install_snapshot_fixture(temp)
            backup = master.with_name(master.name + ".backup")
            master.replace(backup)

            def timeout_at_first_gate(name):
                if name == "SNAPSHOT_GIT_STATE_BEFORE":
                    raise snapshot.PreparationTimeout("PREPARATION_TIMEOUT")

            with self.assertRaises(snapshot.PreparationTimeout):
                snapshot.create_snapshot(
                    deadline=time.monotonic() + 10,
                    phase_callback=timeout_at_first_gate,
                    policy=synthetic_policy(),
                )
            self.assertTrue(master.is_dir())
            self.assertEqual((master / "last-good.txt").read_text(encoding="utf-8"),
                             "known good generation")
            self.assertFalse(backup.exists())

    def test_timeout_during_content_scan_discards_candidate_and_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            _, master = self._install_snapshot_fixture(temp)
            audit_path = Path(temp) / "evidence" / "privacy-scan.json"
            def timeout_during_scan(candidate, records, checkpoint=None):
                if checkpoint:
                    checkpoint()
                raise snapshot.PreparationTimeout("PREPARATION_TIMEOUT")

            with patch.object(snapshot, "scan_candidate", side_effect=timeout_during_scan):
                with self.assertRaises(snapshot.PreparationTimeout):
                    snapshot.create_snapshot(
                        deadline=time.monotonic() + 10,
                        policy=synthetic_policy(), privacy_audit_path=audit_path,
                        job_destination=Path(temp) / "job" / "snapshot",
                    )
            self.assertEqual((master / "last-good.txt").read_text(encoding="utf-8"), "known good generation")
            self.assertFalse(audit_path.exists())
            self.assertFalse(master.with_name("master.candidate").exists())
            self.assertFalse((Path(temp) / "job" / "snapshot.candidate").exists())

    def test_publish_occurs_only_after_coherence_and_privacy_evidence_are_prepared(self):
        with tempfile.TemporaryDirectory() as temp:
            _, master = self._install_snapshot_fixture(temp)
            job_snapshot = Path(temp) / "job" / "snapshot"
            timings_path = Path(temp) / "evidence" / "preparation-timings.json"
            observed = []

            def observe_publish_gate(name):
                if name == "SNAPSHOT_PUBLISH_READY":
                    candidate = master.with_name("master.candidate")
                    manifest = json.loads((candidate / "snapshot-manifest.json").read_text(encoding="utf-8"))
                    audit = json.loads((candidate / "repo-state-and-audit.json").read_text(encoding="utf-8"))
                    privacy_audit = json.loads((candidate / "privacy-scan.json").read_text(encoding="utf-8"))
                    observed.append((manifest["coherence_status"], privacy_audit["status"], audit["privacy_scan"]["blocking_finding_count"], (master / "last-good.txt").exists()))

            result = snapshot.create_snapshot(
                deadline=time.monotonic() + 10,
                phase_callback=observe_publish_gate, policy=synthetic_policy(),
                job_destination=job_snapshot, timings_path=timings_path,
            )
            self.assertEqual(observed, [("PASS", "PASS", 0, True)])
            self.assertEqual(result["coherence"], "PASS")
            self.assertTrue((master / "snapshot-manifest.json").is_file())
            self.assertTrue((master / "privacy-scan.json").is_file())
            self.assertTrue((job_snapshot / "snapshot-manifest.json").is_file())
            self.assertTrue((job_snapshot / "privacy-scan.json").is_file())
            self.assertFalse((master / "last-good.txt").exists())
            timings = json.loads(timings_path.read_text(encoding="utf-8"))
            self.assertEqual(timings["status"], "PASS")
            self.assertGreaterEqual(timings["timings_ms"]["publication_ms"], 0)
            for name in ("git_state_before_ms", "source_selection_ms", "source_before_hash_ms", "candidate_copy_ms",
                         "candidate_hash_ms", "content_secret_scan_ms", "post_scan_candidate_hash_ms", "git_state_after_ms",
                         "source_after_hash_ms", "coherence_validate_ms", "privacy_evidence_prepare_ms",
                         "job_copy_ms", "stale_backup_cleanup_ms", "publication_ms", "total_refresh_ms"):
                self.assertIn(name, timings["timings_ms"])

    def test_failed_snapshot_preparation_never_starts_per_job_copy(self):
        from bridge import executor
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "job" / "snapshot"
            with patch.object(executor, "create_snapshot", side_effect=snapshot.PreparationTimeout("PREPARATION_TIMEOUT")), \
                    patch.object(executor.shutil, "copytree") as copytree:
                with self.assertRaises(snapshot.PreparationTimeout):
                    executor._prepare_snapshot(
                        "DEPUTY_SHELL", destination, "synthetic-job",
                        deadline=time.monotonic() + 10,
                        state={}, evdir=None, started=time.monotonic(),
                    )
            copytree.assert_not_called()
            self.assertFalse(destination.exists())

    def test_reparse_point_is_excluded_by_hard_safety_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src").mkdir()
            (root / "src/target.txt").write_text("safe", encoding="utf-8")
            (root / "src/link.txt").write_text("synthetic reparse placeholder", encoding="utf-8")
            subprocess.run(["git", "add", "-f", "src/target.txt", "src/link.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, Path(temp) / "state" / "master"
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            is_reparse = snapshot._is_reparse
            with patch.object(snapshot, "_is_reparse", side_effect=lambda path: path.name == "link.txt" or is_reparse(path)):
                result = snapshot.create_snapshot(policy=synthetic_policy())
            included = {item["path"] for item in result["manifest"]["files"]}
            self.assertIn("src/target.txt", included)
            self.assertNotIn("src/link.txt", included)

    def test_reparse_parent_component_is_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "src/linked").mkdir(parents=True)
            (root / "src/linked/file.txt").write_text("safe", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            snapshot.REPO, snapshot.SNAPSHOT_ROOT = root, Path(temp) / "state" / "master"
            snapshot.EVIDENCE_ROOT = Path(temp) / "evidence"
            is_reparse = snapshot._is_reparse
            with patch.object(snapshot, "_is_reparse", side_effect=lambda path: path.name == "linked" or is_reparse(path)):
                result = snapshot.create_snapshot(policy=synthetic_policy())
            included = {item["path"] for item in result["manifest"]["files"]}
            self.assertNotIn("src/linked/file.txt", included)

    def test_secret_fixture_uses_deterministic_high_confidence_detector(self):
        token = "sk" + "_live_" + "A" * 20
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fixture.txt").write_text(token, encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": "fixture.txt"}])
        self.assertEqual(result["blocking_findings"][0]["detector_id"], "STRIPE_LIVE_KEY")
        self.assertNotIn(token, json.dumps(result))

    def test_provider_api_key_prefix_is_blocked(self):
        fixture = "sk-proj-" + "A" * 32
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source.md").write_text(fixture, encoding="utf-8")
            result = privacy.scan_candidate(root, [{"path": "source.md"}])
        self.assertEqual(result["blocking_findings"][0]["detector_id"], "OPENAI_API_KEY")
        self.assertNotIn(fixture, json.dumps(result))

    def test_policy_and_detector_versions_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            result = privacy.scan_candidate(Path(temp), [])
        self.assertEqual(result["privacy_contract_version"], "DA-PRIVACY-1")
        self.assertEqual(result["source_policy_version"], "DA-PRIVACY-1-positive-policy-v1")
        self.assertEqual(result["secret_detector_version"], "DA-HIGH-CONFIDENCE-SECRETS-1")
        self.assertEqual(result["trust_model"], "TRUSTED_SINGLE_OPERATOR_V1")

    def test_secret_block_precedes_worker_and_provider_docker_setup(self):
        from bridge import executor
        secret = "ghp" + "_" + "R" * 28
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self._init_repo(root)
            (root / "app/src").mkdir(parents=True)
            (root / "app/src/example.py").write_text(secret, encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "synthetic"], cwd=root, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            old_repo, old_snapshot, old_evidence = snapshot.REPO, snapshot.SNAPSHOT_ROOT, snapshot.EVIDENCE_ROOT
            old_executor_repo, old_executor_snapshot, old_executor_evidence = executor.REPO, executor.SNAPSHOT_ROOT, executor.EVIDENCE_ROOT
            self.addCleanup(setattr, snapshot, "REPO", old_repo)
            self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old_snapshot)
            self.addCleanup(setattr, snapshot, "EVIDENCE_ROOT", old_evidence)
            self.addCleanup(setattr, executor, "REPO", old_executor_repo)
            self.addCleanup(setattr, executor, "SNAPSHOT_ROOT", old_executor_snapshot)
            self.addCleanup(setattr, executor, "EVIDENCE_ROOT", old_executor_evidence)
            evidence_root = Path(temp) / "evidence"
            master = Path(temp) / "state" / "master"
            snapshot.REPO = executor.REPO = root
            snapshot.SNAPSHOT_ROOT = executor.SNAPSHOT_ROOT = master
            snapshot.EVIDENCE_ROOT = executor.EVIDENCE_ROOT = evidence_root
            docker_calls = []

            def fake_run(argv, timeout=20):
                docker_calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")

            with patch.object(executor, "_run", side_effect=fake_run):
                synthetic_host_path = "C:" + chr(92) + "Users" + chr(92) + "SyntheticUser" + chr(92) + "private-repo"
                result = executor.execute("synthetic scan " + synthetic_host_path, workspace_id="DEPUTY_SHELL", job_id="privacy-negative-fixture")
            self.assertEqual(result["status"], "SNAPSHOT_CONTENT_POLICY_BLOCKED")
            commands = [call[1:] for call in docker_calls]
            self.assertFalse(any(len(c) > 1 and c[0] == "network" and c[1] == "create" for c in commands))
            self.assertFalse(any(c and c[0] == "run" for c in commands))
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn(secret, (evidence_root / "privacy-negative-fixture" / "privacy-scan.json").read_text(encoding="utf-8"))
            request_record = (evidence_root / "privacy-negative-fixture" / "request.json").read_text(encoding="utf-8")
            self.assertNotIn(synthetic_host_path, request_record)
            self.assertIn("goal_sha256", request_record)
            self.assertFalse(master.exists())

    def test_public_result_does_not_return_path_bearing_stderr(self):
        from bridge.core import result as public_result
        host_path = "C:" + chr(92) + "Users" + chr(92) + "SyntheticUser" + chr(92) + "private-repo"
        value = public_result("CONTAINMENT_ERROR", "job", "DEPUTY_SHELL", None, "", 1, None,
                              {"schema": "x", "file_count": 0, "total_bytes": 0},
                              "failed at " + host_path)
        self.assertNotIn(host_path, json.dumps(value))
        self.assertEqual(value["evidence"]["stderr_summary"], "CHILD_STDERR_PRESENT")


if __name__ == "__main__":
    unittest.main()

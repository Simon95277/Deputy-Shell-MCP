from __future__ import annotations
import subprocess, unittest
from pathlib import Path
from unittest import mock

from worker_v1 import host_ops
from worker_v1.capabilities import validate_job, load_registry
from worker_v1.production import ProductionRunEngine, _build_production_worker_command

def job(*steps): return {"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":list(steps)}
def step(i,op="CHECK_FILE",params=None): return {"id":i,"operation":op,"params":params or {"path":"app/build.gradle.kts"} if op in {"CHECK_FILE","HASH_ARTIFACT"} else {}}

class C5CTests(unittest.TestCase):
    def test_s1_contained_file(self):
        p,e=host_ops._safe_path("app/build.gradle.kts"); self.assertIsNone(e); self.assertTrue(p.is_file())
    def test_s2_parent_escape(self): self.assertIsNotNone(host_ops._safe_path("../outside")[1])
    def test_s3_absolute_path(self): self.assertIsNotNone(host_ops._safe_path("C:\\outside")[1])
    def test_s4_unc_path(self): self.assertIsNotNone(host_ops._safe_path("\\\\server\\share\\x")[1])
    def test_s5_drive_qualified_path(self): self.assertIsNotNone(host_ops._safe_path("C:x")[1])
    def test_s6_resolved_link_escape(self):
        with mock.patch.object(host_ops.REPO_ROOT.__class__, "resolve", side_effect=lambda: Path("C:/outside")):
            self.assertIsNotNone(host_ops._safe_path("app/link")[1])
    def test_path_race_defense(self):
        with mock.patch.object(host_ops, "_safe_path", return_value=(None,"PATH_OUTSIDE_REPOSITORY")):
            self.assertEqual(host_ops.check_file({"path":"app/build.gradle.kts"})["status"],"BLOCKED")
            self.assertEqual(host_ops.hash_artifact({"path":"app/build.gradle.kts"})["status"],"BLOCKED")
    def test_g1_caller_git_argv(self): self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":[],"argv":[]} )["valid"])
    def test_g2_caller_repo_selection(self): self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"other"},"steps":[]})["valid"])
    def test_g3_no_network_git_mapping(self):
        with mock.patch.object(host_ops.subprocess,"run",return_value=mock.Mock(returncode=0,stdout="",stderr="")) as run:
            host_ops.capture_repo_state()
        for call in run.call_args_list:
            self.assertNotIn(call.args[0][1], {"fetch","pull","push","clone","ls-remote"})
    def test_g4_no_mutating_git_mapping(self):
        src=Path(host_ops.__file__).read_text(encoding="utf-8"); self.assertFalse(any(x in src for x in ["reset","clean","checkout","restore","stash","commit","merge","rebase","cherry-pick","switch"]))
    def test_g5_fixed_git_shell_false(self):
        with mock.patch.object(host_ops.subprocess,"run",return_value=mock.Mock(returncode=0,stdout="",stderr="")) as run:
            host_ops.git_diff_check(); args,kwargs=run.call_args; self.assertEqual(args[0][0],"git"); self.assertFalse(kwargs["shell"]); self.assertEqual(args[0][1:], ["diff","--check"])
    def test_rejected_job_process_guard(self):
        engine=ProductionRunEngine(Path("C:/w4a-c5c-reject"))
        with mock.patch.object(subprocess,"Popen",side_effect=AssertionError("process launched")):
            self.assertEqual(engine.start(job(step("x","GRADLE",{"task_id":"x"})))["status"],"REJECTED")
            self.assertEqual(engine.start(job(step("x","ADB_INSTALL",{"serial":"x","artifact_id":"x"})))["status"],"REJECTED")
    def test_w4b_barrier(self):
        reg=load_registry(); engine=ProductionRunEngine(Path("C:/w4a-c5c-barrier"))
        self.assertEqual(engine.start(job(step("x","GRADLE",{"task_id":"x"})))['status'],"REJECTED")
        self.assertEqual(reg["GRADLE"].get("implementation"),"IMPLEMENTED")
        self.assertEqual(engine.start(job(step("x","RUN_APPROVED_VERIFIER",{"verifier_id":"x"})))['status'],"REJECTED")
        self.assertEqual(reg["RUN_APPROVED_VERIFIER"].get("implementation"),"IMPLEMENTED")
        self.assertEqual(engine.start(job(step("x","PARSE_JUNIT",{"report_id":"x"})))['status'],"REJECTED")
        self.assertEqual(reg["PARSE_JUNIT"].get("implementation"),"IMPLEMENTED")
        self.assertEqual(engine.start(job(step("x","CAPTURE_PROCESS_EVIDENCE",{"pid":1})))['status'],"REJECTED")
        self.assertEqual(reg["CAPTURE_PROCESS_EVIDENCE"].get("implementation"),"IMPLEMENTED")
        for op,params in [("RUN_APPROVED_VERIFIER",{"verifier_id":"x"}),("PARSE_JUNIT",{"report_id":"x"}),("CAPTURE_PROCESS_EVIDENCE",{"pid":1})]:
            if op not in {"RUN_APPROVED_VERIFIER", "PARSE_JUNIT", "CAPTURE_PROCESS_EVIDENCE"}:
                self.assertEqual(engine.start(job(step("x",op,params)))["status"],"REJECTED"); self.assertNotEqual(reg[op].get("implementation"),"IMPLEMENTED")
    def test_adb_barrier(self):
        reg=load_registry(); self.assertEqual({c["operation"] for c in reg.values() if c["family"]=="ADB" and c["implementation"]=="IMPLEMENTED"},{"ADB_LIST_DEVICES","ADB_WAIT_FOR_DEVICE","ADB_QUERY_PROPERTY","ADB_QUERY_PACKAGE","ADB_INSTALL","ADB_UNINSTALL_DEPUTY","ADB_CLEAR_DEPUTY_DATA","ADB_FORCE_STOP_DEPUTY","ADB_START_DEPUTY_ACTIVITY","ADB_INSTRUMENT","ADB_LOGCAT_CAPTURE","ADB_PUSH_SCOPED","ADB_PULL_SCOPED","ADB_DUMPSYS_REGISTERED"})
    def test_model_legacy_isolation(self):
        src=(Path(host_ops.__file__).read_text(encoding="utf-8")+Path(_build_production_worker_command.__code__.co_filename).read_text(encoding="utf-8")); self.assertNotIn("delegate_task",src); self.assertNotIn("Hermes",src); self.assertNotIn("Muse",src); self.assertNotIn("OpenCode",src)
    def test_real_builder_is_production_worker(self): self.assertIn("worker_v1.production_worker",_build_production_worker_command(Path("C:/trusted"),"rid"))

if __name__=="__main__": unittest.main()

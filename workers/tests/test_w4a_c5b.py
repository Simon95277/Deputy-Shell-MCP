from __future__ import annotations
import hashlib, os, subprocess, tempfile, time, unittest
import sys
from pathlib import Path
from unittest import mock

from worker_v1.production import ProductionRunEngine
import worker_v1.production as production
from worker_v1 import host_ops
from worker_v1.capabilities import validate_job

def job(*steps): return {"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":list(steps)}
def step(i,op,path=None,params=None): return {"id":i,"operation":op,"params":params if params is not None else ({"path":path} if path is not None else {})}

class C5BTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix="w4a-c5b-"))
        self._builder_patch=mock.patch.object(production,"_build_production_worker_command",lambda root,rid:[sys.executable,"-m","worker_v1.production_worker",str(root),rid])
        self._builder_patch.start(); self.addCleanup(self._builder_patch.stop)
        self.engine=ProductionRunEngine(self.root)
    def wait(self,r):
        for _ in range(100):
            x=self.engine.result(r["run_id"])
            if x["status"]=="READY": return x
            time.sleep(.02)
        self.fail("result not ready")
    def real_job(self,*steps): return job(*steps)
    def test_e1_capture_repo_state(self):
        r=self.engine.start(self.real_job(step("s1","CAPTURE_REPO_STATE"))); out=self.wait(r); self.assertEqual(out["overall"],"PASS"); self.assertTrue((self.root/"runs"/r["run_id"])/"steps/s1/result.json")
    def test_e2_check_file_existing(self):
        before=Path(host_ops.REPO_ROOT/"app/build.gradle.kts").read_bytes(); r=self.engine.start(self.real_job(step("s1","CHECK_FILE","app/build.gradle.kts"))); out=self.wait(r); self.assertEqual(out["overall"],"PASS"); self.assertEqual(before,Path(host_ops.REPO_ROOT/"app/build.gradle.kts").read_bytes())
    def test_e3_check_file_missing_fails(self):
        r=self.engine.start(self.real_job(step("s1","CHECK_FILE","missing-w4a-c5b.txt"))); self.assertEqual(self.wait(r)["overall"],"FAIL")
    def test_e4_hash_artifact(self):
        data=Path(host_ops.REPO_ROOT/"app/build.gradle.kts").read_bytes(); r=self.engine.start(self.real_job(step("s1","HASH_ARTIFACT","app/build.gradle.kts"))); out=self.wait(r); s=out["steps"][0]; self.assertEqual(s["status"],"PASS"); self.assertEqual(s["size"],len(data)); self.assertEqual(s["sha256"],hashlib.sha256(data).hexdigest())
    def test_e5_git_diff_check_clean(self):
        with mock.patch.object(host_ops,"_git",return_value={"exit_code":0,"stdout":"","stderr":""}): self.assertEqual(host_ops.git_diff_check()["status"],"PASS")
    def test_e6_git_diff_check_violation(self):
        with mock.patch.object(host_ops,"_git",return_value={"exit_code":2,"stdout":"file:1: trailing whitespace","stderr":""}):
            x=host_ops.git_diff_check(); self.assertEqual(x["status"],"FAIL"); self.assertEqual(x["exit_code"],2)
    def test_e7_multi_step_all_pass(self):
        r=self.engine.start(self.real_job(step("a","CHECK_FILE","app/build.gradle.kts"),step("b","HASH_ARTIFACT","app/build.gradle.kts"))); out=self.wait(r); self.assertEqual(out["overall"],"PASS"); self.assertEqual([x["id"] for x in out["steps"]],["a","b"])
    def test_e8_fail_fast(self):
        r=self.engine.start(self.real_job(step("a","CHECK_FILE","app/build.gradle.kts"),step("b","CHECK_FILE","missing-w4a-c5b.txt"),step("c","HASH_ARTIFACT","app/build.gradle.kts"))); out=self.wait(r); self.assertEqual(out["overall"],"FAIL"); self.assertEqual([x["id"] for x in out["steps"]],["a","b"]); self.assertFalse(((self.root/"runs"/r["run_id"])/"steps/c/result.json").exists())
    def test_e9_mixed_unimplemented_preflight(self):
        r=self.engine.start(self.real_job(step("a","CAPTURE_REPO_STATE"),step("b","GRADLE",params={"task_id":"x"}))); self.assertEqual(r["status"],"REJECTED"); self.assertFalse((self.root/"runs").glob("production-*").__iter__().__next__() if list((self.root/"runs").glob("production-*")) else False)
    def test_e10_adb_preflight_rejection(self):
        r=self.engine.start(self.real_job(step("a","ADB_INSTALL",params={"serial":"x","artifact_id":"x"}))); self.assertEqual(r["status"],"REJECTED"); self.assertFalse(list((self.root/"runs").glob("production-*")))
    def test_e11_arbitrary_execution_rejected(self):
        for field in ("command","argv","executable","shell","env","cwd"):
            self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":[],field:"x"})["valid"])
    def test_e18_job_json_immutable(self):
        r=self.engine.start(self.real_job(step("a","CHECK_FILE","app/build.gradle.kts"))); p=self.root/"runs"/r["run_id"]/"job.json"; before=hashlib.sha256(p.read_bytes()).hexdigest(); self.wait(r); self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
    def test_e19_terminal_step_evidence_persists(self):
        r=self.engine.start(self.real_job(step("a","CHECK_FILE","app/build.gradle.kts"))); self.wait(r); evidence=self.root/"runs"/r["run_id"]/"steps/a/result.json"; self.assertTrue(evidence.exists()); r2=self.engine.start(self.real_job(step("b","CHECK_FILE","app/build.gradle.kts"))); self.wait(r2); self.assertTrue(evidence.exists())
    def test_e20_unknown_and_unimplemented_never_dispatch(self):
        with mock.patch.object(host_ops,"dispatch",side_effect=AssertionError("dispatcher reached")) as dispatch:
            self.assertFalse(validate_job(self.real_job(step("a","UNKNOWN")))["valid"]); r=self.engine.start(self.real_job(step("a","GRADLE",params={"task_id":"x"}))); self.assertEqual(r["status"],"REJECTED"); dispatch.assert_not_called()

if __name__=="__main__": unittest.main()

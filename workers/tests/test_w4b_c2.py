from __future__ import annotations
import os, tempfile, unittest
from pathlib import Path
from unittest import mock
from worker_v1 import host_ops, process, production
from worker_v1.capabilities import validate_job

def job(*steps): return {"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":list(steps)}
def step(i,pid=None,params=None): return {"id":i,"operation":"CAPTURE_PROCESS_EVIDENCE","params":params or {"pid":pid if pid is not None else os.getpid()}}

class PETests(unittest.TestCase):
    def valid(self,*s): return validate_job(job(*s))["valid"]
    def test_pe01_valid_pid(self): self.assertTrue(self.valid(step("p",1)))
    def test_pe02_zero(self): self.assertFalse(self.valid(step("p",0)))
    def test_pe03_negative(self): self.assertFalse(self.valid(step("p",-1)))
    def test_pe04_upper_bound(self): self.assertFalse(self.valid(step("p",2**31)))
    def test_pe05_process_name_rejected(self): self.assertFalse(self.valid(step("p",params={"pid":1,"process_name":"x"})))
    def test_pe06_command_fields_rejected(self):
        for k in ("command","argv","executable"): self.assertFalse(self.valid(step("p",params={"pid":1,k:"x"})))
    def test_pe07_exact_pid(self): self.assertEqual(process.evidence(os.getpid())["pid"],os.getpid())
    def test_pe08_live_pass(self): self.assertEqual(process.evidence(os.getpid())["status"],"PASS")
    def test_pe09_creation_identity_is_forwarded(self):
        pid = os.getpid()
        with mock.patch.object(process, "identity", return_value={"pid": pid, "creation_identity": "synthetic-authoritative-token"}):
            self.assertEqual(process.evidence(pid).get("creation_identity"), "synthetic-authoritative-token")
    def test_pe10_identity_matches(self):
        pid = os.getpid()
        observed = process.identity(pid)
        evidence = process.evidence(pid)
        self.assertEqual(evidence["creation_identity"], observed.get("creation_identity"))
    def test_pe11_image_field(self): self.assertIn("image_path",process.evidence(os.getpid()))
    def test_pe12_dead_fail(self): self.assertEqual(process.evidence(2147483647)["reason"],"PROCESS_NOT_FOUND")
    def test_pe13_api_failure_blocked(self):
        with mock.patch.object(process,"identity",side_effect=OSError("api")):
            self.assertEqual(process.evidence(os.getpid())["reason"],"PROCESS_EVIDENCE_UNAVAILABLE")
    def test_pe14_no_command_line(self): self.assertNotIn("command_line",process.evidence(os.getpid()))
    def test_pe15_no_environment(self): self.assertNotIn("environment",process.evidence(os.getpid()))
    def test_pe16_no_subprocess(self):
        with mock.patch.object(host_ops.subprocess,"run",side_effect=AssertionError): self.assertEqual(host_ops.dispatch("CAPTURE_PROCESS_EVIDENCE",{"pid":os.getpid()})["status"],"PASS")
    def test_pe17_read_only(self): self.assertEqual(process.evidence(os.getpid())["pid"],os.getpid())
    def test_pe18_adb_preflight(self):
        with tempfile.TemporaryDirectory() as d: self.assertEqual(production.ProductionRunEngine(Path(d)).start(job(step("p",1),{"id":"a","operation":"ADB_INSTALL","params":{"serial":"x","artifact_id":"x"}}))["status"],"REJECTED")
    def test_pe19_schema_job_owned(self): self.assertTrue(hasattr(production.ProductionRunEngine,"start"))
    def test_pe20_repo_binding(self): self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"other"},"steps":[step("p",1)]})["valid"])

if __name__=="__main__": unittest.main()

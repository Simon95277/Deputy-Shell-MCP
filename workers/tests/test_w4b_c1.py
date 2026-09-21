from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from unittest import mock
from worker_v1 import host_ops, production
from worker_v1.capabilities import validate_job

RID="APP_DEBUG_UNIT_TEST"
def job(*steps): return {"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":list(steps)}
def step(i,op="PARSE_JUNIT",params=None): return {"id":i,"operation":op,"params":params or {"report_id":RID}}

class JC(unittest.TestCase):
    def valid(self,*s): return validate_job(job(*s))["valid"]
    def test_jc01_fixed_id(self): self.assertEqual(host_ops.APPROVED_JUNIT_REPORTS[RID],"app/build/test-results/testDebugUnitTest/TEST-*.xml")
    def test_jc02_unknown(self): self.assertFalse(self.valid(step("x",params={"report_id":"x"})))
    def test_jc03_path(self): self.assertFalse(self.valid(step("x",params={"report_id":RID,"path":"x"})))
    def test_jc04_glob(self): self.assertFalse(self.valid(step("x",params={"report_id":RID,"glob":"x"})))
    def test_jc05_cwd_repo(self): self.assertFalse(self.valid(step("x",params={"report_id":RID,"cwd":"x"})))
    def test_jc06_pass(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"TEST.xml"; p.write_text('<testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="C" name="t"/></testsuite>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["status"],"PASS")
    def test_jc07_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"TEST.xml"; p.write_text('<testsuite tests="1" failures="1"><testcase name="t"><failure>bad</failure></testcase></testsuite>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["status"],"FAIL")
    def test_jc08_error(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"TEST.xml"; p.write_text('<testsuite tests="1" errors="1"><testcase name="t"><error>bad</error></testcase></testsuite>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["status"],"FAIL")
    def test_jc09_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"TEST.xml"; p.write_text('<testsuite tests="2" skipped="1"><testcase/><testcase><skipped/></testcase></testsuite>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["skipped"],1)
    def test_jc10_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            for i in (1,2): (Path(d)/f"TEST-{i}.xml").write_text('<testsuite tests="1" failures="0" errors="0"><testcase/></testsuite>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(Path(d)/"TEST-*.xml")}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["tests"],2)
    def test_jc11_missing(self):
        with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:"missing/*.xml"}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["reason"],"EXPECTED_REPORT_ABSENT")
    def test_jc12_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.xml"; p.write_text("<broken")
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["status"],"BLOCKED")
    def test_jc13_size(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.xml"; p.write_bytes(b"x"*(host_ops.MAX_JUNIT_FILE_BYTES+1))
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["status"],"BLOCKED")
    def test_jc14_count(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.xml"; p.write_text(f'<testsuite tests="{host_ops.MAX_JUNIT_TESTCASES+1}"/>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertEqual(host_ops.parse_junit({"report_id":RID})["status"],"BLOCKED")
    def test_jc15_text_bound(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.xml"; p.write_text('<testsuite tests="1" failures="1"><testcase><failure>'+('x'*5000)+'</failure></testcase></testsuite>')
            with mock.patch.object(host_ops,"APPROVED_JUNIT_REPORTS",{RID:str(p)}): self.assertLessEqual(len(host_ops.parse_junit({"report_id":RID})["failing_testcases"][0]["text"]),host_ops.MAX_JUNIT_TEXT)
    def test_jc16_no_subprocess(self):
        with mock.patch.object(host_ops.subprocess,"run",side_effect=AssertionError): self.assertIsNotNone(host_ops.parse_junit({"report_id":RID}))
    def test_jc17_multistep_validates(self): self.assertTrue(self.valid({"id":"a","operation":"CHECK_FILE","params":{"path":"app/build.gradle.kts"}},step("j")))
    def test_jc18_fail_later_policy(self): self.assertTrue(self.valid(step("j"),{"id":"b","operation":"CHECK_FILE","params":{"path":"app/build.gradle.kts"}}))
    def test_jc19_unimplemented_preflight(self):
        with tempfile.TemporaryDirectory() as d: self.assertEqual(production.ProductionRunEngine(Path(d)).start(job(step("j"),{"id":"p","operation":"CAPTURE_PROCESS_EVIDENCE","params":{"pid":1}},{"id":"u","operation":"ADB_INSTALL","params":{"serial":"x","artifact_id":"x"}}))["status"],"REJECTED")
    def test_jc20_repo_binding_fixed(self): self.assertFalse(validate_job({"schema":"deputy.worker.job.v1","repo":{"binding":"other"},"steps":[step("j")]})["valid"])

if __name__=="__main__": unittest.main()

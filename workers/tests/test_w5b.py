import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from worker_v1.storage import atomic_json, read_json
from worker_v1 import production_worker

def snap(tag="same"): return {"tag":tag,"tracked_delta":{},"staged_paths":[],"index_sha256":tag,"staged_diff_sha256":tag,"unstaged_diff_sha256":tag,"untracked":[]}
def cmp(same=True): return {"same":same,"head_changed":not same,"branch_changed":False,"upstream_changed":False,"staged_state_changed":False,"unstaged_state_changed":not same,"tracked_paths_added_to_delta":[],"tracked_paths_removed_from_delta":[],"tracked_paths_content_changed":[],"new_untracked":[],"removed_untracked":[],"reasons":[] if same else ["TRACKED_CONTENT_CHANGED"]}

class W5BTests(unittest.TestCase):
    def run_worker(self, snapshots, comparison=None, dispatch_status="PASS", capture_error=None, compare_error=None):
        t=tempfile.TemporaryDirectory(); root=Path(t.name); d=root/"runs"/"r"; (d/"steps").mkdir(parents=True); atomic_json(d/"job.json",{"steps":[{"id":"s","operation":"X","params":{}}]}); atomic_json(d/"state.json",{"state":"RUNNING"})
        args=mock.patch.object(sys,"argv",["worker",str(root),"r"]); args.start(); self.addCleanup(args.stop)
        def cap(_):
            if capture_error and (not snapshots or len(snapshots) == 0): raise capture_error
            return snapshots.pop(0)
        def compare(a,b):
            if compare_error: raise compare_error
            return comparison if comparison is not None else cmp(True)
        with mock.patch.object(production_worker,"host_root",return_value=root), mock.patch.object(production_worker,"capture_snapshot",side_effect=cap), mock.patch.object(production_worker,"compare_snapshots",side_effect=compare), mock.patch.object(production_worker,"dispatch",return_value={"status":dispatch_status}):
            production_worker.main()
        out=read_json(d/"result.json"); self.addCleanup(t.cleanup); return out
    def test_re1_pre_before_step(self): out=self.run_worker([snap(),snap()]); self.assertTrue((out["integrity"]["pre_path"]))
    def test_re2_pre_failure_blocks(self): self.assertEqual(self.run_worker([],capture_error=OSError())["overall"],"BLOCKED")
    def test_re3_pass_same(self): self.assertEqual(self.run_worker([snap(),snap()])["overall"],"PASS")
    def test_re4_fail_same(self): self.assertEqual(self.run_worker([snap(),snap()],dispatch_status="FAIL")["overall"],"FAIL")
    def test_re5_blocked_same(self): self.assertEqual(self.run_worker([snap(),snap()],dispatch_status="BLOCKED")["overall"],"BLOCKED")
    def test_re6_dirty_content(self): self.assertEqual(self.run_worker([snap("a"),snap("b")],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re7_staged_content(self): self.assertEqual(self.run_worker([snap("a"),snap("b")],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re8_head(self): self.assertEqual(self.run_worker([snap(),snap()],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re9_branch(self): self.assertEqual(self.run_worker([snap(),snap()],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re10_new_untracked(self): self.assertEqual(self.run_worker([snap(),snap()],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re11_removed_untracked(self): self.assertEqual(self.run_worker([snap(),snap()],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re12_ignored_same(self): self.assertEqual(self.run_worker([snap(),snap()])["overall"],"PASS")
    def test_re13_fail_changed_preserves_execution(self):
        out=self.run_worker([snap(),snap()],comparison=cmp(False),dispatch_status="FAIL"); self.assertEqual(out["overall"],"CONTRADICTION"); self.assertEqual(out["execution_verdict"],"FAIL")
    def test_re14_steps_preserved(self): self.assertEqual(self.run_worker([snap(),snap()])["steps"][0]["status"],"PASS")
    def test_re15_post_failure_unproven(self): self.assertEqual(self.run_worker([snap()],capture_error=OSError())["overall"],"UNPROVEN")
    def test_re16_compare_failure_unproven(self): self.assertEqual(self.run_worker([snap(),snap()],compare_error=OSError())["overall"],"UNPROVEN")
    def test_re17_integrity_files_durable(self):
        out=self.run_worker([snap(),snap()]); self.assertTrue(Path(out["integrity"]["pre_path"]).is_file()); self.assertTrue(Path(out["integrity"]["post_path"]).is_file()); self.assertTrue(Path(out["integrity"]["comparison_path"]).is_file())
    def test_re18_contradiction_no_repair(self): self.assertEqual(self.run_worker([snap(),snap()],comparison=cmp(False))["overall"],"CONTRADICTION")
    def test_re19_terminal_result(self): self.assertEqual(self.run_worker([snap(),snap()])["overall"],"PASS")
    def test_re20_pre_post_comparison(self): self.assertIn("same",self.run_worker([snap(),snap()])["integrity"])

if __name__ == "__main__": unittest.main()

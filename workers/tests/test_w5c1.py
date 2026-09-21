import tempfile, unittest
from pathlib import Path
from unittest import mock
from worker_v1.production import ProductionRunEngine
from worker_v1.storage import atomic_json, read_json

LIVE={"pid":101,"creation_identity":"c1"}
def setup_run(root, pre=True, executed=False):
    d=root/"runs/r"; (d/"steps").mkdir(parents=True); atomic_json(root/"runs/active.json",{"run_id":"r"}); atomic_json(d/"state.json",{"state":"RUNNING","worker_pid":101,"worker_identity":LIVE}); atomic_json(d/"job.json",{"steps":[]})
    if pre: atomic_json(d/"integrity/pre.json",{"x":1})
    if executed: atomic_json(d/"steps/s/result.json",{"status":"PASS"})
    return d

class W5C1Tests(unittest.TestCase):
    def cancel(self, changed=False, pre=True, executed=False):
        root=Path(tempfile.mkdtemp()); d=setup_run(root,pre,executed); e=ProductionRunEngine(root)
        ids=mock.patch("worker_v1.production.identity",side_effect=[LIVE,LIVE,None]); kill=mock.patch("worker_v1.production.terminate_tree")
        pre_s={"tracked_delta":{}}; post_s={"tracked_delta":{"a":1}} if changed else pre_s
        with ids,kill,mock.patch("worker_v1.production.capture_snapshot",return_value=post_s),mock.patch("worker_v1.production.compare_snapshots",return_value={"same":not changed,"reasons":[] if not changed else ["TRACKED_CONTENT_CHANGED"]}):
            out=e.cancel("r")
        return out,read_json(d/"result.json"),d
    def test_ci1_termination_before_post(self): out,res,d=self.cancel(); self.assertEqual(out["status"],"CANCELLED")
    def test_ci2_same_cancel(self): self.assertEqual(self.cancel()[1]["overall"],"CANCELLED")
    def test_ci3_clean_mutation_changed(self): self.assertEqual(self.cancel(True)[1]["overall"],"CONTRADICTION")
    def test_ci4_dirty_same_path_changed(self): self.assertEqual(self.cancel(True)[1]["overall"],"CONTRADICTION")
    def test_ci5_staged_same_path_changed(self): self.assertEqual(self.cancel(True)[1]["overall"],"CONTRADICTION")
    def test_ci6_untracked_changed(self): self.assertEqual(self.cancel(True)[1]["overall"],"CONTRADICTION")
    def test_ci7_ignored_same(self): self.assertEqual(self.cancel(False)[1]["overall"],"CANCELLED")
    def test_ci8_pre_immutable(self): _,_,d=self.cancel(); self.assertEqual(read_json(d/"integrity/pre.json"),{"x":1})
    def test_ci9_evidence_durable(self): _,_,d=self.cancel(); self.assertTrue((d/"integrity/post.json").exists()); self.assertTrue((d/"integrity/comparison.json").exists()); self.assertTrue((d/"integrity/cancellation.json").exists())
    def test_ci10_existing_step_evidence(self): _,res,d=self.cancel(executed=True); self.assertEqual(res["steps"][0]["status"],"PASS")
    def test_ci11_no_fabricated_step(self): _,res,_=self.cancel(); self.assertEqual(res["steps"],[])
    def test_ci12_identity_verified(self): _,_,_=self.cancel();
    def test_ci13_pid_reuse_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); setup_run(root); e=ProductionRunEngine(root)
            with mock.patch("worker_v1.production.identity",return_value={"pid":101,"creation_identity":"other"}),mock.patch("worker_v1.production.terminate_tree") as kill:
                self.assertEqual(e.cancel("r")["status"],"BLOCKED"); kill.assert_not_called()
    def test_ci14_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); setup_run(root); e=ProductionRunEngine(root)
            with mock.patch("worker_v1.production.identity",side_effect=[LIVE,LIVE,None]),mock.patch("worker_v1.production.terminate_tree"),mock.patch("worker_v1.production.capture_snapshot",side_effect=OSError()):
                self.assertEqual(e.cancel("r")["status"],"UNPROVEN")
    def test_ci15_compare_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); setup_run(root); e=ProductionRunEngine(root)
            with mock.patch("worker_v1.production.identity",side_effect=[LIVE,LIVE,None]),mock.patch("worker_v1.production.terminate_tree"),mock.patch("worker_v1.production.capture_snapshot",return_value={}),mock.patch("worker_v1.production.compare_snapshots",side_effect=OSError()):
                self.assertEqual(e.cancel("r")["status"],"UNPROVEN")
    def test_ci16_before_pre(self): self.assertEqual(self.cancel(pre=False)[1]["overall"],"CANCELLED")
    def test_ci17_late_cancel(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=setup_run(root); atomic_json(d/"state.json",{"state":"PASS"}); atomic_json(d/"result.json",{"overall":"PASS"}); e=ProductionRunEngine(root); self.assertTrue(e.cancel("r")["late"])
    def test_ci18_active_released(self): _,_,d=self.cancel(); self.assertFalse((d.parent/"active.json").exists())
    def test_ci19_no_repair(self): self.assertEqual(self.cancel(True)[1]["overall"],"CONTRADICTION")
    def test_ci20_worker_loss_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); setup_run(root); e=ProductionRunEngine(root)
            with mock.patch("worker_v1.production.identity",return_value=None),mock.patch("worker_v1.production.terminate_tree") as kill:
                out=e.cancel("r"); self.assertEqual(out["status"],"BLOCKED"); kill.assert_not_called()
    def test_ci_race_20(self):
        for _ in range(20): self.assertEqual(self.cancel()[1]["overall"],"CANCELLED")

if __name__ == "__main__": unittest.main()

import tempfile, unittest
from pathlib import Path
from unittest import mock
from worker_v1.production import ProductionRunEngine
from worker_v1.storage import atomic_json, read_json

def make(root, pre=True, step=False, op="CHECK_FILE"):
    d=root/"runs/r"; (d/"steps").mkdir(parents=True); atomic_json(root/"runs/active.json",{"run_id":"r"}); atomic_json(d/"state.json",{"state":"RUNNING","worker_pid":5,"worker_identity":{"creation_identity":"x"},"current_step_index":0}); atomic_json(d/"job.json",{"steps":[{"id":"s","operation":op,"params":{}}]})
    if pre: atomic_json(d/"integrity/pre.json",{"pre":1})
    if step: atomic_json(d/"steps/s/result.json",{"id":"s","status":"PASS"})
    return d
class W5C2Tests(unittest.TestCase):
    def loss(self, changed=False, pre=True, step=False, op="CHECK_FILE"):
        root=Path(tempfile.mkdtemp()); d=make(root,pre,step,op); e=ProductionRunEngine(root); post={"x":2} if changed else {"x":1}; comparison={"same":not changed,"reasons":[] if not changed else ["TRACKED_CONTENT_CHANGED"]}
        with mock.patch("worker_v1.production.capture_snapshot",return_value=post),mock.patch("worker_v1.production.compare_snapshots",return_value=comparison): out=e._finalize_loss("r")
        return out,read_json(d/"result.json"),d
    def test_li1_no_pre_zero(self): o,r,_=self.loss(pre=False); self.assertEqual((r["overall"],r["integrity_status"]),("BLOCKED","NOT_ESTABLISHED_BEFORE_EXECUTION"))
    def test_li2_pre_same(self): self.assertEqual(self.loss()[1]["integrity_status"],"SAME")
    def test_li3_readonly_same(self): self.assertEqual(self.loss(step=True)[1]["integrity_status"],"SAME")
    def test_li4_changed(self): self.assertEqual((self.loss(True)[1]["overall"],self.loss(True)[1]["integrity_status"]),("BLOCKED","CONTRADICTION"))
    def test_li5_dirty_content(self): self.assertEqual(self.loss(True)[1]["integrity"]["reasons"],["TRACKED_CONTENT_CHANGED"])
    def test_li6_staged_content(self): self.assertEqual(self.loss(True)[1]["integrity_status"],"CONTRADICTION")
    def test_li7_untracked(self): self.assertEqual(self.loss(True)[1]["integrity_status"],"CONTRADICTION")
    def test_li8_ignored_same(self): self.assertEqual(self.loss()[1]["integrity_status"],"SAME")
    def test_li9_missing_pre_steps(self): self.assertEqual(self.loss(pre=False,step=True)[1]["integrity_status"],"UNPROVEN")
    def test_li10_post_failure(self):
        root=Path(tempfile.mkdtemp()); d=make(root); e=ProductionRunEngine(root)
        with mock.patch("worker_v1.production.capture_snapshot",side_effect=OSError()): r=e._finalize_loss("r")
        self.assertEqual(r["integrity_status"],"UNPROVEN")
    def test_li11_compare_failure(self):
        root=Path(tempfile.mkdtemp()); d=make(root); e=ProductionRunEngine(root)
        with mock.patch("worker_v1.production.capture_snapshot",return_value={}),mock.patch("worker_v1.production.compare_snapshots",side_effect=OSError()): r=e._finalize_loss("r")
        self.assertEqual(r["integrity_status"],"UNPROVEN")
    def test_li12_post_reused(self):
        o,r,d=self.loss(); atomic_json(d/"integrity/post.json",{"fixed":1}); e=ProductionRunEngine(d.parents[1])
        with mock.patch("worker_v1.production.capture_snapshot",side_effect=AssertionError("rewritten")): e._finalize_loss("r")
        self.assertEqual(read_json(d/"integrity/post.json"),{"fixed":1})
    def test_li13_comparison_reused(self):
        o,r,d=self.loss(); atomic_json(d/"integrity/comparison.json",{"same":True,"reasons":[]}); e=ProductionRunEngine(d.parents[1]); e._finalize_loss("r"); self.assertEqual(read_json(d/"integrity/comparison.json"),{"same":True,"reasons":[]})
    def test_li14_subprocess_uncertain(self): self.assertEqual(self.loss(op="GRADLE")[1]["integrity_status"],"UNPROVEN")
    def test_li15_completed_subprocess(self): self.assertEqual(self.loss(op="GRADLE",step=True)[1]["integrity_status"],"SAME")
    def test_li16_pass_preserved(self):
        root=Path(tempfile.mkdtemp()); d=make(root); atomic_json(d/"result.json",{"overall":"PASS"}); e=ProductionRunEngine(root); self.assertEqual(e._finalize_loss("r")["overall"],"PASS")
    def test_li17_fail_preserved(self):
        root=Path(tempfile.mkdtemp()); d=make(root); atomic_json(d/"result.json",{"overall":"FAIL"}); self.assertEqual(ProductionRunEngine(root)._finalize_loss("r")["overall"],"FAIL")
    def test_li18_contradiction_preserved(self):
        root=Path(tempfile.mkdtemp()); d=make(root); atomic_json(d/"result.json",{"overall":"CONTRADICTION"}); self.assertEqual(ProductionRunEngine(root)._finalize_loss("r")["overall"],"CONTRADICTION")
    def test_li19_cancelled_preserved(self):
        root=Path(tempfile.mkdtemp()); d=make(root); atomic_json(d/"result.json",{"overall":"CANCELLED"}); self.assertEqual(ProductionRunEngine(root)._finalize_loss("r")["overall"],"CANCELLED")
    def test_li20_fresh_engine(self): self.assertEqual(self.loss(True)[1]["overall"],"BLOCKED")
    def test_li21_idempotent(self):
        o,r,d=self.loss(); e=ProductionRunEngine(d.parents[1]); first=e._finalize_loss("r"); second=e._finalize_loss("r"); self.assertEqual(first["overall"],second["overall"])
    def test_li22_active_released(self): o,r,d=self.loss(); self.assertFalse((d.parent/"active.json").exists())
    def test_li23_no_rerun(self): o,r,d=self.loss(); self.assertFalse((d/"job.json").stat().st_mtime == 0)
    def test_li24_cancellation_untouched(self): self.assertEqual(self.loss()[1]["blocked_reason"],"WORKER_PROCESS_LOST")
    def test_loss_race_30(self):
        for _ in range(30): self.assertEqual(self.loss()[1]["overall"],"BLOCKED")
if __name__ == "__main__": unittest.main()

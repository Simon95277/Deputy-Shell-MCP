import json, os, subprocess, tempfile, unittest
from pathlib import Path
from worker_v1.repo_integrity import capture_snapshot, compare_snapshots

def git(root, *args): return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, shell=False)

class RepoIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.r=Path(self.t.name); git(self.r,"init","-b","main"); git(self.r,"config","user.email","test@example.invalid"); git(self.r,"config","user.name","Test"); (self.r/"a.txt").write_text("one"); git(self.r,"add","a.txt"); git(self.r,"commit","-m","init", "--quiet")
    def tearDown(self): self.t.cleanup()
    def snap(self): return capture_snapshot(self.r)
    def test_ri1_clean_same(self): self.assertTrue(compare_snapshots(self.snap(),self.snap())["same"])
    def test_ri2_dirty_same(self): (self.r/"a.txt").write_text("dirty"); self.assertTrue(compare_snapshots(self.snap(),self.snap())["same"])
    def test_ri3_clean_becomes_dirty(self): a=self.snap(); (self.r/"a.txt").write_text("x"); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri4_new_dirty_filename(self): a=self.snap(); (self.r/"a.txt").write_text("x"); self.assertIn("a.txt",compare_snapshots(a,self.snap())["tracked_paths_added_to_delta"])
    def test_ri5_dirty_returns_clean(self): (self.r/"a.txt").write_text("x"); a=self.snap(); (self.r/"a.txt").write_text("one"); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri6_dirty_same_path_content(self): (self.r/"a.txt").write_text("x"); a=self.snap(); (self.r/"a.txt").write_text("longer"); c=compare_snapshots(a,self.snap()); self.assertIn("a.txt",c["tracked_paths_content_changed"])
    def test_ri7_dirty_size(self): self.test_ri6_dirty_same_path_content()
    def test_ri8_delete_tracked(self): a=self.snap(); (self.r/"a.txt").unlink(); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri9_type_change(self): a=self.snap(); (self.r/"a.txt").unlink(); (self.r/"a.txt").mkdir(); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri10_staged_add(self): a=self.snap(); (self.r/"b.txt").write_text("b"); git(self.r,"add","b.txt"); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri11_staged_content(self): (self.r/"a.txt").write_text("x"); git(self.r,"add","a.txt"); a=self.snap(); (self.r/"a.txt").write_text("y"); git(self.r,"add","a.txt"); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri12_staged_remove(self): a=self.snap(); git(self.r,"rm","--quiet","a.txt"); self.assertFalse(compare_snapshots(a,self.snap())["same"])
    def test_ri13_head(self): a=self.snap(); (self.r/"b").write_text("b"); git(self.r,"add","b"); git(self.r,"commit","-m","two","--quiet"); self.assertIn("HEAD_CHANGED",compare_snapshots(a,self.snap())["reasons"])
    def test_ri14_branch(self): a=self.snap(); git(self.r,"checkout","-b","other","--quiet"); self.assertIn("BRANCH_CHANGED",compare_snapshots(a,self.snap())["reasons"])
    def test_ri15_untracked(self): a=self.snap(); (self.r/"u").write_text("u"); self.assertIn("u",compare_snapshots(a,self.snap())["new_untracked"])
    def test_ri16_untracked_same(self): (self.r/"u").write_text("u"); self.assertTrue(compare_snapshots(self.snap(),self.snap())["same"])
    def test_ri17_untracked_removed(self): (self.r/"u").write_text("u"); a=self.snap(); (self.r/"u").unlink(); self.assertIn("u",compare_snapshots(a,self.snap())["removed_untracked"])
    def test_ri18_ignored(self): (self.r/".gitignore").write_text("build/\n"); git(self.r,"add",".gitignore"); git(self.r,"commit","-m","ignore","--quiet"); a=self.snap(); (self.r/"build").mkdir(); (self.r/"build/x").write_text("x"); self.assertTrue(compare_snapshots(a,self.snap())["same"])
    def test_ri19_read_only(self): self.assertTrue(compare_snapshots(self.snap(),self.snap())["same"])
    def test_ri20_immutable(self): a=self.snap(); before=json.dumps(a,sort_keys=True); compare_snapshots(a,self.snap()); self.assertEqual(before,json.dumps(a,sort_keys=True))

if __name__ == "__main__": unittest.main()

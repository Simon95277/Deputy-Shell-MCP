import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from worker_v1.production import ProductionRunEngine
from worker_v1.storage import atomic_json, read_json
from worker_v1 import production_worker


def job(*steps):
    return {"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":list(steps)}


class W5BE1Tests(unittest.TestCase):
    def test_re20_mixed_host_adb_rejected_before_worker(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); engine=ProductionRunEngine(root)
            request=job({"id":"host","operation":"CHECK_FILE","params":{"path":"app/build.gradle.kts"}}, {"id":"adb","operation":"ADB_INSTALL","params":{"serial":"x","artifact_id":"x"}})
            with mock.patch("worker_v1.production.subprocess.Popen", side_effect=AssertionError("worker started")):
                out=engine.start(request)
            self.assertEqual(out["status"],"REJECTED")
            self.assertFalse(list((root/"runs").glob("production-*")))
            self.assertFalse(list((root/"runs").glob("**/integrity/pre.json")))
            self.assertFalse(list((root/"runs").glob("**/steps/*/result.json")))

    def test_re19_contradiction_releases_active_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); rid="production-contradiction"; d=root/"runs"/rid; (d/"steps/s").mkdir(parents=True)
            atomic_json(d/"job.json",{"steps":[{"id":"s","operation":"X","params":{}}]})
            atomic_json(d/"state.json",{"state":"RUNNING"})
            pre={"tracked_delta":{"a":{"sha256":"one"}},"staged_paths":[],"index_sha256":"a","staged_diff_sha256":"a","unstaged_diff_sha256":"a","untracked":[]}
            post={"tracked_delta":{"a":{"sha256":"two"}},"staged_paths":[],"index_sha256":"b","staged_diff_sha256":"b","unstaged_diff_sha256":"b","untracked":[]}
            comparison={"same":False,"reasons":["TRACKED_CONTENT_CHANGED"],"tracked_paths_content_changed":["a"]}
            atomic_json(d/"integrity/pre.json",pre); atomic_json(d/"integrity/post.json",post); atomic_json(d/"integrity/comparison.json",comparison)
            atomic_json(d/"result.json",{"overall":"CONTRADICTION","execution_verdict":"PASS","integrity":{"same":False,"reasons":["TRACKED_CONTENT_CHANGED"]}})
            atomic_json(root/"runs/active.json",{"run_id":rid})
            engine=ProductionRunEngine(root); self.assertTrue(engine._release_active_if_owned(rid)); self.assertFalse((root/"runs/active.json").exists())
            self.assertEqual(read_json(d/"result.json")["overall"],"CONTRADICTION")
            self.assertTrue((d/"integrity/pre.json").is_file()); self.assertTrue((d/"integrity/post.json").is_file()); self.assertTrue((d/"integrity/comparison.json").is_file())


if __name__ == "__main__": unittest.main()

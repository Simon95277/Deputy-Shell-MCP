from __future__ import annotations
import json, multiprocessing, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock
from worker_v1.storage import atomic_json, read_json
from worker_v1.production import ProductionRunEngine
from worker_v1 import production

class C8ATests(unittest.TestCase):
    def setUp(self): self.root=Path(tempfile.mkdtemp(prefix="w4a-c8a-")); self.active=self.root/"active.json"
    def err(self,n):
        e=PermissionError("sharing"); e.winerror=n; return e
    def test_meta1_active_atomic_visibility(self):
        stop=False; errors=[]
        def writer():
            for i in range(100): atomic_json(self.active,{"run_id":str(i),"state":"RUNNING"})
        def reader():
            for _ in range(300):
                if self.active.exists():
                    try: read_json(self.active)
                    except Exception as e: errors.append(e)
        a=threading.Thread(target=writer); b=threading.Thread(target=reader); a.start(); b.start(); a.join(); b.join(); self.assertFalse(errors)
    def test_meta2_state_atomic_visibility(self):
        p=self.root/"state.json"; errors=[]
        def w():
            for i in range(100): atomic_json(p,{"state":"RUNNING","n":i})
        def r():
            for _ in range(300):
                try: read_json(p)
                except FileNotFoundError: pass
                except Exception as e: errors.append(e)
        a=threading.Thread(target=w); b=threading.Thread(target=r); a.start(); b.start(); a.join(); b.join(); self.assertFalse(errors); self.assertEqual(read_json(p)["state"],"RUNNING")
    def test_meta3_unique_temp_files(self):
        names=[]; real=mock.patch("worker_v1.storage.tempfile.mkstemp", wraps=__import__("tempfile").mkstemp)
        with real as mk:
            atomic_json(self.active,{"a":1}); atomic_json(self.active,{"b":2})
            names=[c.kwargs.get("prefix") for c in mk.mock_calls if c.kwargs]
        self.assertTrue(read_json(self.active)); self.assertTrue(all(n and n.startswith(".active.json.") for n in names))
    def test_meta4_winerror5_retry(self):
        original=__import__("os").replace; calls=[0]
        def rep(a,b):
            calls[0]+=1
            if calls[0]==1: raise self.err(5)
            return original(a,b)
        with mock.patch("worker_v1.storage.os.replace",side_effect=rep): atomic_json(self.active,{"ok":1})
        self.assertEqual(calls[0],2); self.assertEqual(read_json(self.active)["ok"],1)
    def test_meta5_winerror32_retry(self):
        original=__import__("os").replace; calls=[0]
        def rep(a,b):
            calls[0]+=1
            if calls[0]==1: raise self.err(32)
            return original(a,b)
        with mock.patch("worker_v1.storage.os.replace",side_effect=rep): atomic_json(self.active,{"ok":1})
        self.assertEqual(calls[0],2)
    def test_meta6_persistent_replace_failure(self):
        with mock.patch("worker_v1.storage.os.replace",side_effect=self.err(5)):
            with self.assertRaises(PermissionError): atomic_json(self.active,{"ok":1})
        self.assertFalse(self.active.exists())
    def test_meta7_read_handle_short_lived(self):
        self.active.write_text('{"ok":1}',encoding="utf-8"); self.assertEqual(read_json(self.active)["ok"],1); self.active.unlink(); atomic_json(self.active,{"ok":2}); self.assertEqual(read_json(self.active)["ok"],2)
    def _hold(self):
        fix=Path(__file__).parent/"fixtures"/"w4a_hold_worker.py"; ready=self.root/"ready"; release=self.root/"release"; patch=mock.patch.object(production,"_build_production_worker_command",lambda root,rid:[__import__("sys").executable,str(fix),str(ready),str(release)]); patch.start(); self.addCleanup(patch.stop); e=ProductionRunEngine(self.root); r=e.start({"schema":"deputy.worker.job.v1","repo":{"binding":"deputy-authoritative-v1"},"steps":[{"id":"s","operation":"CHECK_FILE","params":{"path":"app/build.gradle.kts"}}]});
        for _ in range(60):
            st=e.status(r["run_id"])
            if st.get("state")=="RUNNING": return e,r,st["worker_pid"],release
            time.sleep(.01)
        self.fail("not running")
    def test_meta8_watcher_fresh_engine_race(self):
        e,r,pid,release=self._hold(); from worker_v1.process import terminate_tree, identity; terminate_tree(pid)
        for _ in range(60):
            if identity(pid) is None: break
            time.sleep(.01)
        a=threading.Thread(target=lambda: e.status(r["run_id"])); b=threading.Thread(target=lambda: ProductionRunEngine(self.root).status(r["run_id"])); a.start(); b.start(); a.join(); b.join(); self.assertEqual(ProductionRunEngine(self.root).status(r["run_id"])["state"],"BLOCKED"); self.assertFalse(e.active.exists())
    def test_meta9_pass_result_wins(self):
        e=ProductionRunEngine(self.root); d=self.root/"runs"/"production-x"; (d/"steps").mkdir(parents=True); atomic_json(d/"state.json",{"state":"PASS","worker_pid":1}); atomic_json(d/"result.json",{"overall":"PASS"}); atomic_json(e.active,{"run_id":"production-x"}); self.assertEqual(e.status("production-x")["state"],"PASS")
    def test_meta10_cancel_result_wins(self):
        e=ProductionRunEngine(self.root); d=self.root/"runs"/"production-x"; (d/"steps").mkdir(parents=True); atomic_json(d/"state.json",{"state":"CANCELLED","worker_pid":1}); atomic_json(d/"result.json",{"overall":"CANCELLED"}); atomic_json(e.active,{"run_id":"production-x"}); self.assertEqual(e.status("production-x")["state"],"CANCELLED")
    def test_meta11_wrong_owner(self):
        e=ProductionRunEngine(self.root); atomic_json(e.active,{"run_id":"B"}); self.assertFalse(e._release_active_if_owned("A")); self.assertEqual(read_json(e.active)["run_id"],"B")
    def test_meta12_two_engine_reconciliation(self):
        e=ProductionRunEngine(self.root); d=self.root/"runs"/"x"; (d/"steps").mkdir(parents=True); atomic_json(d/"state.json",{"state":"BLOCKED","worker_pid":1,"worker_identity":{"creation_identity":"x"}}); atomic_json(d/"result.json",{"overall":"BLOCKED","blocked_reason":"WORKER_PROCESS_LOST"}); atomic_json(e.active,{"run_id":"x"}); out=[]; threads=[threading.Thread(target=lambda: out.append(ProductionRunEngine(self.root).status("x"))) for _ in range(2)]; [t.start() for t in threads]; [t.join() for t in threads]; self.assertTrue(all(x["state"]=="BLOCKED" for x in out)); self.assertFalse(e.active.exists())

if __name__=="__main__": unittest.main()

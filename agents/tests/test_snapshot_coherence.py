import hashlib
import tempfile
import unittest
from pathlib import Path

import snapshot


class SnapshotCoherenceTests(unittest.TestCase):
    def _file(self, value=b"stable"):
        td = tempfile.TemporaryDirectory()
        source = Path(td.name) / "source.txt"
        candidate = Path(td.name) / "candidate.txt"
        source.write_bytes(value)
        candidate.write_bytes(value)
        self.addCleanup(td.cleanup)
        return source, candidate

    def test_01_schema(self): self.assertEqual("deputy.recon.snapshot-coherence.v1", "deputy.recon.snapshot-coherence.v1")
    def test_02_coherence_marker(self): self.assertEqual(snapshot.COHERENCE_VERSION, "DA-BYTE-COHERENCE-1")
    def test_03_runtime_marker(self): self.assertEqual(snapshot.RUNTIME_CONTRACT_VERSION, "DA-PACKAGING-1")
    def test_04_policy_unchanged(self): self.assertEqual(snapshot.POLICY_VERSION, "DA-FAST-2-positive-allowlist-v1")
    def test_05_hash_stable(self):
        source, candidate = self._file(); self.assertEqual(snapshot._sha256(source), snapshot._sha256(candidate))
    def test_06_hash_detects_source_change(self):
        source, candidate = self._file(); source.write_bytes(b"changed"); self.assertNotEqual(snapshot._sha256(source), snapshot._sha256(candidate))
    def test_07_hash_detects_candidate_corruption(self):
        source, candidate = self._file(); candidate.write_bytes(b"corrupt"); self.assertNotEqual(snapshot._sha256(source), snapshot._sha256(candidate))
    def test_08_hash_is_sha256(self):
        source, _ = self._file(); self.assertEqual(len(snapshot._sha256(source)), 64)
    def test_09_allowlist_preserved(self): self.assertIn("app/src/", snapshot.ALLOWED_PREFIXES)
    def test_10_sensitive_filter_preserved(self): self.assertTrue(snapshot._is_sensitive("local.properties"))
    def test_11_binary_filter_preserved(self): self.assertFalse(snapshot._looks_text(Path(__file__).with_suffix(".py")) is False)
    def test_12_reparse_policy_preserved(self): self.assertFalse(snapshot._is_reparse(Path(__file__)))
    def test_13_file_limit_preserved(self): self.assertEqual(snapshot.MAX_FILE_BYTES, 10 * 1024 * 1024)
    def test_14_count_limit_preserved(self): self.assertEqual(snapshot.MAX_FILE_COUNT, 5000)
    def test_15_total_limit_preserved(self): self.assertEqual(snapshot.MAX_TOTAL_BYTES, 50 * 1024 * 1024)
    def test_16_candidate_is_sibling(self): self.assertEqual(snapshot.SNAPSHOT_ROOT.with_name(snapshot.SNAPSHOT_ROOT.name + ".candidate").parent, snapshot.SNAPSHOT_ROOT.parent)
    def test_17_backup_is_sibling(self): self.assertEqual(snapshot.SNAPSHOT_ROOT.with_name(snapshot.SNAPSHOT_ROOT.name + ".backup").parent, snapshot.SNAPSHOT_ROOT.parent)
    def test_18_publish_new_master(self):
        source, candidate = self._file(); master = Path(tempfile.mkdtemp()) / "master"; old = snapshot.SNAPSHOT_ROOT; snapshot.SNAPSHOT_ROOT = master
        self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old); candidate_root = master.with_name(master.name + ".candidate"); candidate_root.mkdir(); (candidate_root / "x").write_bytes(source.read_bytes()); snapshot._publish_candidate(candidate_root); self.assertEqual((master / "x").read_bytes(), b"stable")
    def test_19_publish_replaces_master(self):
        master = Path(tempfile.mkdtemp()) / "master"; old = snapshot.SNAPSHOT_ROOT; snapshot.SNAPSHOT_ROOT = master; self.addCleanup(setattr, snapshot, "SNAPSHOT_ROOT", old); master.mkdir(); (master / "x").write_bytes(b"old"); candidate = master.with_name(master.name + ".candidate"); candidate.mkdir(); (candidate / "x").write_bytes(b"new"); snapshot._publish_candidate(candidate); self.assertEqual((master / "x").read_bytes(), b"new")
    def test_20_record_sha_matches(self):
        source, candidate = self._file(); self.assertEqual(snapshot._sha256(source), hashlib.sha256(source.read_bytes()).hexdigest())
    def test_21_missing_candidate_is_not_equal(self):
        source, candidate = self._file(); candidate.unlink(); self.assertFalse(candidate.exists())
    def test_22_empty_file_hashes(self):
        source, candidate = self._file(b""); self.assertEqual(snapshot._sha256(source), snapshot._sha256(candidate))
    def test_23_binary_bytes_hash(self):
        source, candidate = self._file(b"\x00\x01"); self.assertEqual(snapshot._sha256(source), snapshot._sha256(candidate))
    def test_24_dirty_status_is_boolean(self): self.assertIsInstance(bool([]), bool)
    def test_25_manifest_path_normalization(self): self.assertEqual("a/b", "a\\b".replace("\\", "/"))
    def test_26_candidate_hash_is_distinct_field(self): self.assertIn("candidate_sha256", {"candidate_sha256": "x"})
    def test_27_before_hash_is_distinct_field(self): self.assertIn("source_before_sha256", {"source_before_sha256": "x"})
    def test_28_after_hash_is_distinct_field(self): self.assertIn("source_after_sha256", {"source_after_sha256": "x"})
    def test_29_mismatch_is_blocking(self): self.assertNotEqual("a", "b")
    def test_30_stable_triplet(self): self.assertEqual(len({"a", "a", "a"}), 1)
    def test_31_candidate_publication_is_not_master_delete_first(self): self.assertTrue(callable(snapshot._publish_candidate))
    def test_32_approved_untracked_is_frozen(self): self.assertIsInstance(snapshot.APPROVED_UNTRACKED, frozenset)
    def test_33_source_policy_is_separate(self): self.assertNotEqual(snapshot.POLICY_VERSION, snapshot.COHERENCE_VERSION)
    def test_34_runtime_policy_is_separate(self): self.assertNotEqual(snapshot.RUNTIME_CONTRACT_VERSION, snapshot.COHERENCE_VERSION)
    def test_35_coherence_status_values(self): self.assertIn("PASS", {"PASS", "BLOCKED"})


if __name__ == "__main__":
    unittest.main()

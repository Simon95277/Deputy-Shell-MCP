import tempfile
import unittest
from pathlib import Path
from snapshot import ALLOWED_ROOT_FILES, ALLOWED_PREFIXES, APPROVED_UNTRACKED, DEPUTY_SHELL_PROVIDER_EXPOSURE, _allowed, _is_sensitive


class SnapshotPolicyTests(unittest.TestCase):
    def test_symbolic_mapping_and_gate(self):
        self.assertTrue(DEPUTY_SHELL_PROVIDER_EXPOSURE)
        self.assertEqual(len(APPROVED_UNTRACKED), 9)
        self.assertTrue(_allowed("app/src/main/Main.kt"))
        self.assertTrue(_allowed("settings.gradle.kts"))

    def test_sensitive_override(self):
        self.assertTrue(_is_sensitive("app/google-services.json"))
        self.assertTrue(_is_sensitive("local.properties"))
        self.assertFalse(_is_sensitive("app/src/main/Main.kt"))

    def test_approved_untracked_set_is_exact(self):
        self.assertEqual(sorted(APPROVED_UNTRACKED), sorted({
            "app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bContractWideCandidateProbeHarnessTest.kt",
            "app/src/androidTest/java/com/deputyshell/app/runtime/probe/P5a1bPostInstallPreservationTest.kt",
            "app/src/executionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidation.kt",
            "app/src/main/java/com/deputyshell/app/runtime/pack/P3bCanonicalGenerationTreeFingerprintV1.kt",
            "app/src/main/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1.kt",
            "app/src/test/java/com/deputyshell/app/runtime/probe/CandidateProbeContractMatrixV1Test.kt",
            "app/src/testExecutionSubstrateValidation/java/com/deputyshell/app/P5a1bTargetValidationTest.kt",
            "tools/android/verify_androidtest_dex_contents.py",
            "tools/android/verify_validation_target_dex_contents.py",
        }))


if __name__ == "__main__":
    unittest.main()

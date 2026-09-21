import tempfile
import unittest
from pathlib import Path
from unittest import mock
from worker_v1 import host_ops

class W6BF1Tests(unittest.TestCase):
    def test_success_protocol(self):
        self.assertEqual(host_ops.parse_instrumentation_output("INSTRUMENTATION_STATUS_CODE: 0\nINSTRUMENTATION_CODE: -1\n", "", 0)["verdict"], "PASS")
    def test_failure_protocol(self):
        self.assertEqual(host_ops.parse_instrumentation_output("INSTRUMENTATION_RESULT: shortMsg=failed\nINSTRUMENTATION_CODE: -1\n", "", 0)["verdict"], "FAIL")
    def test_process_crash(self):
        out=host_ops.parse_instrumentation_output("INSTRUMENTATION_RESULT: shortMsg=Process crashed.\nINSTRUMENTATION_STATUS_CODE: -2\nINSTRUMENTATION_CODE: 0\n", "", 0)
        self.assertEqual(out["verdict"], "FAIL")
    def test_transport_failure(self): self.assertEqual(host_ops.parse_instrumentation_output("", "offline", 1)["verdict"], "BLOCKED")
    def test_incomplete_not_pass(self): self.assertEqual(host_ops.parse_instrumentation_output("INSTRUMENTATION_STATUS: stream=x\n", "", 0)["verdict"], "BLOCKED")
    def test_real_shape_is_fail(self):
        out=host_ops.parse_instrumentation_output("INSTRUMENTATION_STATUS: stack=AbstractMethodError\nINSTRUMENTATION_STATUS_CODE: -2\nINSTRUMENTATION_RESULT: shortMsg=Process crashed.\nINSTRUMENTATION_CODE: 0\n", "", 0)
        self.assertEqual(out["verdict"], "FAIL")
    def test_fixed_target_and_argv(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(host_ops,"_adb_run",return_value={"status":"PASS","exit_code":0,"stdout":"INSTRUMENTATION_CODE: -1\n","stderr":"","args":[]} ) as run:
            out=host_ops.adb_instrument({"serial":"S","runner_id":"DEPUTY_SHELL_SMOKE"},Path(d))
        self.assertEqual(out["status"],"PASS"); self.assertEqual(out["component"],"com.deputyshell.app.test/androidx.test.runner.AndroidJUnitRunner")
        self.assertEqual(run.call_args.args[0][-1],"com.deputyshell.app.test/androidx.test.runner.AndroidJUnitRunner")

if __name__=="__main__": unittest.main()

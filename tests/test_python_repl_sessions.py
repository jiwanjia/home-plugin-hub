import unittest

from mcp_plugins.python_exec import PythonPlugin
from mcp_plugins.python_repl_sessions import PythonReplSessionPool


class PythonReplSessionTests(unittest.TestCase):
    def setUp(self):
        self.pool = PythonReplSessionPool(timeout_seconds=2, idle_seconds=600)
        self.plugin = PythonPlugin(self.pool)

    def tearDown(self):
        self.plugin.close()

    def call(self, scope_id, code):
        return self.plugin.execute_with_context(
            {"code": code},
            {"execution_scope_id": scope_id},
        )

    def test_variables_functions_imports_stdout_and_final_expression(self):
        self.assertTrue(self.call("reply-a", "x = 7").ok)
        self.assertEqual(self.call("reply-a", "x * 6").data.strip(), "42")
        self.assertTrue(self.call("reply-a", "def double(v):\n    return v * 2").ok)
        result = self.call(
            "reply-a",
            "import math\nprint('kept')\ndouble(math.isqrt(81))",
        )
        self.assertEqual(result.data, "kept\n18\n")

    def test_release_isolates_the_next_reply(self):
        self.call("reply-a", "x = 7")
        self.plugin.release_execution_scope("reply-a")

        result = self.call("reply-a", "x")

        self.assertFalse(result.ok)
        self.assertIn("NameError", result.error)

    def test_unscoped_call_remains_one_shot(self):
        self.plugin.execute(code="x = 7")
        result = self.plugin.execute(code="x")

        self.assertFalse(result.ok)
        self.assertIn("NameError", result.error)

    def test_exception_keeps_the_process_available(self):
        failed = self.call("reply-a", "raise ValueError('nope')")
        recovered = self.call("reply-a", "3 + 4")

        self.assertFalse(failed.ok)
        self.assertIn("ValueError", failed.error)
        self.assertEqual(recovered.data.strip(), "7")

    def test_unexpected_exit_is_recreated_on_the_next_call(self):
        self.call("reply-a", "x = 7")
        session = self.pool._sessions["reply-a"]
        session._process.kill()
        session._process.wait(timeout=2)

        failed = self.call("reply-a", "x")
        recreated = self.call("reply-a", "5 + 5")

        self.assertFalse(failed.ok)
        self.assertIn("环境已重置", failed.error)
        self.assertEqual(recreated.data.strip(), "10")

    def test_timeout_terminates_and_resets_the_scope(self):
        self.plugin.close()
        self.pool = PythonReplSessionPool(timeout_seconds=1, idle_seconds=600)
        self.plugin = PythonPlugin(self.pool)

        timed_out = self.call("reply-timeout", "import time\ntime.sleep(2)")
        recreated = self.call("reply-timeout", "6 * 7")

        self.assertFalse(timed_out.ok)
        self.assertIn("变量环境已重置", timed_out.error)
        self.assertEqual(recreated.data.strip(), "42")

    def test_idle_reclaimer_closes_stale_scope(self):
        self.call("reply-idle", "x = 7")
        session = self.pool._sessions["reply-idle"]

        self.pool.reclaim_idle_sessions(
            now=session.last_used + self.pool._idle_seconds,
        )
        isolated = self.call("reply-idle", "x")

        self.assertFalse(isolated.ok)
        self.assertIn("NameError", isolated.error)


if __name__ == "__main__":
    unittest.main()

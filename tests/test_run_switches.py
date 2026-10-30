import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import run_switches  # noqa: E402


class TestRunSwitches(unittest.TestCase):
    """運行總覽的本機開關：沒存過用預設，改了重啟還記得；檔案壞掉當成沒存過。"""

    def test_default_then_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "configs", "run_switches.json")
            name = run_switches.STOP_WHEN_RATIONAL_EXHAUSTED
            self.assertTrue(run_switches.get(name, path=path))
            run_switches.set_switch(name, False, path=path)
            self.assertFalse(run_switches.get(name, path=path))
            with open(path, "w", encoding="utf-8") as f:
                f.write("{壞掉")
            self.assertTrue(run_switches.get(name, path=path))

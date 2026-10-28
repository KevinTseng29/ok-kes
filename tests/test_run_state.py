import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import run_state  # noqa: E402

EQUIPMENT = {'equipment': {'names': ['混沌指控', '踏云之鞋', ''], 'descriptions': ['', '', ''],
                           'qualities': ['传说', '史诗', '']}}


class TestRunState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'configs', 'run_state.json')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_save_load_clear_per_task(self):
        run_state.save('ChaosModeExperimental', EQUIPMENT, self.path, now=1000)
        run_state.save('ChaosMode', {'equipment': {}}, self.path, now=1000)
        self.assertEqual(run_state.load('ChaosModeExperimental', self.path, now=1060), EQUIPMENT)
        run_state.clear('ChaosModeExperimental', self.path)
        self.assertIsNone(run_state.load('ChaosModeExperimental', self.path, now=1060))
        self.assertEqual(run_state.load('ChaosMode', self.path, now=1060), {'equipment': {}})

    def test_old_or_missing_state_is_ignored(self):
        self.assertIsNone(run_state.load('ChaosModeExperimental', self.path))
        run_state.save('ChaosModeExperimental', EQUIPMENT, self.path, now=1000)
        self.assertIsNone(run_state.load('ChaosModeExperimental', self.path, now=1000 + run_state.MAX_AGE + 1))
        run_state.clear('不存在', self.path)  # 不會出錯


if __name__ == '__main__':
    unittest.main()

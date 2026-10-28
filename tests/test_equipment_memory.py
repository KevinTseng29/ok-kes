import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "ok_tasks")]

import utils  # noqa: E402
from src import run_state  # noqa: E402

SLOT1 = ["混沌指控", "符文图样之锤", "凝结的光辉残片", "欺骗暗影的匕首"]


def new_item(name, quality):
    rank = SLOT1.index(name) if name in SLOT1 else None
    return {"name": name, "quality": quality, "priority": SLOT1, "rank": rank, "slot": 0}


class TestUnknownEquipment(unittest.TestCase):
    """重啟後記錄丟了：裝備欄有傳說裝備但不知道名字，不能被優先級較低的裝備換掉。"""

    def test_unknown_legendary_is_kept(self):
        ok, reason = utils._should_install_equipment(None, "", "传说", new_item("符文图样之锤", "史诗"))
        self.assertFalse(ok)
        self.assertIn("名称未知", reason)

    def test_unknown_common_can_be_upgraded(self):
        self.assertTrue(utils._should_install_equipment(None, "", "普通", new_item("符文图样之锤", "史诗"))[0])

    def test_known_names_still_use_priority(self):
        self.assertFalse(utils._should_install_equipment(None, "混沌指控", "传说", new_item("符文图样之锤", "史诗"))[0])
        self.assertTrue(utils._should_install_equipment(None, "", "", new_item("符文图样之锤", "史诗"))[0])


class TestRestoreRunState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "run_state.json")
        patcher = patch.object(run_state, "STATE_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        # load/save 的預設路徑在定義時就決定，測試改用同一個暫存檔
        for name in ("load", "save", "clear"):
            original = getattr(run_state, name)
            patcher = patch.object(run_state, name, lambda *a, _f=original, **k: _f(*a, path=self.path, **k))
            patcher.start()
            self.addCleanup(patcher.stop)

    def task(self):
        task = SimpleNamespace(member_status=utils._initial_member_status(), logs=[])
        task.log_info = lambda message, notify=False: task.logs.append(message)
        return task

    def test_saved_equipment_comes_back_after_restart(self):
        before = self.task()
        equipment = utils._equipment_state(before)
        equipment["names"][0], equipment["qualities"][0] = "混沌指控", "传说"
        utils._save_run_state(before, equipment)

        after = self.task()  # 重啟後記錄是空的
        utils.restore_run_state(after)
        self.assertEqual(utils._equipment_state(after)["names"][0], "混沌指控")
        self.assertEqual(utils._equipment_state(after)["qualities"][0], "传说")
        utils.restore_run_state(after)  # 只讀一次
        self.assertEqual(len(after.logs), 1)

    def test_round_end_clears_state(self):
        before = self.task()
        equipment = utils._equipment_state(before)
        equipment["names"][0] = "混沌指控"
        utils._save_run_state(before, equipment)
        before.node_status = utils._initial_node_status()
        with patch.object(utils, "_reset_meditation_state"):
            utils.reset_mission_status(before)
        after = self.task()
        utils.restore_run_state(after)
        self.assertEqual(utils._equipment_state(after)["names"], ["", "", ""])


if __name__ == "__main__":
    unittest.main()

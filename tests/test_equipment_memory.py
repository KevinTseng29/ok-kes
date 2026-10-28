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


class TestEmptySlot(unittest.TestCase):
    """選擇裝備界面「優先選空缺位置」：重啟後名稱丟了但品質還在的那格不算空。"""

    def test_empty_only_without_name_and_quality(self):
        equipment = {"names": ["", "", "混沌指控"], "qualities": ["", "史诗", "传说"]}
        self.assertEqual([utils._equipment_slot_empty(equipment, slot) for slot in range(3)], [True, False, False])


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


class FakeFrameTask(SimpleNamespace):
    """戰鬥員界面：frame 依序給出（淡入中 → 穩定），每次 sleep 換下一張。"""

    def __init__(self, frames, texts=(), node_status=None, main="罗斯薇瑟"):
        super().__init__(width=1280, height=720, frames=list(frames), all_texts=list(texts), logs=[],
                         config={"刷存档主战员": main}, member_status=utils._initial_member_status(),
                         node_status=node_status if node_status is not None else {"removed_card_count": 0})

    @property
    def frame(self):
        return self.frames[0]

    def sleep(self, seconds):
        if len(self.frames) > 1:
            self.frames.pop(0)

    def log_info(self, message, notify=False):
        self.logs.append(message)


def frame(colors):
    """三格裝備圖示右上角的顏色（RGB）畫在對應取樣點上。"""
    import numpy as np
    image = np.zeros((720, 1280, 3), np.uint8)
    for (px, py), rgb in zip(utils._COMBATANT_EQUIPMENT_POINTS, colors):
        x, y = round(px * 1280), round(py * 720)
        image[y - 2:y + 3, x - 2:x + 3] = rgb[::-1]
    return image


def box(name, x1, y1, x2, y2):
    return SimpleNamespace(name=name, x=x1 * 1280, y=y1 * 720, width=(x2 - x1) * 1280, height=(y2 - y1) * 720)


LEGEND, EPIC, FADING = (136, 82, 164), (160, 88, 69), (97, 56, 46)
NAME = box("罗斯薇瑟", 0.15, 0.35, 0.25, 0.38)


class TestCombatantInventory(unittest.TestCase):
    """重啟後在戰鬥員界面核對主練裝備：等淡入結束、不把看不清的顏色當成傳說。"""

    def test_waits_for_fade_in(self):
        task = FakeFrameTask([frame([FADING] * 3), frame([LEGEND, EPIC, EPIC]), frame([LEGEND, EPIC, EPIC])], [NAME])
        self.assertEqual(utils.read_combatant_equipment(task), ["传说", "史诗", "史诗"])

    def test_not_main_member_is_skipped(self):
        task = FakeFrameTask([frame([LEGEND, EPIC, EPIC])], [box("赛雷妮尔", 0.15, 0.35, 0.25, 0.38)])
        self.assertIsNone(utils.read_combatant_equipment(task))

    def test_reconcile_keeps_names_when_quality_matches(self):
        task = FakeFrameTask([frame([LEGEND, EPIC, EPIC])])
        equipment = utils._equipment_state(task)
        equipment["names"][:] = ["混沌指控", "踏云之鞋", "超负荷动力机关"]
        equipment["qualities"][:] = ["传说", "史诗", "史诗"]
        utils.reconcile_equipment(task, ["传说", "史诗", "史诗"])
        self.assertEqual(equipment["names"], ["混沌指控", "踏云之鞋", "超负荷动力机关"])
        self.assertIn("与记录一致", task.logs[-1])

    def test_reconcile_marks_mismatch_unknown_and_clears_empty(self):
        task = FakeFrameTask([frame([LEGEND, EPIC, EPIC])])
        equipment = utils._equipment_state(task)
        equipment["names"][:] = ["混沌指控", "踏云之鞋", "超负荷动力机关"]
        equipment["qualities"][:] = ["传说", "史诗", "史诗"]
        utils.reconcile_equipment(task, ["史诗", "", None])  # 3 號位看不清：不動
        self.assertEqual(equipment["names"], ["", "", "超负荷动力机关"])
        self.assertEqual(equipment["qualities"], ["史诗", "", "史诗"])
        # 名稱未知、品質史詩：之後只比品質，不會被優先級較低的史詩換掉
        self.assertFalse(utils._should_install_equipment(None, "", "史诗", new_item("符文图样之锤", "史诗"))[0])

    def test_removed_count_from_panel(self):
        texts = [box("移除", 0.17, 0.66, 0.21, 0.69), box("3/5", 0.35, 0.66, 0.38, 0.69)]
        task = FakeFrameTask([frame([LEGEND, EPIC, EPIC])], texts)
        utils.read_combatant_removed_count(task)
        self.assertEqual(task.node_status["removed_card_count"], 3)


if __name__ == "__main__":
    unittest.main()

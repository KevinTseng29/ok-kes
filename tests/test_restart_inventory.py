import importlib.util
import os
import sys
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import preset_deck  # noqa: E402

RECORDS = [{"name": "明滅劍", "effects": ["片鱗:暗(閃擊)"], "divine_text": [], "reject_divine": False},
           {"name": "劍之共鳴", "effects": ["生成3張劍穗"], "divine_text": [], "reject_divine": False}]


def task(name="自动卡厄思模式（实验）", preset=True, records=RECORDS):
    t = SimpleNamespace(name=name, preset_deck_enabled=preset, config={"预设卡组": records},
                        _needs_inventory=True, logs=[])
    t.log_info = lambda message, notify=False: t.logs.append(message)
    t.sleep = lambda seconds: None
    t.ocr = lambda *args, **kwargs: []
    return t


class TestRestartInventory(unittest.TestCase):
    """重啟後第一次到路線頁：戰鬥員界面核對裝備與移除次數，實驗模式再讀牌組，最後關回地圖。"""

    def run_inventory(self, t, combatant=True, deck=True, live=("传说", "史诗", "史诗")):
        def read(task_, groups):
            task_._preset_name_counts = {"明灭剑": 1, "剑之共鸣": 2}
            return {}

        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch.object(preset_deck, name, **kwargs)) for name, kwargs in {
                "_enter_combatant_page": {"return_value": combatant},
                "_enter_deck_from_combatant": {"return_value": deck},
                "_read_deck_counts": {"side_effect": read},
                "read_combatant_equipment": {"return_value": list(live) if live else None},
                "reconcile_equipment": {},
                "read_combatant_removed_count": {},
                "_close_combatant_page": {},
            }.items()}
            result = preset_deck.inventory_after_restart(t)
        self.assertFalse(t._needs_inventory)
        return result, mocks

    def test_checks_equipment_and_reads_deck(self):
        t = task()
        result, mocks = self.run_inventory(t)
        self.assertTrue(result)
        mocks["reconcile_equipment"].assert_called_once_with(t, ["传说", "史诗", "史诗"])
        mocks["read_combatant_removed_count"].assert_called_once()
        mocks["_read_deck_counts"].assert_called_once()
        mocks["_close_combatant_page"].assert_called_once()
        self.assertIn("明灭剑 1张", t.logs[-1])

    def test_normal_chaos_mode_checks_equipment_only(self):
        t = task(name="自动卡厄思模式", preset=False)
        result, mocks = self.run_inventory(t)
        self.assertTrue(result)
        mocks["reconcile_equipment"].assert_called_once()
        mocks["_enter_deck_from_combatant"].assert_not_called()

    def test_not_main_member_or_cannot_open(self):
        result, mocks = self.run_inventory(task(), live=None)
        mocks["reconcile_equipment"].assert_not_called()
        result, mocks = self.run_inventory(task(), combatant=False)
        self.assertTrue(result)
        mocks["read_combatant_equipment"].assert_not_called()
        result, mocks = self.run_inventory(task(), deck=False)
        mocks["_read_deck_counts"].assert_not_called()
        mocks["_close_combatant_page"].assert_called_once()

    def test_other_modes_skip(self):
        result, mocks = self.run_inventory(task(name="自动出击模式"))
        self.assertFalse(result)
        mocks["_enter_combatant_page"].assert_not_called()


if __name__ == "__main__":
    unittest.main()

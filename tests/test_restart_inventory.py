import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import preset_deck  # noqa: E402

RECORDS = [{"name": "明滅劍", "effects": ["片鱗:暗(閃擊)"], "divine_text": [], "reject_divine": False},
           {"name": "劍之共鳴", "effects": ["生成3張劍穗"], "divine_text": [], "reject_divine": False}]


def task(enabled=True, records=RECORDS):
    t = SimpleNamespace(preset_deck_enabled=enabled, config={"预设卡组": records}, _needs_inventory=True, logs=[])
    t.log_info = lambda message, notify=False: t.logs.append(message)
    return t


class TestRestartInventory(unittest.TestCase):
    def test_reads_main_deck_once(self):
        t = task()

        def read(task_, groups):
            task_._preset_name_counts = {"明灭剑": 1, "剑之共鸣": 2}
            return {}

        with patch.object(preset_deck, "_open_all_decks_from_any_page", return_value=True), \
                patch.object(preset_deck, "_read_deck_counts", side_effect=read) as reader, \
                patch.object(preset_deck, "_close_combatant_page") as close:
            self.assertTrue(preset_deck.inventory_after_restart(t))
        reader.assert_called_once()
        close.assert_called_once()
        self.assertFalse(t._needs_inventory)
        self.assertIn("明灭剑 1张", t.logs[-1])

    def test_open_failure_still_clears_flag(self):
        t = task()
        with patch.object(preset_deck, "_open_all_decks_from_any_page", return_value=False), \
                patch.object(preset_deck, "_read_deck_counts") as reader, \
                patch.object(preset_deck, "_close_combatant_page"):
            self.assertTrue(preset_deck.inventory_after_restart(t))
        reader.assert_not_called()
        self.assertFalse(t._needs_inventory)

    def test_skipped_without_preset_deck(self):
        for t in (task(enabled=False), task(records=[])):
            with patch.object(preset_deck, "_open_all_decks_from_any_page") as opener:
                self.assertFalse(preset_deck.inventory_after_restart(t))
            opener.assert_not_called()
            self.assertFalse(t._needs_inventory)


if __name__ == "__main__":
    unittest.main()

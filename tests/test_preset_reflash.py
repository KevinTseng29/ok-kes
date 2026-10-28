import importlib.util
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import preset_deck  # noqa: E402

CARDS = [{"name": "明灭剑", "description": "赋予目标痛苦4"}, {"name": "明灭剑 (无限)", "description": "依X"},
         {"name": "明灭剑", "description": "获得AP1"}]


class TestReflashFallback(unittest.TestCase):
    """冥想（再次灵光一闪）三张都不符合目标：跳过保留原本效果，不随机换掉。"""

    def task(self, reflash_in):
        return SimpleNamespace(_preset_reflash_until=time.time() + reflash_in, log_info=lambda *_: None)

    def test_reflash_skips_instead_of_random(self):
        task = self.task(60)
        with patch.object(preset_deck, "_card_has_big_divine", return_value=False), \
                patch.object(preset_deck, "_bump_name_count") as bump, \
                patch.object(preset_deck, "_add_pending_for_card") as pending:
            self.assertIs(preset_deck._fallback_choice(task, CARDS), preset_deck.SKIP_CHOICE)
        bump.assert_not_called()
        pending.assert_not_called()

    def test_normal_flash_still_picks_a_card(self):
        task = self.task(-1)  # 期限已過＝不是冥想
        with patch.object(preset_deck, "_card_has_big_divine", return_value=False), \
                patch.object(preset_deck, "_bump_name_count"), patch.object(preset_deck, "_add_pending_for_card"):
            self.assertIn(preset_deck._fallback_choice(task, CARDS), CARDS)

    def test_reflash_flag_expiry(self):
        self.assertTrue(preset_deck._reflash_active(self.task(30)))
        self.assertFalse(preset_deck._reflash_active(self.task(-1)))
        self.assertFalse(preset_deck._reflash_active(SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()

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

import utils  # noqa: E402


class TestDiceRoll(unittest.TestCase):
    """事件技能檢定的擲骰頁（下方「掷骰影响+5」）：點中間的骰子；動畫期間不連點（2026-10-29 卡 90 秒兩次）。"""

    def task(self, texts):
        t = SimpleNamespace(width=1280, height=720, logs=[],
                            all_texts=[SimpleNamespace(name=n, x=560, y=y * 720, width=160, height=20) for n, y in texts])
        t.log_info = t.logs.append
        return t

    def test_clicks_dice_once_per_interval(self):
        t = self.task([("巧手", 0.15), ("掷骰影响+5", 0.90)])
        with patch.object(utils, "_move_and_click") as click:
            self.assertTrue(utils.handle_dice_roll(t))
            self.assertTrue(utils.handle_dice_roll(t))  # 動畫中：不再點
        click.assert_called_once_with(t, 0.5, 0.45)

    def test_event_option_with_dice_text_is_not_dice_page(self):
        """事件選項「[口才]说明方向掷骰6成功时…」在畫面下方，不是擲骰頁（16:58 誤判點了畫面中間）。"""
        with patch.object(utils, "_move_and_click") as click:
            self.assertFalse(utils.handle_dice_roll(self.task([("[口才]说明方向", 0.86), ("掷骰6", 0.88)])))
        click.assert_not_called()

    def test_other_page(self):
        with patch.object(utils, "_move_and_click") as click:
            self.assertFalse(utils.handle_dice_roll(self.task([("请选择你的命运", 0.93)])))
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

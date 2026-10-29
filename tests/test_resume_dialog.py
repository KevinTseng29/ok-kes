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
import utils_chaos  # noqa: E402


def box(name, cx, cy):
    return SimpleNamespace(name=name, x=cx * 1280 - 40, y=cy * 720 - 10, width=80, height=20)


def task_with(texts):
    t = SimpleNamespace(width=1280, height=720, all_texts=texts, logs=[], clicked=[],
                        node_status={"save_target_member": False}, config={"刷存档主战员": "奥尔莱亚"})
    t.log_info = lambda message, notify=False: t.logs.append(message)
    t.click_box = t.clicked.append
    t.sleep = lambda *_: None
    return t


class TestResumeDialog(unittest.TestCase):
    """「卡厄思連線意外中斷。是否要繼續進行？」：按繼續進行接回這一局（19:20 卡在這裡 8 分鐘）。"""

    def test_clicks_resume(self):
        resume = box("继续进行", 0.63, 0.77)
        t = task_with([box("卡厄思连线意外中断。", 0.5, 0.44), box("是否要继续进行？", 0.5, 0.48),
                       box("撤退", 0.38, 0.77), resume])
        self.assertTrue(utils.handle_resume_dialog(t))
        self.assertEqual(t.clicked, [resume])

    def test_other_pages(self):
        self.assertFalse(utils.handle_resume_dialog(task_with([box("继续进行", 0.92, 0.92)])))


class TestSaveTargetMemberWaitsForBusyPage(unittest.TestCase):
    """卡牌分配這類頁面上方也有血量：不要去點頭像打斷它（19:20 一邊按跳過一邊點頭像，來回 13 次）。"""

    def test_skip_on_busy_page(self):
        t = task_with([box("跳过", 0.75, 0.92)])
        with patch.object(utils_chaos, "_get_current_hp_percent", return_value=80), \
                patch.object(utils_chaos, "_move_and_click") as click:
            self.assertFalse(utils_chaos.handle_save_target_member(t))
        click.assert_not_called()

    def test_goes_on_map_page(self):
        t = task_with([box("第1层", 0.1, 0.1)])
        with patch.object(utils_chaos, "_get_current_hp_percent", return_value=80), \
                patch.object(utils_chaos, "_move_and_click") as click:
            self.assertTrue(utils_chaos.handle_save_target_member(t))
        click.assert_called_once()


if __name__ == "__main__":
    unittest.main()

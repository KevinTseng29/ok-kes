import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
import unittest.mock
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import utils_sortie  # noqa: E402


def box(name, cx, cy, w=0.06, h=0.04):
    return SimpleNamespace(name=name, x=(cx - w / 2) * 1280, y=(cy - h / 2) * 720, width=w * 1280, height=h * 720,
                           area=lambda: w * h)


class TestBossSelection(unittest.TestCase):
    """換層時的首領選擇頁：簡中「遇見的首領」與繁中「遭遇的BOSS」都要認得（error_scenes/20261028_214704）。"""

    def run_page(self, prompt):
        t = SimpleNamespace(width=1280, height=720, logs=[],
                            all_texts=[box(prompt, 0.5, 0.93, w=0.26), box("美梦", 0.358, 0.708), box("塞拉菲翁", 0.641, 0.708)])
        t.log_info = lambda message, notify=False: t.logs.append(message)
        t.sleep = lambda seconds: None
        with patch.object(utils_sortie, "_move_and_click") as click:
            handled = utils_sortie.handle_boss_selection(t)
        return handled, click

    def test_traditional_server_prompt(self):
        handled, click = self.run_page("请选择在核心遭遇的BOSS。")
        self.assertTrue(handled)
        click.assert_called_once()

    def test_simplified_server_prompt(self):
        self.assertTrue(self.run_page("请选择在核心遇见的首领")[0])

    def test_other_page(self):
        self.assertFalse(self.run_page("请选择1张欲获得的卡牌。")[0])

    def boss_page(self, left, right):
        t = SimpleNamespace(width=1280, height=720, logs=[],
                            all_texts=[box("请选择在核心遭遇的BOSS。", 0.5, 0.93, w=0.26),
                                       box(left[0], 0.358, 0.669), box(left[1], 0.358, 0.708),
                                       box(right[0], 0.641, 0.669), box(right[1], 0.641, 0.708)])
        t.log_info = lambda message, notify=False: t.logs.append(message)
        t.sleep = lambda seconds: None
        with patch.object(utils_sortie, "_move_and_click") as click:
            self.assertTrue(utils_sortie.handle_boss_selection(t))
        return click.call_args.args[1]

    def test_avoids_listed_bosses(self):
        for _ in range(10):  # 原本是隨機，多跑幾次確定每次都避開
            self.assertEqual(self.boss_page(("瘟神", "某某"), ("戴奥斯", "塞拉菲翁")), 0.641)
            self.assertEqual(self.boss_page(("尼希隆", "美梦"), ("金狮子", "某某")), 0.358)

    def test_random_when_both_or_none_avoided(self):
        self.assertIn(self.boss_page(("瘟神", "甲"), ("金狮子", "乙")), (0.358, 0.641))
        self.assertIn(self.boss_page(("尼希隆", "美梦"), ("戴奥斯", "塞拉菲翁")), (0.358, 0.641))


class TestDrawCardSelect(unittest.TestCase):
    """戰鬥中「請選擇1張欲抽取的卡牌」：照出牌優先級挑，沒命中就隨機（error_scenes/20261028_220923）。"""

    def run_page(self, prompt, cards, priority):
        t = SimpleNamespace(width=1280, height=720, logs=[], config={"出牌优先级": priority},
                            all_texts=[box(prompt, 0.5, 0.131, w=0.3)])
        t.log_info = lambda message, notify=False: t.logs.append(message)
        t.sleep = lambda seconds: None
        with patch.object(utils_sortie, "recognize_cards", return_value=cards), \
                patch.object(utils_sortie, "_move_and_click") as click:
            handled = utils_sortie.handle_draw_card_select(t)
        return handled, click

    def test_picks_priority_card(self):
        cards = [{"name": "节奏", "x": 0.25, "y": 0.29}, {"name": "节奏：琶音", "x": 0.5, "y": 0.29}]
        handled, click = self.run_page("请选择1张欲抽取的卡牌。", cards, ["琶音", "节奏"])
        self.assertTrue(handled)
        click.assert_called_once_with(unittest.mock.ANY, 0.5, 0.29)

    def test_random_when_no_priority(self):
        cards = [{"name": "节奏", "x": 0.25, "y": 0.29}]
        handled, click = self.run_page("请选择1张欲抽取的卡牌。", cards, ["琶音"])
        self.assertTrue(handled)
        click.assert_called_once()

    def test_other_prompt(self):
        self.assertFalse(self.run_page("请选择功能", [{"name": "节奏", "x": 0.2, "y": 0.3}], [])[0])


if __name__ == "__main__":
    unittest.main()

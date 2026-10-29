import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

import preset_deck  # noqa: E402
import utils  # noqa: E402
import utils_chaos  # noqa: E402

RECORDS = [{"name": "明滅劍", "effects": [], "divine_text": [], "reject_divine": False},
           {"name": "劍之共鳴", "effects": [], "divine_text": [], "reject_divine": False}]


def empty_deck_task(removed=3, **config):
    task = SimpleNamespace(preset_deck_enabled=True, width=1280, height=720, logs=[],
                           config={"刷空档": True, **config},
                           node_status={"removed_card_count": removed, "empty_deck_done": False})
    task.log_info = lambda message, notify=False: task.logs.append(message)
    task.sleep = lambda *_: None
    return task


class TestEmptyDeckDone(unittest.TestCase):
    """刷空檔（實驗卡厄思）：主練預設卡組以外刪到 0 張、而且主練整段都數到了，才算達成、去逃脫。"""

    def check(self, task, counts):
        with patch.object(preset_deck, "load_preset_records", return_value=RECORDS), \
                patch.object(preset_deck, "read_removal_deck_counts", return_value=counts) as read, \
                patch.object(utils, "_journal"), patch.object(utils, "_move_and_click") as click:
            handled = utils._check_empty_deck_done(task)
        return handled, read, click

    def test_done_when_no_other_cards_left(self):
        task = empty_deck_task()
        handled, read, _ = self.check(task, {"__non_preset__": 0, "__section_complete__": True})
        self.assertTrue(handled)
        self.assertTrue(task.node_status["empty_deck_done"])
        self.assertEqual(read.call_args.kwargs["extra_names"], ["明滅劍", "劍之共鳴"])

    def test_not_done_with_cards_left_or_section_cut(self):
        for counts in ({"__non_preset__": 2, "__section_complete__": True},
                       {"__non_preset__": 0, "__section_complete__": False}):
            task = empty_deck_task()
            self.check(task, counts)
            self.assertFalse(task.node_status["empty_deck_done"], counts)

    def test_counts_once_per_removal(self):
        task = empty_deck_task()
        self.check(task, {"__non_preset__": 2, "__section_complete__": True})
        handled, read, _ = self.check(task, {"__non_preset__": 2, "__section_complete__": True})
        self.assertFalse(handled)
        read.assert_not_called()

    def test_no_removal_yet_or_not_experimental(self):
        handled, read, _ = self.check(empty_deck_task(removed=0), {})
        self.assertFalse(handled)
        task = empty_deck_task()
        task.preset_deck_enabled = False
        handled, read, _ = self.check(task, {})
        self.assertFalse(handled)
        read.assert_not_called()

    def test_done_opens_menu_to_escape(self):
        task = empty_deck_task()
        task.node_status["empty_deck_done"] = True
        handled, _, click = self.check(task, {})
        self.assertTrue(handled)
        click.assert_called_once_with(task, 0.959, 0.053)


class TestDeckSection(unittest.TestCase):
    """所有牌堆頁：主練不一定排第一段，要找主練名字那一段；段首牌堆圖示下的數字就是張數。
    座標取自 2026-10-29 實際截圖：段首圖示 y≈0.139、張數「06」在 (0.116, 0.183)、名字在 y≈0.464、下一段圖示 y≈0.972。"""

    def box(self, name, cx, cy):
        return SimpleNamespace(name=name, x=cx * 1280 - 10, y=cy * 720 - 8, width=20, height=16)

    def card(self, y):
        return {"name": "剑击", "feature_box": SimpleNamespace(x=600, y=y * 720, width=20, height=20)}

    def test_header_count(self):
        task = SimpleNamespace(width=1280, height=720,
                               all_texts=[self.box("所有牌堆", 0.17, 0.05), self.box("17", 0.65, 0.05),
                                          self.box("06", 0.116, 0.183)])
        self.assertEqual(preset_deck._deck_section_header_count(task, 0.139), 6)
        self.assertIsNone(preset_deck._deck_section_header_count(task, 0.60))

    def test_section_excludes_previous_and_next_member(self):
        task = SimpleNamespace(width=1280, height=720)
        cards = [self.card(0.05), self.card(0.15), self.card(0.55), self.card(0.98)]
        filtered, reached_next, top = preset_deck._filter_deck_section(task, cards, [0.02, 0.139, 0.972], 0.464)
        self.assertEqual([c["feature_box"].y / 720 for c in filtered], [0.15, 0.55])
        self.assertTrue(reached_next)
        self.assertAlmostEqual(top, 0.139)


class TestTopRightToggle(unittest.TestCase):
    """配置隊伍頁右上角開關：刷空檔要關著。"""

    def frame_task(self, name):
        strip = cv2.imread(os.path.join(ROOT, "tests", "fixtures", "team", name))
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[0:80, 1080:1280] = strip
        return SimpleNamespace(frame=frame, width=1280, height=720)

    def test_on_and_off(self):
        self.assertTrue(utils_chaos._top_right_toggle_on(self.frame_task("toggle_on.png"))[0])
        self.assertFalse(utils_chaos._top_right_toggle_on(self.frame_task("toggle_off.png"))[0])


class TestInitialPageAffix(unittest.TestCase):
    """刷空檔：初始頁只看地圖詞條，有「在安全區域無法休息」就再次觀測；不看存檔保存上限。"""

    def run_page(self, value_text):
        task = empty_deck_task()
        observe = SimpleNamespace(name="再次观测", x=0.8 * 1280, y=0.8 * 720, width=10, height=10)
        task.all_texts = [observe]
        task.click_box = lambda box: task.logs.append("click_observe")

        def region_text(_task, region):
            return "卡厄思" if region[0] < 0.1 else value_text

        with patch.object(utils_chaos, "_get_region_text", side_effect=region_text), \
                patch.object(utils_chaos, "stop_if_round_finished", return_value=False):
            return utils_chaos.handle_season_chaos_initial_page(task), task.logs

    def test_bad_affix_rerolls(self):
        handled, logs = self.run_page("存档资料储存上限150pt【不安1】在安全区域无法 休息")
        self.assertTrue(handled)
        self.assertIn("click_observe", logs)

    def test_low_storage_ignored(self):
        handled, logs = self.run_page("存档资料储存上限120pt【疾病3】最大HP减少40%")
        self.assertFalse(handled)
        self.assertNotIn("click_observe", logs)


if __name__ == "__main__":
    unittest.main()

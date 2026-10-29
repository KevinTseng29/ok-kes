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
import utils  # noqa: E402

RECORDS = [
    {"name": "明滅劍", "effects": ["片鱗:暗(閃擊)"], "divine_text": [], "reject_divine": False},
    {"name": "劍之共鳴", "effects": ["生成3張劍穗"], "divine_text": [], "reject_divine": False},
    {"name": "劍之共鳴", "effects": ["生成3張劍穗"], "divine_text": [], "reject_divine": False},
    {"name": "光之劍路", "effects": ["持續1回合自身傷害量增加15%"], "divine_text": [], "reject_divine": True},
]


def preset_task(pending=(), reflash=False, counts=None):
    return SimpleNamespace(
        preset_deck_enabled=True, log_info=lambda *_, **__: None,
        _preset_meditation_pending=[{"name": n, "current_effect": "", "target_effect": t} for n, t in pending],
        _preset_reflash_until=time.time() + (60 if reflash else -1),
        _preset_name_counts=counts or {},
    )


class TestPresetSelectNames(unittest.TestCase):
    """實驗卡厄思：要閃、要複製哪張由預設卡組決定，不再看閃光卡牌列表、複製卡牌列表。"""

    def names(self, task, action):
        with patch.object(preset_deck, "load_preset_records", return_value=RECORDS):
            return preset_deck.preset_select_names(task, action)

    def test_meditation_only_pending(self):
        task = preset_task(pending=[("明灭剑", "片鱗:暗(閃擊)")], reflash=True)
        self.assertEqual(self.names(task, "灵光"), ["明灭剑"])

    def test_flash_pending_first_then_preset_order(self):
        task = preset_task(pending=[("之剑路", "持續1回合自身傷害量增加15%")])
        self.assertEqual(self.names(task, "灵光"), ["之剑路", "明滅劍", "劍之共鳴"])

    def test_copy_skips_names_already_enough(self):
        task = preset_task(counts={"明滅劍": 1, "劍之共鳴": 1, "光之劍路": 1})
        self.assertEqual(self.names(task, "复制"), ["劍之共鳴"])

    def test_no_preset_falls_back(self):
        with patch.object(preset_deck, "load_preset_records", return_value=[]):
            self.assertIsNone(preset_deck.preset_select_names(preset_task(), "灵光"))


class TestDropPendingAfterTargetFlash(unittest.TestCase):
    def test_target_hit_removes_one_pending(self):
        """14:21 光之劍路閃到目標效果，14:22 又被拿去冥想：選到目標效果就移出待冥想。"""
        task = preset_task(pending=[("之剑路", "持續1回合自身傷害量增加15%"), ("明灭剑", "片鱗:暗(閃擊)")])
        preset_deck._drop_meditation_pending(task, "光之剑路", "持續1回合自身傷害量增加15%")
        self.assertEqual([item["name"] for item in task._preset_meditation_pending], ["明灭剑"])


class TestSelectCardInOrder(unittest.TestCase):
    """最優先的不在第一頁時，翻完整個列表再回頭選它，不先選到後面的。"""

    def run_pages(self, pages, names):
        """pages：每一頁看得到的卡名；往下翻 index+1、往上翻 index-1。"""
        state = {"page": 0, "clicked": []}
        task = SimpleNamespace(ocr=lambda: [], log_info=lambda *_, **__: None, sleep=lambda *_: None)

        def visible(*_, **__):
            return [{"name": n, "x": 0.3, "y": 0.2} for n in pages[state["page"]]]

        def scroll(_task, _x, _y, amount, _page):
            state["page"] += 1 if amount < 0 else -1

        def at_edge(_task, _x, y, _page):
            return state["page"] == (len(pages) - 1 if y > 0.5 else 0)

        with patch.object(utils, "_simplify_texts", return_value=[]), \
                patch.object(utils, "recognize_cards_in_deck", side_effect=visible), \
                patch.object(utils, "region_white_ratio", return_value=0.2), \
                patch.object(utils, "_point_is_white", side_effect=at_edge), \
                patch.object(utils, "_scroll_card_page", side_effect=scroll), \
                patch.object(utils, "_journal"), \
                patch.object(utils, "_move_and_click", side_effect=lambda *_: state["clicked"].append(
                    (state["page"], [c for c in pages[state["page"]]]))):
            result = utils._select_card_in_order(task, names, "灵光", preset_deck._name_matches)
        return result, state

    def test_top_priority_on_later_page(self):
        pages = [["之剑路", "循环之刃"], ["缕光芒", "明灭剑 (强化)"]]
        result, state = self.run_pages(pages, ["明灭剑", "光之剑路"])
        self.assertTrue(result)
        self.assertEqual(state["clicked"][0][0], 1)

    def test_goes_back_up_for_best_seen(self):
        pages = [["光之剑路", "循环之刃"], ["缕光芒", "剑光"]]
        result, state = self.run_pages(pages, ["明灭剑", "光之剑路"])
        self.assertTrue(result)
        self.assertEqual(state["clicked"], [(0, ["光之剑路", "循环之刃"])])

    def test_ocr_slip_still_matches(self):
        result, state = self.run_pages([["剑光"], ["灭剑（(闪击)"]], ["明灭剑"])
        self.assertTrue(result)

    def test_none_found(self):
        result, state = self.run_pages([["剑光"], ["缕光芒"]], ["明灭剑"])
        self.assertFalse(result)
        self.assertEqual(state["clicked"], [])


class TestEnsureThreeCards(unittest.TestCase):
    def card(self, x):
        return {"name": "光之剑路", "x": x, "description": "造成240%的伤害",
                "name_region": (x - 0.08, 0.22, x + 0.08, 0.27), "type_region": (x - 0.05, 0.26, x + 0.05, 0.31),
                "description_region": (x - 0.10, 0.40, x + 0.10, 0.77),
                "feature_box": SimpleNamespace(x=x * 1280 - 70, y=194, width=20, height=20)}

    def test_one_card_gets_two_neighbours(self):
        """13:55 光之劍路那頁只認到 1 張：照三欄間距補另外兩張，讓普通的也能選。"""
        task = SimpleNamespace(width=1280, height=720, log_info=lambda *_, **__: None)
        with patch.object(preset_deck, "_get_region_text", return_value="造成240%的伤害，获得决心2"):
            cards = preset_deck._ensure_three_cards(task, [self.card(0.269)])
        self.assertEqual(len(cards), 3)
        self.assertAlmostEqual(cards[1]["x"], 0.522, places=2)
        self.assertAlmostEqual(cards[2]["x"], 0.775, places=2)

    def test_empty_column_not_added(self):
        task = SimpleNamespace(width=1280, height=720, log_info=lambda *_, **__: None)
        with patch.object(preset_deck, "_get_region_text", return_value=""):
            cards = preset_deck._ensure_three_cards(task, [self.card(0.269), self.card(0.522)])
        self.assertEqual(len(cards), 2)


if __name__ == "__main__":
    unittest.main()

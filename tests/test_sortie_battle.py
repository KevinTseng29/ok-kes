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

import utils_sortie  # noqa: E402


def battle_task():
    import numpy as np
    keys = []
    t = SimpleNamespace(width=1280, height=720, frame=np.zeros((720, 1280, 3), np.uint8), node_status={}, logs=[],
                        keys=keys, config={})
    t.log_info = lambda message, notify=False: t.logs.append(message)
    t.sleep = lambda seconds: None
    t.send_key = keys.append
    t.box_of_screen = lambda *region: region
    t.find_feature = lambda feature_name, box=None, **kwargs: ["finishturn"] if feature_name == "finishturn" else []
    return t


def run_battle(t, frames, hands, hand_count=None):
    """跑幾幀戰鬥頁；hands 是每一幀的手牌（list of dict），最後一個重複使用。"""
    hands = list(hands)
    for i in range(frames):
        hand = hands[min(i, len(hands) - 1)]
        count = len(hand) if hand_count is None else hand_count
        with patch.object(utils_sortie, "_read_hand_count", return_value=count),                 patch.object(utils_sortie, "mark_battle"),                 patch.object(utils_sortie, "_hand_card_names", return_value=[SimpleNamespace(name=c["name"]) for c in hand]),                 patch.object(utils_sortie, "_hand_cards", return_value=hand):
            utils_sortie.handle_battle_page(t)
    return t.keys


class TestWaitForStableHand(unittest.TestCase):
    """手牌（數量、名稱）要連續兩幀一樣才動作：抽牌、出牌動畫還在播時不塞按鍵（兩次卡死前都是連按）。"""

    def test_first_frame_only_observes(self):
        t = battle_task()
        t.config = {"出牌优先级": ["节奏"]}
        hand = [{"name": "节奏", "key": "1"}]
        self.assertEqual(run_battle(t, 1, [hand]), [])
        self.assertEqual(run_battle(t, 1, [hand]), ["1", "enter"])


class TestUnreadableHand(unittest.TestCase):
    """手牌數不是 0 卻一張都認不出：等 → Enter（卡牌停在選目標狀態）→ 一幀按一張 → 都試過才按 E。"""

    def test_escalates_one_key_per_frame(self):
        t = battle_task()
        keys = run_battle(t, 12, [[]], hand_count=2)
        self.assertEqual(keys[:5], ["enter", "2", "enter", "1", "enter"])
        self.assertIn("e", keys)
        self.assertLess(keys.index("e"), len(keys))

    def test_empty_hand_just_ends_turn(self):
        t = battle_task()
        self.assertEqual(run_battle(t, 4, [[]], hand_count=0), ["e", "e", "e"])


class TestUnplayablePriorityCard(unittest.TestCase):
    """優先級卡牌按了還留在手牌（費用不夠）：第二次還沒出掉就改兜底，一次只按一張。"""

    def test_falls_back_after_one_retry(self):
        t = battle_task()
        t.config = {"出牌优先级": ["节奏"]}
        hand = [{"name": "节奏", "key": "1"}, {"name": "守护", "key": "2"}]
        keys = run_battle(t, 3, [hand])
        self.assertEqual(keys, ["1", "enter", "2", "enter"])  # 先照優先級，還在手上就兜底按一張


class TestArpeggioOrder(unittest.TestCase):
    """好幾張琶音同時在手上：照編號 0→5 先出小的（後面的費用才會降到 0）。"""

    def test_lowest_number_first(self):
        t = battle_task()
        t.config = {"出牌优先级": ["琶音", "节奏"]}
        hand = [{"name": "节奏：琶音（3)", "key": "1"}, {"name": "琶音（0)", "key": "2"},
                {"name": "节奏：琶音(2)", "key": "3"}, {"name": "节奏", "key": "4"}]
        self.assertEqual(run_battle(t, 2, [hand]), ["2", "enter"])


class TestEndTurnWhenNothingPlayable(unittest.TestCase):
    """兜底每張都按過、手牌卻沒變（AP 不夠）：自己按 E；手牌變了就照常繼續出牌。"""

    def test_unplayable_hand_ends_turn(self):
        t = battle_task()
        hand = [{"name": "守护", "key": "1"}, {"name": "防御", "key": "2"}]
        keys = run_battle(t, 4, [hand], hand_count=2)
        self.assertEqual(keys, ["2", "enter", "1", "enter", "e"])

    def test_hand_changed_keeps_playing(self):
        t = battle_task()
        first = [{"name": "守护", "key": "1"}, {"name": "防御", "key": "2"}]
        second = [{"name": "守护", "key": "1"}]
        keys = run_battle(t, 4, [first, first, second, second])
        self.assertEqual(keys, ["2", "enter", "1", "enter"])  # 打出一張後從頭數，沒有按 E


if __name__ == "__main__":
    unittest.main()

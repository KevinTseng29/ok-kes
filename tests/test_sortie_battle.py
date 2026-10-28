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
                        keys=keys, config={}, all_texts=[])
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

    def test_unreadable_means_nothing_playable(self):
        """打不起的牌會變暗往下沉、卡名掉出辨識區：先按一次 Enter（可能有牌停在選目標），再認不到就結束回合，不再一張張試。"""
        t = battle_task()
        self.assertEqual(run_battle(t, 4, [[]], hand_count=2), ["enter", "e"])

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


class TestApAware(unittest.TestCase):
    """讀 AP 和卡名左邊的費用：只出打得起的；費用都認得到又都打不起就直接結束回合（把費用花光）。"""

    def boxes(self, ap, costs):
        def text(name, x, y, w, h):
            return SimpleNamespace(name=name, x=x, y=y, width=w, height=h, area=lambda: w * h)
        texts = [text(str(ap), 0.499 * 1280 - 10, 0.928 * 720 - 15, 20, 30)]
        for i, cost in enumerate(costs):
            texts.append(text(str(cost), (0.30 + 0.15 * i) * 1280 - 25, 0.75 * 720, 10, 20))
        return texts

    def hand(self, names):
        return [{"name": name, "key": str(i + 1), "x": 0.30 + 0.15 * i, "left_x": 0.30 + 0.15 * i}
                for i, name in enumerate(names)]

    def test_card_cost_and_ap(self):
        t = battle_task()
        t.all_texts = self.boxes(1, [2])
        name = SimpleNamespace(name="聚光灯", x=0.30 * 1280, y=0.75 * 720, width=60, height=20, area=lambda: 1200)
        self.assertEqual(utils_sortie._card_cost(t, name), 2)
        self.assertEqual(utils_sortie._read_ap(t), 1)

    def test_skips_unaffordable_priority_and_ends_turn(self):
        t = battle_task()
        t.config = {"出牌优先级": ["聚光灯", "小丑"]}
        hand = [dict(c, cost=cost) for c, cost in zip(self.hand(["聚光灯", "小丑"]), (2, 1))]
        t.all_texts = self.boxes(1, [2, 1])
        self.assertEqual(run_battle(t, 2, [hand]), ["2", "enter"])  # 聚光燈 2 費打不起，出 1 費的小丑
        t.all_texts = self.boxes(0, [2])
        self.assertEqual(run_battle(t, 2, [[hand[0]]])[-1], "e")  # AP 0、剩 2 費：結束回合


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

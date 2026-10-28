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


class TestUnreadableHand(unittest.TestCase):
    """有卡牌停在選目標狀態（手牌被擠到下面、一張都認不出）時按 E 沒反應：連續兩次就按 Enter 確認。"""

    def run_frames(self, hand_count, frames, cards=()):
        t = battle_task()
        with patch.object(utils_sortie, "_read_hand_count", return_value=hand_count), \
                patch.object(utils_sortie, "mark_battle"), \
                patch.object(utils_sortie, "_hand_card_names", return_value=[]), \
                patch.object(utils_sortie, "_hand_cards", return_value=list(cards)), \
                patch.object(utils_sortie, "_try_all_card_keys"):
            for _ in range(frames):
                utils_sortie.handle_battle_page(t)
        return t.keys

    def test_selected_card_gets_confirmed(self):
        self.assertEqual(self.run_frames(6, 4), ["e", "enter", "e", "enter"])

    def test_empty_hand_just_ends_turn(self):
        self.assertEqual(self.run_frames(0, 3), ["e", "e", "e"])


class TestUnplayablePriorityCard(unittest.TestCase):
    """優先級卡牌按了還留在手牌（費用不夠）：第二次還沒出掉就改兜底出牌，不再同一張連試四次。"""

    def test_falls_back_after_one_retry(self):
        t = battle_task()
        t.config = {"出牌优先级": ["节奏"]}
        hand = [{"name": "节奏", "key": "1"}, {"name": "守护", "key": "2"}]
        with patch.object(utils_sortie, "_read_hand_count", return_value=2), \
                patch.object(utils_sortie, "mark_battle"), \
                patch.object(utils_sortie, "_hand_card_names", return_value=["节奏", "守护"]), \
                patch.object(utils_sortie, "_hand_cards", return_value=hand), \
                patch.object(utils_sortie, "_try_all_card_keys") as fallback:
            for _ in range(2):
                utils_sortie.handle_battle_page(t)
        self.assertEqual(t.keys, ["1", "enter"])  # 第一次照優先級出牌
        fallback.assert_called_once_with(t, 2)  # 第二次還在手上就改兜底


class TestEndTurnWhenNothingPlayable(unittest.TestCase):
    """兜底出牌每張都按過、手牌卻沒變（AP 不夠）：自己按 E 結束回合，不再一直循環跳 AP 不足。"""

    def run_frames(self, hands, priority=("节奏",)):
        t = battle_task()
        t.config = {"出牌优先级": list(priority)}
        frames = iter(hands)
        current = {}

        def next_hand():
            current["hand"] = next(frames)

        with patch.object(utils_sortie, "_read_hand_count", side_effect=lambda task: len(current["hand"])), \
                patch.object(utils_sortie, "mark_battle"), \
                patch.object(utils_sortie, "_hand_card_names",
                             side_effect=lambda task: [c["name"] for c in current["hand"]]), \
                patch.object(utils_sortie, "_hand_cards", side_effect=lambda task: list(current["hand"])), \
                patch.object(utils_sortie, "_try_all_card_keys") as fallback:
            for _ in hands:
                next_hand()
                utils_sortie.handle_battle_page(t)
        return t.keys, fallback

    def test_unplayable_hand_ends_turn(self):
        hand = [{"name": "节奏", "key": "1"}, {"name": "聚光灯", "key": "2"}]
        keys, fallback = self.run_frames([hand] * 3)
        fallback.assert_called_once()
        self.assertEqual(keys, ["1", "enter", "e"])  # 出牌 → 沒出掉改兜底 → 手牌沒變就結束回合

    def test_hand_changed_keeps_playing(self):
        hand = [{"name": "节奏", "key": "1"}, {"name": "聚光灯", "key": "2"}]
        after = [{"name": "聚光灯", "key": "1"}]  # 兜底打出了一張
        keys, fallback = self.run_frames([hand, hand, after], priority=("节奏", "聚光灯"))
        self.assertNotIn("e", keys)
        self.assertEqual(keys, ["1", "enter", "1", "enter"])  # 照常打下一張


if __name__ == "__main__":
    unittest.main()

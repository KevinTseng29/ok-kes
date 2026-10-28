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


if __name__ == "__main__":
    unittest.main()

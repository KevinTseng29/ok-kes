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

# 安裝裝備頁三名主戰員的等級標籤（1280x720，實際日誌的中心位置）
LEVEL_TAGS = [SimpleNamespace(x=790, y=y - 10, width=26, height=20) for y in (231, 391, 552)]


def avatar(row, confidence):
    """頭像比對結果：落在第 row 號（1 起算）的那一列。"""
    tag = LEVEL_TAGS[row - 1]
    return SimpleNamespace(x=tag.x + 40, y=tag.y - 20, width=40, height=40, confidence=confidence)


class FakeTask:
    def __init__(self, matches, remembered=None):
        self.matches = list(matches)
        self.logs = []
        self.sleeps = 0
        if remembered is not None:
            self._target_member_index = remembered

    def feature_exists(self, name):
        return True

    def box_of_screen(self, *region):
        return region

    def find_one(self, **kwargs):
        return self.matches.pop(0) if self.matches else None

    def log_info(self, message, notify=False):
        self.logs.append(message)

    def sleep(self, seconds):
        self.sleeps += 1


class TestTargetMemberIndex(unittest.TestCase):
    def find(self, task):
        with patch.object(utils.guard, "save_scene") as scene:
            index = utils._find_target_member_index(task, LEVEL_TAGS, (0, 0, 1, 1), "target_member_tiny")
        return index, scene.call_count

    def test_confident_match_is_used_and_remembered(self):
        task = FakeTask([avatar(1, 0.8569)])
        self.assertEqual(self.find(task), (0, 0))
        self.assertEqual(task._target_member_index, 0)

    def test_low_confidence_wrong_member_is_rechecked(self):
        # 今天 05:16 的情況：第一次在第 3 號誤配到 0.6455，重新比對後第 1 號 0.85
        task = FakeTask([avatar(3, 0.6455), avatar(1, 0.8500)])
        self.assertEqual(self.find(task), (0, 1))
        self.assertEqual(task.sleeps, 1)

    def test_still_low_uses_member_seen_earlier_this_run(self):
        task = FakeTask([avatar(3, 0.6314), avatar(3, 0.6404)], remembered=0)
        self.assertEqual(self.find(task)[0], 0)
        task = FakeTask([None, None], remembered=0)
        self.assertEqual(self.find(task)[0], 0)

    def test_unknown_when_never_seen(self):
        task = FakeTask([avatar(3, 0.64), avatar(3, 0.64)])
        self.assertIsNone(self.find(task)[0])

    def test_reset_clears_remembered_member(self):
        task = SimpleNamespace(node_status=utils._initial_node_status(), _target_member_index=2)
        with patch.object(utils, "_reset_meditation_state"):
            utils.reset_mission_status(task)
        self.assertIsNone(task._target_member_index)


if __name__ == "__main__":
    unittest.main()

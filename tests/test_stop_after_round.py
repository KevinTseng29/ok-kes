import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import utils  # noqa: E402


class FakeTask(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logs, self.disabled = [], False

    def log_info(self, message, notify=False):
        self.logs.append((message, notify))

    def disable(self):
        self.disabled = True


class TestStopAfterRound(unittest.TestCase):
    def test_stops_once_and_notifies(self):
        task = FakeTask(_stop_after_round=True)
        self.assertTrue(utils.stop_if_round_finished(task))
        self.assertTrue(task.disabled)
        self.assertFalse(task._stop_after_round)
        self.assertTrue(task.logs[-1][1], "停止時要發通知")
        # 旗標已清掉，下次不會再停
        task.disabled = False
        self.assertFalse(utils.stop_if_round_finished(task))
        self.assertFalse(task.disabled)

    def test_no_second_notice_after_empty_deck_success(self):
        """刷空檔成功那行已經通知過，停下來那行不再通知。"""
        task = FakeTask(_stop_after_round=True, _stop_notified=True)
        self.assertTrue(utils.stop_if_round_finished(task))
        self.assertFalse(task.logs[-1][1])
        self.assertFalse(task._stop_notified)

    def test_not_requested(self):
        task = FakeTask()
        self.assertFalse(utils.stop_if_round_finished(task))
        self.assertFalse(task.disabled)


if __name__ == "__main__":
    unittest.main()

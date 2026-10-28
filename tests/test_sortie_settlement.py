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
import utils_sortie  # noqa: E402

W, H = 1280, 720


def box(name, cx, cy, w=0.06, h=0.04):
    return SimpleNamespace(name=name, x=(cx - w / 2) * W, y=(cy - h / 2) * H, width=w * W, height=h * H,
                           area=lambda: w * h)


def task(passed=0, escaped=False, only_first=True):
    t = SimpleNamespace(width=W, height=H, all_texts=[box("结算", 0.550, 0.068)], logs=[],
                        config={"只打第一层": only_first, "领取奖励": False},
                        node_status={"pass_final_boss_count": passed, "is_escaped": escaped, "success_rounds": 0})
    t.log_info = lambda message, notify=False: t.logs.append(message)
    t.sleep = lambda seconds: None
    return t


class TestSortieRewardSettlement(unittest.TestCase):
    """出擊模式獎勵結算頁只在打完一層 boss 後出現：重啟後沒記到通關，也要照「只打第一層」撤退。"""

    def setUp(self):
        patcher = patch.object(utils, "_move_and_click")
        self.click = patcher.start()
        self.addCleanup(patcher.stop)

    def test_restart_lost_boss_record_still_escapes(self):
        t = task(passed=0)
        self.assertTrue(utils_sortie.handle_sortie_reward_settlement(t))
        self.assertEqual(t.node_status["pass_final_boss_count"], 1)
        self.assertEqual(t.node_status["success_rounds"], 1)
        self.click.assert_called_once_with(t, 0.959, 0.051)

    def test_normal_flow_unchanged(self):
        t = task(passed=1)
        self.assertTrue(utils_sortie.handle_sortie_reward_settlement(t))
        self.assertEqual(t.node_status["pass_final_boss_count"], 1)

    def test_escaped_or_multi_floor(self):
        self.assertFalse(utils_sortie.handle_sortie_reward_settlement(task(escaped=True)))
        self.assertFalse(utils_sortie.handle_sortie_reward_settlement(task(only_first=False)))
        self.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

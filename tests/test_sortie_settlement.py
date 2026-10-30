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


class TestRationalSupply(unittest.TestCase):
    """理性不夠領額外戰利品時跳出補充理性：一律放棄、不花鑽石、不改設定；這一局之後不再按「獲得」。"""

    def setUp(self):
        for name in ("_move_and_click",):
            for module in (utils, utils_sortie):
                patcher = patch.object(module, name)
                setattr(self, f"{module.__name__}_click", patcher.start())
                self.addCleanup(patcher.stop)

    def page(self, *texts):
        t = task()
        t.config["领取奖励"] = True
        t.all_texts = list(texts)
        t.click_box = lambda b: t.logs.append(f"click {b.name}")
        return t

    def test_always_cancels_and_keeps_config(self):
        t = self.page(box("补充理性", 0.5, 0.17), box("确认", 0.664, 0.774))
        self.assertTrue(utils_sortie.handle_rational_supply(t))
        self.utils_sortie_click.assert_called_once_with(t, 0.352, 0.774)
        self.assertTrue(t.node_status["rational_exhausted"])
        self.assertTrue(t.config["领取奖励"])  # 不再把設定永久關掉

    def test_stop_after_round_when_switch_on(self):
        """運行總覽「理性用完就停（出擊）」打開：理性用完就打完這局停，只通知一次（停下來那行不再通知）。"""
        t = self.page(box("补充理性", 0.5, 0.17))
        notices = []
        t.log_info = lambda message, notify=False: notices.append(notify)
        with patch.object(utils_sortie, "_stop_when_rational_exhausted", return_value=True):
            utils_sortie.handle_rational_supply(t)
            utils_sortie.handle_rational_supply(t)
        self.assertTrue(t._stop_after_round)
        self.assertTrue(t._stop_notified)
        self.assertEqual(notices, [True, False])

    def test_keep_going_when_switch_off(self):
        t = self.page(box("补充理性", 0.5, 0.17))
        with patch.object(utils_sortie, "_stop_when_rational_exhausted", return_value=False):
            utils_sortie.handle_rational_supply(t)
        self.assertFalse(getattr(t, "_stop_after_round", False))

    def test_no_more_claims_this_run(self):
        t = self.page(box("结算", 0.550, 0.068), box("获得", 0.848, 0.389))
        self.assertTrue(utils_sortie.handle_sortie_reward_settlement(t))
        self.assertIn("click 获得", t.logs)  # 理性夠：領
        t.logs.clear()
        t.node_status["rational_exhausted"] = True
        t.config["只打第一层"] = False
        utils_sortie.handle_sortie_reward_settlement(t)
        self.assertNotIn("click 获得", t.logs)  # 理性用完：不再按獲得
        t.all_texts = [box("卡厄思战利品", 0.503, 0.335)]
        utils_sortie.handle_sortie_reward_claim(t)
        self.utils_sortie_click.assert_called_with(t, 0.355, 0.714)  # 戰利品視窗按放棄

    def test_rational_supply_runs_before_confirm_handlers(self):
        order = utils_sortie.PAGE_HANDLERS
        self.assertLess(order.index(utils_sortie.handle_rational_supply), order.index(utils_sortie.handle_center_confirm))
        self.assertLess(order.index(utils_sortie.handle_rational_supply), order.index(utils_sortie.handle_confirm))


if __name__ == "__main__":
    unittest.main()

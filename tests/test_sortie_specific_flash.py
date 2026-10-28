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

PARPEGGIO = {"name": "音乐开始", "description": "在抽牌堆中所有节奏：琶音各生成1张，基本卡牌费用减少1", "x": 0.5, "y": 0.4}
PLAIN = [{"name": "音乐开始", "description": "抽取2张卡牌", "x": 0.25, "y": 0.4},
         {"name": "音乐开始", "description": "获得2点AP", "x": 0.75, "y": 0.4}]


def skip_box():
    return SimpleNamespace(name="跳过", x=0.94 * 1280 - 20, y=0.93 * 720 - 10, width=40, height=20)


class TestSpecificFlash(unittest.TestCase):
    """出擊實驗模式「首層刷特定閃光」：三選一有琶音就選並記錄；沒有就跳過；觸發的神閃不能跳過就隨便選。"""

    def run_page(self, cards, texts=(), experimental=True, floor=0, obtained=False):
        t = SimpleNamespace(width=1280, height=720, logs=[], all_texts=list(texts),
                            config={"首层刷特定闪光": True, "闪光优先级": ["琶音", "移动至手牌并发动"]},
                            node_status={"pass_final_boss_count": floor, "get_specific_flash": obtained})
        if experimental:
            t.specific_flash_skip = True
        t.log_info = lambda message, notify=False: t.logs.append(message)
        t.sleep = lambda seconds: None
        t.click_box = lambda box: t.logs.append("click_skip")
        with patch.object(utils, "recognize_cards", return_value=cards), \
                patch.object(utils, "find_target_card", return_value=([], [])), \
                patch.object(utils, "_matching_meditation_card_names", return_value=[]), \
                patch.object(utils, "_confirm_divine_flash"), \
                patch.object(utils, "_move_and_click") as click:
            self.assertTrue(utils.handle_view_original(t, page_confirmed=True))
        return t, click

    def test_target_effect_chosen_and_recorded(self):
        t, click = self.run_page(PLAIN + [PARPEGGIO], texts=[skip_box()])
        click.assert_called_once_with(t, 0.5, 0.4)
        self.assertTrue(t.node_status["get_specific_flash"])

    def test_no_target_skips(self):
        t, click = self.run_page(PLAIN, texts=[skip_box()])
        self.assertIn("click_skip", t.logs)
        click.assert_not_called()
        self.assertFalse(t.node_status["get_specific_flash"])

    def test_unskippable_divine_picks_any(self):
        t, click = self.run_page(PLAIN)  # 觸發的神閃：畫面上沒有「跳过」
        click.assert_called_once()
        self.assertNotIn("click_skip", t.logs)

    def test_after_obtained_or_later_floor_uses_priority_then_random(self):
        for kwargs in ({"obtained": True}, {"floor": 1}):
            t, click = self.run_page(PLAIN, texts=[skip_box()], **kwargs)
            click.assert_called_once()
            self.assertNotIn("click_skip", t.logs)

    def test_chaos_mode_keeps_random(self):
        """卡厄思模式的同名設定不受影響：沒命中照舊隨機選。"""
        t, click = self.run_page(PLAIN, texts=[skip_box()], experimental=False)
        click.assert_called_once()
        self.assertNotIn("click_skip", t.logs)


class TestSortieModeExperimental(unittest.TestCase):
    """出擊實驗模式：閃光優先級和首層刷特定閃光接在閃光卡牌列表後面，都有說明；其餘設定和出擊模式一樣。"""

    def test_config(self):
        from SortieMode import SortieMode
        from SortieModeExperimental import SortieModeExperimental
        base = SortieMode(SimpleNamespace(scene=None), None)
        task = SortieModeExperimental(SimpleNamespace(scene=None), None)
        keys = list(task.default_config)
        index = keys.index("闪光卡牌列表")
        self.assertEqual(keys[index + 1:index + 3], ["闪光优先级", "首层刷特定闪光"])
        self.assertEqual([k for k in keys if k not in ("闪光优先级", "首层刷特定闪光")], list(base.default_config))
        self.assertIn("撤退", task.config_description["首层刷特定闪光"])
        self.assertTrue(task.specific_flash_skip)
        self.assertEqual(task.name, "自动出击模式（实验）")


if __name__ == "__main__":
    unittest.main()

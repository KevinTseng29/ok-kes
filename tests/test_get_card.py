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
CARD_STEP = 0.2766  # 獲得卡牌頁三張卡的間距（error_scenes/20261028_182933_SortieMode_stuck）


def box(name, cx, cy, w=0.02, h=0.02, confidence=1.0):
    return SimpleNamespace(name=name, x=(cx - w / 2) * W, y=(cy - h / 2) * H, width=w * W, height=h * H,
                           confidence=confidence, area=lambda: w * h)


class Task(SimpleNamespace):
    def __init__(self, texts, features):
        super().__init__(width=W, height=H, all_texts=texts, features=features, logs=[])

    def box_of_screen(self, *region):
        return region

    def find_feature(self, feature_name, box=None, threshold=0):
        return [b for b in self.features.get(feature_name, []) if b.confidence >= threshold]

    def log_info(self, message, notify=False):
        self.logs.append(message)

    def sleep(self, seconds):
        pass


def get_card_page():
    """實際截圖的比對結果：角色頭像旁的 ✦ 被當成「強化」（0.82），真正的「技能」圖示 0.78。"""
    texts = [box("获得卡牌", 0.502, 0.128, w=0.1), box("请选择1张欲获得的卡牌。", 0.883, 0.131, w=0.18)]
    features = {"enhance": [], "skill": []}
    for i, name in enumerate(("逮到机会", "隐密上膛", "未知：变异体样本")):
        dx = i * CARD_STEP
        texts += [box(name, 0.211 + dx, 0.311, w=0.08), box("技能", 0.234 + dx, 0.347),
                  box("卡牌说明", 0.22 + dx, 0.65, w=0.1)]
        features["enhance"].append(box("enhance", 0.1113 + dx, 0.3090, confidence=0.821))
        features["skill"].append(box("skill", 0.1844 + dx, 0.3472, confidence=0.777))
    return texts, features


class TestRecognizeCards(unittest.TestCase):
    def test_false_enhance_does_not_hide_real_type_icon(self):
        task = Task(*get_card_page())
        cards = utils.recognize_cards(task, page="获得卡牌页面")
        self.assertEqual([c["name"] for c in cards], ["逮到机会", "隐密上膛", "未知：变异体样本"])
        self.assertTrue(all(c["feature_name"] == "skill" for c in cards))


class TestGetCardFallback(unittest.TestCase):
    """獲得卡牌頁認不出卡牌時確認鍵是灰的，連續幾次就點跳過，不卡在這頁。"""

    def setUp(self):
        patcher = patch.object(utils_sortie, "_move_and_click")
        self.click = patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_after_misses(self):
        texts, _ = get_card_page()
        task = Task(texts, {})
        task.config = {}
        with patch.object(utils_sortie, "recognize_cards", return_value=[]):
            results = [utils_sortie.handle_get_card(task) for _ in range(utils_sortie._GET_CARD_MAX_MISSES)]
        self.assertEqual(results, [False] * (utils_sortie._GET_CARD_MAX_MISSES - 1) + [True])
        self.click.assert_called_once_with(task, 0.749, 0.931)

    def test_other_page_resets_misses(self):
        texts, _ = get_card_page()
        task = Task(texts, {})
        with patch.object(utils_sortie, "recognize_cards", return_value=[]):
            for _ in range(utils_sortie._GET_CARD_MAX_MISSES - 1):
                utils_sortie.handle_get_card(task)
            task.all_texts = []
            self.assertFalse(utils_sortie.handle_get_card(task))
            task.all_texts = texts
            self.assertFalse(utils_sortie.handle_get_card(task))
        self.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

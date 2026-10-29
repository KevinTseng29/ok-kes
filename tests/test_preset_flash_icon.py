import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

import preset_deck  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "flash")
# 目錄存的卡圖是 1280×720 畫面上「名稱、類型、描述、特徵」區域外擴 0.005 的裁切，類型圖標中心在裁切的 (79, 50)
FEATURE_IN_CROP = (79, 50)
CROP_AT = (300, 120)


def card_on_frame(name):
    """把閃光頁的卡圖貼回 1280×720 畫面原本的位置，回傳 (task, card)。"""
    crop = cv2.imread(os.path.join(FIXTURES, name))
    frame = np.zeros((720, 1280, 3), np.uint8)
    x, y = CROP_AT
    frame[y:y + crop.shape[0], x:x + crop.shape[1]] = crop
    fx, fy = x + FEATURE_IN_CROP[0], y + FEATURE_IN_CROP[1]
    task = SimpleNamespace(frame=frame, width=1280, height=720, log_info=lambda *_: None)
    card = {"name": "光之剑路", "feature_box": SimpleNamespace(x=fx - 10, y=fy - 10, width=20, height=20)}
    return task, card


class TestNormalFlashIcon(unittest.TestCase):
    """神閃圖示有很多種，普通靈光一閃固定是準星：認得到準星就是普通，認不到就是神閃。"""

    def test_normal_options(self):
        for name in ("normal_skill.jpg", "normal_glowing.jpg"):  # 後者是閃光動畫整張發白的時候
            task, card = card_on_frame(name)
            self.assertFalse(preset_deck._card_has_big_divine(task, card), name)
            self.assertGreater(card["_normal_flash_score"], 0.6)

    def test_divine_options(self):
        for name in ("divine_attack.jpg", "divine_swirl.jpg"):  # 綠色徽章、藍色漩渦
            task, card = card_on_frame(name)
            self.assertTrue(preset_deck._card_has_big_divine(task, card), name)
            self.assertLess(card["_normal_flash_score"], 0.6)

    def test_unknown_layout_counts_as_normal(self):
        """沒有特徵框（算不出圖示位置）時當普通，照舊流程選。"""
        task, card = card_on_frame("divine_attack.jpg")
        card.pop("feature_box")
        self.assertFalse(preset_deck._card_has_big_divine(task, card))


class TestNameMatchesOcrSlips(unittest.TestCase):
    def test_missing_first_char_with_variant(self):
        """14:07 冥想時「明滅劍 (閃擊)」被讀成「灭剑（(闪击)」，比對不到預設卡組就跳過了閃擊。"""
        self.assertTrue(preset_deck._name_matches("明滅劍", "灭剑（(闪击)"))
        self.assertTrue(preset_deck._name_matches("明滅劍", "月灭剑(循环)"))
        self.assertTrue(preset_deck._name_matches("光之劍路", "之剑路"))

    def test_different_cards_still_differ(self):
        self.assertFalse(preset_deck._name_matches("明滅劍", "剑光"))
        self.assertFalse(preset_deck._name_matches("劍之共鳴", "光之剑路"))
        self.assertFalse(preset_deck._name_matches("循環之刃", "海浪的庇佑"))


if __name__ == "__main__":
    unittest.main()

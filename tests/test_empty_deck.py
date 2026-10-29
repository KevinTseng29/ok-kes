import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

import preset_deck  # noqa: E402
import utils  # noqa: E402
import utils_chaos  # noqa: E402

RECORDS = [{"name": "明滅劍", "effects": [], "divine_text": [], "reject_divine": False},
           {"name": "劍之共鳴", "effects": [], "divine_text": [], "reject_divine": False}]


def empty_deck_task(removed=3, main_removed=None, **config):
    task = SimpleNamespace(preset_deck_enabled=True, width=1280, height=720, logs=[],
                           config={"刷空档": True, **config},
                           node_status={"removed_card_count": removed, "empty_deck_done": False,
                                        "empty_deck_abandon": False,
                                        "main_removed_count": removed if main_removed is None else main_removed})
    task.log_info = lambda message, notify=False: task.logs.append(message)
    task.sleep = lambda *_: None
    return task


class TestEmptyDeckDone(unittest.TestCase):
    """刷空檔（實驗卡厄思）：主練預設卡組以外刪到 0 張、而且主練整段都數到了，才算達成、去逃脫。"""

    def check(self, task, counts):
        with patch.object(preset_deck, "load_preset_records", return_value=RECORDS), \
                patch.object(preset_deck, "read_removal_deck_counts", return_value=counts) as read, \
                patch.object(utils, "_journal"), patch.object(utils, "_move_and_click") as click:
            handled = utils._check_empty_deck_done(task)
        return handled, read, click

    def test_done_after_two_consistent_reads(self):
        """讀錯一次就會提早逃脫（19:00 剛刪 2 張讀成剩 2 張）：要連續兩次都數到刪光才算達成。"""
        task = empty_deck_task()
        done_counts = {"__non_preset__": 0, "__section_complete__": True}
        handled, read, _ = self.check(task, done_counts)
        self.assertTrue(handled)
        self.assertFalse(task.node_status["empty_deck_done"])
        self.assertEqual(read.call_args.kwargs["extra_names"], ["明滅劍", "劍之共鳴"])
        handled, read, _ = self.check(task, done_counts)  # 同一個移除數也要再數一次
        read.assert_called_once()
        self.assertTrue(task.node_status["empty_deck_done"])

    def test_abandon_when_removals_used_up(self):
        """主練自己的移除次數用完（5 張）還有剩：這局刪不到，提早逃脫重來（記失敗，不是達成）。"""
        task = empty_deck_task(removed=7, main_removed=5)
        self.check(task, {"__non_preset__": 2, "__section_complete__": True})
        self.assertTrue(task.node_status["empty_deck_abandon"])
        self.assertFalse(task.node_status["empty_deck_done"])
        handled, _, click = self.check(task, {})
        self.assertTrue(handled)
        click.assert_called_once_with(task, 0.959, 0.053)

    def test_not_abandon_before_cap_or_unsure(self):
        # 全局刪了 7 張但主練只被刪 4 張（上限是每位戰鬥員各 5 次，19:16 還能刪）；或段首張數讀不到
        for removed, main_removed, counts in ((7, 4, {"__non_preset__": 2, "__section_complete__": True}),
                                              (5, 5, {"__non_preset__": 2, "__section_complete__": False})):
            task = empty_deck_task(removed=removed, main_removed=main_removed)
            self.check(task, counts)
            self.assertFalse(task.node_status.get("empty_deck_abandon"), (removed, main_removed, counts))

    def test_read_failure_retries_on_next_route_page(self):
        """主練次數滿了就不會再有下次移除：讀失敗要在下個路線頁再數（最多 2 次），刪不完才逃得掉。"""
        task = empty_deck_task(removed=6, main_removed=5)
        self.check(task, None)
        _, read, _ = self.check(task, {"__non_preset__": 1, "__section_complete__": True})
        read.assert_called_once()
        self.assertTrue(task.node_status["empty_deck_abandon"])

    def test_layer_change_keeps_empty_deck_state(self):
        """刷空檔是整局的狀態：換層不能歸零（20:39 主練移除次數從 3 變 0，刪不完判斷不出來）。"""
        task = empty_deck_task(removed=5, main_removed=3)
        task.node_status.update(empty_deck_abandon=True, pass_final_boss_count=1)
        utils.reset_layer_status(task)
        self.assertEqual(task.node_status["main_removed_count"], 3)
        self.assertTrue(task.node_status["empty_deck_abandon"])

    def test_main_removals_counted_on_confirm(self):
        task = empty_deck_task(removed=2, main_removed=2)
        task._pending_main_removals = 1
        utils._record_removed_cards(task, 1)
        self.assertEqual(task.node_status["main_removed_count"], 3)
        utils._record_removed_cards(task, 1)  # 不是從主練那一排點的
        self.assertEqual(task.node_status["main_removed_count"], 3)
        self.assertEqual(task.node_status["removed_card_count"], 4)

    def test_second_read_disagrees(self):
        task = empty_deck_task()
        self.check(task, {"__non_preset__": 0, "__section_complete__": True})
        self.check(task, {"__non_preset__": 2, "__section_complete__": True})
        self.assertFalse(task.node_status["empty_deck_done"])
        _, read, _ = self.check(task, {})
        read.assert_not_called()  # 不一致就等下一次移除再數

    def test_not_done_with_cards_left_or_section_cut(self):
        for counts in ({"__non_preset__": 2, "__section_complete__": True},
                       {"__non_preset__": 0, "__section_complete__": False}):
            task = empty_deck_task()
            self.check(task, counts)
            self.assertFalse(task.node_status["empty_deck_done"], counts)

    def test_counts_once_per_removal(self):
        task = empty_deck_task()
        self.check(task, {"__non_preset__": 2, "__section_complete__": True})
        handled, read, _ = self.check(task, {"__non_preset__": 2, "__section_complete__": True})
        self.assertFalse(handled)
        read.assert_not_called()

    def test_no_removal_yet_or_not_experimental(self):
        handled, read, _ = self.check(empty_deck_task(removed=0), {})
        self.assertFalse(handled)
        task = empty_deck_task()
        task.preset_deck_enabled = False
        handled, read, _ = self.check(task, {})
        self.assertFalse(handled)
        read.assert_not_called()

    def test_done_opens_menu_to_escape(self):
        task = empty_deck_task()
        task.node_status["empty_deck_done"] = True
        handled, _, click = self.check(task, {})
        self.assertTrue(handled)
        click.assert_called_once_with(task, 0.959, 0.053)


class TestDeckSection(unittest.TestCase):
    """所有牌堆頁：主練不一定排第一段，要找主練名字那一段；段首牌堆圖示下的數字就是張數。
    座標取自 2026-10-29 實際截圖：段首圖示 y≈0.139、張數「06」在 (0.116, 0.183)、名字在 y≈0.464、下一段圖示 y≈0.972。"""

    def box(self, name, cx, cy):
        return SimpleNamespace(name=name, x=cx * 1280 - 10, y=cy * 720 - 8, width=20, height=16)

    def card(self, y):
        return {"name": "剑击", "feature_box": SimpleNamespace(x=600, y=y * 720, width=20, height=20)}

    def test_header_count(self):
        task = SimpleNamespace(width=1280, height=720,
                               all_texts=[self.box("所有牌堆", 0.17, 0.05), self.box("17", 0.65, 0.05),
                                          self.box("06", 0.116, 0.183)])
        self.assertEqual(preset_deck._deck_section_header_count(task, 0.139), 6)
        self.assertIsNone(preset_deck._deck_section_header_count(task, 0.60))

    def test_header_count_from_crop_when_full_ocr_misses(self):
        """整張 OCR 漏掉奧爾萊亞段首的「02」：放大那一小塊單獨讀（18:56 讀不到被當成 0 張、提早逃脫）。"""
        if importlib.util.find_spec("onnxocr") is None:
            self.skipTest("需要 onnxocr")
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[180:520, 0:400] = cv2.imread(os.path.join(ROOT, "tests", "fixtures", "team", "deck_section_header.png"))
        task = SimpleNamespace(width=1280, height=720, frame=frame, all_texts=[], log_info=lambda *_: None)
        self.assertEqual(preset_deck._deck_section_header_count(task, 0.328), 2)

    def test_section_excludes_previous_and_next_member(self):
        task = SimpleNamespace(width=1280, height=720)
        cards = [self.card(0.05), self.card(0.15), self.card(0.55), self.card(0.98)]
        filtered, reached_next, top = preset_deck._filter_deck_section(task, cards, [0.02, 0.139, 0.972], 0.464)
        self.assertEqual([c["feature_box"].y / 720 for c in filtered], [0.15, 0.55])
        self.assertTrue(reached_next)
        self.assertAlmostEqual(top, 0.139)


class TestEmptyDeckSkipsFlash(unittest.TestCase):
    def test_skip_flash_page_when_possible(self):
        """刷空檔用不到閃光，戰鬥後的靈光一閃還會拿到新卡（主練越刪越多）：能跳過就跳過。"""
        task = empty_deck_task()
        task.all_texts = [SimpleNamespace(name="跳过", x=0.94 * 1280 - 20, y=0.93 * 720 - 10, width=40, height=20)]
        task.click_box = lambda box: task.logs.append("click_skip")
        with patch.object(utils, "recognize_cards") as recognize, patch.object(utils, "_journal"):
            self.assertTrue(utils.handle_view_original(task, page_confirmed=True))
        recognize.assert_not_called()
        self.assertIn("click_skip", task.logs)


class TestMainAvatarFromDeck(unittest.TestCase):
    """選卡頁改用所有牌堆頁靠名字找到的主練主戰員卡來認主練：同一張圖實測 0.998、別人 0.22。
    （舊的刷存檔主戰員頭像比對把長得像的羅斯薇瑟認成麗塔，3 局 15 次移除全刪到羅斯薇瑟。）"""

    def frame_with(self, name, top, left=0):
        image = cv2.imread(os.path.join(ROOT, "tests", "fixtures", "team", name))
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[top:top + image.shape[0], left:left + image.shape[1]] = image
        return frame

    def test_deck_avatar_finds_main_not_lookalike(self):
        import tempfile
        folder = tempfile.mkdtemp()
        task = empty_deck_task(**{"刷存档主战员": "奥尔莱亚"})
        with patch.object(preset_deck, "_MAIN_AVATAR_FILE", os.path.join(folder, "a.png")), \
                patch.object(preset_deck, "_MAIN_AVATAR_NAME_FILE", os.path.join(folder, "a.txt")):
            # 牌堆頁：奧爾萊亞的名字中心在 y≈0.65（素材貼在 180 列）
            task.frame = self.frame_with("deck_section_header.png", 180)
            preset_deck._save_main_avatar(task, 468 / 720)
            avatar = preset_deck.load_main_avatar(task)
            self.assertIsNotNone(avatar)
            # 選卡頁：她的主戰員卡上緣在 y≈0.232，換算成舊特徵中心約 0.339
            task.frame = self.frame_with("select_main_column.png", 100)
            found_y, score = utils._find_main_avatar_y(task, avatar)
            self.assertGreater(score, 0.95)
            self.assertAlmostEqual(found_y, 0.339, delta=0.02)
            # 長得不一樣的別人（羅斯薇瑟）認不到
            task.frame = self.frame_with("deck_other_member.png", 60, left=-0)
            found_y, score = utils._find_main_avatar_y(task, avatar)
            self.assertIsNone(found_y)
            # 換了刷存檔主戰員就不用舊的頭像
            task.config["刷存档主战员"] = "丽塔"
            self.assertIsNone(preset_deck.load_main_avatar(task))


class TestTopRightToggle(unittest.TestCase):
    """配置隊伍頁右上角開關：刷空檔要關著。"""

    def frame_task(self, name):
        strip = cv2.imread(os.path.join(ROOT, "tests", "fixtures", "team", name))
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[0:80, 1080:1280] = strip
        return SimpleNamespace(frame=frame, width=1280, height=720)

    def test_on_and_off(self):
        self.assertTrue(utils_chaos._top_right_toggle_on(self.frame_task("toggle_on.png"))[0])
        self.assertFalse(utils_chaos._top_right_toggle_on(self.frame_task("toggle_off.png"))[0])


class TestInitialPageAffix(unittest.TestCase):
    """刷空檔：初始頁只看地圖詞條，有「在安全區域無法休息」就再次觀測；不看存檔保存上限。"""

    def run_page(self, value_text):
        task = empty_deck_task()
        observe = SimpleNamespace(name="再次观测", x=0.8 * 1280, y=0.8 * 720, width=10, height=10)
        task.all_texts = [observe]
        task.click_box = lambda box: task.logs.append("click_observe")

        def region_text(_task, region):
            return "卡厄思" if region[0] < 0.1 else value_text

        with patch.object(utils_chaos, "_get_region_text", side_effect=region_text), \
                patch.object(utils_chaos, "stop_if_round_finished", return_value=False):
            return utils_chaos.handle_season_chaos_initial_page(task), task.logs

    def test_bad_affix_rerolls(self):
        handled, logs = self.run_page("存档资料储存上限150pt【不安1】在安全区域无法 休息")
        self.assertTrue(handled)
        self.assertIn("click_observe", logs)

    def test_low_storage_ignored(self):
        handled, logs = self.run_page("存档资料储存上限120pt【疾病3】最大HP减少40%")
        self.assertFalse(handled)
        self.assertNotIn("click_observe", logs)


if __name__ == "__main__":
    unittest.main()

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
                        keys=keys, config={}, all_texts=[])
    t.log_info = lambda message, notify=False: t.logs.append(message)
    t.sleep = lambda seconds: None
    t.send_key = keys.append
    t.box_of_screen = lambda *region: region
    t.find_feature = lambda feature_name, box=None, **kwargs: ["finishturn"] if feature_name == "finishturn" else []
    return t


def run_battle(t, frames, hands, hand_count=None):
    """跑幾幀戰鬥頁；hands 是每一幀的手牌（list of dict），最後一個重複使用。"""
    hands = list(hands)
    for i in range(frames):
        hand = hands[min(i, len(hands) - 1)]
        count = len(hand) if hand_count is None else hand_count
        with patch.object(utils_sortie, "_read_hand_count", return_value=count),                 patch.object(utils_sortie, "mark_battle"),                 patch.object(utils_sortie, "_hand_card_names", return_value=[SimpleNamespace(name=c["name"]) for c in hand]),                 patch.object(utils_sortie, "_hand_cards", return_value=hand):
            utils_sortie.handle_battle_page(t)
    return t.keys


class TestWaitForStableHand(unittest.TestCase):
    """手牌（數量、名稱）要連續兩幀一樣才動作：抽牌、出牌動畫還在播時不塞按鍵（兩次卡死前都是連按）。"""

    def test_first_frame_only_observes(self):
        t = battle_task()
        t.config = {"出牌优先级": ["节奏"]}
        hand = [{"name": "节奏", "key": "1"}]
        self.assertEqual(run_battle(t, 1, [hand]), [])
        self.assertEqual(run_battle(t, 1, [hand]), ["1", "enter"])


class TestUnreadableHand(unittest.TestCase):
    """手牌數不是 0 卻一張都認不出：等 → Enter（卡牌停在選目標狀態）→ 一幀按一張 → 都試過才按 E。"""

    def test_unreadable_tries_slowly_then_ends(self):
        """連變暗的牌都認不到：Enter 一次，AP 不是 0 就一幀按一張，都試過才結束回合（不能直接把能出的牌丟掉）。"""
        t = battle_task()
        self.assertEqual(run_battle(t, 6, [[]], hand_count=2), ["enter", "2", "enter", "1", "enter", "e"])

    def test_unreadable_with_zero_ap_ends(self):
        t = battle_task()
        with patch.object(utils_sortie, "_read_ap", return_value=0):
            self.assertEqual(run_battle(t, 4, [[]], hand_count=2), ["enter", "e"])

    def test_dim_cards_skipped(self):
        """變暗沉下去的牌（打不起）不出；亮著的照優先級出；全部變暗就結束回合。"""
        t = battle_task()
        t.config = {"出牌优先级": ["聚光灯", "小丑"]}
        hand = [{"name": "聚光灯", "key": "1", "dim": True}, {"name": "小丑", "key": "2", "dim": False}]
        self.assertEqual(run_battle(t, 2, [hand]), ["2", "enter"])
        t = battle_task()
        t.config = {"出牌优先级": ["聚光灯"]}
        self.assertEqual(run_battle(t, 2, [[dict(hand[0])]]), ["e"])

    def test_empty_hand_just_ends_turn(self):
        t = battle_task()
        self.assertEqual(run_battle(t, 4, [[]], hand_count=0), ["e", "e", "e"])


class TestUnplayablePriorityCard(unittest.TestCase):
    """優先級卡牌按了還留在手牌（費用不夠）：第二次還沒出掉就改兜底，一次只按一張。"""

    def test_falls_back_after_one_retry(self):
        t = battle_task()
        t.config = {"出牌优先级": ["节奏"]}
        hand = [{"name": "节奏", "key": "1"}, {"name": "守护", "key": "2"}]
        keys = run_battle(t, 3, [hand])
        self.assertEqual(keys, ["1", "enter", "2", "enter"])  # 先照優先級，還在手上就兜底按一張


class TestDuplicateCards(unittest.TestCase):
    """兩張聚光燈：打出一張後手上還有一張同名的，不能當成沒出掉而改去兜底打別人的牌。"""

    def test_second_copy_played_by_priority(self):
        t = battle_task()
        t.config = {"出牌优先级": ["聚光灯"]}
        two = [{"name": "聚光灯", "key": "1"}, {"name": "聚光灯", "key": "2"}, {"name": "守护", "key": "3"}]
        one = [{"name": "聚光灯", "key": "1"}, {"name": "守护", "key": "2"}]
        keys = run_battle(t, 4, [two, two, one, one])
        self.assertEqual(keys, ["1", "enter", "1", "enter"])


class TestArpeggioOrder(unittest.TestCase):
    """好幾張琶音同時在手上：照編號 0→5 先出小的（後面的費用才會降到 0）。"""

    def test_lowest_number_first(self):
        t = battle_task()
        t.config = {"出牌优先级": ["琶音", "节奏"]}
        hand = [{"name": "节奏：琶音（3)", "key": "1"}, {"name": "琶音（0)", "key": "2"},
                {"name": "节奏：琶音(2)", "key": "3"}, {"name": "节奏", "key": "4"}]
        self.assertEqual(run_battle(t, 2, [hand]), ["2", "enter"])


class TestApAware(unittest.TestCase):
    """讀 AP 和卡名左邊的費用：只出打得起的；費用都認得到又都打不起就直接結束回合（把費用花光）。"""

    def boxes(self, ap, costs):
        def text(name, x, y, w, h):
            return SimpleNamespace(name=name, x=x, y=y, width=w, height=h, area=lambda: w * h)
        texts = [text(str(ap), 0.499 * 1280 - 10, 0.928 * 720 - 15, 20, 30)]
        for i, cost in enumerate(costs):
            texts.append(text(str(cost), (0.30 + 0.15 * i) * 1280 - 25, 0.75 * 720, 10, 20))
        return texts

    def hand(self, names):
        return [{"name": name, "key": str(i + 1), "x": 0.30 + 0.15 * i, "left_x": 0.30 + 0.15 * i}
                for i, name in enumerate(names)]

    def test_card_cost_and_ap(self):
        t = battle_task()
        t.all_texts = self.boxes(1, [2])
        name = SimpleNamespace(name="聚光灯", x=0.30 * 1280, y=0.75 * 720, width=60, height=20, area=lambda: 1200)
        self.assertEqual(utils_sortie._card_cost(t, name), 2)
        self.assertEqual(utils_sortie._read_ap(t), 1)

    def test_skips_unaffordable_priority_and_ends_turn(self):
        t = battle_task()
        t.config = {"出牌优先级": ["聚光灯", "小丑"]}
        hand = [dict(c, cost=cost) for c, cost in zip(self.hand(["聚光灯", "小丑"]), (2, 1))]
        t.all_texts = self.boxes(1, [2, 1])
        self.assertEqual(run_battle(t, 2, [hand]), ["2", "enter"])  # 聚光燈 2 費打不起，出 1 費的小丑
        t.all_texts = self.boxes(0, [2])
        self.assertEqual(run_battle(t, 2, [[hand[0]]])[-1], "e")  # AP 0、剩 2 費：結束回合


class TestHandNamesWithNumbers(unittest.TestCase):
    """卡名裡有編號（節奏：琶音（1））不能被當成按鍵提示濾掉，不然琶音永遠認不到。"""

    def test_arpeggio_name_kept(self):
        self.assertTrue(utils_sortie._is_key_text("1"))
        self.assertTrue(utils_sortie._is_key_text("②"))
        self.assertFalse(utils_sortie._is_key_text("节奏：琶音（1)"))
        self.assertFalse(utils_sortie._is_key_text("琶音（0)"))
        t = battle_task()
        t.all_texts = [SimpleNamespace(name="节奏：琶音（1)", x=0.70 * 1280, y=0.76 * 720, width=90, height=20),
                       SimpleNamespace(name="2", x=0.69 * 1280, y=0.72 * 720, width=10, height=20)]
        self.assertEqual([b.name for b in utils_sortie._hand_card_names(t)], ["节奏：琶音（1)"])


class TestChainedArpeggio(unittest.TestCase):
    """打出琶音2 連帶自動打出手上的琶音3、4：手上的琶音消失、手牌數也變少，就記成這回合打過。"""

    def test_auto_played_recorded(self):
        t = battle_task()
        t.config = {"出牌优先级": ["琶音", "小丑"]}
        before = [{"name": f"节奏：琶音（{n}）", "key": str(i + 1)} for i, n in enumerate((2, 3, 4))]
        after = [{"name": "小丑", "key": "1"}]
        run_battle(t, 2, [before])
        run_battle(t, 2, [after], hand_count=0)  # 三張琶音都離手（手牌數 3 → 0）
        self.assertEqual(t._arpeggio_played, {2, 3, 4})


class TestArpeggioSearchFirst(unittest.TestCase):
    """手上只有琶音5、0～4 都還沒打：先打聚光燈把前面的琶音檢索上來，不先打琶音5。"""

    def test_search_before_late_arpeggio(self):
        t = battle_task()
        t.config = {"出牌优先级": ["琶音", "聚光灯"]}
        hand = [{"name": "节奏：琶音（5）", "key": "1"}, {"name": "聚光灯", "key": "2"}]
        self.assertEqual(run_battle(t, 2, [hand]), ["2", "enter"])

    def test_play_arpeggio_in_order(self):
        t = battle_task()
        t.config = {"出牌优先级": ["琶音", "聚光灯"]}
        hand = [{"name": "琶音（0）", "key": "1"}, {"name": "聚光灯", "key": "2"}]
        self.assertEqual(run_battle(t, 2, [hand]), ["1", "enter"])


class TestApGlyph(unittest.TestCase):
    """AP 的「1」太細 OCR 常認不出：用白色字形的寬高比補判（實機截圖 tests/fixtures/ap）。"""

    def test_one_vs_three(self):
        import cv2
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ap")
        self.assertTrue(utils_sortie._ap_glyph_is_one(cv2.imread(os.path.join(folder, "ap_1.png"))))
        self.assertFalse(utils_sortie._ap_glyph_is_one(cv2.imread(os.path.join(folder, "ap_3.png"))))


class TestEndTurnWhenNothingPlayable(unittest.TestCase):
    """兜底每張都按過、手牌卻沒變（AP 不夠）：自己按 E；手牌變了就照常繼續出牌。"""

    def test_unplayable_hand_ends_turn(self):
        t = battle_task()
        hand = [{"name": "守护", "key": "1"}, {"name": "防御", "key": "2"}]
        keys = run_battle(t, 4, [hand], hand_count=2)
        self.assertEqual(keys, ["2", "enter", "1", "enter", "e"])

    def test_hand_changed_keeps_playing(self):
        t = battle_task()
        first = [{"name": "守护", "key": "1"}, {"name": "防御", "key": "2"}]
        second = [{"name": "守护", "key": "1"}]
        keys = run_battle(t, 4, [first, first, second, second])
        self.assertEqual(keys, ["2", "enter", "1", "enter"])  # 打出一張後從頭數，沒有按 E


if __name__ == "__main__":
    unittest.main()


class TestHandKeysFromLayout(unittest.TestCase):
    """手牌按鍵照排法推：最左邊那張打不起、沉下去認不到卡名時，認得到的第一張不能當成 1。
    座標取自 2026-10-30 09:17、09:23 的 OCR（09:23 一直按 1＝打不起的暗黑凝聚，卡了一分鐘）。"""

    def hand(self, texts, count):
        t = battle_task()
        t.all_texts = [SimpleNamespace(name=name, x=left * 1280, y=cy * 720 - 10,
                                       width=(cx - left) * 2 * 1280, height=20) for name, left, cx, cy in texts]
        with patch.object(utils_sortie, "_read_hand_count", return_value=count):
            return [(c["name"], c["key"]) for c in utils_sortie._hand_cards(t)]

    def test_dim_leftmost_card_unreadable(self):
        texts = [("节奏：琶音(0)", 0.3969, 0.4352, 0.7486), ("节奏", 0.5383, 0.5539, 0.7479),
                 ("琶音（2）", 0.5758, 0.5930, 0.7507), ("基本攻击", 0.4100, 0.4324, 0.7701)]
        self.assertEqual(self.hand(texts, 4), [("节奏：琶音(0)", "2"), ("节奏琶音（2）", "3")])

    def test_five_cards_split_name(self):
        """5 張以上不照排法（間距會擠），但「节奏」「琶音（0）」接回一張後間距正常，按鍵照樣 1～5
        （09:27 舊算法多算一張、把琶音(0) 推成 6）。"""
        texts = [("物质再生", 0.2422, 0.2656, 0.7792), ("暗黑凝聚", 0.3586, 0.3805, 0.7625),
                 ("节奏", 0.4703, 0.4844, 0.7549), ("琶音（0）", 0.5008, 0.5199, 0.7542),
                 ("节奏：琶音（1）", 0.5820, 0.6188, 0.7611), ("奏：琶音（5)", 0.7078, 0.7391, 0.8750)]
        self.assertEqual([key for _, key in self.hand(texts, 5)], ["1", "2", "3", "4", "5"])

    def test_two_cards(self):
        texts = [("物质再生", 0.3992, 0.4215, 0.8458), ("暗黑凝聚", 0.5430, 0.5652, 0.8451)]
        self.assertEqual(self.hand(texts, 2), [("物质再生", "1"), ("暗黑凝聚", "2")])

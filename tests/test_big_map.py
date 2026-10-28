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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ok_tasks"))

import big_map  # noqa: E402
import utils  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "big_map")
PRIORITY = ["休息", "事件", "小怪", "精英"]


def frames():
    return [cv2.imread(os.path.join(FIXTURES, name)) for name in ("open_1.jpg", "open_2.jpg")]


def by_column(map_info):
    columns = {}
    for node in map_info["nodes"]:
        tag = node["type"] + "".join("+" + item["feature_name"] for item in node["special_features"])
        columns.setdefault(node["column"], {})[node["slot"]] = tag
    return columns


class TestParseBigMap(unittest.TestCase):
    """出擊大地圖（error 之外實際截的兩張：打開後一張、往左滑 800 像素後一張）。"""

    @classmethod
    def setUpClass(cls):
        cls.frames = frames()
        cls.map = big_map.parse_big_map(cls.frames)

    def test_open_and_offset(self):
        self.assertTrue(big_map.is_open(self.frames[0]))
        self.assertAlmostEqual(big_map.frame_offset(self.frames[0], self.frames[1]), 799, delta=3)

    def test_nodes_and_badges(self):
        columns = by_column(self.map)
        self.assertEqual(columns[0], {1: "当前位置"})
        self.assertEqual(columns[1], {0: "小怪", 1: "小怪", 4: "小怪"})  # 可選那一列罩著光帶也要認得
        self.assertEqual(columns[2], {0: "事件", 1: "事件", 2: "休息+shop_in_map", 4: "小怪"})
        self.assertEqual(columns[3][1], "精英+hard_in_map")
        self.assertEqual(columns[5], {0: "结算", 1: "结算", 2: "结算", 4: "结算"})
        self.assertEqual(columns[7], {0: "精英", 1: "小怪", 2: "小怪", 3: "休息", 4: "事件"})  # 第二張才看得到
        self.assertEqual(columns[10], {0: "休息+shop_in_map", 2: "休息+shop_in_map", 3: "休息+shop_in_map",
                                       4: "休息+shop_in_map"})
        self.assertEqual(max(columns), 10)  # 第 11 列是 boss，不當成一般節點

    def test_connections(self):
        nodes = {node["id"]: node for node in self.map["nodes"]}
        edges = {(nodes[c["from"]]["column"], nodes[c["from"]]["slot"], nodes[c["to"]]["slot"])
                 for c in self.map["connections"]}
        for edge in [(0, 1, 0), (0, 1, 1), (0, 1, 4), (1, 0, 1), (2, 4, 2), (3, 0, 1), (6, 4, 3), (9, 2, 0)]:
            self.assertIn(edge, edges)
        for edge in [(0, 1, 2), (1, 4, 2), (3, 0, 0)]:
            self.assertNotIn(edge, edges)


class TestBigMapRoutePlan(unittest.TestCase):
    """每層掃一次大地圖、照整層規劃走；畫面上的選項數對不上就下次重掃。"""

    def setUp(self):
        self.map = big_map.parse_big_map(frames())
        self.task = SimpleNamespace(node_status={"pass_final_boss_count": 0}, logs=[])
        self.task.log_info = lambda message, notify=False: self.task.logs.append(message)

    def plan(self, visible_count):
        with patch.object(utils, "scan_big_map", return_value=self.map) as scan:
            result = utils._big_map_route_plan(self.task, PRIORITY, visible_count)
        return result, scan

    def test_plans_from_current_and_tracks_moves(self):
        plan, scan = self.plan(3)
        scan.assert_called_once()
        self.assertEqual(plan["source"], "大地图")
        self.assertIn(plan["next_row"], (1, 2, 3))
        self.assertEqual(len(plan["route"]), 11)  # 目前位置 + 10 列
        utils._big_map_moved(self.task, plan["next_row"] - 1)
        moved_to = self.task._big_map["current"]
        self.assertEqual(self.map["nodes"][moved_to]["column"], 1)
        # 同一層下一次不再掃描，從新位置往後規劃
        successors = len(self.map["adjacency"][moved_to])
        plan, scan = self.plan(successors)
        scan.assert_not_called()
        self.assertTrue(plan["route"][0].startswith("1列"))  # 從剛走到的第 1 列節點出發

    def plan_on_floor(self, floor, priority):
        self.task.node_status["pass_final_boss_count"] = floor
        self.task._big_map = None
        with patch.object(utils, "scan_big_map", return_value=self.map):
            plan = utils._big_map_route_plan(self.task, priority, 3)
        return [step.split("列", 1)[1] for step in plan["route"][1:]]

    def test_top_priority_type_is_favoured(self):
        """第二層起照設定：精英排第一（泰妮多走精英），權重加倍後整層路線走兩個精英；照原本線性權重只走一個。"""
        route = self.plan_on_floor(1, ["精英", "休息", "事件", "小怪"])
        self.assertEqual(route.count("精英"), 2)
        linear = utils.find_best_map_route_by_priority(self.map, ["精英", "休息", "事件", "小怪"])
        self.assertEqual(linear["type_counts"]["精英"], 1)

    def test_first_floor_prefers_rest(self):
        """第一層篝火優先：同樣設定精英第一，第一層的整層路線休息比精英多。"""
        route = self.plan_on_floor(0, ["精英", "休息", "事件", "小怪"])
        self.assertGreater(route.count("休息"), route.count("精英"))

    def test_mismatch_rescans_next_time(self):
        self.assertIsNone(self.plan(2)[0])  # 記錄 3 個、畫面 2 個
        self.assertTrue(self.task._big_map["stale"])
        _, scan = self.plan(3)
        scan.assert_called_once()

    def test_new_floor_rescans(self):
        self.plan(3)
        self.task.node_status["pass_final_boss_count"] = 1
        _, scan = self.plan(3)
        scan.assert_called_once()

    def test_scan_failure_falls_back(self):
        with patch.object(utils, "scan_big_map", return_value=None):
            self.assertIsNone(utils._big_map_route_plan(self.task, PRIORITY, 3))
        self.assertIsNone(self.task._big_map)


if __name__ == "__main__":
    unittest.main()

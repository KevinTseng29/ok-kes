import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import utils  # noqa: E402


class TestRunHistory(unittest.TestCase):
    """每局歷程寫進 logs/run_history.jsonl：同一局共用 run、記層數與節點；重複的同一筆 5 秒內只記一次；換局另起 run。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "logs", "run_history.jsonl")

    def rows(self):
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_entries_grouped_by_run(self):
        task = SimpleNamespace(node_status={"pass_final_boss_count": 0, "node_count": 3}, logs=[])
        task.log_info = task.logs.append
        with patch.object(utils, "RUN_HISTORY_FILE", self.path):
            utils._journal(task, "灵光卡牌", "音乐开始")
            utils._journal(task, "灵光卡牌", "音乐开始")  # 頁面又處理一次
            task.node_status["pass_final_boss_count"] = 1
            utils._note_fate(task, "轻盈身法 ")
            task._run_id = None  # reset_mission_status：下一局
            utils._journal(task, "首领", "金狮子")
        rows = self.rows()
        self.assertEqual([(r["kind"], r["detail"], r["floor"]) for r in rows],
                         [("灵光卡牌", "音乐开始", 1), ("命运", "轻盈身法", 2), ("首领", "金狮子", 2)])
        self.assertEqual(rows[0]["run"], rows[1]["run"])
        self.assertEqual(rows[0]["node"], 3)
        self.assertEqual(rows[0]["mode"], "SimpleNamespace")

    def test_failure_does_not_raise(self):
        task = SimpleNamespace(node_status=None, logs=[])
        task.log_info = task.logs.append
        with patch.object(utils, "RUN_HISTORY_FILE", os.path.join(self.tmp, "nul\0bad", "x.jsonl")):
            utils._journal(task, "结果", "成功")
        self.assertTrue(task.logs and "记录历程失败" in task.logs[0])


if __name__ == "__main__":
    unittest.main()

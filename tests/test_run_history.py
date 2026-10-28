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


class TestRunProgress(unittest.TestCase):
    """本局進度存檔：ok-kes／遊戲重啟後接回同一局（層數、刷到琶音沒有、命運）；別的模式、太舊、局結束都不還原。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = patch.object(utils, "RUN_PROGRESS_FILE", os.path.join(self.tmp, "logs", "run_progress.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def task(self, **status):
        t = SimpleNamespace(node_status=dict(utils._initial_node_status(), **status), logs=[])
        t.log_info = t.logs.append
        return t

    def test_restore_after_restart(self):
        before = self.task(pass_final_boss_count=1, get_specific_flash=True, node_count=4)
        before._run_fates = [{"floor": 1, "name": "轻盈身法"}]
        utils.save_run_progress(before)
        after = self.task()
        self.assertTrue(utils.restore_run_progress(after))
        self.assertEqual((after.node_status["pass_final_boss_count"], after.node_status["get_specific_flash"],
                          after.node_status["node_count"]), (1, True, 4))
        self.assertEqual(after._run_fates[0]["name"], "轻盈身法")

    def test_not_restored_for_other_mode_old_or_finished(self):
        utils.save_run_progress(self.task(pass_final_boss_count=2))
        other = SimpleNamespace(**vars(self.task()))  # 類別名稱同為 SimpleNamespace：用 mode 欄位改掉來模擬別的模式
        with open(utils.RUN_PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        with open(utils.RUN_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(data, mode="ChaosMode"), f)
        self.assertFalse(utils.restore_run_progress(other))
        with open(utils.RUN_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(data, saved_at=data["saved_at"] - utils.RUN_PROGRESS_MAX_AGE - 1), f)
        self.assertFalse(utils.restore_run_progress(self.task()))
        utils.clear_run_progress(self.task())
        self.assertFalse(utils.restore_run_progress(self.task()))


if __name__ == "__main__":
    unittest.main()

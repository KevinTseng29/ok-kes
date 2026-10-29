import importlib.util
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "cv2", "opencc")):
    raise unittest.SkipTest("需要 ok-script、opencv 與 opencc")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ok_tasks"))

import config_io  # noqa: E402


class ChaosMode(SimpleNamespace):
    pass


class ChaosModeExperimental(SimpleNamespace):
    pass


class TestExperimentalProfileBucket(unittest.TestCase):
    """實驗模式的保存／切換配置用自己的清單：共用清單交叉載入會留下另一邊上一個角色的卡牌設定。"""

    def setUp(self):
        folder = tempfile.mkdtemp()
        self.path = os.path.join(folder, "local_config_profiles.json")
        patcher = patch.object(config_io, "_local_profiles_file", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs = []

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_bucket_by_task_class(self):
        self.assertEqual(config_io._profile_bucket(ChaosMode(), "chaos"), "chaos")
        self.assertEqual(config_io._profile_bucket(ChaosModeExperimental(), "chaos"), "chaos_experimental")

    def test_moves_profiles_with_preset_deck_once(self):
        self.write({"chaos": {"海德瑪麗": {"闪光卡牌列表": ["a"]}, "羅斯薇瑟": {"预设卡组": [], "游戏语言": "繁体中文"}}})
        task = ChaosModeExperimental(log_info=self.logs.append)
        config_io._migrate_experimental_profiles(task, "chaos")
        data = self.read()
        self.assertEqual(list(data["chaos"]), ["海德瑪麗"])
        self.assertEqual(list(data["chaos_experimental"]), ["羅斯薇瑟"])
        # 之後一般版再存了帶預設卡組的也不會被搬（清單已經分開）
        data["chaos"]["新的"] = {"预设卡组": []}
        self.write(data)
        config_io._migrate_experimental_profiles(task, "chaos")
        self.assertIn("新的", self.read()["chaos"])

    def test_normal_mode_never_migrates(self):
        self.write({"chaos": {"羅斯薇瑟": {"预设卡组": []}}})
        config_io._migrate_experimental_profiles(ChaosMode(log_info=self.logs.append), "chaos")
        self.assertEqual(self.read(), {"chaos": {"羅斯薇瑟": {"预设卡组": []}}})


if __name__ == "__main__":
    unittest.main()

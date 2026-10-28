import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# 沒有安裝框架的環境（GitHub Actions 的單元測試）整個檔案略過
if not all(importlib.util.find_spec(m) for m in ("ok", "PySide6", "qfluentwidgets")):
    raise unittest.SkipTest("需要 ok-script 與 PySide6")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ok.gui.MainWindow import MainWindow  # noqa: E402
from src.ui import run_overview  # noqa: E402


class TestStartJumpsToOverview(unittest.TestCase):
    """在開始頁按開始後跳到運行總覽，沒有總覽時照框架原本的規則。"""

    def test_startup_tab(self):
        run_overview.install()
        window = SimpleNamespace(onetime_tab="一次性任務頁", grouped_task_tabs=[], imported_tabs={}, trigger_tab="觸發頁")
        with patch.object(run_overview.RunOverviewTab, "instance", "運行總覽"):
            self.assertEqual(MainWindow.startup_task_tab(window), "運行總覽")
        with patch.object(run_overview.RunOverviewTab, "instance", None):
            self.assertEqual(MainWindow.startup_task_tab(window), "一次性任務頁")


class TestStartButton(unittest.TestCase):
    """總覽的開始鍵：暫停中就開始，執行中就暫停。"""

    def toggle(self, paused):
        executor = SimpleNamespace(paused=paused, pause=MagicMock())
        app = SimpleNamespace(start_controller=SimpleNamespace(start=MagicMock()))
        with patch.object(run_overview.og, "executor", executor), patch.object(run_overview.og, "app", app):
            run_overview.RunOverviewTab._toggle_start()
        return executor.pause, app.start_controller.start

    def test_paused_starts(self):
        pause, start = self.toggle(paused=True)
        start.assert_called_once_with()
        pause.assert_not_called()

    def test_running_pauses(self):
        pause, start = self.toggle(paused=False)
        pause.assert_called_once_with()
        start.assert_not_called()


class TestStatsGroup(unittest.TestCase):
    """戰績只顯示現在啟動的模式那一組；沒在跑卡厄思／出擊時兩組都列。"""

    def html(self, task):
        stats = {"today": (1, 0), "total": (2, 1), "since": ""}
        with patch.object(run_overview.run_stats, "summary", return_value=stats), \
                patch.object(run_overview, "_tr", lambda text: text):
            return run_overview.RunOverviewTab._stats_html(None, task)

    def test_only_active_mode(self):
        sortie = self.html(type("SortieMode", (), {})())
        self.assertIn("出击", sortie)
        self.assertNotIn("卡厄思", sortie)
        chaos = self.html(type("ChaosModeExperimental", (), {})())
        self.assertIn("卡厄思", chaos)
        self.assertNotIn("出击", chaos)

    def test_both_when_idle_or_story(self):
        for task in (None, type("StoryMode", (), {})()):
            html = self.html(task)
            self.assertIn("卡厄思", html)
            self.assertIn("出击", html)


if __name__ == "__main__":
    unittest.main()

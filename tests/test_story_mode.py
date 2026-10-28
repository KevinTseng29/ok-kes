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

import utils_story  # noqa: E402


def box(name, cx, cy, w=0.06, h=0.04):
    return SimpleNamespace(name=name, x=(cx - w / 2) * 1280, y=(cy - h / 2) * 720, width=w * 1280, height=h * 720,
                           area=lambda: w * h)


def story_map(chapter="第1章"):
    return [box("故事", 0.103, 0.046), box(chapter, 0.493, 0.042), box("孤立", 0.17, 0.44)]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now


class StoryTask(SimpleNamespace):
    def __init__(self, texts):
        super().__init__(width=1280, height=720, all_texts=texts, logs=[], notified=[])

    def log_info(self, message, notify=False):
        self.logs.append(message)
        if notify:
            self.notified.append(message)

    def sleep(self, seconds):
        pass


class StoryCase(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for patcher in (patch.object(utils_story, "time", self.clock),
                        patch.object(utils_story, "_move_and_click")):
            self.mock = patcher.start()
            self.addCleanup(patcher.stop)

    def frames(self, task, count, step=2):
        results = []
        for _ in range(count):
            results.append(utils_story.handle_next_chapter(task))
            self.clock.now += step
        return results


class TestNextChapter(StoryCase):
    """一章打完（地圖上沒有可進入的關卡）就點 ▷ 切到下一章，切不動就提醒一次後停手。"""

    def test_switches_after_idle_frames(self):
        task = StoryTask(story_map())
        self.assertEqual(self.frames(task, 3), [False, False, True])
        self.mock.assert_called_once_with(task, *utils_story._NEXT_CHAPTER)

    def test_stops_when_chapter_does_not_change(self):
        task = StoryTask(story_map())
        self.frames(task, 3)
        self.assertEqual(self.frames(task, 6), [False] * 6)  # 章節名沒變：最後一章或未開放
        self.assertEqual(self.mock.call_count, 1)
        self.assertEqual(len(task.notified), 1)
        task.all_texts = story_map("第2章")  # 使用者手動切了章節，重新判斷
        self.assertEqual(self.frames(task, 3), [False, False, True])

    def test_stops_after_too_many_switches(self):
        task = StoryTask(story_map("第1章"))
        for chapter in ("第1章", "第2章", "第3章", "第4章"):
            task.all_texts = story_map(chapter)
            self.frames(task, 3)
        self.assertEqual(self.mock.call_count, utils_story._CHAPTER_MAX_SWITCHES)
        self.assertEqual(len(task.notified), 1)

    def test_not_story_map_or_gap_resets(self):
        task = StoryTask([box("故事", 0.103, 0.046)])  # 沒有章節名：不是故事地圖
        self.assertEqual(self.frames(task, 5), [False] * 5)
        task.all_texts = story_map()
        self.assertEqual(self.frames(task, 3, step=10), [False] * 3)  # 中間隔太久（在別的頁面）重新數
        self.mock.assert_not_called()

    def test_entry_click_resets_switch_record(self):
        task = StoryTask(story_map())
        task._story_chapter_switches, task._story_switched_from, task._story_chapter_blocked = 2, "第1章", "第1章"
        entry = SimpleNamespace(x=720, confidence=0.9)
        task.box_of_screen = lambda *args: None
        task.find_feature = lambda feature_name, **kwargs: [entry] if feature_name == "enterstory" else []
        task.click_box = lambda chosen: None
        self.assertTrue(utils_story.handle_enter_story_or_battle(task))
        self.assertEqual((task._story_chapter_switches, task._story_switched_from, task._story_chapter_blocked),
                         (0, None, None))


class TestTeamEnter(StoryCase):
    """配置隊伍頁隊伍沒配滿時點進入沒反應：連點幾次就停手提醒，之後隔一段時間才再試。"""

    def setUp(self):
        super().setUp()
        patcher = patch.object(utils_story, "handle_enter", return_value=True)
        self.enter = patcher.start()
        self.addCleanup(patcher.stop)

    def test_pauses_after_tries_and_retries_later(self):
        task = StoryTask([box("配置队伍", 0.122, 0.047)])
        for _ in range(6):
            self.assertTrue(utils_story.handle_team_enter(task))
            self.clock.now += 2
        self.assertEqual(self.enter.call_count, utils_story._TEAM_ENTER_TRIES)
        self.assertEqual(len(task.notified), 1)
        self.clock.now += utils_story._TEAM_ENTER_RETRY_AFTER
        utils_story.handle_team_enter(task)
        self.assertEqual(self.enter.call_count, utils_story._TEAM_ENTER_TRIES + 1)
        self.assertEqual(len(task.notified), 1)  # 再試不重複提醒

    def test_leaving_page_resets(self):
        task = StoryTask([box("配置队伍", 0.122, 0.047)])
        for _ in range(3):
            utils_story.handle_team_enter(task)
        task.all_texts = story_map()
        self.assertFalse(utils_story.handle_team_enter(task))
        task.all_texts = [box("配置队伍", 0.122, 0.047)]
        utils_story.handle_team_enter(task)
        self.assertEqual(self.enter.call_count, 4)

    def test_other_pages_untouched(self):
        task = StoryTask(story_map())
        self.assertFalse(utils_story.handle_team_enter(task))
        self.enter.assert_not_called()


if __name__ == "__main__":
    unittest.main()

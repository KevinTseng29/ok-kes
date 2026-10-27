import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ok_tasks'))

import guard  # noqa: E402
from guard import GuardSettings, guarded_run, save_scene  # noqa: E402


class TaskDisabledException(Exception):
    """與框架的例外同名；guard 以類別名稱辨認，不需要匯入 ok。"""


class FakeFrame:
    def __init__(self, n):
        self.n = n

    def copy(self):
        return FakeFrame(self.n)


class FakeTask:
    """模擬 TriggerTask 會用到的方法，只記錄呼叫。"""

    def __init__(self):
        self.calls = []
        self.frame = FakeFrame(0)
        self.fail_with = None

    def log_error(self, message, exception=None):
        self.calls.append(('error', message, exception))

    def log_info(self, message):
        self.calls.append(('info', message))

    def sleep(self, t):
        self.calls.append(('sleep', t))

    @guarded_run
    def run(self):
        if self.fail_with:
            raise self.fail_with
        return 'ok'

    def kinds(self, kind):
        return [c for c in self.calls if c[0] == kind]


def fake_write_image(path, frame):
    with open(path, 'w') as f:
        f.write(str(frame.n))


def write_file(path, size, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'x' * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved_settings = guard.GUARD
        self.saved_writer = guard._write_image
        guard.GUARD = GuardSettings(
            scene_dir=os.path.join(self.tmp, 'scenes'),
            log_file=os.path.join(self.tmp, 'ok-script.log'),
            screenshot_dir=os.path.join(self.tmp, 'screenshots'),
            scene_min_interval=0,
            retry_delay=(0, 0),
        )
        guard._write_image = fake_write_image
        guard._last_screenshot_check = None
        self.task = FakeTask()

    def tearDown(self):
        guard.GUARD = self.saved_settings
        guard._write_image = self.saved_writer
        guard._last_screenshot_check = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scenes(self):
        root = guard.GUARD.scene_dir
        return sorted(os.listdir(root)) if os.path.isdir(root) else []


class TestGuardedRun(GuardTestCase):
    def test_success_returns_result_and_records_frame(self):
        self.assertEqual(self.task.run(), 'ok')
        self.assertEqual(len(self.task._guard_state.frames), 1)
        self.assertEqual(self.task.kinds('error'), [])

    def test_failures_retried_then_gives_up(self):
        self.task.fail_with = ValueError('bad ocr')
        self.assertIsNone(self.task.run())
        self.assertIsNone(self.task.run())
        self.assertEqual(len(self.task.kinds('sleep')), 2)
        with self.assertRaises(ValueError):
            self.task.run()
        self.assertEqual(len(self.task.kinds('error')), 3)
        # 停止後重新計算：使用者再開任務時，第一次失敗仍會重試
        self.assertIsNone(self.task.run())

    def test_success_resets_consecutive_count(self):
        for fail in (True, True, False, True, True):
            self.task.fail_with = ValueError('x') if fail else None
            self.task.run()
        self.assertEqual(self.task._guard_state.consecutive, 2)

    def test_window_limit_stops_alternating_failures(self):
        guard.GUARD.max_failures_in_window = 4
        for _ in range(3):
            self.task.fail_with = ValueError('x')
            self.task.run()
            self.task.fail_with = None
            self.task.run()
        self.task.fail_with = ValueError('x')
        with self.assertRaises(ValueError):
            self.task.run()

    def test_framework_exceptions_pass_through(self):
        self.task.fail_with = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            self.task.run()
        self.assertEqual(self.task.kinds('error'), [])
        self.assertEqual(self.task.kinds('sleep'), [])

    def test_disabled_is_passthrough(self):
        guard.GUARD.enabled = False
        self.task.fail_with = ValueError('x')
        with self.assertRaises(ValueError):
            self.task.run()
        self.assertEqual(self.task.calls, [])

    def test_frame_buffer_keeps_latest(self):
        guard.GUARD.frame_buffer_size = 3
        for n in range(5):
            self.task.frame = FakeFrame(n)
            self.task.run()
        self.assertEqual([f.n for _, f in self.task._guard_state.frames], [2, 3, 4])

    def test_failure_saves_scene_with_frames_and_traceback(self):
        for n in range(3):
            self.task.frame = FakeFrame(n)
            self.task.run()
        self.task.fail_with = ValueError('bad ocr')
        self.task.run()
        scenes = self.scenes()
        self.assertEqual(len(scenes), 1)
        folder = os.path.join(guard.GUARD.scene_dir, scenes[0])
        self.assertTrue(scenes[0].endswith('_FakeTask_exception'))
        images = sorted(f for f in os.listdir(folder) if f.endswith(('.png', '.jpg')))
        # 前三輪加上出錯那一輪；只有最後一張存 PNG
        self.assertEqual(len(images), 4)
        self.assertEqual([f[-3:] for f in images], ['jpg', 'jpg', 'jpg', 'png'])
        with open(os.path.join(folder, 'info.txt'), encoding='utf-8') as f:
            info = f.read()
        self.assertIn('ValueError: bad ocr', info)


class TestSaveScene(GuardTestCase):
    def test_throttled_per_reason(self):
        guard.GUARD.scene_min_interval = 60
        self.assertIsNotNone(save_scene(self.task, 'stuck'))
        self.assertIsNone(save_scene(self.task, 'stuck'))
        self.assertIsNotNone(save_scene(self.task, 'exception'))

    def test_log_tail_saved(self):
        with open(guard.GUARD.log_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(f'行 {i}' for i in range(500)))
        guard.GUARD.log_tail_lines = 5
        folder = save_scene(self.task, 'stuck')
        with open(os.path.join(folder, 'log.txt'), encoding='utf-8') as f:
            self.assertEqual(f.read().splitlines(), [f'行 {i}' for i in range(495, 500)])

    def test_prune_keeps_latest_and_ignores_other_folders(self):
        root = guard.GUARD.scene_dir
        for name in ('20260101_000000_A_stuck', '20260102_000000_A_stuck', '20260103_000000_A_stuck', 'keep_me'):
            os.makedirs(os.path.join(root, name))
        guard._prune_scenes(root, 2)
        self.assertEqual(self.scenes(), ['20260102_000000_A_stuck', '20260103_000000_A_stuck', 'keep_me'])

    def test_prune_by_total_size_keeps_newest(self):
        root = guard.GUARD.scene_dir
        for name, size in (('20260101_000000_A_stuck', 400), ('20260102_000000_A_stuck', 400),
                           ('20260103_000000_A_stuck', 400), ('20260104_000000_A_stuck', 2000)):
            write_file(os.path.join(root, name, 'a.jpg'), size)
        guard._prune_scenes(root, 30, max_bytes=1000)
        # 最新那份單獨就超過上限，仍然保留；較舊的全部刪掉
        self.assertEqual(self.scenes(), ['20260104_000000_A_stuck'])

        write_file(os.path.join(root, '20260105_000000_A_stuck', 'a.jpg'), 300)
        guard._prune_scenes(root, 30, max_bytes=2500)
        self.assertEqual(self.scenes(), ['20260104_000000_A_stuck', '20260105_000000_A_stuck'])

    def test_write_failure_does_not_raise(self):
        def broken(path, frame):
            raise OSError('disk full')
        guard._write_image = broken
        self.task.run()
        self.assertIsNone(save_scene(self.task, 'stuck'))
        self.assertTrue(any('保存錯誤現場失敗' in c[1] for c in self.task.kinds('info')))


class TestCleanScreenshots(GuardTestCase):
    def make_shots(self):
        root = guard.GUARD.screenshot_dir
        # 檔名順序與時間順序刻意相反，確認是依修改時間刪
        for i, name in enumerate(('c.png', 'b.png', 'a.png')):
            write_file(os.path.join(root, 'log', name), 400, mtime=1_700_000_000 + i)
        return root

    def remaining(self):
        return sorted(os.listdir(os.path.join(guard.GUARD.screenshot_dir, 'log')))

    def test_trims_oldest_files_until_under_limit(self):
        root = self.make_shots()
        removed, freed = guard._trim_folder(root, 900)
        self.assertEqual((removed, freed), (1, 400))
        self.assertEqual(self.remaining(), ['a.png', 'b.png'])
        self.assertEqual(guard._trim_folder(os.path.join(self.tmp, 'missing'), 0), (0, 0))

    def test_checked_periodically_from_run(self):
        self.make_shots()
        guard.GUARD.screenshot_max_mb = 900 / 1024 / 1024
        guard.GUARD.screenshot_check_interval = 3600
        # 第一輪只開始計時（框架啟動時剛清理過），間隔未到也不檢查
        self.task.run()
        self.task.run()
        self.assertEqual(len(self.remaining()), 3)
        guard._last_screenshot_check -= 3600
        self.task.run()
        self.assertEqual(self.remaining(), ['a.png', 'b.png'])
        self.assertTrue(any('刪除最舊的 1 個檔案' in c[1] for c in self.task.kinds('info')))


if __name__ == '__main__':
    unittest.main()

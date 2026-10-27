import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ok_tasks'))

import humanize  # noqa: E402
from humanize import (HUMANIZE, HumanizeMixin, HumanizeSettings, jitter_point,  # noqa: E402
                      point_in_box, scale_duration)


class FakeBox:
    def __init__(self, x, y, width, height, name='box'):
        self.x, self.y, self.width, self.height, self.name = x, y, width, height, name


class FakeBase:
    """模擬 ok-script BaseTask 的輸入方法，只記錄呼叫。"""
    width = 1920
    height = 1080

    def __init__(self):
        self.calls = []

    def sleep(self, t):
        self.calls.append(('sleep', t))

    def get_box_by_name(self, name):
        return None

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1, move=True,
              down_time=0.02, after_sleep=0, key='left', hcenter=False, vcenter=False):
        if 0 < x < 1 or 0 < y < 1:  # 框架行為：相對座標轉像素後再呼叫 self.click
            return self.click(int(self.width * x), int(self.height * y), name=name,
                              down_time=down_time, after_sleep=after_sleep)
        self.calls.append(('click', x, y, down_time, after_sleep))
        return True

    def click_box(self, box=None, relative_x=0.5, relative_y=0.5, raise_if_not_found=False,
                  move_back=False, move=True, down_time=0.01, after_sleep=1):
        self.calls.append(('base_click_box', box))
        return None

    def swipe_relative(self, from_x, from_y, to_x, to_y, duration=0.5, settle_time=0):
        self.calls.append(('swipe', from_x, from_y, to_x, to_y, duration))

    def mouse_down(self, x=-1, y=-1, name=None, key='left'):
        self.calls.append(('down', x, y))

    def send_key(self, key, down_time=0.02, interval=-1, after_sleep=0):
        self.calls.append(('key', key, down_time, after_sleep))


class Task(HumanizeMixin, FakeBase):
    pass


class TestPureFunctions(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(1234)

    def test_point_in_box_stays_inside_and_varies(self):
        pts = {point_in_box(100, 200, 80, 40, rng=self.rng) for _ in range(500)}
        self.assertGreater(len(pts), 50)
        for x, y in pts:
            self.assertTrue(100 <= x <= 179 and 200 <= y <= 239, (x, y))

    def test_point_in_box_centered_distribution(self):
        xs = [point_in_box(0, 0, 200, 200, rng=self.rng)[0] for _ in range(4000)]
        mean = sum(xs) / len(xs)
        self.assertAlmostEqual(mean, 100, delta=3)
        # 近似常態：中間 1/3 的命中率應明顯高於均勻分布的 1/3
        middle = sum(1 for x in xs if 67 <= x <= 133) / len(xs)
        self.assertGreater(middle, 0.5)

    def test_tiny_box_clicks_center(self):
        self.assertEqual(point_in_box(10, 10, 4, 4, rng=self.rng), (12, 12))

    def test_relative_point_outside_box_not_clamped(self):
        x, y = point_in_box(0, 0, 100, 20, relative_x=0.5, relative_y=3.0, rng=self.rng)
        self.assertGreater(y, 20)

    def test_jitter_point_small_and_clamped(self):
        for _ in range(500):
            x, y = jitter_point(960, 540, 1920, 1080, rng=self.rng)
            self.assertLessEqual(abs(x - 960), 6)
            self.assertLessEqual(abs(y - 540), 6)
        for _ in range(200):
            x, y = jitter_point(0, 1079, 1920, 1080, rng=self.rng)
            self.assertTrue(0 <= x and y <= 1079)

    def test_scale_duration(self):
        self.assertEqual(scale_duration(0, (0.85, 1.35)), 0)
        for _ in range(200):
            v = scale_duration(1.0, (0.85, 1.35), rng=self.rng)
            self.assertTrue(0.85 <= v <= 1.35)


class TestMixin(unittest.TestCase):
    def setUp(self):
        humanize._rng.seed(42)
        self.task = Task()

    def tearDown(self):
        HUMANIZE.enabled = True

    def clicks(self):
        return [c for c in self.task.calls if c[0] == 'click']

    def test_click_box_randomizes_within_box_without_extra_jitter(self):
        box = FakeBox(500, 300, 120, 60)
        seen = set()
        for _ in range(200):
            self.task.click_box(box)
        for _, x, y, down, after in self.clicks():
            self.assertTrue(500 <= x <= 619 and 300 <= y <= 359, (x, y))
            self.assertTrue(0.04 <= down <= 0.11)
            self.assertTrue(0.85 <= after <= 1.35)
            seen.add((x, y))
        self.assertGreater(len(seen), 50)
        # 點擊前有反應延遲
        self.assertTrue(any(c[0] == 'sleep' for c in self.task.calls))

    def test_each_click_recorded_once_for_loop_detection(self):
        self.task.click(0.5, 0.5)            # 相對座標：框架轉像素後再進來一次
        self.task.click_box(FakeBox(0, 0, 50, 50))
        self.task.click(960, 540)
        self.task.click(-1, -1)              # 目前位置，不記
        clicks = list(self.task._guard_state.clicks)
        self.assertEqual(len(clicks), 3)
        self.assertEqual(clicks[0], clicks[2])

    def test_click_box_accepts_list_and_missing(self):
        self.task.click_box([FakeBox(0, 0, 50, 50)])
        self.assertEqual(len(self.clicks()), 1)
        self.task.click_box([])
        self.task.click_box(None)
        self.assertEqual([c for c in self.task.calls if c[0] == 'base_click_box'], [('base_click_box', None)] * 2)

    def test_click_absolute_and_relative_jittered_once(self):
        self.task.click(1000, 500)
        self.task.click(0.5, 0.5)
        (_, x1, y1, *_), (_, x2, y2, *_) = self.clicks()
        self.assertLessEqual(abs(x1 - 1000), 6)
        self.assertLessEqual(abs(y1 - 500), 6)
        self.assertLessEqual(abs(x2 - 960), 6)
        self.assertLessEqual(abs(y2 - 540), 6)

    def test_click_current_position_untouched(self):
        self.task.click(-1, -1)
        self.assertEqual(self.clicks()[0][1:3], (-1, -1))

    def test_disabled_is_passthrough(self):
        HUMANIZE.enabled = False
        self.task.click(1000, 500, after_sleep=1)
        self.assertEqual(self.clicks(), [('click', 1000, 500, 0.02, 1)])
        self.task.click_box(FakeBox(0, 0, 50, 50))
        self.assertEqual(self.task.calls[-1][0], 'base_click_box')

    def test_swipe_send_key_mouse_down(self):
        self.task.swipe_relative(0.3, 0.8, 0.6, 0.2, duration=0.5)
        sw = [c for c in self.task.calls if c[0] == 'swipe'][0]
        for got, want in zip(sw[1:5], (0.3, 0.8, 0.6, 0.2)):
            self.assertAlmostEqual(got, want, delta=0.006)
        self.assertTrue(0.42 <= sw[5] <= 0.63)
        self.task.send_key('1', after_sleep=0.5)
        k = [c for c in self.task.calls if c[0] == 'key'][0]
        self.assertTrue(0.04 <= k[2] <= 0.11 and 0.42 <= k[3] <= 0.68)
        self.task.mouse_down(800, 600)
        d = [c for c in self.task.calls if c[0] == 'down'][0]
        self.assertLessEqual(abs(d[1] - 800), 6)


if __name__ == '__main__':
    unittest.main()

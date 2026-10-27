import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ok_tasks'))

import navigation  # noqa: E402
from navigation import (HOME_BUTTON, SEASON_BANNER_POINT, WAKE_POINT, NavigationSettings,  # noqa: E402
                        chaos_entry, handle_chaos_navigation, handle_sortie_navigation, is_lobby)


class FakeBox:
    """OCR 框；以中心的相對座標建立（畫面 1280x720）。"""

    def __init__(self, name, rx, ry, width=80, height=30):
        self.name = name
        self.width, self.height = width, height
        self.x = rx * 1280 - width / 2
        self.y = ry * 720 - height / 2


class FakeTask:
    width, height = 1280, 720

    def __init__(self, texts=()):
        self.all_texts = list(texts)
        self.calls = []

    def click(self, x=-1, y=-1, **kwargs):
        self.calls.append(('click', x, y))

    def click_box(self, box, after_sleep=1, **kwargs):
        self.calls.append(('click_box', box.name))

    def sleep(self, t):
        pass

    def log_info(self, message):
        pass

    def disable(self):
        self.calls.append(('disable',))


class SeasonTask(FakeTask):
    """設定頁的卡厄思入口選了賽季卡厄思。"""

    def get_global_config(self, option):
        return {'导航设置': {'卡厄思入口': '赛季卡厄思'}}[option]


# 依國際服實測的畫面配置（OCR 結果已轉簡體）
LOBBY = [
    FakeBox('黑兔', 0.11, 0.05), FakeBox('36/290', 0.70, 0.05),
    FakeBox('故事', 0.89, 0.16), FakeBox('第1幕——第5章第7话', 0.84, 0.20, width=200),
    FakeBox('出击', 0.90, 0.27), FakeBox('模拟', 0.90, 0.36), FakeBox('卡厄思', 0.90, 0.44),
    FakeBox('方舟都市', 0.88, 0.52), FakeBox('战斗员', 0.90, 0.62), FakeBox('救援', 0.90, 0.71),
]
# 子頁右上角的全域選單：同樣的項目出現在畫面中間
GLOBAL_MENU = [FakeBox('故事', 0.58, 0.09), FakeBox('出击', 0.58, 0.20), FakeBox('卡厄思', 0.58, 0.38),
               FakeBox('日常任务', 0.80, 0.24)]
CHAOS_MENU = [FakeBox('卡厄思', 0.11, 0.045), FakeBox('卡厄思显现', 0.30, 0.80, width=160),
              FakeBox('零号系统', 0.69, 0.80, width=140)]
SEASON_CHAOS_INITIAL = [FakeBox('卡厄思', 0.11, 0.045), FakeBox('再次观测', 0.80, 0.78)]
# 大廳左上活動橫幅與右下賽季橫幅都有倒數
LOBBY_WITH_SEASON = LOBBY + [FakeBox('35天10小时', 0.07, 0.21, width=120),
                             FakeBox('56天10小时', 0.91, 0.83, width=120),
                             FakeBox('雪凝结的约产', 0.88, 0.905, width=160)]
# 賽季首頁（2026-10「雪上凝結的約定」，標題每季不同）
SEASON_HUB = [FakeBox('银河系灾害', 0.13, 0.045, width=140), FakeBox('银河徽章', 0.12, 0.15),
              FakeBox('故事', 0.45, 0.37), FakeBox('第6幕——第0章第1话', 0.40, 0.41, width=200),
              FakeBox('卡厄思', 0.204, 0.526), FakeBox('每周进度', 0.208, 0.565), FakeBox('0/8000', 0.20, 0.60),
              FakeBox('前半期', 0.84, 0.17), FakeBox('14天11小时', 0.81, 0.26, width=120),
              FakeBox('雪上凝结约定', 0.83, 0.73, width=160), FakeBox('赛季资讯', 0.92, 0.86)]
SEASON_CHAOS_PAGE = [FakeBox('卡厄思', 0.115, 0.045), FakeBox('赛季资讯', 0.196, 0.045),
                     FakeBox('天上防护墙', 0.75, 0.215), FakeBox('存档资料储存上限120pt', 0.785, 0.40, width=220),
                     FakeBox('再次观测', 0.762, 0.793), FakeBox('每周进度', 0.461, 0.884),
                     FakeBox('0/8000', 0.63, 0.885), FakeBox('进入', 0.941, 0.898)]
ZERO_SYSTEM_HOME = [FakeBox('零号系统', 0.12, 0.046), FakeBox('法典', 0.81, 0.47),
                    FakeBox('卡厄思物质', 0.14, 0.91), FakeBox('每周进度', 0.73, 0.905)]


def page(title, *extra):
    return [FakeBox(title, 0.12, 0.046), *extra]


class NavigationTestCase(unittest.TestCase):
    def setUp(self):
        navigation.NAV = NavigationSettings()

    def tearDown(self):
        navigation.NAV = NavigationSettings()
        navigation.time = __import__('time')


class TestLobby(NavigationTestCase):
    def test_lobby_detected_but_not_global_menu(self):
        self.assertTrue(is_lobby(FakeTask(LOBBY)))
        self.assertFalse(is_lobby(FakeTask(GLOBAL_MENU)))
        self.assertFalse(is_lobby(FakeTask(page('故事'))))

    def test_lobby_enters_mode(self):
        task = FakeTask(LOBBY)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('click_box', '卡厄思')])
        task = FakeTask(LOBBY)
        self.assertTrue(handle_sortie_navigation(task))
        self.assertEqual(task.calls, [('click_box', '出击')])

    def test_lobby_stops_when_auto_enter_disabled(self):
        navigation.NAV.enter_mode_from_lobby = False
        task = FakeTask(LOBBY)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('disable',)])

    def test_global_menu_is_left_alone(self):
        task = FakeTask(GLOBAL_MENU)
        self.assertFalse(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [])


class TestChaosMenu(NavigationTestCase):
    def test_clicks_configured_entry(self):
        task = FakeTask(CHAOS_MENU)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('click_box', '零号系统')])
        navigation.NAV.chaos_entry = '卡厄思显现'
        task = FakeTask(CHAOS_MENU)
        handle_chaos_navigation(task)
        self.assertEqual(task.calls, [('click_box', '卡厄思显现')])

    def test_cn_server_card_name(self):
        task = FakeTask([FakeBox('卡厄思', 0.11, 0.045), FakeBox('零式系统', 0.69, 0.80)])
        handle_chaos_navigation(task)
        self.assertEqual(task.calls, [('click_box', '零式系统')])

    def test_season_chaos_page_not_mistaken_for_menu(self):
        task = FakeTask(SEASON_CHAOS_INITIAL)
        self.assertFalse(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [])

    def test_sortie_leaves_chaos_menu(self):
        task = FakeTask(CHAOS_MENU)
        self.assertTrue(handle_sortie_navigation(task))
        self.assertEqual(task.calls, [('click', *HOME_BUTTON)])


class TestSeasonChaos(NavigationTestCase):
    def test_entry_setting_and_fallbacks(self):
        self.assertEqual(chaos_entry(FakeTask()), '零号系统')
        self.assertEqual(chaos_entry(SeasonTask()), '赛季卡厄思')

        class Broken(FakeTask):
            def get_global_config(self, option):
                raise KeyError(option)

        class Unknown(FakeTask):
            def get_global_config(self, option):
                return {'卡厄思入口': '不存在的入口'}

        self.assertEqual(chaos_entry(Broken()), '零号系统')
        self.assertEqual(chaos_entry(Unknown()), '零号系统')
        navigation.NAV.chaos_entry = '赛季卡厄思'
        self.assertEqual(chaos_entry(FakeTask()), '赛季卡厄思')

    def test_lobby_clicks_season_banner(self):
        task = SeasonTask(LOBBY_WITH_SEASON)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('click', *SEASON_BANNER_POINT)])

    def test_zero_system_entry_ignores_season_banner(self):
        task = FakeTask(LOBBY_WITH_SEASON)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('click_box', '卡厄思')])

    def test_lobby_without_season_banner_stops_after_misses(self):
        task = SeasonTask(LOBBY + [FakeBox('35天10小时', 0.07, 0.21, width=120)])
        results = [handle_chaos_navigation(task) for _ in range(3)]
        self.assertEqual(results, [False, False, True])
        self.assertEqual(task.calls, [('disable',)])

    def test_banner_found_resets_misses(self):
        task = SeasonTask(LOBBY)
        handle_chaos_navigation(task)
        handle_chaos_navigation(task)
        task.all_texts = LOBBY_WITH_SEASON
        handle_chaos_navigation(task)
        task.all_texts = LOBBY
        self.assertFalse(handle_chaos_navigation(task))
        self.assertNotIn(('disable',), task.calls)

    def test_countdown_formats(self):
        for text, expected in (('56天10小时', True), ('5小时', True), ('23分钟', True), ('1天', True),
                               ('63/290', False), ('第1幕', False), ('天', False)):
            task = SeasonTask(LOBBY + [FakeBox(text, 0.91, 0.83, width=120)])
            self.assertEqual(handle_chaos_navigation(task), expected, text)

    def test_lobby_stops_when_auto_enter_disabled(self):
        navigation.NAV.enter_mode_from_lobby = False
        task = SeasonTask(LOBBY_WITH_SEASON)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('disable',)])

    def test_hub_clicks_chaos_node(self):
        task = SeasonTask(SEASON_HUB)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('click_box', '卡厄思')])
        # 入口選零號系統時不動賽季首頁
        task = FakeTask(SEASON_HUB)
        self.assertFalse(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [])

    def test_chaos_menu_goes_home_for_season(self):
        task = SeasonTask(CHAOS_MENU)
        self.assertTrue(handle_chaos_navigation(task))
        self.assertEqual(task.calls, [('click', *HOME_BUTTON)])

    def test_chaos_pages_left_to_mode_handlers(self):
        for texts in (SEASON_CHAOS_PAGE, SEASON_CHAOS_INITIAL, ZERO_SYSTEM_HOME):
            for task in (SeasonTask(texts), FakeTask(texts)):
                self.assertFalse(handle_chaos_navigation(task))
                self.assertEqual(task.calls, [])

    def test_sortie_ignores_season_setting(self):
        task = SeasonTask(LOBBY_WITH_SEASON)
        self.assertTrue(handle_sortie_navigation(task))
        self.assertEqual(task.calls, [('click_box', '出击')])


class TestForeignPages(NavigationTestCase):
    def test_rescue_and_ark_city_go_home(self):
        for title in ('救援', '营救', '方舟都市', '方舟城市'):
            for handler in (handle_chaos_navigation, handle_sortie_navigation):
                task = FakeTask(page(title))
                self.assertTrue(handler(task), title)
                self.assertEqual(task.calls, [('click', *HOME_BUTTON)])

    def test_own_and_story_pages_untouched(self):
        cases = [
            (handle_chaos_navigation, '零号系统'),
            (handle_chaos_navigation, '卡厄思显现'),
            (handle_sortie_navigation, '出击'),
            (handle_chaos_navigation, '故事'),  # 劇情裡的卡厄思關卡
            (handle_sortie_navigation, '故事'),  # 劇情裡的戰鬥
            (handle_sortie_navigation, '战斗员配置'),
            (handle_sortie_navigation, '战斗员列表'),
        ]
        for handler, title in cases:
            task = FakeTask(page(title))
            self.assertFalse(handler(task), title)
            self.assertEqual(task.calls, [], title)

    def test_cross_mode_pages_go_home(self):
        task = FakeTask(page('出击'))
        self.assertTrue(handle_chaos_navigation(task))
        task = FakeTask(page('零号系统'))
        self.assertTrue(handle_sortie_navigation(task))
        self.assertEqual(task.calls, [('click', *HOME_BUTTON)])

    def test_title_outside_header_ignored(self):
        task = FakeTask([FakeBox('救援', 0.5, 0.5)])
        self.assertFalse(handle_chaos_navigation(task))

    def test_stops_when_leaving_disabled(self):
        navigation.NAV.leave_foreign_pages = False
        task = FakeTask(page('救援'))
        self.assertTrue(handle_sortie_navigation(task))
        self.assertEqual(task.calls, [('disable',)])


class TestWakeBlankScreen(NavigationTestCase):
    def set_clock(self, t):
        navigation.time = types.SimpleNamespace(time=lambda: t)

    def tick(self, task, t):
        self.set_clock(t)
        return handle_chaos_navigation(task)

    def test_wakes_after_blank_period(self):
        task = FakeTask([])
        results = [self.tick(task, t) for t in range(7)]
        self.assertEqual(results, [False] * 6 + [True])
        self.assertEqual(task.calls, [('click', *WAKE_POINT)])
        # 點完重新計時，不會每輪都點
        self.assertFalse(self.tick(task, 8))

    def test_text_resets_timer(self):
        task = FakeTask([])
        for t in range(5):
            self.tick(task, t)
        task.all_texts = [FakeBox('载入中', 0.5, 0.9)]
        self.tick(task, 5)
        task.all_texts = []
        self.assertFalse(any(self.tick(task, t) for t in range(6, 11)))
        self.assertEqual(task.calls, [])

    def test_gap_between_calls_restarts_timer(self):
        task = FakeTask([])
        self.tick(task, 0)
        # 期間其他處理函式接手了好幾輪，回來時重新計時
        self.assertFalse(self.tick(task, 10))
        self.assertFalse(self.tick(task, 11))
        self.assertEqual(task.calls, [])


if __name__ == '__main__':
    unittest.main()

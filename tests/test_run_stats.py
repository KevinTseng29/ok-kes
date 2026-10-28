import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import run_overview_data as data  # noqa: E402
from src import run_stats  # noqa: E402


def at(text):
    return time.mktime(time.strptime(text, '%Y-%m-%d %H:%M'))


class TestRunStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'configs', 'run_stats.json')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_today_and_total_survive_reload(self):
        run_stats.record(True, 'ChaosModeExperimental', self.path, now=at('2026-10-27 23:50'))
        run_stats.record(False, 'ChaosModeExperimental', self.path, now=at('2026-10-28 01:26'))
        run_stats.record(True, 'ChaosModeExperimental', self.path, now=at('2026-10-28 03:01'))
        run_stats._cache.update(path=None, mtime=None, data=None)  # 模擬重啟後重新讀檔
        stats = run_stats.summary(self.path, now=at('2026-10-28 06:00'))
        self.assertEqual(stats['today'], (1, 1))
        self.assertEqual(stats['total'], (2, 1))
        self.assertEqual(stats['since'], '2026-10-27 23:50')
        self.assertTrue(stats['last']['success'])

    def test_modes_counted_separately(self):
        run_stats.record(True, 'ChaosModeExperimental', self.path, now=at('2026-10-28 09:00'))
        run_stats.record(False, 'ChaosMode', self.path, now=at('2026-10-28 10:00'))
        run_stats.record(True, 'SortieMode', self.path, now=at('2026-10-28 18:36'))
        run_stats.record(True, 'SortieMode', self.path, now=at('2026-10-28 18:45'))
        now = at('2026-10-28 19:00')
        chaos = run_stats.summary(self.path, now=now, modes=('ChaosModeExperimental', 'ChaosMode'))
        sortie = run_stats.summary(self.path, now=now, modes=('SortieMode',))
        self.assertEqual((chaos['today'], chaos['total']), ((1, 1), (1, 1)))
        self.assertEqual((sortie['today'], sortie['total']), ((2, 0), (2, 0)))
        self.assertEqual(run_stats.summary(self.path, now=now)['total'], (3, 1))  # 不分模式時照舊全部算

    def test_fate_summary(self):
        """各層選的命運跟著每局戰績存下來：統計被選次數、各層分布、選過的局勝率（同一局選兩次只算一局）。"""
        run_stats.record(True, 'SortieMode', self.path, fates=[{'floor': 1, 'name': '轻盈身法'},
                                                              {'floor': 2, 'name': '公平的交易'}], floors=3)
        run_stats.record(False, 'SortieMode', self.path, fates=[{'floor': 1, 'name': '轻盈身法'},
                                                               {'floor': 3, 'name': '轻盈身法'}], floors=2)
        run_stats.record(True, 'ChaosMode', self.path, fates=[{'floor': 1, 'name': '公平的交易'}])
        run_stats.record(True, 'SortieMode', self.path)  # 舊格式、沒選命運的局
        fates = run_stats.fate_summary(self.path, modes=('SortieMode',))
        self.assertEqual([(f['name'], f['picks'], f['floors'], f['wins'], f['losses']) for f in fates],
                         [('轻盈身法', 3, {1: 2, 3: 1}, 1, 1), ('公平的交易', 1, {2: 1}, 1, 0)])
        self.assertEqual(run_stats.fate_summary(self.path)[1]['picks'], 2)  # 不分模式
        with open(self.path, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['rounds'][0]['floors'], 3)
        light = fates[0]
        self.assertEqual((light['counted'], light['avg_floors'], light['full_clears']), (2, 2.5, 1))
        self.assertEqual(run_stats.floors_text(light), '平均 2.5 層、三層通關 1/2')

    def test_equipment_summary(self):
        """裝備跟命運一樣統計：裝過的局平均打到第幾層、三層通關幾局。"""
        run_stats.record(True, 'SortieMode', self.path, floors=1,
                         equipment=[{'floor': 1, 'name': '誓死拳甲', 'slot': 2}])
        run_stats.record(True, 'SortieMode', self.path, floors=3,
                         equipment=[{'floor': 2, 'name': '誓死拳甲', 'slot': 2},
                                    {'floor': 2, 'name': '无眼者之瞳', 'slot': 3}])
        items = {item['name']: item for item in run_stats.equipment_summary(self.path)}
        self.assertEqual((items['誓死拳甲']['picks'], items['誓死拳甲']['avg_floors'],
                          items['誓死拳甲']['full_clears']), (2, 2.0, 1))
        self.assertEqual(items['无眼者之瞳']['floors'], {2: 1})

    def test_reset_and_missing_file(self):
        self.assertEqual(run_stats.summary(self.path)['total'], (0, 0))
        run_stats.record(True, path=self.path, now=at('2026-10-28 09:00'))
        run_stats.reset(self.path, now=at('2026-10-28 10:00'))
        stats = run_stats.summary(self.path, now=at('2026-10-28 10:00'))
        self.assertEqual(stats['total'], (0, 0))
        self.assertEqual(stats['since'], '2026-10-28 10:00')

    def test_keeps_recent_rounds_only(self):
        old = run_stats.MAX_ROUNDS
        run_stats.MAX_ROUNDS = 3
        self.addCleanup(setattr, run_stats, 'MAX_ROUNDS', old)
        for i in range(5):
            run_stats.record(i % 2 == 0, path=self.path, now=at('2026-10-28 09:00') + i)
        with open(self.path, encoding='utf-8') as f:
            self.assertEqual(len(json.load(f)['rounds']), 3)

    def test_rate_text(self):
        self.assertEqual(run_stats.rate_text(6, 1), '6 勝 1 敗（86%）')
        self.assertEqual(run_stats.rate_text(0, 0), '0 勝 0 敗')


class TestOverviewData(unittest.TestCase):
    def test_parse_log_and_hp(self):
        line = '2026-10-28 12:55:23,123 INFO TaskExecutor ChaosModeExperimental:当前生命值: 1313/1323 = 99%'
        time_text, source, message = data.parse_log(line)
        self.assertEqual((time_text, source), ('12:55:23', 'ChaosModeExperimental'))
        self.assertEqual(data.hp_from(message), (1313, 1323))
        self.assertIsNone(data.hp_from('检测到进入按钮'))
        self.assertEqual(data.parse_log('隨便一行'), ('', '', '隨便一行'))

    def test_noisy_lines(self):
        self.assertTrue(data.is_noisy('info_set 当前信用点 560'))
        self.assertTrue(data.is_noisy('   '))
        self.assertFalse(data.is_noisy('检测到赛季卡厄思初始页面'))

    def test_deck_progress_groups_by_name(self):
        records = [{'name': '明滅劍'}, {'name': '劍之共鳴'}, {'name': '劍之共鳴'}, {'name': ''}]
        same = lambda a, b: a.replace('滅', '灭').replace('劍', '剑').replace('鳴', '鸣') == \
            b.replace('滅', '灭').replace('劍', '剑').replace('鳴', '鸣')
        self.assertEqual(data.deck_progress(records, None, same), [('明滅劍', None, 1), ('劍之共鳴', None, 2)])
        counts = {'明灭剑': 1, '剑之共鸣': 1, '循环之刃': 1}
        self.assertEqual(data.deck_progress(records, counts, same), [('明滅劍', 1, 1), ('劍之共鳴', 1, 2)])

    def test_equipment_rows(self):
        rows = data.equipment_rows({'names': ['混沌指控', ''], 'qualities': ['传说'], 'descriptions': None})
        self.assertEqual(rows, [(1, '混沌指控', '传说', ''), (2, '', '', ''), (3, '', '', '')])
        self.assertEqual(data.equipment_rows(None)[2], (3, '', '', ''))


if __name__ == '__main__':
    unittest.main()

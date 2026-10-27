import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import catalog  # noqa: E402
from src.catalog import CatalogSettings  # noqa: E402

HAS_NUMPY = importlib.util.find_spec('numpy') is not None


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def fake_write_image(path, image):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(str(image))


class CatalogTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = catalog.CATALOG, catalog._write_image
        catalog.CATALOG = CatalogSettings(repeat_window=60, save_interval=30)
        catalog._write_image = fake_write_image
        self.addCleanup(self.restore)
        self.path = os.path.join(self.tmp, 'catalog.json')
        self.clock = Clock()
        self.cat = catalog.Catalog(self.path, clock=self.clock)

    def restore(self):
        catalog.CATALOG, catalog._write_image = self.saved

    def saved_data(self):
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)

    def names(self, kind, lang='繁体中文'):
        return [entry.get('name') or entry['text'] for _, entry in self.cat.entries(kind, lang)]


class TestRecord(CatalogTestCase):
    def test_new_entry_and_repeat_window(self):
        self.assertTrue(self.cat.record('event', '', '移除2张卡牌', '繁体中文'))
        self.assertFalse(self.cat.record('event', '', '移除 2张卡牌', '繁体中文'))  # 去空白後同一項
        self.clock.now += 10
        self.cat.record('event', '', '移除2张卡牌', '繁体中文')
        self.assertEqual(self.cat.entries('event', '繁体中文')[0][1]['seen'], 1)
        self.clock.now += 61
        self.cat.record('event', '', '移除2张卡牌', '繁体中文')
        self.assertEqual(self.cat.entries('event', '繁体中文')[0][1]['seen'], 2)

    def test_rejects_unreadable_entries(self):
        self.assertFalse(self.cat.record('event', '', '移', '繁体中文'))
        self.assertFalse(self.cat.record('card', '', '造成伤害', '繁体中文'))
        self.assertFalse(self.cat.record('equipment', ' ', '', '繁体中文'))
        self.assertFalse(self.cat.record('unknown', '名字', '内容', '繁体中文'))
        self.assertFalse(os.path.exists(self.path))

    def test_languages_kept_apart(self):
        self.cat.record('card', '剑雨', '造成伤害', '简体中文')
        self.cat.record('card', '剑之雨', '造成伤害', '繁体中文')
        self.assertEqual(self.names('card', '简体中文'), ['剑雨'])
        self.assertEqual(self.names('card', '繁体中文'), ['剑之雨'])

    def test_card_variants_and_equipment_updates(self):
        self.cat.record('card', '剑之雨', '造成3次伤害', '繁体中文', '攻击')
        self.cat.record('card', '剑之雨', '造成4次伤害', '繁体中文', '攻击')
        self.assertEqual(len(self.cat.entries('card', '繁体中文')), 2)
        self.cat.record('equipment', '蚀化臂铠', '攻击力+10', '繁体中文', '1号位 武器')
        self.clock.now += 100
        self.cat.record('equipment', '蚀化臂铠', '攻击力+12', '繁体中文', '1号位 武器 传说')
        (_, entry), = self.cat.entries('equipment', '繁体中文')
        self.assertEqual((entry['text'], entry['info'], entry['seen']), ('攻击力+12', '1号位 武器 传说', 2))

    def test_entries_sorted_by_seen(self):
        self.cat.record('event', '', '较少出现', '繁体中文')
        for _ in range(3):
            self.clock.now += 61
            self.cat.record('event', '', '经常出现', '繁体中文')
        self.assertEqual(self.names('event'), ['经常出现', '较少出现'])


class TestPersistence(CatalogTestCase):
    def test_new_entries_saved_immediately_counts_throttled(self):
        catalog.CATALOG.save_interval = 120
        self.cat.record('event', '', '移除2张卡牌', '繁体中文')
        self.assertEqual(self.saved_data()['繁体中文']['event']['移除2张卡牌']['seen'], 1)
        self.clock.now += 61
        self.cat.record('event', '', '移除2张卡牌', '繁体中文')
        self.assertEqual(self.saved_data()['繁体中文']['event']['移除2张卡牌']['seen'], 1)
        self.clock.now += 60
        self.cat.record('event', '', '移除2张卡牌', '繁体中文')
        self.assertEqual(self.saved_data()['繁体中文']['event']['移除2张卡牌']['seen'], 3)

    def test_reload_and_broken_file(self):
        self.cat.record('card', '剑之雨', '造成伤害', '繁体中文')
        reloaded = catalog.Catalog(self.path)
        self.assertEqual(len(reloaded.entries('card', '繁体中文')), 1)
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{壞掉的 json')
        self.assertEqual(catalog.Catalog(self.path).entries('card', '繁体中文'), [])

    def test_eviction_keeps_new_entry_and_deletes_image(self):
        catalog.CATALOG.max_entries_per_kind = 2
        self.cat.record('card', '常见', '效果', '繁体中文', image='a')
        self.clock.now += 61
        self.cat.record('card', '常见', '效果', '繁体中文')
        self.cat.record('card', '少见', '效果', '繁体中文', image='b')
        rare_image = self.cat.image_path(dict(self.cat.entries('card', '繁体中文'))['少见|效果'])
        self.clock.now += 1
        self.cat.record('card', '新的', '效果', '繁体中文')
        self.assertEqual(sorted(self.names('card')), ['常见', '新的'])
        self.assertFalse(os.path.exists(rare_image))

    def test_remove_deletes_entries_and_images(self):
        self.cat.record('card', '剑之雨', '造成伤害', '繁体中文', image='a')
        key, entry = self.cat.entries('card', '繁体中文')[0]
        image = self.cat.image_path(entry)
        self.cat.remove('card', '繁体中文', [key])
        self.assertEqual(self.cat.entries('card', '繁体中文'), [])
        self.assertFalse(os.path.exists(image))
        self.assertEqual(self.saved_data()['繁体中文']['card'], {})


class TestImages(CatalogTestCase):
    def test_image_saved_once_and_lazily(self):
        calls = []

        def make_image():
            calls.append(1)
            return 'image-bytes'

        self.cat.record('card', '剑之雨', '造成伤害', '繁体中文', image=make_image)
        self.clock.now += 61
        self.cat.record('card', '剑之雨', '造成伤害', '繁体中文', image=make_image)
        self.assertEqual(len(calls), 1)
        (_, entry), = self.cat.entries('card', '繁体中文')
        path = self.cat.image_path(entry)
        self.assertTrue(path.startswith(os.path.join(self.tmp, 'catalog_images', 'card')))
        self.assertTrue(entry['image'].startswith('catalog_images/card/'))

    def test_write_failure_keeps_entry_without_image(self):
        def broken(path, image):
            raise OSError('disk full')
        catalog._write_image = broken
        self.assertTrue(self.cat.record('card', '剑之雨', '造成伤害', '繁体中文', image='x'))
        (_, entry), = self.cat.entries('card', '繁体中文')
        self.assertIsNone(self.cat.image_path(entry))

    @unittest.skipUnless(HAS_NUMPY, '需要 numpy')
    def test_crop_and_union(self):
        import numpy as np
        frame = np.arange(100 * 200 * 3, dtype=np.uint8).reshape(100, 200, 3)
        region = catalog.union((0.1, 0.2, 0.3, 0.4), (0.2, 0.1, 0.5, 0.3))
        self.assertEqual(region, (0.1, 0.1, 0.5, 0.4))
        # 外擴 0.005：x 19~101、y 9~40
        self.assertEqual(catalog.crop(frame, region).shape, (31, 82, 3))
        self.assertIsNone(catalog.crop(None, region))
        self.assertIsNone(catalog.crop(frame, (0.5, 0.5, 0.5, 0.5 - 0.02)))


class FakeTask:
    def __init__(self, enabled=None, broken=False):
        self.enabled, self.broken = enabled, broken
        self.frame = None

    def get_global_config(self, option):
        if self.broken:
            raise KeyError(option)
        return {'目录设置': {} if self.enabled is None else {'自动收集目录': self.enabled}}[option]


class TestModuleRecord(CatalogTestCase):
    def test_switch_controls_collecting(self):
        self.assertTrue(catalog.collecting_enabled(FakeTask()))
        self.assertTrue(catalog.collecting_enabled(FakeTask(broken=True)))
        self.assertFalse(catalog.collecting_enabled(FakeTask(enabled=False)))
        self.assertFalse(catalog.record(FakeTask(enabled=False), 'event', '', '移除2张卡牌', '繁体中文',
                                        path=self.path))
        self.assertTrue(catalog.record(FakeTask(enabled=True), 'event', '', '移除2张卡牌', '繁体中文',
                                       path=self.path))
        self.assertIs(catalog.get_catalog(self.path), catalog.get_catalog(self.path))


class TestMatches(unittest.TestCase):
    def test_query_against_fields_and_shown_text(self):
        entry = {'name': '剑之雨', 'text': '造成 3 次伤害', 'info': '攻击'}
        self.assertTrue(catalog.matches(entry, ''))
        self.assertTrue(catalog.matches(entry, '3次'))
        self.assertTrue(catalog.matches(entry, '攻击'))
        self.assertFalse(catalog.matches(entry, '劍之雨'))
        shown = lambda text: text.replace('剑', '劍')  # noqa: E731
        self.assertTrue(catalog.matches(entry, '劍之雨', shown))


if __name__ == '__main__':
    unittest.main()

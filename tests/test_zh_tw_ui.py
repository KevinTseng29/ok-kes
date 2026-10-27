import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import zh_tw_ui  # noqa: E402

HAS_OPENCC = importlib.util.find_spec('opencc') is not None
FAKE_TABLE = {'游戏语言': '遊戲語言', '简体中文': '簡體中文', '第1层': '第1層'}


class FakeLocale:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class FakeApp:
    """模擬框架 App.tr：有翻譯就回翻譯，沒有就回原字串。"""
    translations = {'Start': '開始', '刷新': '已有翻譯'}

    def __init__(self, locale='zh_TW'):
        self.locale = FakeLocale(locale)

    def tr(self, key):
        if not key:
            return key
        return self.translations.get(key, key)


def fake_convert(text):
    return FAKE_TABLE.get(text, text)


class TestWrapTr(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(zh_tw_ui, '_convert', side_effect=fake_convert)
        self.convert = patcher.start()
        self.addCleanup(patcher.stop)
        self.tr = zh_tw_ui.wrap_tr(FakeApp.tr)

    def test_converts_untranslated_text_for_traditional_locales(self):
        for locale in ('zh_TW', 'zh_HK', 'zh_MO'):
            self.assertEqual(self.tr(FakeApp(locale), '游戏语言'), '遊戲語言')
        self.assertEqual(self.tr(FakeApp(), '第1层'), '第1層')

    def test_keeps_existing_translations(self):
        self.assertEqual(self.tr(FakeApp(), 'Start'), '開始')
        self.assertEqual(self.tr(FakeApp(), '刷新'), '已有翻譯')
        self.convert.assert_not_called()

    def test_other_locales_untouched(self):
        for locale in ('zh_CN', 'en_US', 'ja_JP'):
            self.assertEqual(self.tr(FakeApp(locale), '游戏语言'), '游戏语言')
        self.convert.assert_not_called()

    def test_non_chinese_and_empty_keys_pass_through(self):
        app = FakeApp()
        for key in (None, '', 'True', 'NaN', '0/0'):
            self.assertEqual(self.tr(app, key), key)
        self.convert.assert_not_called()

    def test_converter_failure_falls_back_to_original(self):
        self.convert.side_effect = RuntimeError('opencc missing')
        self.assertEqual(self.tr(FakeApp(), '游戏语言'), '游戏语言')

    def test_broken_locale_falls_back_to_original(self):
        app = FakeApp()
        app.locale = None
        self.assertEqual(self.tr(app, '游戏语言'), '游戏语言')


class TestInstall(unittest.TestCase):
    def test_install_wraps_once(self):
        fake_app_class = type('App', (FakeApp,), {})
        fake_app_class.tr = FakeApp.tr
        with mock.patch.dict(sys.modules, {'ok': types.SimpleNamespace(App=fake_app_class)}), \
                mock.patch.object(zh_tw_ui, '_convert', side_effect=fake_convert):
            zh_tw_ui.install()
            wrapped = fake_app_class.tr
            zh_tw_ui.install()
            self.assertIs(fake_app_class.tr, wrapped)
            self.assertEqual(fake_app_class().tr('简体中文'), '簡體中文')


@unittest.skipUnless(HAS_OPENCC, '需要 opencc')
class TestRealConversion(unittest.TestCase):
    def test_s2tw_changes_characters_not_wording(self):
        tr = zh_tw_ui.wrap_tr(FakeApp.tr)
        app = FakeApp()
        self.assertEqual(tr(app, '游戏语言'), '遊戲語言')
        self.assertEqual(tr(app, '商店刷新信用点阈值'), '商店刷新信用點閾值')
        self.assertEqual(tr(app, '所处层数，节点，类型'), '所處層數，節點，類型')


if __name__ == '__main__':
    unittest.main()

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_GUI = all(importlib.util.find_spec(m) is not None for m in ('ok', 'PySide6', 'qfluentwidgets'))


class FakeApp:
    """模擬繁體介面的 og.app.tr。"""
    table = {'海德玛丽': '海德瑪麗', '尼娅': '尼婭'}

    def tr(self, key):
        return self.table.get(key, key)


@unittest.skipUnless(HAS_GUI, '需要 ok-script 與 PySide6')
class TestEditableDropDown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ok import og
        self.og = og
        self.saved_app = getattr(og, 'app', None)
        og.app = FakeApp()
        self.addCleanup(setattr, og, 'app', self.saved_app)
        from src.ui.LabelAndEditableDropDown import LabelAndEditableDropDown
        self.config = {'刷存档主战员': '海德玛丽'}
        self.widget = LabelAndEditableDropDown(None, ['海德玛丽', '尼娅', '九'], self.config, '刷存档主战员')
        self.combo = self.widget.combo_box

    def test_shows_options_and_value_in_ui_language(self):
        self.assertEqual([self.combo.itemText(i) for i in range(self.combo.count())], ['海德瑪麗', '尼婭', '九'])
        self.assertEqual(self.combo.text(), '海德瑪麗')
        self.assertEqual(self.config['刷存档主战员'], '海德玛丽')

    def test_selecting_option_stores_original_text(self):
        self.combo.setCurrentIndex(1)
        self.assertEqual(self.combo.text(), '尼婭')
        self.assertEqual(self.config['刷存档主战员'], '尼娅')

    def test_typing_stores_text_or_matching_option(self):
        self.combo.setText(' 新角色 ')
        self.assertEqual(self.config['刷存档主战员'], '新角色')
        self.combo.setText('海德瑪麗')
        self.assertEqual(self.config['刷存档主战员'], '海德玛丽')

    def test_update_value_does_not_write_back(self):
        self.config['刷存档主战员'] = '自訂名字'
        self.widget.update_value()
        self.assertEqual(self.combo.text(), '自訂名字')
        self.assertEqual(self.config['刷存档主战员'], '自訂名字')

    def test_typing_filters_options_by_substring(self):
        from PySide6.QtCore import Qt
        completer = self.combo.completer()
        self.assertEqual(completer.filterMode(), Qt.MatchFlag.MatchContains)
        completer.setCompletionPrefix('瑪')
        matches = [completer.completionModel().index(i, 0).data() for i in range(completer.completionCount())]
        self.assertEqual(matches, ['海德瑪麗'])

    def test_options_follow_another_setting(self):
        from src.ui.LabelAndEditableDropDown import LabelAndEditableDropDown
        config = {'游戏语言': '简体中文', '刷存档主战员': '尼娅'}
        names = {'繁体中文': ['妮雅', '海德瑪麗'], '简体中文': ['尼娅', '海德玛丽']}
        widget = LabelAndEditableDropDown(None, names, config, '刷存档主战员', options_key='游戏语言')
        items = lambda: [widget.combo_box.itemText(i) for i in range(widget.combo_box.count())]  # noqa: E731
        self.assertEqual(items(), ['尼婭', '海德瑪麗'])

        config['游戏语言'] = '繁体中文'
        widget.load_options()
        self.assertEqual(items(), ['妮雅', '海德瑪麗'])
        # 換選項不會改到已填的值
        self.assertEqual(widget.combo_box.text(), '尼婭')
        self.assertEqual(config['刷存档主战员'], '尼娅')

        config['游戏语言'] = '未知'
        widget.load_options()
        self.assertEqual(items(), ['妮雅', '海德瑪麗'])


@unittest.skipUnless(HAS_GUI, '需要 ok-script 與 PySide6')
class TestInstall(unittest.TestCase):
    def test_dispatches_new_type_and_delegates_others(self):
        from ok.gui.tasks import ConfigCard, ConfigItemFactory
        from src.ui import LabelAndEditableDropDown as module

        original = ConfigItemFactory.config_widget
        self.addCleanup(setattr, ConfigItemFactory, 'config_widget', original)
        self.addCleanup(setattr, ConfigCard, 'config_widget', ConfigCard.config_widget)
        calls = []
        ConfigItemFactory.config_widget = lambda *args: calls.append(args) or 'framework'

        module.install()
        installed = ConfigItemFactory.config_widget
        module.install()
        self.assertIs(ConfigItemFactory.config_widget, installed)
        self.assertIs(ConfigCard.config_widget, installed)

        sentinel = object()
        saved_widget = module.LabelAndEditableDropDown
        self.addCleanup(setattr, module, 'LabelAndEditableDropDown', saved_widget)
        module.LabelAndEditableDropDown = (
            lambda desc, options, config, key, options_key=None: (sentinel, options, key, options_key))

        config_type = {'a': {'type': 'editable_drop_down', 'options': ['x'], 'options_key': 'lang'},
                       'b': {'type': 'drop_down'}}
        self.assertEqual(installed(config_type, None, {}, 'a', '', None), (sentinel, ['x'], 'a', 'lang'))
        self.assertEqual(installed(config_type, None, {}, 'b', '', None), 'framework')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()

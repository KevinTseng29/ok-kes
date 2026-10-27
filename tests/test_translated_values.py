import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_GUI = all(importlib.util.find_spec(m) is not None for m in ('ok', 'PySide6', 'qfluentwidgets'))


class FakeApp:
    """模擬繁體介面的 og.app.tr。"""
    table = {'复制': '複製', '移除': '移除', '剑雨': '劍雨', '丢弃最多2张卡牌': '丟棄最多2張卡牌'}

    def tr(self, key):
        return self.table.get(key, key)


@unittest.skipUnless(HAS_GUI, '需要 ok-script 與 PySide6')
class TestTranslatedValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.qt_app = QApplication.instance() or QApplication([])
        from src.ui import translated_values
        translated_values.install()
        translated_values.install()

    def setUp(self):
        from ok import og
        from PySide6.QtWidgets import QWidget
        self.saved_app = getattr(og, 'app', None)
        og.app = FakeApp()
        self.addCleanup(setattr, og, 'app', self.saved_app)
        # 對話框需要有父視窗
        self.window = QWidget()
        self.window.resize(1000, 700)

    def test_free_text_list_shows_translated_items(self):
        from ok.gui.tasks.ModifyListItem import ModifyListItem
        config = {'任务优先级': ['复制', '信用点增加']}
        item = ModifyListItem(None, config, '任务优先级')
        self.assertEqual(item.list_text.text(), '複製, 信用点增加')
        self.assertEqual(config['任务优先级'], ['复制', '信用点增加'])

    def test_list_dialog_maps_unchanged_items_back(self):
        from ok.gui.tasks.ModifyListDialog import ModifyListDialog
        dialog = ModifyListDialog(['复制', '剑雨'], self.window)
        shown = [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]
        self.assertEqual(shown, ['複製', '劍雨'])
        dialog.list_widget.addItem('劍之雨')
        result = []
        dialog.list_modified.connect(result.append)
        dialog.confirm()
        self.assertEqual(result, [['复制', '剑雨', '劍之雨']])

    def test_list_dialog_with_options_unchanged(self):
        from ok.gui.tasks.ModifyListDialog import ModifyListDialog
        dialog = ModifyListDialog(['复制'], self.window, options_available=['复制', '移除'])
        result = []
        dialog.list_modified.connect(result.append)
        dialog.confirm()
        self.assertEqual(result, [['复制']])

    def test_line_edit_keeps_source_until_edited(self):
        from ok.gui.tasks.LabelAndLineEdit import LabelAndLineEdit
        config = {'指定面具卡牌': '丢弃最多2张卡牌'}
        widget = LabelAndLineEdit(None, config, '指定面具卡牌')
        self.assertEqual(widget.line_edit.text(), '丟棄最多2張卡牌')
        self.assertEqual(config['指定面具卡牌'], '丢弃最多2张卡牌')
        widget.line_edit.setText('丟棄1張')
        self.assertEqual(config['指定面具卡牌'], '丟棄1張')
        widget.line_edit.setText('丟棄最多2張卡牌')
        self.assertEqual(config['指定面具卡牌'], '丢弃最多2张卡牌')

    def test_text_edit_keeps_source_until_edited(self):
        from ok.gui.tasks.LabelAndTextEdit import LabelAndTextEdit
        config = {'说明': '丢弃最多2张卡牌'}
        widget = LabelAndTextEdit(None, config, '说明')
        self.assertEqual(widget.text_edit.toPlainText(), '丟棄最多2張卡牌')
        widget.text_edit.setPlainText('新的內容')
        self.assertEqual(config['说明'], '新的內容')


if __name__ == '__main__':
    unittest.main()

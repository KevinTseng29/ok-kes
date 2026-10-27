import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_GUI = all(importlib.util.find_spec(m) is not None for m in ('ok', 'PySide6', 'qfluentwidgets', 'cv2'))


class FakeApp:
    """模擬繁體介面的 og.app.tr。"""
    table = {'剑之雨': '劍之雨', '剑幕': '劍幕', '造成3次伤害': '造成3次傷害', '移除2张卡牌': '移除2張卡牌'}

    def tr(self, key):
        return self.table.get(key, key)


@unittest.skipUnless(HAS_GUI, '需要 ok-script、PySide6 與 opencv')
class TestCatalogDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.qt_app = QApplication.instance() or QApplication([])
        from src.ui import translated_values
        translated_values.install()

    def setUp(self):
        import numpy as np
        from ok import og
        from PySide6.QtWidgets import QWidget
        from src import catalog
        self.saved_app = getattr(og, 'app', None)
        og.app = FakeApp()
        self.addCleanup(setattr, og, 'app', self.saved_app)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'catalog.json')
        cat = catalog.get_catalog(self.path)
        image = np.full((40, 30, 3), 200, dtype=np.uint8)
        cat.record('card', '剑之雨', '造成3次伤害', '繁体中文', '攻击', image)
        cat.record('card', '剑幕', '获得护盾', '繁体中文', '技能')
        cat.record('event', '', '移除2张卡牌', '繁体中文')
        cat.record('card', '国服卡', '只在简体', '简体中文')
        self.catalog = cat
        self.window = QWidget()
        self.window.resize(1200, 800)

    def list_dialog(self, items, **kwargs):
        from ok.gui.tasks.ModifyListDialog import ModifyListDialog
        return ModifyListDialog(items, self.window, **kwargs)

    def picker(self, kind='card', with_text=False):
        from src.ui.catalog_dialog import CatalogDialog
        added = []
        dialog = CatalogDialog(kind, '繁体中文', self.window, added.extend, with_text=with_text, path=self.path)
        return dialog, added

    @staticmethod
    def row_of(picker, name):
        return next(i for i, (_, entry) in enumerate(picker.rows) if entry['name'] == name)

    def test_attach_only_for_catalog_lists(self):
        from src.ui.catalog_dialog import attach
        config = {'游戏语言': '繁体中文'}
        dialog = self.list_dialog(['剑幕'])
        self.assertTrue(attach(dialog, '移除卡牌列表', config, path=self.path))
        self.assertEqual(dialog.list_widget.item(0).toolTip(), '获得护盾')
        self.assertFalse(attach(self.list_dialog(['休息']), '路线优先级', config, path=self.path))
        restricted = self.list_dialog(['a'], options_available=['a', 'b'])
        self.assertFalse(attach(restricted, '移除卡牌列表', config, path=self.path))

    def test_picker_lists_search_and_language(self):
        picker, _ = self.picker()
        self.assertEqual(picker.table.rowCount(), 2)
        row = self.row_of(picker, '剑之雨')
        self.assertEqual([picker.table.item(row, c).text() for c in range(4)], ['劍之雨', '造成3次傷害', '攻击', '1'])
        picker.search.setText('劍之')
        self.assertEqual(picker.table.rowCount(), 1)
        picker.search.setText('不存在')
        self.assertEqual(picker.table.rowCount(), 0)
        self.assertTrue(picker.empty_label.isVisible() or picker.empty_label.text())

    def test_add_keywords_into_list_and_save_source(self):
        from src.ui.catalog_dialog import add_keywords
        dialog = self.list_dialog(['剑幕'])
        picker, added = self.picker(with_text=True)
        picker.add_rows([self.row_of(picker, '剑之雨'), self.row_of(picker, '剑幕')])
        self.assertEqual(added, ['剑之雨造成3次伤害', '剑幕获得护盾'])
        add_keywords(dialog, ['剑之雨', '剑幕'])
        shown = [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]
        self.assertEqual(shown, ['劍幕', '劍之雨'])
        result = []
        dialog.list_modified.connect(result.append)
        dialog.confirm()
        self.assertEqual(result, [['剑幕', '剑之雨']])

    def test_event_picker_inserts_task_text(self):
        picker, added = self.picker(kind='event')
        self.assertIsNone(picker.preview)
        picker.add_rows([0])
        self.assertEqual(added, ['移除2张卡牌'])

    def test_preview_and_delete(self):
        picker, _ = self.picker()
        with_image, without_image = self.row_of(picker, '剑之雨'), self.row_of(picker, '剑幕')
        picker.table.selectRow(with_image)
        self.assertFalse(picker.preview.pixmap().isNull())
        picker.table.selectRow(without_image)
        self.assertTrue(picker.preview.pixmap().isNull())
        self.assertTrue(picker.preview.text())
        picker.table.selectRow(with_image)
        image = self.catalog.image_path(picker.rows[with_image][1])
        self.assertTrue(os.path.exists(image))
        picker.delete_selected()
        self.assertEqual(picker.table.rowCount(), 1)
        self.assertFalse(os.path.exists(image))

    def test_install_patches_list_item_once(self):
        from ok.gui.tasks.ModifyListItem import ModifyListItem
        from src.ui import catalog_dialog
        saved = ModifyListItem.clicked, getattr(ModifyListItem, '_ok_kes_catalog', False)
        self.addCleanup(lambda: (setattr(ModifyListItem, 'clicked', saved[0]),
                                 setattr(ModifyListItem, '_ok_kes_catalog', saved[1])))
        ModifyListItem._ok_kes_catalog = False
        catalog_dialog.install()
        patched = ModifyListItem.clicked
        catalog_dialog.install()
        self.assertIs(ModifyListItem.clicked, patched)
        self.assertIsNot(patched, saved[0])


if __name__ == '__main__':
    unittest.main()

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_GUI = all(importlib.util.find_spec(m) is not None for m in ('ok', 'PySide6', 'qfluentwidgets'))


class FakeApp:
    def tr(self, key):
        return key


@unittest.skipUnless(HAS_GUI, '需要 ok-script 與 PySide6')
class TestCardPicker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ok import og
        from PySide6.QtWidgets import QWidget
        from src import card_db, catalog
        self.saved_app = getattr(og, 'app', None)
        og.app = FakeApp()
        self.addCleanup(setattr, og, 'app', self.saved_app)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = card_db.load()
        self.path = os.path.join(self.tmp, 'catalog.json')
        catalog.get_catalog(self.path).record('card', '剑之雨', '造成伤害', '繁体中文', '攻击')
        self.window = QWidget()
        self.window.resize(1300, 800)

    def picker(self, config=None, with_text=False):
        from src.ui.card_picker import CardPickerDialog
        added = []
        dialog = CardPickerDialog(self.db, '繁体中文', 'ChaosMode', config or {'刷存档主战员': '海德瑪麗'},
                                  self.window, added.extend, with_text=with_text, path=self.path,
                                  team_folder=self.tmp)
        return dialog, added

    def owners(self, dialog):
        return {row[1] for row in dialog.rows}

    def test_default_team_lists_only_team_and_neutral(self):
        dialog, _ = self.picker()
        self.assertEqual(dialog.team(), ['海德瑪麗'])
        self.assertEqual(self.owners(dialog), {'海德瑪麗', '中立'})
        dialog.neutral_box.setChecked(False)
        self.assertEqual(self.owners(dialog), {'海德瑪麗'})

    def test_team_change_is_saved_and_filters(self):
        from src import card_db
        dialog, _ = self.picker()
        box = dialog.member_boxes[1]
        box.setCurrentIndex(box.findData('米卡'))
        self.assertEqual(dialog.team(), ['海德瑪麗', '米卡'])
        self.assertEqual(card_db.load_team('ChaosMode', self.tmp), ['海德瑪麗', '米卡'])
        self.assertIn('米卡', self.owners(dialog))
        reopened, _ = self.picker(config={})
        self.assertEqual(reopened.team(), ['海德瑪麗', '米卡'])

    def test_search_seen_count_and_add(self):
        dialog, added = self.picker()
        dialog.search.setText('劍之雨')
        self.assertEqual([row[0] for row in dialog.rows], ['劍之雨'])
        self.assertEqual(dialog.table.item(0, 3).text(), '1')  # 執行時看過一次（簡體卡名也對得上）
        dialog.add_rows([0])
        self.assertEqual(added, ['劍之雨'])

    def test_flash_priority_lists_variants_with_effect_keyword(self):
        dialog, added = self.picker(with_text=True)
        dialog.search.setText('劍之雨')
        self.assertGreater(len(dialog.rows), 1)
        dialog.add_rows(list(range(len(dialog.rows))))
        self.assertTrue(all(word.startswith('劍之雨') for word in added))
        self.assertGreater(len(set(added)), 1)

    def test_attach_uses_database_only_for_international_cards(self):
        from src.ui import catalog_dialog
        self.assertIsNotNone(catalog_dialog._card_db_for('card', '繁体中文'))
        self.assertIsNone(catalog_dialog._card_db_for('card', '简体中文'))
        self.assertIsNone(catalog_dialog._card_db_for('equipment', '繁体中文'))


if __name__ == '__main__':
    unittest.main()

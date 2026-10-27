import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'ok_tasks'))

from src import card_db  # noqa: E402
from members import MEMBER_NAMES  # noqa: E402


class TestDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = card_db.load()

    def test_loaded_and_covers_international_roster(self):
        self.assertIsNotNone(self.db)
        missing = [name for name in MEMBER_NAMES['繁体中文'] if not self.db.has_character(name)]
        self.assertEqual(missing, [])

    def test_duplicate_names_use_id_with_cards(self):
        self.assertEqual(self.db.character_ids('友紀'), ['1057'])
        self.assertEqual(self.db.character_ids('不存在的角色'), [])

    def test_cards_only_from_team_and_neutral(self):
        cards = self.db.cards_for(['海德瑪麗'], neutral=False)
        self.assertTrue(cards)
        self.assertEqual({owner for *_, owner in cards}, {'海德瑪麗'})
        names = {name for _, name, _, _ in cards}
        self.assertIn('劍之雨', names)
        self.assertNotIn('閃耀核心', names)  # 賽雷妮爾的牌
        with_neutral = self.db.cards_for(['海德瑪麗'], neutral=True)
        self.assertEqual({owner for *_, owner in with_neutral}, {'海德瑪麗', card_db.NEUTRAL})
        self.assertEqual({owner for *_, owner in self.db.cards_for([], neutral=False, other=True)}, {card_db.OTHER})

    def test_team_cards_first_in_member_order_then_neutral(self):
        owners = [owner for *_, owner in self.db.cards_for(['米卡', '海德瑪麗'], neutral=True, other=True)]
        groups = [owner for i, owner in enumerate(owners) if i == 0 or owners[i - 1] != owner]
        self.assertEqual(groups, ['米卡', '海德瑪麗', card_db.NEUTRAL, card_db.OTHER])

    def test_rows_dedupe_names_or_list_variants(self):
        names_only = card_db.rows(self.db, ['海德瑪麗'], neutral=False)
        names = [name for name, *_ in names_only]
        self.assertEqual(len(names), len(set(names)))
        variants = [row for row in card_db.rows(self.db, ['海德瑪麗'], with_text=True, neutral=False)
                    if row[0] == '劍之雨']
        self.assertGreater(len(variants), 1)
        for name, owner, shown, keyword in variants:
            self.assertTrue(keyword.startswith('劍之雨'))
            self.assertNotIn('#', shown)


class TestText(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(card_db.clean_text('造成#result_damage_0#的傷害\n^TRIGGER_RETAIN^生成3張'),
                         '造成X的傷害／生成3張')

    def test_keyword_fragment_skips_short_and_placeholders(self):
        text = '使用時\n造成#result_damage_pct_off_0#%×#final_ecv_0#的傷害\n被丟棄時\n對所有敵人造成X'
        self.assertEqual(card_db.keyword_fragment(text), '被丟棄時')
        self.assertEqual(card_db.keyword_fragment('#a#'), '')

    def test_missing_file(self):
        self.assertIsNone(card_db.load(os.path.join(ROOT, 'no_such_file.json')))


class TestTeam(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.db = card_db.load()

    def test_save_and_load_per_mode(self):
        self.assertIsNone(card_db.load_team('ChaosMode', self.folder))
        card_db.save_team('ChaosMode', ['海德瑪麗', '米卡'], self.folder)
        card_db.save_team('SortieMode', ['妮雅'], self.folder)
        self.assertEqual(card_db.load_team('ChaosMode', self.folder), ['海德瑪麗', '米卡'])
        self.assertEqual(card_db.load_team('SortieMode', self.folder), ['妮雅'])

    def test_default_team_from_mode_config(self):
        self.assertEqual(card_db.default_team(self.db, {'刷存档主战员': '海德瑪麗'}, 'ChaosMode'), ['海德瑪麗'])
        sortie = {'出战主战员优先级': ['海德瑪麗', '查無此人', '米卡', '妮雅', '蒂菲拉']}
        self.assertEqual(card_db.default_team(self.db, sortie, 'SortieMode'), ['海德瑪麗', '米卡'])
        self.assertEqual(card_db.default_team(self.db, {}, 'StoryMode'), [])


if __name__ == '__main__':
    unittest.main()

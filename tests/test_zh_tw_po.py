import gettext
import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import update_zh_tw_po as po  # noqa: E402

FAKE_TABLE = str.maketrans({'动': '動', '战': '戰', '设': '設', '导': '導', '航': '航', '刷': '刷',
                            '层': '層', '节': '節', '点': '點', '换': '換', '体': '體', '简': '簡'})


def fake_convert(text):
    return text.translate(FAKE_TABLE)


SAMPLE = textwrap.dedent('''
    from ok import ConfigOption
    ENTRY = "零号系统"

    class Mode:
        def __init__(self):
            self.name = "自动模式"
            self.description = "说明\\n第二行"
            self.default_config['游戏语言'] = "简体中文"
            self.default_config.update({'Hotkey': 'q'})
            self.config_type = {
                '游戏语言': {'type': 'drop_down', 'options': ['简体中文', '繁体中文']},
                '配置操作': {'buttons': [{'text': '导入配置码', 'callback': None}]},
            }
            self.config_type['刷存档主战员'] = {'type': 'editable_drop_down', 'options': NAMES}
            self.config_description['游戏语言'] = ("国际服请设置" "为繁体中文")

        def run(self):
            self.info_set("所处层数", 1)
            self.info_set(f"动态{1}", 2)
            self.log_info("日志不收")
            QLabel(_tr("当前版本："))

    option = ConfigOption('导航设置', {'卡厄思入口': ENTRY},
                          config_type={'卡厄思入口': {'options': [ENTRY, '赛季卡厄思']}},
                          description='全局说明')
''')


class TestCollect(unittest.TestCase):
    def test_collects_ui_strings_only(self):
        found = po.collect_from_source(SAMPLE)
        expected = ['自动模式', '说明\n第二行', '游戏语言', 'Hotkey', '游戏语言', '简体中文', '繁体中文',
                    '配置操作', '导入配置码', '刷存档主战员', '游戏语言', '国际服请设置为繁体中文', '所处层数', '当前版本：',
                    '导航设置', '卡厄思入口', '卡厄思入口', '零号系统', '赛季卡厄思', '全局说明']
        self.assertEqual(sorted(found), sorted(expected))
        self.assertNotIn('日志不收', found)

    def test_collect_strings_dedupes_with_reference(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, 'ok_tasks'))
        with open(os.path.join(root, 'ok_tasks', 'Mode.py'), 'w', encoding='utf-8') as f:
            f.write(SAMPLE)
        result = po.collect_strings(root)
        self.assertEqual(result[0], ('自动模式', 'ok_tasks/Mode.py'))
        self.assertEqual(len(result), len({text for text, _ in result}))


class TestPoFormat(unittest.TestCase):
    def test_roundtrip_with_escapes(self):
        entries = [('说明\n"引号"\\', '說明\n"引號"\\'), ('甲', '乙')]
        self.assertEqual(po.parse_po(po.format_po(entries, {'甲': 'ok_tasks/a.py'})), entries)

    def test_parses_multiline_and_skips_header(self):
        text = textwrap.dedent('''\
            msgid ""
            msgstr ""
            "Content-Type: text/plain; charset=UTF-8\\n"

            # 註解
            msgid "Long "
            "message"
            msgstr "長"
            "訊息"

            msgid "Empty"
            msgstr ""
        ''')
        self.assertEqual(po.parse_po(text), [('Long message', '長訊息'), ('Empty', '')])


class TestBuildEntries(unittest.TestCase):
    def test_prefill_keep_manual_and_drop_stale(self):
        collected = ['自动模式', 'Hotkey', '刷新设置', '游戏语言']
        zh_cn = {'Game Hotkey Config': '游戏快捷键配置', 'Untranslated': ''}
        existing = {
            '刷新设置': '重新整理設定',   # 手動修正
            '游戏语言': '',              # 空的要補
            '旧的自动条目': fake_convert('旧的自动条目'),
            '旧的手动条目': '人工翻譯',
        }
        entries = dict(po.build_entries(collected, zh_cn, existing, fake_convert))
        self.assertEqual(entries['自动模式'], '自動模式')
        self.assertEqual(entries['刷新设置'], '重新整理設定')
        self.assertEqual(entries['游戏语言'], fake_convert('游戏语言'))
        self.assertEqual(entries['Game Hotkey Config'], fake_convert('游戏快捷键配置'))
        self.assertEqual(entries['旧的手动条目'], '人工翻譯')
        self.assertNotIn('旧的自动条目', entries)
        self.assertNotIn('Hotkey', entries)
        self.assertNotIn('Untranslated', entries)


class TestCompileMo(unittest.TestCase):
    def test_gettext_reads_compiled_catalog(self):
        data = po.compile_mo([('游戏语言', '遊戲語言'), ('说明\n两行', '說明\n兩行'), ('空', '')])
        catalog = gettext.GNUTranslations(io.BytesIO(data))
        self.assertEqual(catalog.gettext('游戏语言'), '遊戲語言')
        self.assertEqual(catalog.gettext('说明\n两行'), '說明\n兩行')
        self.assertEqual(catalog.gettext('空'), '空')
        self.assertEqual(catalog.gettext('没有'), '没有')


class TestUpdate(unittest.TestCase):
    def test_rerun_keeps_manual_fix(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, 'ok_tasks'))
        with open(os.path.join(root, 'ok_tasks', 'Mode.py'), 'w', encoding='utf-8') as f:
            f.write(SAMPLE)
        total, added, removed = po.update(root, fake_convert)
        self.assertEqual((added, removed), (total, 0))

        po_path = os.path.join(root, po.ZH_TW_PO)
        with open(po_path, encoding='utf-8') as f:
            text = f.read()
        with open(po_path, 'w', encoding='utf-8') as f:
            f.write(text.replace('msgstr "導航設置"', 'msgstr "導航設定"'))
        po.update(root, fake_convert)

        entries = dict(po.read_po(po_path))
        self.assertEqual(entries['导航设置'], '導航設定')
        with open(os.path.join(root, po.ZH_TW_MO), 'rb') as f:
            catalog = gettext.GNUTranslations(f)
        self.assertEqual(catalog.gettext('导航设置'), '導航設定')
        self.assertEqual(catalog.gettext('自动模式'), '自動模式')


if __name__ == '__main__':
    unittest.main()

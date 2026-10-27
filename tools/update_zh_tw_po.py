"""產生／更新繁體中文介面翻譯檔 i18n/zh_TW/LC_MESSAGES/ok.po 與 ok.mo。

用法（在 repo 根目錄）：
    .venv\\Scripts\\python.exe tools\\update_zh_tw_po.py

做的事：
1. 從 ok_tasks/ 與 src/ 收集介面字串：任務名稱與說明、設定名稱與說明、下拉選項、按鈕文字、
   狀態欄名稱（info_set）、全域設定（ConfigOption）、tr()／_tr() 包住的對話框文字。再加上 zh_CN 已經翻好的條目
   （例如英文的 Game Hotkey Config），避免繁體介面退回去用 zh_CN 的簡體譯文。
2. 新條目用 OpenCC 預填（與 src/zh_tw_ui 同一種轉換）。
3. 已存在的條目保留現有譯文：直接改 ok.po 的 msgstr 就是手動修正，重跑不會被蓋掉。
   程式裡已經不用、譯文又只是自動轉換結果的條目會移除；手動改過的會保留。
4. 編譯成 ok.mo（框架執行時讀 .mo）。沒收錄的字串，執行時由 src/zh_tw_ui 自動轉換。

po 的讀寫與 mo 的編譯只用標準函式庫，不需要 polib。
"""
import array
import ast
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIRS = ('ok_tasks', 'src')
ZH_CN_PO = 'i18n/zh_CN/LC_MESSAGES/ok.po'
ZH_TW_PO = 'i18n/zh_TW/LC_MESSAGES/ok.po'
ZH_TW_MO = 'i18n/zh_TW/LC_MESSAGES/ok.mo'

HEADER_COMMENT = (
    '# ok-kes 繁體中文介面翻譯，由 tools/update_zh_tw_po.py 產生。\n'
    '# 直接修改 msgstr 即可手動修正；改完重跑該腳本重新編譯 ok.mo，手動修正不會被覆蓋。\n'
)
HEADER = 'Content-Type: text/plain; charset=UTF-8\nLanguage: zh_TW\n'
_HAN = re.compile(r'[\u4e00-\u9fff]')


# ---------- 收集介面字串 ----------

class _Collector(ast.NodeVisitor):
    def __init__(self, consts):
        self.consts = consts
        self.found = []

    def add(self, node):
        text = self.text(node)
        if text:
            self.found.append(text)

    def text(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.consts.get(node.id)
        return None

    def add_keys(self, node, values=False):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                self.add(key)
                if values:
                    self.add(value)

    def add_config_types(self, node):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                self.add(key)
                self.add_config_type(value)

    def add_config_type(self, node):
        if not isinstance(node, ast.Dict):
            return
        for key, value in zip(node.keys, node.values):
            name = self.text(key)
            if name == 'options' and isinstance(value, (ast.List, ast.Tuple)):
                for item in value.elts:
                    self.add(item)
            elif name == 'buttons' and isinstance(value, (ast.List, ast.Tuple)):
                for button in value.elts:
                    self.add_config_type(button)
            elif name == 'text':
                self.add(value)

    def visit_Assign(self, node):
        for target in node.targets:
            self.handle_target(target, node.value)
        self.generic_visit(node)

    def handle_target(self, target, value):
        if isinstance(target, ast.Attribute):
            if target.attr in ('name', 'description', 'first_run_alert'):
                self.add(value)
            elif target.attr == 'config_type':
                self.add_config_types(value)
            elif target.attr == 'config_description':
                self.add_keys(value, values=True)
        elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute):
            attr = target.value.attr
            if attr in ('default_config', 'config_description', 'config_type'):
                self.add(target.slice)
            if attr == 'config_description':
                self.add(value)
            elif attr == 'config_type':
                self.add_config_type(value)

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', None)
        if name in ('info_set', 'tr', '_tr') and node.args:
            self.add(node.args[0])
        elif name == 'update' and isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
            if func.value.attr in ('default_config', 'config_description') and node.args:
                self.add_keys(node.args[0], values=func.value.attr == 'config_description')
        elif name == 'ConfigOption':
            if node.args:
                self.add(node.args[0])
            if len(node.args) > 1:
                self.add_keys(node.args[1])
            for keyword in node.keywords:
                if keyword.arg in ('description',):
                    self.add(keyword.value)
                elif keyword.arg == 'config_description':
                    self.add_keys(keyword.value, values=True)
                elif keyword.arg == 'config_type':
                    self.add_config_types(keyword.value)
        self.generic_visit(node)


def _module_constants(tree):
    consts = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
    return consts


def collect_from_source(source):
    tree = ast.parse(source)
    collector = _Collector(_module_constants(tree))
    collector.visit(tree)
    return collector.found


def collect_strings(root=ROOT, dirs=SOURCE_DIRS):
    """回傳 [(字串, 相對路徑)]，依檔案與出現順序排列，同一字串只留第一次。"""
    seen, result = set(), []
    for folder in dirs:
        for current, _, files in sorted(os.walk(os.path.join(root, folder))):
            for file in sorted(files):
                if not file.endswith('.py'):
                    continue
                path = os.path.join(current, file)
                with open(path, encoding='utf-8') as f:
                    found = collect_from_source(f.read())
                rel = os.path.relpath(path, root).replace(os.sep, '/')
                for text in found:
                    if text.strip() and text not in seen:
                        seen.add(text)
                        result.append((text, rel))
    return result


# ---------- po 讀寫 ----------

_UNESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def _unescape(text):
    return re.sub(r'\\(.)', lambda m: _UNESCAPES.get(m.group(1), m.group(1)), text)


def _escape(text):
    return (text.replace('\\', '\\\\').replace('"', '\\"')
            .replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r'))


def parse_po(text):
    """回傳 [(msgid, msgstr)]（不含標頭）；支援多行字串，忽略註解。"""
    entries, msgid, msgstr, field = [], None, None, None

    def flush():
        if msgid is not None and msgid != '':
            entries.append((msgid, msgstr or ''))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.match(r'^(msgid|msgstr)\s+"(.*)"$', line)
        if match:
            if match.group(1) == 'msgid':
                flush()
                msgid, msgstr = _unescape(match.group(2)), None
            else:
                msgstr = _unescape(match.group(2))
            field = match.group(1)
        elif line.startswith('"') and line.endswith('"') and field:
            if field == 'msgid':
                msgid += _unescape(line[1:-1])
            else:
                msgstr = (msgstr or '') + _unescape(line[1:-1])
        else:
            field = None
    flush()
    return entries


def read_po(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return parse_po(f.read())


def format_po(entries, references=None):
    references = references or {}
    lines = [HEADER_COMMENT.rstrip('\n'), 'msgid ""', 'msgstr ""']
    lines += [f'"{_escape(line)}\\n"' for line in HEADER.rstrip('\n').split('\n')]
    for msgid, msgstr in entries:
        lines.append('')
        if msgid in references:
            lines.append(f'#: {references[msgid]}')
        lines.append(f'msgid "{_escape(msgid)}"')
        lines.append(f'msgstr "{_escape(msgstr)}"')
    return '\n'.join(lines) + '\n'


# ---------- 合併 ----------

def build_entries(collected, zh_cn, existing, convert):
    """collected: [字串]；zh_cn / existing: {msgid: msgstr}。回傳 [(msgid, msgstr)]。

    要收的條目 = 含中文的介面字串 + zh_CN 有譯文的條目。預填值是 OpenCC(zh_CN 譯文或原文)；
    現有譯文（含手動修正）優先。程式不再用的條目：手動改過就保留，否則移除。
    """
    def auto(msgid):
        return convert(zh_cn.get(msgid) or msgid)

    wanted = [text for text in collected if _HAN.search(text)]
    wanted += [msgid for msgid, msgstr in zh_cn.items() if msgstr]
    entries, seen = [], set()
    for msgid in wanted:
        if msgid in seen:
            continue
        seen.add(msgid)
        entries.append((msgid, existing.get(msgid) or auto(msgid)))
    for msgid, msgstr in existing.items():
        if msgid not in seen and msgstr and msgstr != auto(msgid):
            entries.append((msgid, msgstr))
    return entries


# ---------- mo 編譯 ----------

def compile_mo(entries):
    """與 CPython Tools/i18n/msgfmt.py 相同的 GNU mo 格式；附 UTF-8 標頭讓 gettext 正確解碼。"""
    messages = {b'': HEADER.encode('utf-8')}
    for msgid, msgstr in entries:
        if msgstr:
            messages[msgid.encode('utf-8')] = msgstr.encode('utf-8')
    keys = sorted(messages)
    offsets, ids, strs = [], b'', b''
    for key in keys:
        offsets.append((len(ids), len(key), len(strs), len(messages[key])))
        ids += key + b'\0'
        strs += messages[key] + b'\0'
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets, voffsets = [], []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack('Iiiiiii', 0x950412de, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    output += array.array('i', koffsets + voffsets).tobytes()
    return output + ids + strs


# ---------- 主程式 ----------

def update(root=ROOT, convert=None):
    if convert is None:
        sys.path.insert(0, root)
        from src.zh_tw_ui import _convert as convert
    po_path, mo_path = os.path.join(root, ZH_TW_PO), os.path.join(root, ZH_TW_MO)
    collected = collect_strings(root)
    references = {text: path for text, path in collected}
    zh_cn = dict(read_po(os.path.join(root, ZH_CN_PO)))
    for msgid, msgstr in zh_cn.items():
        if msgstr:
            references.setdefault(msgid, ZH_CN_PO)
    existing = dict(read_po(po_path))
    entries = build_entries([text for text, _ in collected], zh_cn, existing, convert)

    os.makedirs(os.path.dirname(po_path), exist_ok=True)
    with open(po_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(format_po(entries, references))
    with open(mo_path, 'wb') as f:
        f.write(compile_mo(entries))
    added = sum(1 for msgid, _ in entries if msgid not in existing)
    removed = sum(1 for msgid in existing if msgid not in dict(entries))
    return len(entries), added, removed


def main():
    total, added, removed = update()
    print(f'zh_TW：共 {total} 條，新增 {added} 條，移除 {removed} 條')
    print(f'已寫入 {ZH_TW_PO} 與 {ZH_TW_MO}')


if __name__ == '__main__':
    main()

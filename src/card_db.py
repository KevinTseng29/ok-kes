"""國際服卡牌資料庫：角色、卡牌名稱與效果，給設定頁依隊伍角色挑卡。

資料：ok_tasks/assets/preset_card_texts.json，取自 liuzihua699/ok-kes（codex/experimental 分支，
commit 383c794）。原檔說明為「Local static game build 130, zht」，也就是遊戲第 130 版的繁體中文
靜態資料（國際服用詞）；遊戲改版後若卡牌有變，整份換成新版即可。

- 角色卡的 ID 以 c_<角色編號>_ 開頭（例如 c_30093_ 是海德瑪麗），中立牌以 card_ne_ 開頭。
- 同名卡有多筆，是不同的靈光版本，效果文字不同。
- 效果文字裡的 #變數# 是數值佔位，顯示時換成 X；^TRIGGER_…^ 是觸發標記，顯示時拿掉。
- 只有國際服用詞，國服（簡體）譯名不同，不適用。

隊伍選擇記在設定資料夾的 catalog_team.json（依模式分開），只在本機。
本模組不依賴 ok 套件，方便單元測試。
"""
import json
import os
import re
from functools import lru_cache

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'ok_tasks', 'assets', 'preset_card_texts.json')
TEAM_FILE = 'catalog_team.json'
NEUTRAL = '中立'
OTHER = '其他'

_PLACEHOLDER = re.compile(r'#[A-Za-z_][\w{}]*#')
_TRIGGER = re.compile(r'\^[A-Za-z_]+\^')
_CHAR_CARD = re.compile(r'^c_(\d+)_')


@lru_cache(maxsize=1)
def _to_simplified():
    try:
        from opencc import OpenCC
        return OpenCC('t2s').convert
    except Exception:
        return lambda text: text


def normalize(text):
    """比對用：去空白並轉簡體（沒有 OpenCC 時只去空白）。"""
    return _to_simplified()(re.sub(r'\s+', '', text or ''))


def clean_text(text):
    """效果文字轉成顯示用：數值佔位換成 X、拿掉觸發標記、換行改成「／」。"""
    text = _TRIGGER.sub('', _PLACEHOLDER.sub('X', text or ''))
    return '／'.join(part.strip() for part in text.split('\n') if part.strip())


def keyword_fragment(text, min_length=4):
    """效果文字裡第一段可直接拿來比對的文字（不含佔位、至少 min_length 字），找不到回傳空字串。"""
    for part in re.split(r'#[^#\n]+#|\^[^\^\n]+\^|\n', text or ''):
        part = part.strip(' ，。、：:；;').lstrip('%+-')
        if len(re.sub(r'[\W_]+', '', part)) >= min_length and not re.search(r'[#^<>]', part):
            return part
    return ''


class CardDB:
    def __init__(self, data):
        self.characters = {str(k): v for k, v in (data.get('characters') or {}).items()}
        self.cards = data.get('cards') or {}
        counts = {}
        for key in self.cards:
            match = _CHAR_CARD.match(key)
            if match:
                counts[match.group(1)] = counts.get(match.group(1), 0) + 1
        # 同名角色（例如測試資料）取有卡牌的那個 ID
        self._ids_by_name = {}
        for cid, name in self.characters.items():
            if counts.get(cid):
                self._ids_by_name.setdefault(normalize(name), []).append(cid)

    def character_ids(self, name):
        return list(self._ids_by_name.get(normalize(name), []))

    def has_character(self, name):
        return bool(self.character_ids(name))

    def owner_of(self, key):
        match = _CHAR_CARD.match(key)
        if match:
            return self.characters.get(match.group(1), '')
        return NEUTRAL if key.startswith('card_ne') else OTHER

    def cards_for(self, members, neutral=True, other=False):
        """回傳 [(key, 名稱, 原始效果, 所屬)]，依隊伍角色、中立牌、其他牌篩選。
        排序：隊伍角色的牌（照 members 順序）、中立牌、其他；同一組內保持資料順序。"""
        order = {}
        for index, name in enumerate(members):
            for cid in self.character_ids(name):
                order.setdefault(cid, index)
        groups = {}
        for key, card in self.cards.items():
            match = _CHAR_CARD.match(key)
            if match:
                if match.group(1) not in order:
                    continue
                group = order[match.group(1)]
            elif key.startswith('card_ne'):
                if not neutral:
                    continue
                group = len(members)
            elif other:
                group = len(members) + 1
            else:
                continue
            name = (card.get('name') or '').strip()
            if name:
                groups.setdefault(group, []).append((key, name, card.get('text') or '', self.owner_of(key)))
        return [card for group in sorted(groups) for card in groups[group]]


@lru_cache(maxsize=1)
def load(path=DB_PATH):
    """讀取資料庫；檔案不存在或損壞回傳 None（設定頁改用執行時收集的目錄）。"""
    try:
        with open(path, encoding='utf-8') as f:
            return CardDB(json.load(f))
    except (OSError, ValueError):
        return None


def rows(db, members, with_text=False, neutral=True, other=False):
    """挑選表格的列：[(名稱, 所屬, 顯示用效果, 要加入的關鍵字)]。

    with_text=False 時同名卡只列一次（效果取第一筆）；True 時每個不同效果的版本各列一次，
    關鍵字是「名稱＋效果裡第一段可比對的文字」，供閃光優先級使用。"""
    result, seen = [], set()
    for _, name, text, owner in db.cards_for(members, neutral, other):
        shown = clean_text(text)
        identity = (owner, name, shown) if with_text else (owner, name)
        if identity in seen:
            continue
        seen.add(identity)
        keyword = name + keyword_fragment(text) if with_text else name
        result.append((name, owner, shown, keyword))
    return result


def _team_path(folder=None):
    if folder is None:
        from src.config import _get_config_folder
        folder = _get_config_folder()
    return os.path.join(folder, TEAM_FILE)


def load_team(mode, folder=None):
    try:
        with open(_team_path(folder), encoding='utf-8') as f:
            team = json.load(f).get(mode)
        return [str(name) for name in team] if isinstance(team, list) else None
    except (OSError, ValueError, AttributeError):
        return None


def save_team(mode, members, folder=None):
    path = _team_path(folder)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[mode] = list(members)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def default_team(db, config, mode):
    """沒有記住的隊伍時：卡厄思取刷存档主战员，出擊取出战主战员优先级的前三位（只留資料庫認得的）。"""
    if mode in ('ChaosMode', 'ChaosModeExperimental'):
        candidates = [config.get('刷存档主战员', '')]
    elif mode == 'SortieMode':
        candidates = list(config.get('出战主战员优先级', []) or [])[:3]
    else:
        candidates = []
    team = []
    for name in candidates:
        ids = db.character_ids(name) if isinstance(name, str) else []
        if ids:
            real = db.characters[ids[0]]
            if real not in team:
                team.append(real)
    return team
